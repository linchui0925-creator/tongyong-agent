"""
通用 Action — 不绑定特定工作流模式

LLMThinkAction: 纯 LLM 生成（无工具调用）
ToolCallAction: 通用工具调用
SendToAction: 定向消息
"""

from pydantic import BaseModel, Field
from typing import TYPE_CHECKING, Any, Dict
import logging

from app.core.multi_agent.actions.base import TeamAction, _call_llm

if TYPE_CHECKING:
    from app.core.multi_agent.role import TeamRole, RoleContext

logger = logging.getLogger(__name__)


class LLMThinkAction(TeamAction):
    """纯 LLM 生成（无工具调用）"""
    name: str = "LLMThink"
    description: str = "使用 LLM 直接生成文本回复"

    prompt_template: str = "{prompt}"
    prompt: str = ""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        messages = [{"role": "user", "content": self.prompt_template.format(prompt=self.prompt)}]
        return await _call_llm(role, messages, tools=None)


class ToolCallAction(TeamAction):
    """通用工具调用 Action"""
    name: str = "ToolCall"
    description: str = "调用指定工具执行操作"

    tool_name: str = ""
    arguments: Dict[str, Any] = Field(default_factory=dict)

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        if not self.tool_name:
            return "错误: 未指定工具名"

        if not role.tool_permission.is_tool_allowed(self.tool_name):
            return f"错误: 工具 {self.tool_name} 不在权限范围内。{role.tool_permission.summary()}"

        try:
            from app.tools.manager import get_tool_manager
            tool_mgr = get_tool_manager()
            result = await tool_mgr.execute(self.tool_name, self.arguments)
            return result
        except Exception as e:
            return f"工具执行失败: {e}"


class SendToAction(TeamAction):
    """定向消息 Action"""
    name: str = "SendTo"
    description: str = "向指定的协作 Agent 发送定向消息"

    target: str = ""
    message: str = ""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        if not self.target:
            return "错误: 未指定目标 Agent"
        self.send_to = self.target
        logger.info(f"[ACTION] {role.name} → {self.target}: {self.message[:60]}")
        return self.message
