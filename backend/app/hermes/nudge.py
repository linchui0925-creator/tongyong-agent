"""
NudgeEngine - 后台反思引擎 (Hermes 风格)

在用户无感知的情况下后台审查对话，自动生成记忆和技能。
- 每 N 次用户轮 → 审查并更新 MEMORY.md/USER.md
- 每 N 次工具调用 → 审查并创建/修补 SKILL.md
- 审查 prompt 以 "Nothing to save? Just stop." 结尾，防止刷数据
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

_MEMORY_REVIEW_PROMPT = """You are a memory curator. Review the recent conversation and decide if anything should be saved to the agent's long-term memory files.

MEMORY.md stores **declarative facts** about the project, environment, conventions, and workarounds. Only save facts that are:
- Non-obvious and would be useful in future sessions
- Project-specific conventions or decisions
- Environment setup details or workarounds
- User preferences that affect how work is done

USER.md stores **user preferences and communication style**:
- Preferred response style (concise, detailed, etc.)
- Coding style preferences
- Commonly used tools or workflows
- Personal conventions

Current MEMORY.md:
{memory_content}

Current USER.md:
{user_content}

Recent conversation:
{conversation_history}

Respond with JSON:
- If nothing worth saving: {{"action": "skip"}}
- To add to MEMORY.md: {{"action": "add_memory", "entry": "the fact to save"}}
- To add to USER.md: {{"action": "add_user", "entry": "the preference to save"}}
- To replace in MEMORY.md: {{"action": "replace_memory", "old": "exact text to replace", "new": "new text"}}
- To replace in USER.md: {{"action": "replace_user", "old": "exact text to replace", "new": "new text"}}

If nothing is worth saving, just say {{"action": "skip"}} and stop."""

_SKILL_REVIEW_PROMPT = """You are a skill curator. Review recent tool calls and task executions to decide if a reusable skill should be created or updated.

A skill should be created when:
- A complex task was completed successfully (5+ tool calls or 3+ unique actions)
- A non-trivial workflow was discovered
- A tricky bug was fixed with a specific procedure
- The user corrected the approach, revealing a better way

Current skills:
{skills_list}

Recent execution history:
{execution_history}

Respond with JSON:
- If nothing worth saving: {{"action": "skip"}}
- To create a skill: {{"action": "create_skill", "name": "skill-name", "description": "brief description", "steps": ["step1", "step2", ...], "pitfalls": ["pitfall1", ...], "category": "category-name"}}
- To patch an existing skill: {{"action": "patch_skill", "name": "skill-name", "old": "text to replace", "new": "replacement text"}}

If nothing is worth saving, just say {{"action": "skip"}} and stop."""


class NudgeEngine:
    """后台反思引擎"""

    def __init__(
        self,
        memory_manager=None,
        skill_manager=None,
        llm=None,
        memory_interval: int = 10,
        skill_interval: int = 10,
    ):
        self.memory_manager = memory_manager
        self.skill_manager = skill_manager
        self.llm = llm

        self.memory_interval = memory_interval
        self.skill_interval = skill_interval

        self._user_turn_count = 0
        self._tool_call_count = 0
        self._conversation_buffer: List[Dict] = []
        self._execution_buffer: List[Dict] = []
        self._running = False

        logger.info(f"NudgeEngine 初始化 (memory_every={memory_interval}, skill_every={skill_interval})")

    # ── 事件接口 ──────────────────────────────

    def on_user_message(self, message: str):
        """用户消息事件"""
        self._user_turn_count += 1
        self._conversation_buffer.append({
            "role": "user",
            "content": message[:500],
            "time": datetime.now().isoformat(),
        })
        self._trim_buffer(self._conversation_buffer, max_len=20)

    def on_assistant_message(self, message: str):
        """助手回复事件"""
        self._conversation_buffer.append({
            "role": "assistant",
            "content": message[:500],
            "time": datetime.now().isoformat(),
        })
        self._trim_buffer(self._conversation_buffer, max_len=20)

    def on_tool_call(self, tool_name: str, params: Dict, result: str, success: bool):
        """工具调用事件"""
        self._tool_call_count += 1
        self._execution_buffer.append({
            "tool": tool_name,
            "params": params,
            "result": str(result)[:300],
            "success": success,
            "time": datetime.now().isoformat(),
        })
        self._trim_buffer(self._execution_buffer, max_len=30)

    # ── 触发检查 ──────────────────────────────

    async def check_and_nudge(self):
        """检查是否需要触发反思，异步执行不阻塞"""
        memory_triggered = self._user_turn_count > 0 and self._user_turn_count % self.memory_interval == 0
        skill_triggered = self._tool_call_count > 0 and self._tool_call_count % self.skill_interval == 0

        if memory_triggered:
            asyncio.create_task(self._run_memory_review())

        if skill_triggered:
            asyncio.create_task(self._run_skill_review())

    # ── 后台审查 ──────────────────────────────

    async def _run_memory_review(self):
        """后台执行记忆审查"""
        if self._running or not self.llm or not self.memory_manager:
            return
        self._running = True
        try:
            memory_content = self.memory_manager.read_memory()
            user_content = self.memory_manager.read_user()
            history = self._format_conversation()

            if not history:
                return

            prompt = _MEMORY_REVIEW_PROMPT.format(
                memory_content=memory_content or "(empty)",
                user_content=user_content or "(empty)",
                conversation_history=history,
            )

            _resp = await self.llm.chat([{"role": "user", "content": prompt}])
            response = _resp.content if hasattr(_resp, 'content') else str(_resp)
            await self._handle_memory_review_response(response)

        except Exception as e:
            logger.warning(f"记忆审查失败: {e}")
        finally:
            self._running = False

    async def _run_skill_review(self):
        """后台执行技能审查"""
        if self._running or not self.llm or not self.skill_manager:
            return
        self._running = True
        try:
            skills_list = self.skill_manager.list_skills()
            skills_text = "\n".join(
                [f"- {s['name']}: {s['description']}" for s in skills_list]
            ) or "(no skills yet)"

            history = self._format_execution()

            if not history:
                return

            prompt = _SKILL_REVIEW_PROMPT.format(
                skills_list=skills_text,
                execution_history=history,
            )

            _resp = await self.llm.chat([{"role": "user", "content": prompt}])
            response = _resp.content if hasattr(_resp, 'content') else str(_resp)
            await self._handle_skill_review_response(response)

        except Exception as e:
            logger.warning(f"技能审查失败: {e}")
        finally:
            self._running = False

    # ── 响应处理 ──────────────────────────────

    async def _handle_memory_review_response(self, response: str):
        import json
        try:
            data = json.loads(self._extract_json(response))
            action = data.get("action", "skip")

            if action == "skip":
                logger.debug("记忆审查: 无内容需要保存")
                return

            if action == "add_memory":
                self.memory_manager.add_entry("memory", data["entry"])
                logger.info(f"记忆审查: 添加 MEMORY.md 条目")

            elif action == "add_user":
                self.memory_manager.add_entry("user", data["entry"])
                logger.info(f"记忆审查: 添加 USER.md 条目")

            elif action == "replace_memory":
                self.memory_manager.replace_entry("memory", data["old"], data["new"])
                logger.info(f"记忆审查: 替换 MEMORY.md 条目")

            elif action == "replace_user":
                self.memory_manager.replace_entry("user", data["old"], data["new"])
                logger.info(f"记忆审查: 替换 USER.md 条目")

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"记忆审查响应解析失败: {e}, response={response[:200]}")

    async def _handle_skill_review_response(self, response: str):
        import json
        try:
            data = json.loads(self._extract_json(response))
            action = data.get("action", "skip")

            if action == "skip":
                logger.debug("技能审查: 无内容需要保存")
                return

            if action == "create_skill":
                ok, msg = self.skill_manager.create_skill(
                    name=data["name"],
                    description=data.get("description", ""),
                    steps=data.get("steps", []),
                    pitfalls=data.get("pitfalls"),
                    category=data.get("category", "general"),
                )
                if ok:
                    logger.info(f"技能审查: 创建技能 {data['name']}")
                else:
                    logger.warning(f"技能审查: 创建失败 {msg}")

            elif action == "patch_skill":
                ok, msg = self.skill_manager.patch_skill(
                    name=data["name"],
                    old=data["old"],
                    new=data["new"],
                )
                if ok:
                    logger.info(f"技能审查: 修补技能 {data['name']}")
                else:
                    logger.warning(f"技能审查: 修补失败 {msg}")

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"技能审查响应解析失败: {e}")

    # ── 辅助 ──────────────────────────────────

    def _format_conversation(self) -> str:
        lines = []
        for msg in self._conversation_buffer[-10:]:
            lines.append(f"[{msg['role']}] {msg['content'][:200]}")
        return "\n".join(lines)

    def _format_execution(self) -> str:
        lines = []
        for exec_ in self._execution_buffer[-10:]:
            status = "✓" if exec_["success"] else "✗"
            lines.append(f"{status} {exec_['tool']}({exec_['params']}) -> {exec_['result'][:100]}")
        return "\n".join(lines)

    def _extract_json(self, text: str) -> str:
        import re
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return match.group() if match else text

    def _trim_buffer(self, buffer: List, max_len: int):
        while len(buffer) > max_len:
            buffer.pop(0)

    def reset_counters(self):
        self._user_turn_count = 0
        self._tool_call_count = 0

    def get_stats(self) -> Dict:
        return {
            "user_turns": self._user_turn_count,
            "tool_calls": self._tool_call_count,
            "memory_interval": self.memory_interval,
            "skill_interval": self.skill_interval,
            "conversation_buffer": len(self._conversation_buffer),
            "execution_buffer": len(self._execution_buffer),
            "running": self._running,
        }
