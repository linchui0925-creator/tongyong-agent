"""
ToMessage - 对象转 TeamMessage 工具模块

提供将各种数据类型（工具执行结果、文本、字典等）转换为 TeamMessage 的实用函数，
方便 Agent 在协作流程中将处理结果格式化为结构化消息并路由给其他 Agent。
"""

from typing import Any, Dict, Optional
import json

from app.core.multi_agent.message import TeamMessage, new_message


def from_tool_result(
    result: str,
    tool_name: str,
    sent_from: str = "",
    send_to: str = "",
    cause_by: str = "",
    session_id: Optional[str] = None,
    **extra_metadata: Any,
) -> TeamMessage:
    """将工具执行结果转换为 TeamMessage

    Args:
        result: 工具返回的原始结果文本
        tool_name: 工具名称（存入 metadata）
        sent_from: 发送方 Agent 名称
        send_to: 目标 Agent（空=广播）
        cause_by: 触发该消息的 Action 名称
        session_id: 会话 ID
        extra_metadata: 额外元数据（存入 metadata 字段）

    Returns:
        TeamMessage: 结构化消息（role="tool"）
    """
    metadata = {
        "tool_name": tool_name,
        "source": "tool_call",
        **extra_metadata,
    }
    return new_message(
        content=result,
        role="tool",
        sent_from=sent_from,
        send_to=send_to,
        cause_by=cause_by or tool_name,
        session_id=session_id,
    )


def from_text(
    content: str,
    sent_from: str = "",
    send_to: str = "",
    cause_by: str = "",
    session_id: Optional[str] = None,
    **extra_metadata: Any,
) -> TeamMessage:
    """将文本内容转换为 TeamMessage

    Args:
        content: 消息文本
        sent_from: 发送方 Agent 名称
        send_to: 目标 Agent（空=广播）
        cause_by: 触发 Action 名称
        session_id: 会话 ID
        extra_metadata: 额外元数据

    Returns:
        TeamMessage: 结构化消息（role="assistant"）
    """
    msg = new_message(
        content=content,
        role="assistant",
        sent_from=sent_from,
        send_to=send_to,
        cause_by=cause_by,
        session_id=session_id,
    )
    if extra_metadata:
        msg.metadata.update(extra_metadata)
    return msg


def from_dict(
    data: Dict[str, Any],
    sent_from: str = "",
    send_to: str = "",
    cause_by: str = "",
    session_id: Optional[str] = None,
    **extra_metadata: Any,
) -> TeamMessage:
    """将字典数据转换为 TeamMessage（JSON 序列化后作为 content）

    Args:
        data: 字典数据
        sent_from: 发送方 Agent 名称
        send_to: 目标 Agent（空=广播）
        cause_by: 触发 Action 名称
        session_id: 会话 ID
        extra_metadata: 额外元数据

    Returns:
        TeamMessage: content 为 JSON 格式的结构化消息
    """
    content = json.dumps(data, ensure_ascii=False, default=str)
    msg = new_message(
        content=content,
        role="assistant",
        sent_from=sent_from,
        send_to=send_to,
        cause_by=cause_by,
        session_id=session_id,
    )
    if extra_metadata:
        msg.metadata.update(extra_metadata)
    return msg


def from_message(
    msg: TeamMessage,
    content: Optional[str] = None,
    send_to: str = "",
    cause_by: str = "",
    **extra_metadata: Any,
) -> TeamMessage:
    """基于已有 TeamMessage 创建派生消息（保留原消息上下文）

    常用于 Agent 对收到的消息做回复或转发。
    新消息默认继承原消息的 session_id、sent_from（调用方覆盖）。

    Args:
        msg: 源消息
        content: 新内容（None=沿用原消息内容）
        send_to: 目标 Agent
        cause_by: 触发 Action 名称
        extra_metadata: 额外元数据

    Returns:
        TeamMessage: 派生消息
    """
    new = new_message(
        content=content if content is not None else msg.content,
        role="assistant",
        sent_from=msg.sent_from,
        send_to=send_to or msg.send_to,
        cause_by=cause_by or msg.cause_by,
        session_id=msg.session_id,
    )
    new.metadata.update(msg.metadata)
    if extra_metadata:
        new.metadata.update(extra_metadata)
    return new
