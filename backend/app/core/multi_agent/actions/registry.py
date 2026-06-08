"""
Action 注册表 + 工厂函数

遵循 llm/factory.py 的模式：显式注册，延迟导入具体实现类。
新增 Action 只需在 _register_defaults() 中添加一行注册。
"""

from typing import Dict, List, Optional, Type

from app.core.multi_agent.actions.base import TeamAction


_ACTION_REGISTRY: Dict[str, Type[TeamAction]] = {}


def _register_defaults():
    """注册所有内置 Action（延迟导入，避免循环依赖）"""
    from app.core.multi_agent.actions.generic import LLMThinkAction, ToolCallAction, SendToAction
    from app.core.multi_agent.actions.pipeline import (
        WriteCodeAction, WriteTestAction, WriteReviewAction,
        AnalyzeTaskAction, DistributeTaskAction, ApprovalAction, RejectAction,
    )
    from app.core.multi_agent.actions.debate import SpeakAloudAction, DebateSpeechAction, DebateJudgeAction

    _ACTION_REGISTRY.update({
        "llm_think": LLMThinkAction,
        "write_code": WriteCodeAction,
        "write_test": WriteTestAction,
        "write_review": WriteReviewAction,
        "speak_aloud": SpeakAloudAction,
        "debate_speech": DebateSpeechAction,
        "debate_judge": DebateJudgeAction,
        "tool_call": ToolCallAction,
        "send_to": SendToAction,
        # Leader 专用
        "analyze_task": AnalyzeTaskAction,
        "distribute_task": DistributeTaskAction,
        "approve": ApprovalAction,
        "reject": RejectAction,
    })


_register_defaults()


def get_action_class(action_type: str) -> Optional[Type[TeamAction]]:
    return _ACTION_REGISTRY.get(action_type)


def list_action_types() -> List[str]:
    return list(_ACTION_REGISTRY.keys())


def create_action(action_type: str, **kwargs) -> TeamAction:
    cls = get_action_class(action_type)
    if not cls:
        raise ValueError(f"未知 Action 类型: {action_type}")
    return cls(**kwargs)
