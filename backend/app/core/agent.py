from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import asyncio
from app.core.base import Message, Session, Memory
from app.core.context import ContextManager
from app.core.context_compressor import ContextCompressor
from app.core.iteration_budget import IterationBudget
from app.memory.storage import MemoryStorage
from app.memory.vector import VectorStore
from app.llm.base import LLMResponse
from app.tools.registry import registry as _tool_registry
import re
import logging
import uuid

logger = logging.getLogger(__name__)


# ── 模块级工具函数（供 chat() 和 stream_chat() 共用）────────────────────────────

def _has_execution_claim(text: str) -> bool:
    """检测模型是否声称已经执行了外部动作。"""
    if not text:
        return False
    patterns = [
        # 已完成时 - 声称已经做了
        r"已(?:经)?(?:调用|执行|运行|打开|访问|搜索|读取|写入|修改|创建|删除|安装|启动|截图|导航)",
        r"我(?:已|已经)(?:调用|执行|运行|打开|访问|搜索|读取|写入|修改|创建|删除|安装|启动|截图|导航)",
        r"(?:调用|执行|运行|打开|访问|搜索|读取|写入|修改|创建|删除|安装|启动|截图|导航).{0,12}(?:完成|成功|完毕)",
        r"(?:successfully|have|has)\s+(?:called|executed|run|opened|visited|searched|read|wrote|modified|created|deleted|installed|started)",
        # 将来时 - 声称要做什么（但实际还没做）
        r"让我(?:看看|搜索|查找|分析|执行|运行|检查|查看)",
        r"让我来(?:看看|搜索|查找|分析|执行|运行|检查|查看)",
        r"我来(?:看看|搜索|查找|分析|执行|运行|检查|查看)",
        r"我(?:将|要)去?(?:看看|搜索|查找|分析|执行|运行|检查|查看)",
        r"我(?:将|要)(?:调用|执行|运行|打开|访问|搜索|读取|写入|修改|创建|删除|安装|启动)",
        r"(?:let me|i'll|i am going to|i will)\s+(?:search|find|look|check|execute|run|read|write|open|visit|analyze)",
        r"(?:现在|马上|这就去)(?:搜索|查找|分析|执行|运行|检查)",
    ]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _is_error_result(result: str) -> bool:
    """检测工具返回结果是否为错误。"""
    if result.startswith("工具执行失败"):
        return True
    lower = result.lower()
    if "超时" in result or "timeout" in lower or "timed out" in lower:
        return True
    if "不在允许列表中" in result or "请使用 browser 工具" in result:
        return True
    if "executable doesn't exist" in lower or "please run the following command to download new browsers" in lower:
        return True
    if "error" in lower or "错误" in result or "失败" in result:
        return True
    return False


def _classify_error_type(error_msg: str) -> str:
    """将错误信息分类为语义类型。"""
    msg = error_msg.lower()
    if "permission" in msg or "权限" in error_msg or "denied" in msg or "拒绝" in error_msg:
        return "permission"
    elif "executable doesn't exist" in msg or "playwright install" in msg or "浏览器未安装" in error_msg:
        return "environment_missing"
    elif "timeout" in msg or "超时" in error_msg or "timed out" in msg:
        return "timeout"
    elif "invalid" in msg or "参数" in error_msg or "格式" in error_msg:
        return "invalid_args"
    return "generic"


def _validate_execution_claim(text: str, tools_used: list, commands_executed: list) -> Tuple[bool, Optional[str]]:
    """最终输出硬校验：声明执行必须有本轮工具证据。"""
    if _has_execution_claim(text) and not tools_used and not commands_executed:
        return False, (
            "你刚才的回复声称已经执行了任务，但本轮没有任何真实工具调用记录。"
            "禁止把计划、意图或文字描述当成执行结果。"
            "下一轮必须二选一：实际调用合适的工具；或明确说明尚未执行。"
        )
    return True, None


class AgentEngine:
    def __init__(self, llm=None):
        self.llm = llm
        self.context = ContextManager()
        self.memory_storage = MemoryStorage()
        self.vector_store = VectorStore()
        self._cli_executor = None  # 延迟初始化
        # ask 交互状态 {question_id: {"question": ..., "choices": ..., "user_response": None}}
        self._ask_pending: Dict[str, dict] = {}
        # 约束引擎：防止 agent 幻觉式自我欺骗
        # 延迟导入，模块不存在时降级为无约束模式
        self._constraint_engine = None
        try:
            from app.hermes.constraint import HermesConstraintEngine
            self._constraint_engine = HermesConstraintEngine()
            logger.info("ConstraintEngine 已加载")
        except ImportError:
            logger.warning("ConstraintEngine 未找到，约束验证已禁用")

        # Context Compressor — 自动压缩长对话
        # 默认 50% threshold，保护前 3 条 + 后 20 条
        self.context_compressor = ContextCompressor(
            context_length=128000,
            threshold_percent=0.50,
            protect_first_n=3,
            protect_last_n=20,
        )

    def set_ask_response(self, question_id: str, answer: str) -> bool:
        """存储用户对某个 ask 问题的回答"""
        if question_id in self._ask_pending:
            self._ask_pending[question_id]["user_response"] = answer
            logger.info(f"[ask] 回答已记录: question_id={question_id}")
            return True
        logger.warning(f"[ask] 问题不存在或已过期: question_id={question_id}")
        return False

    def get_ask_response(self, question_id: str) -> Optional[str]:
        """获取某个 ask 问题的用户回答"""
        entry = self._ask_pending.get(question_id)
        if entry:
            return entry.get("user_response")
        return None

    def _get_cli_executor(self):
        """获取 CLI 执行器（延迟初始化）"""
        if self._cli_executor is None:
            try:
                from app.domains import CLIExecutor
                self._cli_executor = CLIExecutor(working_dir=".")
                logger.info("CLIExecutor 已初始化")
            except Exception as e:
                logger.warning(f"CLIExecutor 初始化失败: {e}")
        return self._cli_executor

    def _try_fallback_llm(self):
        """尝试获取 fallback LLM（当主 provider 失败时）"""
        try:
            from app.services.llm_manager import LLMManager
            llm_mgr = LLMManager()
            available = ["openai", "anthropic", "deepseek", "google"]
            for provider in available:
                if provider == getattr(self.llm, 'provider', None):
                    continue
                api_key = llm_mgr.get_api_key(provider)
                if api_key:
                    from app.llm.factory import get_llm
                    fallback_llm = get_llm(provider, api_key)
                    if fallback_llm:
                        logger.info(f"找到 fallback LLM: {provider}")
                        return fallback_llm
        except Exception as e:
            logger.warning(f"获取 fallback LLM 失败: {e}")
        return None

    async def _ensure_domain_prompts(self, session_id: str):
        """注入身份与能力认知提示词（每次对话都注入，覆盖 LLM 默认自我认知）"""
        try:
            from app.domains import get_integrator
            integrator = get_integrator()
            prompt = integrator.get_all()
            if prompt:
                self.context.messages.insert(0, Message(
                    role="system",
                    content=prompt,
                    created_at=""
                ))
                logger.info(f"注入全部领域认知 ({len(integrator.get_domain_keys())} 个领域)")
            logger.warning(f"[DOMAIN] injected | context.messages count after={len(self.context.messages)}")
        except Exception as e:
            logger.warning(f"领域认知注入失败: {e}")

    async def _inject_memory(self, session_id: str):
        """注入平文件记忆内容（MEMORY.md / USER.md）"""
        try:
            from app.hermes.memory_file import MemoryFileManager
            mfm = MemoryFileManager(base_dir="./data/hermes")
            mem_content = mfm.read_memory()
            user_content = mfm.read_user()
            if mem_content:
                self.context.messages.insert(0, Message(
                    role="system",
                    content=f"[长期事实记忆]\n{mem_content}",
                    created_at=""
                ))
                logger.info("注入 MEMORY.md 长期记忆")
            if user_content:
                self.context.messages.insert(0, Message(
                    role="system",
                    content=f"[用户偏好]\n{user_content}",
                    created_at=""
                ))
                logger.info("注入 USER.md 用户画像")
            logger.warning(f"[MEMORY] injected | context.messages count after={len(self.context.messages)}")
        except Exception as e:
            logger.debug(f"平文件记忆注入跳过: {e}")

    async def _get_or_create_session(self) -> str:
        sessions = await self.memory_storage.get_sessions()
        if sessions:
            session_id = sessions[0].id
            await self._load_operation_habits(session_id)
            return session_id
        
        session = await self.memory_storage.create_session("默认会话")
        session_id = session.id
        
        await self._load_operation_habits(session_id)
        
        return session_id

    async def _load_operation_habits(self, session_id: str):
        if not self.llm:
            return
        
        try:
            shared_memories = await self.vector_store.get_shared()
            for habit in shared_memories[:3]:
                self.context.add_message("system", f"记住：{habit.content}")
                logger.info(f"加载操作习惯: {habit.content[:30]}...")
        except Exception as e:
            logger.warning(f"加载操作习惯失败: {e}")

    async def chat(
        self,
        session_id: Optional[str],
        message: str,
        use_memory: bool = True
    ) -> Dict[str, Any]:
        if not session_id:
            session_id = await self._get_or_create_session()
            logger.info(f"创建新会话: {session_id}")

        # 注入身份认知和记忆（放在上下文最前面，覆盖 LLM 默认认知）
        await self._inject_memory(session_id)
        await self._ensure_domain_prompts(session_id)

        # 注入环境能力（让 Agent 知道实际安装了哪些工具）
        from app.core.env_capabilities import get_env_prompt
        env_prompt = get_env_prompt()
        if env_prompt:
            self.context.add_message("system", env_prompt)

        # 加载历史对话
        historical_messages = await self.memory_storage.get_messages(session_id)
        for msg in historical_messages:
            self.context.add_message(msg.role, msg.content)

        # DEBUG: log message order after loading history
        ctx_msgs = self.context.get_messages()
        logger.warning(f"[CHAT] message_order | count={len(ctx_msgs)}, roles={[m.role for m in ctx_msgs]}")

        # ── Preflight Context Compression ──
        # 如果历史消息 token 数已经超过 50% threshold，在循环开始前先压缩
        if self.llm and self.context_compressor.should_compress(self.context.get_messages()):
            logger.info("chat() preflight: 上下文过长，触发压缩")
            compressed, _ = await self.context_compressor.compress(
                self.context.get_messages(), self.llm
            )
            self.context.messages = compressed
            self.context._token_estimate = None  # 清除缓存，否则 get_messages() 会重复压缩
            logger.warning(f"[COMPRESS] after_compress | roles={[m.role for m in compressed]}")

        self.context.add_message("user", message)
        logger.warning(f"[CHAT] before_llm_call | count={len(self.context.messages)}, last3_roles={[m.role for m in self.context.messages[-3:]]}")

        memories = []
        if use_memory and self.llm:
            try:
                embedding = await self.llm.get_embedding(message)
                memories = await self.vector_store.search(
                    message, embedding, k=5, session_id=session_id
                )
                if memories:
                    context = "\n".join([m.content for m in memories])
                    self.context.add_message("system", f"相关记忆：\n{context}")
                    logger.info(f"检索到 {len(memories)} 条记忆")
            except Exception as e:
                logger.error(f"记忆检索失败: {e}")

        response = "智能体已收到消息"
        tools_used = []
        commands_executed = []
        MAX_TOOL_ROUNDS = 20

        if self.llm:
            try:
                import json as _json
                from app.tools.manager import get_tool_manager
                tool_mgr = get_tool_manager()
                tool_schemas = tool_mgr.get_schemas()
                logger.info(f"Agent 可用工具: {tool_mgr.list_tools()}")

                # 工具调用循环 — 每轮都传递工具 schema，让 LLM 可在任意轮次调用工具
                for round_num in range(MAX_TOOL_ROUNDS):
                    llm_messages = [Message(role=m.role, content=m.content) for m in self.context.get_messages()]
                    logger.warning(f"[LLM_CALL] round={round_num} | msg_count={len(llm_messages)}, last3={[m.role for m in llm_messages[-3:]]}")
                    try:
                        llm_response = await self.llm.chat(messages=llm_messages, tools=tool_schemas)
                    except Exception as _tool_err:
                        # 部分模型（如 deepseek-reasoner）不支持工具调用，降级为无工具请求
                        logger.warning(f"带工具的 LLM 调用失败，降级为无工具请求: {_tool_err}")
                        llm_response = await self.llm.chat(messages=llm_messages, tools=None)
                        # 降级后直接取文本回复，不再尝试工具调用
                        response = llm_response.content
                        break

                    if not llm_response.has_tool_calls:
                        response = llm_response.content
                        break

                    # 处理工具调用
                    # 先将 assistant 的 tool_calls 消息加入上下文
                    tool_calls_data = [
                        {
                            "id": tc.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tc.tool_name,
                                "arguments": _json.dumps(tc.arguments, ensure_ascii=False)
                            }
                        }
                        for tc in llm_response.tool_calls
                    ]
                    assistant_tc_content = _json.dumps({
                        "content": llm_response.content or "",
                        "tool_calls": tool_calls_data
                    }, ensure_ascii=False)
                    self.context.add_message("assistant", assistant_tc_content)

                    for tc in llm_response.tool_calls:
                        tools_used.append(tc.tool_name)
                        emoji = _tool_registry.get_emoji(tc.tool_name)
                        logger.info(f"工具调用: {emoji} {tc.tool_name}({tc.arguments})")

                        # 执行工具
                        try:
                            tool_result = await tool_mgr.execute(tc.tool_name, tc.arguments)
                        except Exception as _tool_exec_err:
                            logger.error(f"工具执行失败 {emoji} {tc.tool_name}: {_tool_exec_err}")
                            tool_result = f"工具执行失败: {_tool_exec_err}"

                        # 记录命令执行
                        if tc.tool_name == "terminal":
                            commands_executed.append(tc.arguments.get("command", ""))

                        # 将工具结果以 JSON 格式追加到上下文（含 tool_call_id 供 DashScope 使用）
                        tool_msg_content = _json.dumps({
                            "tool_call_id": tc.tool_call_id,
                            "content": f"[工具 {tc.tool_name} 的返回结果]\n{tool_result}"
                        }, ensure_ascii=False)
                        self.context.add_message("tool", tool_msg_content)

                    logger.info(f"工具调用轮次 {round_num + 1}/{MAX_TOOL_ROUNDS}，工具: {[tc.tool_name for tc in llm_response.tool_calls]}")

                else:
                    # 循环耗尽仍未得到纯文本响应
                    response = "工具调用轮次已达上限，请基于已有结果回复。"
                    logger.warning(f"工具调用轮次耗尽 (max={MAX_TOOL_ROUNDS})")

            except Exception as e:
                logger.error(f"LLM调用失败: {e}", exc_info=True)
                response = "智能体已收到消息"

        # 约束：声称执行了但没有任何工具记录 → 强制说明（chat() 正常执行路径）
        is_valid, correction = _validate_execution_claim(response, tools_used, commands_executed)
        if not is_valid:
            response = (response + f"\n\n[{correction}]").strip()
            logger.warning(f"chat() 执行声明校验未通过: {correction[:80]}")

        # 如果使用了工具，在回复末尾附加执行反馈
        if tools_used:
            unique_tools = list(dict.fromkeys(tools_used))
            tool_summary = "\n\n---\n**已调用工具:** " + "、".join(unique_tools)
            if commands_executed:
                tool_summary += "\n**执行命令:** " + "、".join(commands_executed)
            response += tool_summary

        self.context.add_message("assistant", response)

        await self.memory_storage.add_message(session_id, "user", message)
        await self.memory_storage.add_message(session_id, "assistant", response)

        if self.llm:
            try:
                user_embedding = await self.llm.get_embedding(message)
                user_vector_id = await self.vector_store.add_text(
                    session_id, "user", message, user_embedding
                )
                if not user_vector_id:
                    logger.error(f"用户消息向量存储失败，返回空ID")

                assistant_embedding = await self.llm.get_embedding(response)
                assistant_vector_id = await self.vector_store.add_text(
                    session_id, "assistant", response, assistant_embedding
                )
                if not assistant_vector_id:
                    logger.error(f"助手回复向量存储失败，返回空ID")
            except Exception as e:
                logger.error(f"向量存储失败: {e}")

        self.context.clear()
        logger.info(f"会话 {session_id} 对话完成，消息已保存")

        return {
            "reply": response,
            "session_id": session_id,
            "memory_added": [m.model_dump() for m in memories],
            "tools_used": tools_used,
            "commands_executed": commands_executed,
        }

    async def stream_chat(
        self,
        session_id: Optional[str],
        message: str,
        use_memory: bool = True,
        step_callback: Optional[callable] = None,
        interim_assistant_callback: Optional[callable] = None,
        memory_manager: Optional[Any] = None,
        prompt_caching: bool = False,
        clarify_question_id: Optional[str] = None,
        clarify_answer: Optional[str] = None,
    ):
        """流式聊天（支持工具调用 + 进度反馈）

        Args:
            step_callback: 每次 API 调用前触发
            interim_assistant_callback: 流式输出中间思考过程
            memory_manager: 跨 session 记忆注入
            clarify_question_id: 续接 clarify 时的问题 ID
            clarify_answer: 用户对 clarify 问题的回答
            prompt_caching: 启用 prompt caching（Anthropic/Claude 模型通过 OpenRouter 时）
        """
        import time as _time
        import re as _re
        start_time = _time.time()

        def _progress(text: str):
            return {"type": "progress", "content": text, "timestamp": _time.time()}

        def _content(chunk: str):
            return {"type": "content", "content": chunk, "timestamp": _time.time()}

        def _tool_start(name: str, args: dict):
            emoji = _tool_registry.get_emoji(name)
            return {"type": "tool_start", "tool_name": name, "arguments": args,
                    "emoji": emoji, "timestamp": _time.time()}

        def _tool_complete(name: str, result: str, duration: float, error: bool = False):
            emoji = _tool_registry.get_emoji(name)
            preview = result.strip()[:120].replace("\n", " ")
            if len(result.strip()) > 120:
                preview += "..."
            return {"type": "tool_complete", "tool_name": name,
                    "result_preview": preview, "duration": round(duration, 2),
                    "error": error, "emoji": emoji, "timestamp": _time.time()}

        def _tool_error(name: str, error_msg: str):
            emoji = _tool_registry.get_emoji(name)
            return {"type": "tool_error", "tool_name": name, "error": error_msg,
                    "emoji": emoji, "timestamp": _time.time()}

        def _tool_result_structured(name: str, tool_call_id: str, success: bool,
                                    result: str = "", error_msg: str = "",
                                    error_type: str = "") -> dict:
            """构建结构化的工具执行结果，供模型自我修正参考"""
            emoji = _tool_registry.get_emoji(name)
            content = result if success else error_msg
            # 根据错误类型提供建议
            suggestion = ""
            if not success:
                if error_type == "not_found":
                    suggestion = "可尝试检查路径是否正确，或使用其他工具获取信息"
                elif error_type == "policy_blocked":
                    suggestion = "该路径被策略阻止，请停止绕过调用，直接基于当前失败原因回复用户"
                elif error_type == "permission":
                    suggestion = "请检查权限设置，或尝试其他操作方式"
                elif error_type == "environment_missing":
                    suggestion = "运行环境缺少所需浏览器依赖，请停止继续试错，直接告知用户需要先安装或配置环境"
                elif error_type == "timeout":
                    suggestion = "可尝试减小操作范围或增加超时时间"
                elif error_type == "invalid_args":
                    suggestion = "请检查参数格式是否正确"
            return {
                "tool_call_id": tool_call_id,
                "tool_name": name,
                "success": success,
                "content": content,
                "error_type": error_type,
                "suggestion": suggestion,
                "emoji": emoji,
            }

        def _format_tool_result_text(name: str, success: bool, result: str, error_msg: str = "", error_type: str = "", suggestion: str = "", tool_call_id: str = "") -> str:
            """将工具结果格式化为易读的纯文本，包含 tool_call_id 供 MiniMax 等 API 解析"""
            emoji = _tool_registry.get_emoji(name)
            if success:
                # 成功：简洁的结果描述
                preview = result.strip()[:500]
                if len(result.strip()) > 500:
                    preview += "\n...[结果已截断]"
                content = f"[{emoji} {name}] 执行成功:\n{preview}"
            else:
                # 失败：错误描述 + 建议
                lines = [f"[{emoji} {name}] 执行失败: {error_msg}"]
                if error_type:
                    lines.append(f"错误类型: {error_type}")
                if suggestion:
                    lines.append(f"建议: {suggestion}")
                content = "\n".join(lines)

            # 返回包含 tool_call_id 的 JSON 格式，供 MiniMax 等 API 解析
            return _json.dumps({
                "tool_call_id": tool_call_id,
                "content": content
            }, ensure_ascii=False)

        # _classify_error_type, _is_error_result, _has_execution_claim 已提到模块级
        # _validate_final_text 改为调用模块级 _validate_execution_claim

        async def _summarize_from_existing_context(reason: str) -> str:
            """预算耗尽或工具循环停止时，让模型基于已有 tool 结果生成最终文本。"""
            self.context.add_message(
                "system",
                f"{reason}\n"
                "现在必须停止继续调用工具，只能基于上方真实 tool 消息总结。"
                "禁止声称执行了没有工具记录的动作；工具失败必须如实说明失败。"
            )
            summary_messages = [Message(role=m.role, content=m.content) for m in self.context.get_messages()]
            try:
                summary_response = await self.llm.chat(messages=summary_messages, tools=None)
                # 追踪总结调用 token 使用量
                if summary_response.usage:
                    cumulative_usage["input_tokens"] += summary_response.usage.get("input_tokens", 0)
                    cumulative_usage["output_tokens"] += summary_response.usage.get("output_tokens", 0)
                    cumulative_usage["total_tokens"] += summary_response.usage.get("total_tokens", 0)
                cleaned, _thinking = _clean_thinking(summary_response.content or "")
                is_valid, correction = _validate_execution_claim(cleaned, tools_used, commands_executed)
                if not is_valid:
                    return correction or "工具调用已停止，但最终总结与执行记录不一致。"
                return cleaned or "工具调用已停止，未生成有效总结。"
            except Exception as exc:
                logger.warning("预算耗尽总结失败: %s", exc, exc_info=True)
                return f"工具调用已停止，但生成最终总结失败: {exc}"

        def _thinking_delta(text: str):
            return {"type": "thinking_delta", "content": text, "timestamp": _time.time()}

        def _thinking_done():
            return {"type": "thinking_done", "timestamp": _time.time()}

        def _done():
            return {"type": "done", "session_id": session_id or "",
                    "tools_used": list(dict.fromkeys(tools_used)),
                    "commands_executed": commands_executed,
                    "processing_time": round(_time.time() - start_time, 2),
                    "usage": cumulative_usage}

        def _tool_feedback(text: str):
            return {"type": "tool_feedback", "content": text, "timestamp": _time.time()}

        def _message_requires_tool_call(user_text: str) -> bool:
            text = (user_text or "").lower()
            triggers = [
                "请使用", "务必调用", "必须调用", "用工具", "调用工具",
                "playwright", "browser", "打开网页", "访问", "截图",
                "读取文件", "read_file", "search_files", "terminal"
            ]
            return any(token in text for token in triggers)

        def _message_requires_visible_chrome(user_text: str) -> bool:
            text = (user_text or "").lower()
            triggers = [
                "可视化", "可见窗口", "可见浏览器", "真实浏览器", "本地chrome",
                "本地 chrome", "google浏览器", "google chrome", "chrome浏览器",
                "用我的浏览器", "用我的 chrome", "在 chrome 里", "在浏览器里",
            ]
            return any(token in text for token in triggers)

        def _has_cdp_url(user_text: str) -> bool:
            text = user_text or ""
            return "ws://" in text and ("/json" in text or "/devtools/page/" in text)

        def _clean_thinking(text: str):
            """清理文本中的 <think>...晖 内容，返回 (清理后文本, thinking内容)"""
            match = _re.search(r'<think>([\s\S]*?)晖', text)
            if match:
                thinking = match.group(1)
                cleaned = _re.sub(r'<think>[\s\S]*?晖', '', text, count=1).strip()
                return cleaned, thinking
            match2 = _re.search(r'<think>([\s\S]*?)</think>', text)
            if match2:
                thinking = match2.group(1)
                cleaned = _re.sub(r'<think>[\s\S]*?</think>', '', text, count=1).strip()
                return cleaned, thinking
            return text, ""

        tools_used = []
        commands_executed = []
        ask_triggered = False  # 标记是否触发了 ask 交互
        final_response_chunks: List[str] = []
        budget = IterationBudget()
        must_use_tool = _message_requires_tool_call(message)
        forced_tool_retry_done = False
        final_claim_retry_done = False
        tool_results_for_hermes: List[Tuple[str, str]] = []  # Hermes 循环控制用

        def _classify_and_group_tools(tool_calls: list) -> Dict[str, list]:
            """按并行模式分组工具调用"""
            return _tool_registry.classify_tool_calls(tool_calls)

        async def _execute_safe_parallel(tool_calls: list, tool_mgr) -> Dict[str, Tuple[str, float]]:
            """并行执行 safe 模式的工具调用，返回 {id: (result, elapsed)}"""
            if not tool_calls:
                return {}

            async def _timed(tool_mgr, name, args):
                t0 = _time.time()
                try:
                    result = await tool_mgr.execute(name, args)
                except Exception as e:
                    result = f"工具执行失败: {e}"
                return result, _time.time() - t0

            tasks = [
                _timed(tool_mgr, tc["function"]["name"], _json.loads(tc["function"]["arguments"]))
                for tc in tool_calls
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            out = {}
            for tc, r in zip(tool_calls, results):
                if isinstance(r, Exception):
                    out[tc["id"]] = (str(r), 0.0)
                else:
                    out[tc["id"]] = r  # (result_str, elapsed_float)
            return out

        def _build_ask_events(tool_result: str, tool_args: dict) -> Optional[list]:
            """检测 tool result 中的 __ASK_BLOCK__: 标记，返回 ask 事件列表"""
            if not tool_result.startswith("__ASK_BLOCK__:"):
                return None
            parts = tool_result.split(":", 1)
            if len(parts) < 2:
                return None
            question_id = parts[1].strip()
            entry = self._ask_pending.get(question_id)
            if not entry:
                logger.warning(f"[ask] 问题不存在: {question_id}")
                return None
            question = entry["question"]
            choices = entry["choices"]
            logger.info(f"[ask] 检测到 ask 阻塞: question_id={question_id}, question={question[:30]}...")
            return [
                {"type": "progress", "content": "等待用户回答...", "timestamp": _time.time()},
                {"type": "ask", "question": question, "choices": choices, "question_id": question_id, "timestamp": _time.time()},
            ]

        if not session_id:
            session_id = await self._get_or_create_session()

        # ── ask 恢复逻辑：用户回答后重新发请求时，注入回答到 _ask_pending ──
        if clarify_question_id and clarify_answer:
            self.set_ask_response(clarify_question_id, clarify_answer)
            logger.info(f"[ask] 续接回答: question_id={clarify_question_id}, answer={clarify_answer[:30]}...")

        # ── 阶段 1: 加载上下文 ──
        yield _progress("加载身份认知...")
        await self._inject_memory(session_id)
        await self._ensure_domain_prompts(session_id)

        from app.core.env_capabilities import get_env_prompt
        env_prompt = get_env_prompt()
        if env_prompt:
            self.context.add_message("system", env_prompt)

        from app.core.skills_index import get_skills_prompt
        skills_prompt = get_skills_prompt()
        if skills_prompt:
            self.context.add_message("system", skills_prompt)

        yield _progress("加载历史对话...")
        historical_messages = await self.memory_storage.get_messages(session_id)
        for msg in historical_messages:
            self.context.add_message(msg.role, msg.content)

        self.context.add_message("user", message)

        if _message_requires_visible_chrome(message) and not _has_cdp_url(message):
            question_id = str(uuid.uuid4())
            question = (
                "你要求使用可视化的本地 Chrome。当前需要先提供 Chrome DevTools 连接地址（cdp_url）。\n"
                "请先用远程调试模式启动 Chrome，例如：\n"
                "macOS: /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
                "--remote-debugging-port=9222 --no-first-run --no-default-browser-check\n"
                "然后把 ws://localhost:9222/json 发给我。"
            )
            self._ask_pending[question_id] = {
                "question": question,
                "choices": [],
                "user_response": None,
                "timeout": False,
            }
            yield _progress("等待用户提供可视化 Chrome 的 CDP 连接地址...")
            yield {
                "type": "ask",
                "question": question,
                "choices": [],
                "question_id": question_id,
                "timestamp": _time.time(),
            }
            yield _done()
            self.context.clear()
            return

        # ── 阶段 2: 检索记忆 + memory_manager 跨 session 记忆注入 ──
        if use_memory and self.llm:
            yield _progress("检索相关记忆...")
            try:
                embedding = await self.llm.get_embedding(message)
                memories = await self.vector_store.search(
                    message, embedding, k=5, session_id=session_id
                )
                if memories:
                    context = "\n".join([m.content for m in memories])
                    self.context.add_message("system", f"相关记忆：\n{context}")
                    yield _progress(f"已检索 {len(memories)} 条相关记忆")
            except Exception:
                pass

        # ── memory_manager: 跨 session 记忆注入 ──
        if memory_manager:
            try:
                relevant_memories = await memory_manager.get_relevant_memories(
                    message, session_id=session_id, max_count=3
                )
                for mem in relevant_memories:
                    self.context.add_message("system", f"[跨会话记忆] {mem.content}")
                if relevant_memories:
                    yield _progress(f"跨 session 注入 {len(relevant_memories)} 条记忆")
            except Exception as e:
                logger.warning(f"memory_manager 跨 session 记忆注入失败: {e}")

        # ── 阶段 3: LLM 对话（支持工具调用） ──
        if not self.llm:
            yield _content("智能体已收到消息（LLM未初始化）")
            yield _done()
            self.context.clear()
            return

        try:
            import json as _json
            from app.tools.manager import get_tool_manager
            tool_mgr = get_tool_manager()
            tool_schemas = tool_mgr.get_schemas()
            logger.info(f"Agent stream_chat 可用工具: {tool_mgr.list_tools()}")

            # ── ReAct 工具调用循环（支持并行 + 预算控制） ──
            final_claim_retry_done = False  # 约束：防止声称执行但无工具证据
            cumulative_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}  # Token 使用量追踪
            while True:
                # 检查预算是否耗尽
                if budget.is_exhausted:
                    final_text = await _summarize_from_existing_context(budget.get_exhausted_message())
                    final_response_chunks.append(final_text)
                    yield _content(final_text)
                    break

                # ── Preflight Context Compression（循环内执行，在所有系统提示词注入之后）──
                # 触发条件：
                # 1. 首轮且 token 超过 50% threshold
                # 2. 剩余轮次 <= 5 时，降低 threshold 到 30%（更积极压缩）
                total_chars = sum(len(m.content or "") for m in self.context.messages)
                estimated_tokens = int(total_chars * 0.25)
                remaining_rounds = budget.remaining

                # 动态阈值：剩余轮次少时更积极压缩
                if remaining_rounds <= 5:
                    compress_threshold = int(self.context_compressor.threshold_tokens * 0.6)  # 30% context
                else:
                    compress_threshold = self.context_compressor.threshold_tokens

                if budget.current_round == 0 or remaining_rounds <= 5:
                    if estimated_tokens >= compress_threshold:
                        yield _progress("📦 上下文过长，正在压缩...")
                        compressed, summary_text = await self.context_compressor.compress(
                            self.context.get_messages(), self.llm
                        )
                        self.context.messages = compressed
                        self.context._token_estimate = None
                        yield _progress(f"📦 压缩完成: {summary_text[:80]}...")

                llm_messages = [Message(role=m.role, content=m.content) for m in self.context.get_messages()]

                # ── step_callback：每次 API 调用前触发 ──
                if step_callback:
                    try:
                        step_callback({
                            "round": budget.current_round + 1,
                            "remaining": budget.remaining,
                            "messages_count": len(llm_messages),
                        })
                    except Exception as e:
                        logger.warning(f"step_callback 执行失败: {e}")

                if budget.current_round == 0:
                    yield _progress("正在思考...")
                else:
                    yield _progress(f"继续处理 (第 {budget.current_round + 1} 轮)...")

                # 预算警告
                warning = budget.get_warning_message()
                if warning:
                    yield {"type": "budget_warning", "content": warning, "timestamp": _time.time()}

                try:
                    # ── prompt_caching: 为支持缓存的模型注入缓存提示 ──
                    if prompt_caching and self.llm:
                        cached_prompt_marker = "[缓存优化] 核心上下文已缓存，请基于已有信息继续推理"
                        # 在首轮注入缓存标记
                        if budget.current_round == 0:
                            self.context.add_message("system", cached_prompt_marker)

                    llm_response = await self.llm.chat(messages=llm_messages, tools=tool_schemas)
                    # 追踪 token 使用量
                    if llm_response.usage:
                        cumulative_usage["input_tokens"] += llm_response.usage.get("input_tokens", 0)
                        cumulative_usage["output_tokens"] += llm_response.usage.get("output_tokens", 0)
                        cumulative_usage["total_tokens"] += llm_response.usage.get("total_tokens", 0)
                    if llm_response.has_thinking:
                        for chunk in llm_response.thinking:
                            yield _thinking_delta(chunk)
                        yield _thinking_done()
                except Exception as _tool_err:
                    # LLM API 调用失败，尝试 fallback provider
                    logger.warning(f"带工具的 LLM 调用失败，尝试 fallback: {_tool_err}")
                    fallback_llm = self._try_fallback_llm()
                    if fallback_llm:
                        try:
                            llm_response = await fallback_llm.chat(messages=llm_messages, tools=tool_schemas)
                            # 追踪 fallback token 使用量
                            if llm_response.usage:
                                cumulative_usage["input_tokens"] += llm_response.usage.get("input_tokens", 0)
                                cumulative_usage["output_tokens"] += llm_response.usage.get("output_tokens", 0)
                                cumulative_usage["total_tokens"] += llm_response.usage.get("total_tokens", 0)
                            self.llm = fallback_llm  # 切换成功，更新主 LLM
                            logger.info("LLM fallback 成功，已切换 provider")
                        except Exception as fallback_err:
                            logger.error(f"LLM fallback 也失败: {fallback_err}")
                            llm_response = await self.llm.chat(messages=llm_messages, tools=None)
                    else:
                        # 无 fallback，降级为无工具请求
                        llm_response = await self.llm.chat(messages=llm_messages, tools=None)
                    # 追踪降级调用 token 使用量
                    if llm_response.usage:
                        cumulative_usage["input_tokens"] += llm_response.usage.get("input_tokens", 0)
                        cumulative_usage["output_tokens"] += llm_response.usage.get("output_tokens", 0)
                        cumulative_usage["total_tokens"] += llm_response.usage.get("total_tokens", 0)
                    full_text = llm_response.content
                    if full_text:
                        cleaned, thinking = _clean_thinking(full_text)
                        # 检测 __ASK_BLOCK__: 标记（LLM 降级路径的 fallback）
                        ask_match = _re.search(r'__ASK_BLOCK__:([a-f0-9\-]+)', full_text)
                        if ask_match:
                            question_id = ask_match.group(1)
                            entry = self._ask_pending.get(question_id)
                            if entry:
                                question = entry["question"]
                                choices = entry["choices"]
                            else:
                                question = "请回答以下问题"
                                choices = []
                            yield _progress("等待用户回答...")
                            yield {"type": "ask", "question": question, "choices": choices, "question_id": question_id, "timestamp": _time.time()}
                            break
                        executor = self._get_cli_executor()
                        cmd = executor.extract_from_response(full_text) if executor else None
                        if cmd:
                            _t0 = _time.time()
                            yield _tool_start("terminal", {"command": cmd})
                            try:
                                result = await tool_mgr.execute("terminal", {"command": cmd})
                                elapsed = _time.time() - _t0
                                is_error = _is_error_result(result)
                                yield _tool_complete("terminal", result, elapsed, error=is_error)
                                commands_executed.append(cmd)
                                if self._constraint_engine:
                                    self._constraint_engine.record_tool_execution(
                                        tool_name="terminal",
                                        arguments={"command": cmd},
                                        result=result,
                                        success=not is_error,
                                        timestamp=_time.time()
                                    )
                                self.context.add_message("tool", _json.dumps({
                                    "tool_call_id": "fallback",
                                    "content": f"[命令执行结果]\n{result}"
                                }, ensure_ascii=False))
                                llm_messages2 = [Message(role=m.role, content=m.content) for m in self.context.get_messages()]
                                llm_response2 = await self.llm.chat(messages=llm_messages2, tools=None)
                                if llm_response2.content:
                                    cleaned2, thinking2 = _clean_thinking(llm_response2.content)
                                    if thinking2:
                                        yield _thinking_delta(thinking2)
                                        yield _thinking_done()
                                    final_response_chunks.append(cleaned2)
                                    yield _content(cleaned2)
                            except Exception as _exec_err:
                                elapsed = _time.time() - _t0
                                yield _tool_error("terminal", str(_exec_err))
                        else:
                            is_valid, correction = _validate_execution_claim(cleaned, tools_used, commands_executed)
                            if not is_valid and not final_claim_retry_done:
                                final_claim_retry_done = True
                                self.context.add_message("assistant", f"[拦截的未执行回复]{cleaned}")
                                self.context.add_message("system", correction or "回复声称执行但没有工具证据，请纠正。")
                                continue
                            if not is_valid:
                                cleaned = correction or "我还没有实际执行该任务。"
                            if thinking:
                                yield _thinking_delta(thinking)
                                yield _thinking_done()
                            yield _content(cleaned)
                            final_response_chunks.append(cleaned)
                    break

                if not llm_response.has_tool_calls:
                    full_text = llm_response.content
                    if must_use_tool and not forced_tool_retry_done and not tools_used:
                        # 检查预算是否已耗尽，避免在预算耗尽后继续循环
                        if budget.is_exhausted:
                            yield _content(budget.get_exhausted_message())
                            break
                        forced_tool_retry_done = True
                        self.context.add_message(
                            "system",
                            "用户这次明确要求必须实际调用工具完成任务。"
                            "禁止直接基于已有上下文或记忆作答。"
                            "下一轮必须返回 tool_calls；若工具无法执行，要调用对应工具并把真实错误返回给用户。"
                        )
                        if full_text:
                            self.context.add_message(
                                "assistant",
                                f"[拦截的未执行回复]{full_text}"
                            )
                        budget.advance()  # 推进预算，即使被拦截
                        continue
                    if full_text:
                        cleaned, thinking = _clean_thinking(full_text)
                        is_valid, correction = _validate_execution_claim(cleaned, tools_used, commands_executed)
                        if not is_valid and not final_claim_retry_done:
                            final_claim_retry_done = True
                            self.context.add_message("assistant", f"[拦截的未执行回复]{cleaned}")
                            self.context.add_message("system", correction or "回复声称执行但没有工具证据，请纠正。")
                            yield _progress(f"[约束] {correction}")
                            budget.advance()  # 推进预算，即使被拦截
                            continue
                        if not is_valid:
                            yield _progress(f"[约束] {correction}")
                            cleaned = correction or "我还没有实际执行该任务。"
                        if thinking:
                            yield _thinking_delta(thinking)
                            yield _thinking_done()
                        yield _content(cleaned)
                        # 检测 __ASK_BLOCK__: 标记（fallback 自动检测）
                        ask_match = _re.search(r'__ASK_BLOCK__:([a-f0-9\-]+)', full_text)
                        if ask_match:
                            question_id = ask_match.group(1)
                            entry = self._ask_pending.get(question_id)
                            if entry:
                                question = entry["question"]
                                choices = entry["choices"]
                            else:
                                question = "请回答以下问题"
                                choices = []
                            yield _progress("等待用户回答...")
                            yield {"type": "ask", "question": question, "choices": choices, "question_id": question_id, "timestamp": _time.time()}
                            break
                        # 检测并执行 bash 代码块
                        executor = self._get_cli_executor()
                        cmd = executor.extract_from_response(full_text) if executor else None
                        if cmd:
                            _t0 = _time.time()
                            yield _tool_start("terminal", {"command": cmd})
                            try:
                                result = await tool_mgr.execute("terminal", {"command": cmd})
                                elapsed = _time.time() - _t0
                                is_error = _is_error_result(result)
                                yield _tool_complete("terminal", result, elapsed, error=is_error)
                                commands_executed.append(cmd)
                                # 将命令结果加入上下文，让 LLM 生成最终回复
                                self.context.add_message("tool", _json.dumps({
                                    "tool_call_id": "fallback",
                                    "content": f"[命令执行结果]\n{result}"
                                }, ensure_ascii=False))
                                # 再次调用 LLM 生成包含命令结果的最终回复
                                llm_messages2 = [Message(role=m.role, content=m.content) for m in self.context.get_messages()]
                                llm_response2 = await self.llm.chat(messages=llm_messages2, tools=None)
                                if llm_response2.content:
                                    cleaned2, thinking2 = _clean_thinking(llm_response2.content)
                                    if thinking2:
                                        yield _thinking_delta(thinking2)
                                        yield _thinking_done()
                                    final_response_chunks.append(cleaned2)
                                    yield _content(cleaned2)
                            except Exception as _exec_err:
                                elapsed = _time.time() - _t0
                                yield _tool_error("terminal", str(_exec_err))
                        else:
                            final_response_chunks.append(cleaned)
                    # 推进预算（正常退出：有文本响应，工具调用轮次结束）
                    budget.advance()
                    break

                # ── interim_assistant_callback：流式输出中间思考 ──
                if interim_assistant_callback and llm_response.content:
                    try:
                        interim_assistant_callback(llm_response.content)
                    except Exception as e:
                        logger.warning(f"interim_assistant_callback 执行失败: {e}")

                # ── 处理工具调用 ──
                tool_calls_data = [
                    {"id": tc.tool_call_id, "type": "function",
                     "function": {"name": tc.tool_name, "arguments": _json.dumps(tc.arguments, ensure_ascii=False)}}
                    for tc in llm_response.tool_calls
                ]
                self.context.add_message("assistant", _json.dumps({
                    "content": llm_response.content or "", "tool_calls": tool_calls_data
                }, ensure_ascii=False))

                # 按并行模式分组
                groups = _classify_and_group_tools(tool_calls_data)
                never_calls = groups.get("never", [])
                safe_calls = groups.get("safe", [])
                path_scoped_calls = groups.get("path_scoped", [])

                # 执行 never 模式（串行）
                for tc in never_calls:
                    tool_name = tc["function"]["name"]
                    args = _json.loads(tc["function"]["arguments"])
                    tools_used.append(tool_name)

                    yield _tool_start(tool_name, args)
                    _tool_t0 = _time.time()
                    is_error = True

                    try:
                        tool_result = await tool_mgr.execute(tool_name, args)
                        _elapsed = _time.time() - _tool_t0
                        is_error = _is_error_result(tool_result)
                        yield _tool_complete(tool_name, tool_result, _elapsed, error=is_error)
                        result_structured = _tool_result_structured(tool_name, tc["id"], not is_error, result=tool_result if not is_error else "",
                            error_msg=tool_result if is_error else "", error_type=_classify_error_type(tool_result) if is_error else "")
                        # 检测 ask 交互
                        ask_events = _build_ask_events(tool_result, args)
                        if ask_events:
                            ask_triggered = True
                            for ev in ask_events:
                                yield ev
                            break  # 跳出工具执行循环，等待用户回答
                    except Exception as _tool_exec_err:
                        _elapsed = _time.time() - _tool_t0
                        error_msg = str(_tool_exec_err)
                        error_type = _classify_error_type(error_msg)
                        yield _tool_error(tool_name, error_msg)
                        tool_result = f"工具执行失败: {_tool_exec_err}"
                        result_structured = _tool_result_structured(
                            tool_name, tc["id"], False, error_msg=error_msg, error_type=error_type
                        )

                    if tool_name == "terminal":
                        commands_executed.append(args.get("command", ""))

                    # 存储易读的纯文本
                    tool_text = _format_tool_result_text(
                        name=tool_name,
                        success=not is_error,
                        result=tool_result if not is_error else "",
                        error_msg=tool_result if is_error else "",
                        error_type=_classify_error_type(tool_result) if is_error else "",
                        suggestion=result_structured.get("suggestion", "") if is_error else "",
                        tool_call_id=tc["id"]
                    )
                    self.context.add_message("tool", tool_text)

                    # 约束：记录工具执行结果，防止 agent 幻觉
                    if self._constraint_engine:
                        self._constraint_engine.record_tool_execution(
                            tool_name=tool_name,
                            arguments=args,
                            result=tool_result,
                            success=not is_error,
                            timestamp=_time.time()
                        )
                        tool_results_for_hermes.append((tool_name, tool_result))

                # 执行 safe 模式（并行）
                if safe_calls:
                    safe_results = await _execute_safe_parallel(safe_calls, tool_mgr)
                    for tc in safe_calls:
                        tool_name = tc["function"]["name"]
                        args = _json.loads(tc["function"]["arguments"])
                        tools_used.append(tool_name)
                        result_elapsed = safe_results.get(tc["id"], ("Unknown result", 0.0))
                        tool_result, _elapsed = result_elapsed if isinstance(result_elapsed, tuple) else (str(result_elapsed), 0.0)

                        yield _tool_start(tool_name, args)
                        is_error = _is_error_result(tool_result)
                        yield _tool_complete(tool_name, tool_result, _elapsed, error=is_error)
                        result_structured = _tool_result_structured(
                            tool_name, tc["id"], not is_error, result=tool_result if not is_error else "",
                            error_msg=tool_result if is_error else "", error_type=_classify_error_type(tool_result) if is_error else ""
                        )
                        # 检测 ask 交互
                        if not is_error:
                            ask_events = _build_ask_events(tool_result, args)
                            if ask_events:
                                ask_triggered = True
                                for ev in ask_events:
                                    yield ev
                                break  # 跳出 safe 执行循环

                        if tool_name == "terminal":
                            commands_executed.append(args.get("command", ""))

                        # 存储易读的纯文本
                        tool_text = _format_tool_result_text(
                            name=tool_name,
                            success=not is_error,
                            result=tool_result if not is_error else "",
                            error_msg=tool_result if is_error else "",
                            error_type=_classify_error_type(tool_result) if is_error else "",
                            suggestion=result_structured.get("suggestion", "") if is_error else "",
                            tool_call_id=tc["id"]
                        )
                        self.context.add_message("tool", tool_text)

                        if self._constraint_engine:
                            self._constraint_engine.record_tool_execution(
                                tool_name=tool_name,
                                arguments=args,
                                result=tool_result,
                                success=not is_error,
                                timestamp=_time.time()
                            )
                            tool_results_for_hermes.append((tool_name, tool_result))

                if ask_triggered:
                    budget.advance()  # 推进预算
                    break  # ask 交互触发，等待用户回答

                # 执行 path_scoped 模式（目前串行，后续可扩展路径冲突检测）
                for tc in path_scoped_calls:
                    tool_name = tc["function"]["name"]
                    args = _json.loads(tc["function"]["arguments"])
                    tools_used.append(tool_name)

                    yield _tool_start(tool_name, args)
                    _tool_t0 = _time.time()
                    is_error = True

                    try:
                        tool_result = await tool_mgr.execute(tool_name, args)
                        _elapsed = _time.time() - _tool_t0
                        is_error = _is_error_result(tool_result)
                        yield _tool_complete(tool_name, tool_result, _elapsed, error=is_error)
                        result_structured = _tool_result_structured(tool_name, tc["id"], not is_error, result=tool_result if not is_error else "",
                            error_msg=tool_result if is_error else "", error_type=_classify_error_type(tool_result) if is_error else "")
                        # 检测 ask 交互
                        ask_events = _build_ask_events(tool_result, args)
                        if ask_events:
                            ask_triggered = True
                            for ev in ask_events:
                                yield ev
                            break  # 跳出 path_scoped 执行循环
                    except Exception as _tool_exec_err:
                        _elapsed = _time.time() - _tool_t0
                        error_msg = str(_tool_exec_err)
                        error_type = _classify_error_type(error_msg)
                        yield _tool_error(tool_name, error_msg)
                        tool_result = f"工具执行失败: {_tool_exec_err}"
                        result_structured = _tool_result_structured(
                            tool_name, tc["id"], False, error_msg=error_msg, error_type=error_type
                        )

                    if tool_name == "terminal":
                        commands_executed.append(args.get("command", ""))

                    # 存储易读的纯文本
                    tool_text = _format_tool_result_text(
                        name=tool_name,
                        success=False,
                        result="",
                        error_msg=error_msg,
                        error_type=error_type,
                        suggestion=result_structured.get("suggestion", ""),
                        tool_call_id=tc.get("id", "")
                    )
                    self.context.add_message("tool", tool_text)

                    if self._constraint_engine:
                        self._constraint_engine.record_tool_execution(
                            tool_name=tool_name,
                            arguments=args,
                            result=tool_result,
                            success=False,
                            timestamp=_time.time()
                        )
                        tool_results_for_hermes.append((tool_name, tool_result))

                if ask_triggered:
                    budget.advance()  # 推进预算
                    break  # ask 交互触发，等待用户回答

                # ── Hermes 循环控制：在推进预算前，客观判断是否该继续 ──
                if self._constraint_engine and tool_results_for_hermes:
                    should_cont, reason = self._constraint_engine.should_continue_loop(
                        tools_used=tools_used,
                        tool_results=tool_results_for_hermes,
                        current_round=budget.current_round + 1
                    )
                    if not should_cont:
                        logger.info(f"[Hermes] 循环控制: {reason}")
                        yield _progress(f"[Hermes] {reason}")
                        final_text = await _summarize_from_existing_context(
                            f"[循环终止] {reason}\n基于已有工具执行结果生成总结。"
                        )
                        final_response_chunks.append(final_text)
                        yield _content(final_text)
                        break

                # 推进预算
                if not budget.advance():
                    # 预算耗尽前，尝试最后一次压缩
                    if budget.current_round >= budget.max_rounds - 2:
                        total_chars = sum(len(m.content or "") for m in self.context.messages)
                        estimated_tokens = int(total_chars * 0.25)
                        # 如果上下文较大，尝试压缩后给一次额外机会
                        if estimated_tokens >= self.context_compressor.threshold_tokens * 0.5:
                            yield _progress("📦 预算即将耗尽，尝试最后一次压缩...")
                            compressed, summary_text = await self.context_compressor.compress(
                                self.context.get_messages(), self.llm
                            )
                            self.context.messages = compressed
                            self.context._token_estimate = None
                            # 给一次额外轮次
                            budget.current_round = budget.max_rounds - 1
                            budget.grace_used = budget.grace_calls - 1
                            yield _progress(f"📦 压缩完成，获得额外执行机会: {summary_text[:80]}...")
                            continue
                    final_text = await _summarize_from_existing_context(budget.get_exhausted_message())
                    final_response_chunks.append(final_text)
                    yield _content(final_text)
                    break

        except Exception as e:
            logger.error(f"LLM调用失败: {e}", exc_info=True)
            yield _content(f"智能体已收到消息（发生错误: {str(e)}）")

        # ── 附加工具反馈 ──
        if tools_used:
            unique_tools = list(dict.fromkeys(tools_used))
            feedback = "\n\n---\n**已调用工具:** " + "、".join(unique_tools)
            if commands_executed:
                feedback += "\n**执行命令:** " + "、".join(commands_executed)
            yield _tool_feedback(feedback)

        # ── 保存 ──
        yield _progress("保存对话记录...")
        # 收集完整回复用于存储（从 context 最后的 assistant 消息中取）
        import re
        final_reply = "".join(final_response_chunks).strip()
        if not final_reply:
            for m in reversed(self.context.get_messages()):
                if m.role == "assistant":
                    try:
                        d = _json.loads(m.content)
                        final_reply = d.get("content", "")
                    except (_json.JSONDecodeError, AttributeError):
                        final_reply = m.content
                    if final_reply:
                        break
        if not final_reply:
            final_reply = "（无回复内容）"
        # 清理 <think>...晖 思考标签，不存入数据库
        final_reply = re.sub(r'<think>[\s\S]*?晖', '', final_reply, flags=re.DOTALL).strip()
        final_reply = re.sub(r'<think>[\s\S]*?</think>', '', final_reply, flags=re.DOTALL).strip()
        # 清理 Qwen 风格的 <|im_start|>...<|im_end|> 标签
        final_reply = re.sub(r'<\|im_start\|[^|]*\|[^>]*>[\s\S]*?<\|im_end\|>', '', final_reply).strip()

        self.context.add_message("assistant", final_reply)
        await self.memory_storage.add_message(session_id, "user", message)
        await self.memory_storage.add_message(session_id, "assistant", final_reply)
        self.context.clear()
        # 重置 Hermes 约束引擎状态，避免跨任务误判循环
        if self._constraint_engine:
            self._constraint_engine.reset_session()

        yield _done()

    async def create_session(self, name: str) -> Session:
        return await self.memory_storage.create_session(name)

    async def get_sessions(self) -> List[Session]:
        return await self.memory_storage.get_sessions()

    async def get_session_memories(self, session_id: str) -> List[Memory]:
        return await self.memory_storage.get_memories(session_id)

    async def search_memories(
        self,
        query: str,
        k: int = 10,
        session_id: Optional[str] = None
    ) -> List[Memory]:
        if not self.llm:
            return await self.memory_storage.get_memories(session_id)

        try:
            embedding = await self.llm.get_embedding(query)
            return await self.vector_store.search(query, embedding, k=k, session_id=session_id)
        except Exception as e:
            logger.error(f"记忆搜索失败: {e}")
            return await self.memory_storage.get_memories(session_id)

    async def add_memory(
        self,
        memory_type: str,
        content: str,
        importance: int = 1,
        session_id: Optional[str] = None
    ) -> Memory:
        from uuid import uuid4
        from datetime import datetime

        memory = Memory(
            id=str(uuid4()),
            type=memory_type,
            content=content,
            importance=importance,
            session_id=session_id,
            created_at=datetime.now().isoformat()
        )

        await self.memory_storage.add_memory(memory)
        logger.info(f"添加记忆: {memory_type} - {content[:20]}...")

        if self.llm:
            try:
                embedding = await self.llm.get_embedding(content)
                memory.vector_id = await self.vector_store.add(memory, embedding)
                logger.info(f"记忆已向量化: {memory.id}")
            except Exception as e:
                logger.error(f"记忆向量化失败: {e}")

        return memory

    async def update_memory(self, memory_id: str, content: str, importance: Optional[int] = None) -> Optional[Memory]:
        return await self.memory_storage.update_memory(memory_id, content, importance)

    async def delete_memory(self, memory_id: str) -> bool:
        return await self.memory_storage.delete_memory(memory_id)

    async def update_session(self, session_id: str, name: str) -> Optional[Session]:
        return await self.memory_storage.update_session(session_id, name)

    async def delete_session(self, session_id: str):
        await self.memory_storage.delete_session(session_id)

    async def get_previous_message(self, session_id: str, current_sequence: int) -> Optional[Message]:
        return await self.memory_storage.get_previous_message(session_id, current_sequence)

    async def get_last_user_message(self, session_id: str) -> Optional[Message]:
        return await self.memory_storage.get_last_user_message(session_id)

    async def get_message_by_sequence(self, session_id: str, sequence: int) -> Optional[Message]:
        return await self.memory_storage.get_message_by_sequence(session_id, sequence)

    async def get_conversation_stats(self, session_id: str) -> dict:
        messages = await self.memory_storage.get_messages(session_id)
        memories = await self.memory_storage.get_memories(session_id)
        return {
            "total_messages": len(messages),
            "total_memories": len(memories),
            "session_id": session_id,
        }

    async def get_memory_versions(self, memory_id: str):
        return await self.memory_storage.get_memory_versions(memory_id)

    async def verify_memory_loading(self, session_id: str) -> dict:
        memories = await self.memory_storage.get_memories(session_id)
        settings = await self.memory_storage.get_all_settings(session_id)
        return {
            "total_memories": len(memories),
            "settings": settings,
            "operation_habits": [m for m in memories if m.type == "操作习惯"],
            "conclusions": [m for m in memories if m.type == "分析结论"],
            "decisions": [m for m in memories if m.type == "关键决策"],
        }

    async def add_setting(self, session_id: str, key: str, value: str, setting_type: str = "string") -> dict:
        return await self.memory_storage.add_setting(session_id, key, value, setting_type)

    async def get_all_settings(self, session_id: str) -> list:
        return await self.memory_storage.get_all_settings(session_id)

    async def get_setting(self, session_id: str, key: str) -> Optional[dict]:
        return await self.memory_storage.get_setting(session_id, key)

    async def update_setting(self, session_id: str, key: str, value: str) -> Optional[dict]:
        return await self.memory_storage.update_setting(session_id, key, value)

    async def delete_setting(self, session_id: str, key: str) -> bool:
        return await self.memory_storage.delete_setting(session_id, key)

    async def get_conversation_history(self, session_id: str) -> List[Message]:
        return await self.memory_storage.get_messages(session_id)

    async def get_shared_memories(self, query: str, k: int = 5) -> List[Memory]:
        if not self.llm:
            return []

        try:
            embedding = await self.llm.get_embedding(query)
            return await self.vector_store.search(
                query, embedding, k=k, session_id=None, is_shared=True
            )
        except Exception:
            return []
