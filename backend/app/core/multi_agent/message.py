"""
TeamMessage - Multi-Agent 扩展消息单元
扩展自 core.base.Message，增加 send_to / cause_by 路由字段
"""

from enum import Enum
from pydantic import BaseModel, Field, ValidationError
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid
import json
import threading

class TeamMessage(BaseModel):
    """Multi-Agent 消息单元"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None       # 所属 Team 会话 ID
    role: str = "assistant"                # user/assistant/system/agent
    content: str                            # 消息内容
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    sequence: Optional[int] = None         # 序列号（全局递增）

    # ── Multi-Agent 路由字段 ──
    cause_by: str = ""                     # 触发该消息的 Action 名称
    sent_from: str = ""                    # 发送方 Agent 名称
    send_to: str = ""                      # 接收方 Agent 名称（空=广播）
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 扩展元数据

    def is_broadcast(self) -> bool:
        return self.send_to == ""
    
    def is_direct(self) -> bool:
        return self.send_to != ""
    
    def to_summary(self) -> str:
        """摘要显示"""
        target = self.send_to or "广播"
        return f"[{self.sent_from} → {target}]: {self.content[:80]}"
    
    @classmethod
    def from_text(
        cls, content: str, role: str = "assistant",
        sent_from: str = "", send_to: str = "", cause_by: str = "",
        session_id: Optional[str] = None
    ) -> "TeamMessage":
        """快捷构造"""
        return cls(
            content=content,
            role=role,
            sent_from=sent_from,
            send_to=send_to,
            cause_by=cause_by,
            session_id=session_id,
        )


# 全局序列号计数器（线程安全，进程内单调递增）
_sequence_counter = 0
_sequence_lock = threading.Lock()

def next_sequence() -> int:
    global _sequence_counter
    with _sequence_lock:
        _sequence_counter += 1
        return _sequence_counter


def new_message(
    content: str, role: str = "assistant",
    sent_from: str = "", send_to: str = "", cause_by: str = "",
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TeamMessage:
    """创建新消息（带序列号）"""
    msg = TeamMessage(
        content=content,
        role=role,
        sent_from=sent_from,
        send_to=send_to,
        cause_by=cause_by,
        session_id=session_id,
        metadata=metadata or {},
    )
    msg.sequence = next_sequence()
    return msg


# ══════════════════════════════════════════════════════════
# TaskPayload — 结构化任务信封（MetaGPT/A2A 风格）
# ══════════════════════════════════════════════════════════


class TaskStatus(str, Enum):
    """任务状态枚举（同时兼容字符串赋值）"""
    PENDING = "pending"
    WORKING = "working"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def _missing_(cls, value: object) -> Optional["TaskStatus"]:
        """接受任意字符串，不抛出 ValueError"""
        if isinstance(value, str):
            for member in cls:
                if member.value == value:
                    return member
        return cls.PENDING


class Feedback(BaseModel):
    """结构化退回反馈"""
    reason: str = ""                     # 退回原因
    suggestions: List[str] = Field(default_factory=list)  # 具体修改建议
    from_agent: str = ""                 # 来自哪个 Agent


class TaskPayload(BaseModel):
    """
    结构化任务信封。

    替换纯文本 content 传递，使 Agent 间通信携带类型、状态、上下文、
    结果和退回反馈等结构化字段。灵感来自 MetaGPT 的 Task 和 A2A 协议。
    """
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    task_type: str = ""                   # "analyze" | "code" | "test" | "review"
    status: str = "pending"              # pending | working | completed | rejected | failed
    description: str = ""                 # 任务描述（Leader 设定）
    original_requirement: str = ""        # 用户原始需求（贯穿流水线）
    context: str = ""                     # 上游产出（代码、测试等上下文）
    result: str = ""                      # 本环节产出
    feedback: List[Feedback] = Field(default_factory=list)  # 退回反馈
    subtasks: List[str] = Field(default_factory=list)       # 子任务列表
    current_subtask: str = ""             # 当前执行的子任务
    rejection_count: int = 0              # 退回次数（防止死循环）

    def to_content(self) -> str:
        """序列化为 JSON 字符串（存入 TeamMessage.content）"""
        return self.model_dump_json()

    @classmethod
    def from_message(cls, msg: TeamMessage) -> Optional["TaskPayload"]:
        """从 TeamMessage.content 反序列化（兼容纯文本回退）"""
        try:
            data = json.loads(msg.content)
            if not isinstance(data, dict):
                return None
            return cls(**data)
        except (json.JSONDecodeError, ValidationError):
            return None

    @classmethod
    def from_content(cls, content: str) -> Optional["TaskPayload"]:
        """从字符串反序列化"""
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                return None
            return cls(**data)
        except (json.JSONDecodeError, ValidationError):
            return None


def new_task_message(
    payload: TaskPayload,
    sent_from: str = "",
    send_to: str = "",
    cause_by: str = "",
    session_id: Optional[str] = None,
) -> TeamMessage:
    """创建携带 TaskPayload 的 TeamMessage"""
    msg = new_message(
        content=payload.to_content(),
        sent_from=sent_from,
        send_to=send_to,
        cause_by=cause_by,
        session_id=session_id,
        metadata={"payload_version": "1", "task_id": payload.task_id, "task_status": payload.status},
    )
    return msg