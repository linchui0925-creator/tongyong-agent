"""
TaskState — 多智能体协作任务状态机

定义所有任务状态枚举 + 合法转换规则 + 转换验证函数。
是整个多智能体协作框架的状态基础设施。

状态转换图:
    
    pending ──claim──▶ claimed ──start──▶ running
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
                completed          failed           rejected
                                       │                 │
                                       │                 │
                    ┌─────────────────┘                 │
                    ▼                                   ▼
                 reclaimed ◀───────────────────────────
"""

from enum import Enum
from typing import Dict, List, Set, Optional, Callable
from dataclasses import dataclass


class TaskState(str, Enum):
    """
    任务状态枚举。
    
    状态转换语义:
    - pending:    任务创建，未被认领
    - claimed:   有 Agent 声明执行，但尚未开始工作
    - running:    正在执行（工具调用中或已完成，等待结果）
    - completed:  执行成功，结果已就绪
    - failed:     执行过程异常（非业务拒绝）
    - rejected:   业务层面拒绝（验收不通过、质量不达标）
    - reclaimed:  被回收（超时 / 主动放弃 / 重试场景）
    """
    PENDING   = "pending"
    CLAIMED   = "claimed"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    REJECTED  = "rejected"
    RECLAIMED = "reclaimed"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def _missing_(cls, value: object) -> Optional["TaskState"]:
        """接受任意字符串，不抛出 ValueError"""
        if isinstance(value, str):
            for member in cls:
                if member.value == value:
                    return member
        return cls.PENDING


# ══════════════════════════════════════════════════════════
# 转换规则 — 状态 → 合法的后继状态集合
# ══════════════════════════════════════════════════════════

# 每个状态的合法后继状态（用于 validate_transition）
LEGAL_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
    TaskState.PENDING:   {TaskState.CLAIMED,  TaskState.RECLAIMED},
    TaskState.CLAIMED:  {TaskState.RUNNING,  TaskState.RECLAIMED},
    TaskState.RUNNING:  {TaskState.COMPLETED, TaskState.FAILED, TaskState.REJECTED, TaskState.RECLAIMED},
    TaskState.COMPLETED: set(),                # 终态
    TaskState.FAILED:   {TaskState.RECLAIMED}, # 可重试
    TaskState.REJECTED: {TaskState.RECLAIMED}, # 可重试
    TaskState.RECLAIMED:{TaskState.CLAIMED,  TaskState.PENDING},  # 重新入队
}

# 每个状态的简短中文标签
STATE_LABELS: Dict[TaskState, str] = {
    TaskState.PENDING:   "待认领",
    TaskState.CLAIMED:   "已认领",
    TaskState.RUNNING:   "执行中",
    TaskState.COMPLETED: "已完成",
    TaskState.FAILED:    "执行失败",
    TaskState.REJECTED:   "已拒绝",
    TaskState.RECLAIMED: "已回收",
}


# ══════════════════════════════════════════════════════════
# 转换验证
# ══════════════════════════════════════════════════════════

class TransitionError(ValueError):
    """非法状态转换"""
    def __init__(self, current: TaskState, target: TaskState):
        self.current = current
        self.target = target
        legal = LEGAL_TRANSITIONS.get(current, set())
        legal_str = ", ".join(s.value for s in legal) or "(无)"
        super().__init__(
            f"非法状态转换: {current.value} → {target.value}。"
            f"当前状态 {current.value} 的合法后继: {legal_str}"
        )


def validate_transition(current: TaskState, target: TaskState) -> None:
    """
    验证状态转换是否合法。
    
    Args:
        current: 当前状态
        target:  目标状态
    
    Raises:
        TransitionError: 非法转换时
    """
    legal = LEGAL_TRANSITIONS.get(current, set())
    if target not in legal:
        raise TransitionError(current, target)


def can_transition(current: TaskState, target: TaskState) -> bool:
    """返回转换是否合法（不抛异常）"""
    try:
        validate_transition(current, target)
        return True
    except TransitionError:
        return False


# ══════════════════════════════════════════════════════════
# 事件类型 — 状态转换时广播的事件
# ══════════════════════════════════════════════════════════

class TaskEvent(str, Enum):
    """任务生命周期事件（用于 EventBus 广播）"""
    CLAIMED    = "task.claimed"    # 任务被认领
    STARTED    = "task.started"    # 开始执行
    PROGRESS   = "task.progress"   # 进度更新（工具调用中）
    COMPLETED  = "task.completed"   # 执行成功
    FAILED     = "task.failed"     # 执行异常
    REJECTED   = "task.rejected"   # 验收拒绝
    RECLAIMED  = "task.reclaimed"  # 被回收（超时/放弃）
    PROMOTED   = "task.promoted"  # 子任务被提升为 ready
    
    # 辅助事件
    ENQUEUED   = "task.enqueued"   # 新任务入队


# ══════════════════════════════════════════════════════════
# Transition — 单次状态转换记录（用于持久化审计）
# ══════════════════════════════════════════════════════════

@dataclass
class Transition:
    """单次状态转换记录"""
    task_id:    str
    from_state: TaskState
    to_state:   TaskState
    actor:      str            # 哪个 Agent 触发
    reason:     str = ""       # 可选原因（如 "timeout", "user_reject"）
    is_auto:    bool = False    # 是否系统自动触发

    def to_dict(self) -> dict:
        return {
            "task_id":    self.task_id,
            "from_state": self.from_state.value,
            "to_state":   self.to_state.value,
            "actor":      self.actor,
            "reason":     self.reason,
            "is_auto":    self.is_auto,
        }


# ══════════════════════════════════════════════════════════
# StateMachine — 单任务状态机（内存内）
# ══════════════════════════════════════════════════════════

class StateMachine:
    """
    单任务状态机。
    
    封装状态值 + 转换验证 + 历史记录。
    每个运行中的 Task 对应一个 StateMachine 实例。
    """

    __slots__ = ("task_id", "_state", "_history")

    def __init__(self, task_id: str, initial: TaskState = TaskState.PENDING):
        self.task_id = task_id
        self._state = initial
        self._history: List[Transition] = []

    @property
    def state(self) -> TaskState:
        return self._state

    def transition_to(
        self,
        target: TaskState,
        actor: str,
        reason: str = "",
        is_auto: bool = False,
    ) -> Transition:
        """
        执行状态转换（验证后更新状态并记录历史）。
        
        Returns:
            Transition 记录对象
        
        Raises:
            TransitionError: 非法转换
        """
        validate_transition(self._state, target)
        t = Transition(
            task_id=self.task_id,
            from_state=self._state,
            to_state=target,
            actor=actor,
            reason=reason,
            is_auto=is_auto,
        )
        self._state = target
        self._history.append(t)
        return t

    def history(self) -> List[Transition]:
        return list(self._history)

    def last_transition(self) -> Optional[Transition]:
        return self._history[-1] if self._history else None

    def is_terminal(self) -> bool:
        """是否为终态"""
        return self._state in {TaskState.COMPLETED}

    def is_active(self) -> bool:
        """是否处于活跃状态（可继续处理）"""
        return self._state in {TaskState.PENDING, TaskState.CLAIMED, TaskState.RUNNING}

    def label(self) -> str:
        return STATE_LABELS.get(self._state, self._state.value)

    def __repr__(self) -> str:
        return f"<StateMachine task={self.task_id} state={self._state.value}>"