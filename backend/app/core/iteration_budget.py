"""
IterationBudget - 工具调用迭代预算控制

迭代预算控制，支持 soft/hard limit 和 grace call 机制。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class IterationBudget:
    """Tracks tool-call iteration budget with grace call support.

    Attributes:
        max_rounds: 硬性上限，最大工具调用轮次
        soft_limit: 软性上限，触发警告的阈值
        grace_calls: 达到软上限后允许的额外调用次数
        current_round: 当前轮次计数
        grace_used: 已使用的 grace calls 数量

    支持环境变量配置:
        ITERATION_MAX_ROUNDS: 硬性上限 (默认 50)
        ITERATION_SOFT_LIMIT: 软性上限 (默认 40)
        ITERATION_GRACE_CALLS: grace 调用次数 (默认 10)
    """
    max_rounds: int = 50
    soft_limit: int = 40
    grace_calls: int = 10
    current_round: int = 0
    grace_used: int = 0

    def __post_init__(self):
        import os
        # 从环境变量覆盖默认值（如果有设置）
        max_env = os.getenv("ITERATION_MAX_ROUNDS")
        if max_env:
            try:
                self.max_rounds = max(1, int(max_env))
            except ValueError:
                pass

        soft_env = os.getenv("ITERATION_SOFT_LIMIT")
        if soft_env:
            try:
                self.soft_limit = max(1, int(soft_env))
            except ValueError:
                pass

        grace_env = os.getenv("ITERATION_GRACE_CALLS")
        if grace_env:
            try:
                self.grace_calls = max(0, int(grace_env))
            except ValueError:
                pass

        # 确保 soft_limit <= max_rounds
        if self.soft_limit > self.max_rounds:
            self.soft_limit = self.max_rounds

    @property
    def remaining(self) -> int:
        """剩余可用轮次"""
        return max(0, self.max_rounds - self.current_round)

    @property
    def is_exhausted(self) -> bool:
        """预算是否已耗尽"""
        return self.current_round >= self.max_rounds

    @property
    def is_approaching_limit(self) -> bool:
        """是否接近上限（已达到软上限）"""
        return self.current_round >= self.soft_limit

    @property
    def can_grace_call(self) -> bool:
        """是否可以使用 grace call"""
        return self.grace_used < self.grace_calls

    @property
    def in_grace_period(self) -> bool:
        """是否处于 grace period"""
        return self.is_approaching_limit and not self.is_exhausted

    def advance(self) -> bool:
        """推进轮次计数器

        Returns:
            True 如果迭代应该继续，False 如果应该停止
        """
        if self.is_exhausted:
            return False

        self.current_round += 1

        if self.current_round > self.soft_limit and not self.can_grace_call:
            return False

        if self.current_round > self.soft_limit and self.can_grace_call:
            self.grace_used += 1

        return not self.is_exhausted

    def get_warning_message(self) -> Optional[str]:
        """获取接近上限警告消息"""
        if self.current_round == self.soft_limit:
            return (
                f"[预算警告] 工具调用轮次即将耗尽（已使用 {self.current_round} 轮，"
                f"剩余 {self.remaining} 轮）。请准备结束或合并后续操作。"
            )
        if self.current_round > self.soft_limit and self.in_grace_period:
            return (
                f"[预算警告] 进入 grace period（已用 {self.grace_used}/{self.grace_calls} 次 grace）。"
                f"剩余 {self.remaining} 轮。"
            )
        return None

    def get_exhausted_message(self) -> str:
        """获取预算耗尽消息"""
        return (
            f"[预算耗尽] 工具调用已达上限（{self.max_rounds} 轮）。"
            "请基于已有结果生成最终回复。"
        )

