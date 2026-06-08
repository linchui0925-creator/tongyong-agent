"""
向后兼容 shim — 新代码请从 app.core.multi_agent.actions 导入
"""

from app.core.multi_agent.actions.base import TeamAction, LLMError, _get_llm_for_role, _call_llm
from app.core.multi_agent.actions.registry import get_action_class, list_action_types, create_action
from app.core.multi_agent.actions.generic import LLMThinkAction, ToolCallAction, SendToAction
from app.core.multi_agent.actions.pipeline import (
    WriteCodeAction, WriteTestAction, WriteReviewAction,
    AnalyzeTaskAction, DistributeTaskAction, ApprovalAction, RejectAction,
)
from app.core.multi_agent.actions.debate import SpeakAloudAction, DebateSpeechAction, DebateJudgeAction
