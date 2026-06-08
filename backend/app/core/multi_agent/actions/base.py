"""
Action 基类 + LLM 调用基础设施

TeamAction: 所有 Action 的抽象基类
LLMError: LLM 调用失败异常
_get_llm_for_role / _call_llm: LLM 实例获取和调用辅助

v2 改进：
- Workspace 支持：代码写入工作区文件，不塞 content
- EventBus 支持：action 执行时发布事件，其他 Agent 可感知
- ExecutionContext 支持：通过 context 访问 TaskExecutionContext
"""

from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import TYPE_CHECKING, List, Optional, Union
import asyncio
import re
import logging

from app.core.base import Message

if TYPE_CHECKING:
    from app.core.multi_agent.role import TeamRole, RoleContext
    from app.core.multi_agent.execution_context import TaskExecutionContext

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用失败错误（配置缺失、超时等），与业务异常区分"""
    pass


# ── LLM 辅助函数 ──────────────────────────────────────────

def _get_llm_for_role(role: "TeamRole"):
    """根据 role 的 LLM 配置获取对应的 LLM 实例"""
    from app.llm.factory import get_llm
    from app.services.llm_manager import LLMManager
    llm_mgr = LLMManager()
    provider = role.llm_provider or "deepseek"
    api_key = llm_mgr.get_api_key(provider)
    logger.info(f"[ACTION] _get_llm_for_role: role={role.name}, llm_provider={role.llm_provider}, resolved={provider}, has_key={bool(api_key)}")
    if not api_key:
        # 回退到用户当前配置的 LLM 提供者
        current = llm_mgr.get_current_provider()
        logger.warning(f"[ACTION] {provider} API key 未配置，尝试当前提供者: {current}")
        provider = current
        api_key = llm_mgr.get_api_key(provider)
    if not api_key:
        # 再尝试 openai
        logger.warning(f"[ACTION] {provider} 也无 API key，尝试 openai")
        provider = "openai"
        api_key = llm_mgr.get_api_key("openai")
    if not api_key:
        # 最后尝试任何有 key 的提供者
        for p in ["minimax", "tongyi", "deepseek", "moonshot"]:
            key = llm_mgr.get_api_key(p)
            if key:
                logger.info(f"[ACTION] 回退到 {p}")
                provider = p
                api_key = key
                break
    if not api_key:
        logger.error(f"[ACTION] 所有 LLM 提供者均未配置 API key")
        return None
    model = role.llm_model or ""
    try:
        return get_llm(provider, api_key, model=model)
    except Exception as e:
        logger.error(f"[ACTION] 获取 LLM 失败 (provider={provider}, model={model}): {e}")
        return None


async def _call_llm(role: "TeamRole", messages: List[Union[dict, Message]], tools: Optional[List[dict]] = None, timeout: int = 120) -> str:
    """调用 LLM 并返回 content（异步，带超时保护）"""
    llm = _get_llm_for_role(role)
    if not llm:
        raise LLMError(f"LLM 未配置，请检查 {role.llm_provider} API Key")

    # 将 dict 消息转为 Message 对象
    llm_messages: List[Message] = [
        Message(role=m["role"], content=m["content"]) if isinstance(m, dict) else m
        for m in messages
    ]

    # 注入角色系统提示词（含上下游连接上下文），仅在有内容时注入
    system_prompt = role.build_system_prompt()
    if system_prompt:
        llm_messages.insert(0, Message(role="system", content=system_prompt))

    try:
        if tools:
            response = await asyncio.wait_for(llm.chat(messages=llm_messages, tools=tools), timeout=timeout)
        else:
            response = await asyncio.wait_for(llm.chat(messages=llm_messages), timeout=timeout)
        return response.content
    except asyncio.TimeoutError:
        raise LLMError(f"LLM 调用超时（{timeout}秒），请重试")


# ── Action 基类 ──────────────────────────────────────────

class TeamAction(ABC, BaseModel):
    """
    行为单元基类（v2 - Workspace + EventBus 支持）
    
    改进点：
    - 通过 _workspace 写文件，不塞 content
    - 通过 _publish_event 发布事件
    - 执行结果摘要化，不传大段内容
    """
    name: str = "TeamAction"
    description: str = ""
    send_to: str = ""   # 消息路由目标（空=广播，非空=定向发送给指定 Agent）

    # ── Workspace 支持 ─────────────────────────────────

    def _workspace_path(self, context: "RoleContext", sub: str, filename: str = "") -> str:
        """
        获取当前任务的工作区文件路径。
        
        从 context._execution_context 或 context.news metadata 中提取 task_id。
        """
        task_id = self._get_task_id(context)
        if not task_id:
            return ""
        from app.core.multi_agent.workspace import get_workspace
        ws = get_workspace(task_id, create=False)
        if not ws:
            return ""
        p = ws.path(sub, filename) if filename else ws.path(sub)
        return str(p)

    def _get_task_id(self, context: "RoleContext") -> str:
        """从 context 中提取 task_id"""
        # 优先从 _execution_context
        ec = getattr(context, "_execution_context", None)
        if ec:
            return ec.task_id
        
        # 从最新消息的 metadata 提取
        if context.news:
            latest = context.news[-1]
            task_id = latest.metadata.get("task_id", "")
            if task_id:
                return task_id
        return ""

    def _write_workspace(self, context: "RoleContext", sub: str, filename: str, content: str) -> str:
        """
        写入工作区文件。
        
        Args:
            context:   RoleContext
            sub:       子目录（input/output/artifacts/logs）
            filename:  文件名
            content:   文件内容
        
        Returns:
            workspace 相对路径（用于摘要）
        """
        task_id = self._get_task_id(context)
        if not task_id:
            logger.warning(f"[TeamAction] 无法确定 task_id，跳过 workspace 写入")
            return ""
        
        from app.core.multi_agent.workspace import get_workspace
        ws = get_workspace(task_id, create=True)
        ws.init()
        path = ws.write(sub, filename, content)
        
        # 返回相对路径（用于消息摘要）
        return f"workspace/{sub}/{filename}"

    def _read_workspace(self, context: "RoleContext", sub: str, filename: str) -> str:
        """读取工作区文件"""
        task_id = self._get_task_id(context)
        if not task_id:
            return ""
        from app.core.multi_agent.workspace import get_workspace
        ws = get_workspace(task_id, create=False)
        if not ws:
            return ""
        try:
            return ws.read(sub, filename)
        except FileNotFoundError:
            return ""

    # ── EventBus 支持 ─────────────────────────────────

    async def _publish_event(
        self,
        context: "RoleContext",
        event_type: str,
        payload: Optional[dict] = None,
    ) -> None:
        """发布事件到 EventBus"""
        from app.core.multi_agent.event_bus import get_event_bus
        from app.core.multi_agent.state_machine import TaskEvent

        task_id = self._get_task_id(context)
        session_id = getattr(context, "session_id", "") if context else ""
        
        # 获取发送方角色名
        sender = ""
        if context and hasattr(context, "role_name"):
            sender = context.role_name
        elif context and context.news:
            sender = context.news[-1].sent_from

        bus = get_event_bus()
        await bus.publish(
            event_type=event_type,
            payload=payload or {},
            source=sender,
            task_id=task_id,
            session_id=session_id,
        )

    # ── 抽象接口 ─────────────────────────────────

    @abstractmethod
    async def run(
        self, role: "TeamRole", context: "RoleContext"
    ) -> str:
        """
        执行行为并返回结果字符串

        Args:
            role: 正在执行该行为的 Role
            context: 运行时上下文（包含 todo, news, memory 等）

        Returns:
            str: 执行结果（TaskPayload JSON 字符串或兼容回退纯文本）
            
        v2 约定：
        - 大段内容写 workspace，消息 content 只传摘要路径
        - 执行完成时调用 _publish_event 发布事件
        """
        pass

    def get_memory_text(self, context: "RoleContext") -> str:
        """从上下文构建记忆文本（供 LLM 做上下文）"""
        if not context.memory:
            return ""
        return "\n".join([
            f"{msg.sent_from}: {msg.content}"
            for msg in context.memory[-10:]  # 最近 10 条
        ])

    @staticmethod
    def _parse_code(text: str) -> str:
        """从 LLM 输出中提取代码块"""
        match = re.search(r"```python\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()
