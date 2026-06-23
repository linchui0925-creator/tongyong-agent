"""
ask - 向用户提问交互工具

当 agent 需要用户确认或选择时，调用此工具向用户展示问题，
并同步等待用户回答后返回结果。

工具行为（对比 hermes clarify_tool）：
- 返回结构化 JSON: {"question": "...", "choices": [...], "user_response": "..."}
- 同步等待，不 break ReAct 循环
- 前端解析 user_response 字段，如果为 null 则显示问题 UI
- 用户回答后，前端调用 /api/ask/{question_id} 更新 user_response
- 下次调用 ask 时传入 same question_id，工具返回已填充的 user_response
"""

import uuid
import json
import logging
from typing import Optional, List
from app.tools.registry import registry

logger = logging.getLogger(__name__)

MAX_CHOICES = 4


def _check_ask() -> bool:
    """ask 工具总是可用"""
    return True


ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "要向用户提问的问题",
        },
        "choices": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": MAX_CHOICES,
            "description": f"选项列表（最多 {MAX_CHOICES} 个）。省略则为开放问题。",
        },
        "question_id": {
            "type": "string",
            "description": "问题 ID（首次调用时不传，自动生成；后续调用时传入以获取已有问题的回答）",
        },
    },
    "required": ["question"],
}


async def ask_tool(
    question: str,
    choices: Optional[List[str]] = None,
    question_id: Optional[str] = None,
) -> str:
    """
    向用户提问并等待回答。

    首次调用（question_id=None）：注册问题，检查是否已有回答
    后续调用（question_id 传入）：检查该问题是否已有回答

    返回格式:
    {
        "question": "...",
        "choices": ["A", "B"],
        "question_id": "...",
        "user_response": "A",   // 有回答时返回用户的选择/输入
        "timeout": false
    }
    或（无回答时）:
    {
        "question": "...",
        "choices": ["A", "B"],
        "question_id": "...",
        "user_response": null,  // 无回答，__ASK_BLOCK__ 标记让 agent 暂停
        "timeout": false
    }
    """
    # 验证和裁剪 choices
    if choices is not None:
        if not isinstance(choices, list):
            choices = None
        else:
            choices = [str(c).strip() for c in choices if str(c).strip()]
            if len(choices) > MAX_CHOICES:
                choices = choices[:MAX_CHOICES]
            if not choices:
                choices = None

    # W4-25 P1-4: 用 SQLite store 替代 agent_engine._ask_pending (内存 dict)
    from app.core.ask_store import get_ask_pending_store
    store = get_ask_pending_store()

    # 检查是否已有回答
    if question_id:
        entry = store.pop(question_id)
        if entry is not None:
            user_response = entry.get("user_response")
            logger.info(f"[ask] 返回已有回答: question_id={question_id}, response={str(user_response)[:30]}")
            return json.dumps({
                "question": entry["question"],
                "choices": entry["choices"],
                "question_id": question_id,
                "user_response": user_response,
                "timeout": entry.get("timeout", False),
            }, ensure_ascii=False)

    # 首次调用：注册新问题
    qid = question_id or str(uuid.uuid4())
    store.set(qid, {
        "question": question,
        "choices": choices or [],
        "user_response": None,
        "timeout": False,
    })
    logger.info(f"[ask] 发起提问: question={question[:50]}... id={qid}")

    # 返回 __ASK_BLOCK__ 标记，让 agent 检测并 yield ask 事件后暂停
    return f"__ASK_BLOCK__:{qid}"




def _register_tools():
    registry.register(
        name="ask",
        toolset="interactive",
        description=(
            "向用户提问以获取澄清或决策。使用场景：\n"
            "- 任务目标模糊，需要用户确认方向\n"
            "- 做了重要操作后主动要反馈\n"
            "- 建议用户保存 skill 或更新 memory\n"
            "- 决策有重大权衡，用户应该参与\n\n"
            "支持两种模式：\n"
            "1. 多选模式 — 提供最多 4 个选项，用户选择一个\n"
            "2. 开放问题 — 不提供 choices，用户自由输入\n\n"
            "注意：简单的是/否确认不要用此工具。\n"
            "注意：不要在 cronjob 或子 agent 中使用此工具。"
        ),
        schema=ASK_SCHEMA,
        handler=ask_tool,
        check_fn=_check_ask,
        is_async=True,
        emoji="❓",
        parallel_mode="never",
    )


# 启动时注册 (W4-21 P2-2: 显式 _register_tools, 便于测试 mock)
_register_tools()
