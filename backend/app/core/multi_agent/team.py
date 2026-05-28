"""
Team - Multi-Agent 编排引擎
管理多个 Role 的生命周期和协作流程
"""

import asyncio
import time
from typing import Dict, List, Optional, Set, Any, AsyncGenerator
from datetime import datetime
from pydantic import BaseModel, Field, PrivateAttr
import logging

from app.core.multi_agent.message import TeamMessage, new_message
from app.core.multi_agent.role import TeamRole, RoleContext
from app.core.multi_agent.environment import Environment

logger = logging.getLogger(__name__)


class Team(BaseModel):
    """
    Team 编排引擎

    支持两种协作模式：
    - pipeline（统一图路由模式）: 按 agent 连接图（upstream/downstream）自动路由消息，
      多 action 角色（如 Leader）可基于内部状态自主推进流水线
    - debate（辩论）: 两个角色交替发言，互为对手

    图路由模式流程示例（Leader + Coder + Tester + Reviewer）：
      1. Leader 收到 UserRequirement，分析任务类型（AnalyzeTask）
      2. Leader 通过 DistributeTask 定向分配给 Coder（send_to=Coder）
      3. Coder 完成 WriteCode，结果被 Leader 接收（通过连接图或定向路由）
      4. Leader 审批：通过 → 继续下一环节；退回 → 返回 Coder 修改
      5. Tester → Reviewer → Leader → 循环直到全部子任务完成
      6. 连续 3 轮无产出则自动终止（防死循环保护）

    每轮协作流程（pipeline 模式）：
      1. Team 发布系统消息 [Round N]
      2. 找出有新消息的角色 + 多 action 角色（可基于内部状态行动）
      3. 各角色依次执行：Role.observe() → Role._think() → Role._act()
      4. 消息通过 Environment 发布，yield 供 SSE 流式推送
    """

    # ── 持久化字段 ─────────────────────────────────────────
    name: str = "Team"
    mode: str = "pipeline"  # pipeline | debate
    status: str = "idle"    # idle | running | completed | error | stopped | timeout
    investment: float = 3.0
    timeout: int = 0        # 超时秒数，0=不限制

    # ── 运行时字段（不持久化）────────────────────────────────
    _roles: Dict[str, TeamRole] = PrivateAttr(default_factory=dict)
    _env: Environment = PrivateAttr(default=None)
    _round: int = PrivateAttr(default=0)
    _result_messages: List[TeamMessage] = PrivateAttr(default_factory=list)
    _task_queue: List[str] = PrivateAttr(default_factory=list)  # 剩余子任务队列（Leader 分析后填充）
    _idle_count: int = PrivateAttr(default=0)            # 连续无产出轮次计数（防死循环）

    def __init__(self, **data):
        super().__init__(**data)
        # 构造时建立 Environment → Team 的双向引用
        object.__setattr__(self, "_env", Environment(team=self))
    
    class Config:
        arbitrary_types_allowed = True
    
    # ── Role 管理 ─────────────────────────────────────────
    
    def hire(self, role: TeamRole):
        """雇佣角色加入团队"""
        role.set_environment(self._env)
        self._roles[role.name] = role
        logger.info(f"[TEAM] 雇佣: {role.name} ({role.profile[:30]}...)")
    
    def fire(self, role_name: str):
        """移除角色"""
        if role_name in self._roles:
            del self._roles[role_name]
            logger.info(f"[TEAM] 解雇: {role_name}")
    
    def get_role(self, name: str) -> Optional[TeamRole]:
        return self._roles.get(name)
    
    def list_roles(self) -> List[str]:
        return list(self._roles.keys())
    
    # ── 协作模式核心 ─────────────────────────────────────────

    async def _get_roles_for_round(self, round_num: int) -> List[TeamRole]:
        """
        根据模式返回本轮应执行的角色列表。

        Debate 模式：所有角色都参与（交替发言）
        Pipeline/图路由模式：只返回收到新消息的角色。Worker 仅接收定向消息，
          Leader 通过连接图和 watch_actions 接收。
        """
        if self.mode == "debate":
            return list(self._roles.values())

        # 图路由模式：仅返回有新消息的角色
        result: List[TeamRole] = []
        for role in self._roles.values():
            news = await role.observe()
            if news:
                result.append(role)
        return result

    # ── 运行流程 ─────────────────────────────────────────
    
    async def run_stream(
        self, idea: str, n_round: int = 5, send_to: str = ""
    ) -> AsyncGenerator[TeamMessage, None]:
        """
        流式运行团队协作流程，每生成一条消息立即 yield。

        Pipeline/图路由模式：按连接图 + watch_actions 自动路由，多 action 角色自主推进
        Debate 模式：所有角色交替发言，按 pair 分组
        """
        if self.status == "running":
            logger.warning("[TEAM] 已在运行中，忽略重复调用")
            return

        self.status = "running"
        self._round = 0
        self._result_messages = []
        self._idle_count = 0

        logger.info(f"[TEAM] 开始流式运行: {idea[:50]}... (mode={self.mode}, max {n_round} rounds)")

        # ── 初始消息：用户任务 ────────────────────────────
        start_msg = new_message(
            content=idea,
            role="user",
            sent_from="user",
            send_to=send_to,
            cause_by="UserRequirement",
        )
        self._env.publish(start_msg)
        self._result_messages.append(start_msg)
        yield start_msg

        # ── 主循环 ──────────────────────────────────────
        max_iterations = max(n_round * 4, 20)  # 安全上限，关联 n_round 并取 20 保底
        iteration = 0
        _start_time = time.monotonic()

        while iteration < max_iterations:
            iteration += 1

            # 三重保障：检查是否被主动停止
            if self.status == "stopped":
                logger.info("[TEAM] 收到停止信号，终止流水线")
                break

            # 三重保障：检查是否超时
            if self.timeout > 0 and (time.monotonic() - _start_time) > self.timeout:
                logger.warning(f"[TEAM] 超时 {self.timeout}s，自动终止")
                self.status = "timeout"
                break

            self._round += 1

            round_system = new_message(
                content=f"[Round {self._round}]",
                role="system",
                sent_from="Team",
                metadata={"round": self._round},
            )
            self._env.publish(round_system)
            yield round_system

            roles_this_round = await self._get_roles_for_round(round_num=iteration)

            if not roles_this_round:
                logger.info(f"[TEAM] 第 {self._round} 轮无角色需要执行，提前结束")
                break

            logger.info(f"[TEAM] ===== 第 {self._round} 轮 ({len(roles_this_round)} 个角色) =====")

            idle_this_round = True

            for role in roles_this_round:
                msg = await role.run(self._round)
                if msg:
                    idle_this_round = False
                    msg.metadata["round"] = self._round
                    self._env.publish(msg)
                    self._result_messages.append(msg)
                    logger.info(f"[TEAM] {role.name}: {msg.content[:80]}...")
                    yield msg

            # 防死循环：连续 idle 超过阈值则强制终止
            if idle_this_round:
                self._idle_count += 1
                logger.debug(f"[TEAM] 空闲轮次 +1（总计 {self._idle_count}）")
                if self._idle_count >= 3:
                    logger.warning(f"[TEAM] 连续 {self._idle_count} 轮无产出，触发死循环保护，终止流水线")
                    break
            else:
                self._idle_count = 0

            # 轮次上限保护（仅空闲时生效，活跃重试可继续）
            if self._round >= n_round:
                if self._idle_count > 0:
                    logger.info(f"[TEAM] 达到指定轮次上限 {n_round} 且空闲，终止流水线")
                    break
                logger.debug(f"[TEAM] 轮次上限 {n_round} 但还有活跃任务，继续执行")

            await asyncio.sleep(0.05)

        # 仅在非异常状态下标记完成
        if self.status == "running":
            self.status = "completed"
        logger.info(f"[TEAM] 运行结束 (status={self.status})，共 {len(self._result_messages)} 条消息")

    # ── _update_next_trigger / _find_prev_worker_cause 已移除 ──
    # 路由逻辑由连接图（upstream_roles / downstream_roles）+ 环境过滤 + 多 action 角色内部决策替代

    async def run(
        self, idea: str, n_round: int = 5, send_to: str = ""
    ) -> List[TeamMessage]:
        """运行团队协作流程（非流式）"""
        results: List[TeamMessage] = []
        async for msg in self.run_stream(idea=idea, n_round=n_round, send_to=send_to):
            results.append(msg)
        return results
    
    # ── 消息查询 ─────────────────────────────────────────
    
    def get_all_messages(self) -> List[TeamMessage]:
        return self._env.get_all_messages()
    
    def get_messages_for_role(self, role_name: str) -> List[TeamMessage]:
        role = self.get_role(role_name)
        if not role:
            return []
        return self._env.get_messages_for_role(role)
    
    def get_messages_by_sender(self, sender: str) -> List[TeamMessage]:
        return self._env.get_messages_by_sender(sender)
    
    def get_messages_by_round(self, round_num: int) -> List[TeamMessage]:
        return self._env.get_round_messages(round_num)
    
    # ── 状态 ─────────────────────────────────────────
    
    def is_running(self) -> bool:
        return self.status == "running"
    
    def is_completed(self) -> bool:
        return self.status == "completed"

    def stop(self):
        """主动终止正在运行的流水线"""
        if self.status == "running":
            logger.info(f"[TEAM] 主动终止流水线: {self.name}")
            self.status = "stopped"
    
    def summary(self) -> str:
        return (
            f"Team(name={self.name}, mode={self.mode}, status={self.status}, "
            f"roles={list(self._roles.keys())}, "
            f"messages={len(self._env.messages)})"
        )


# ── 异步运行包装 ─────────────────────────────────────────

async def run_team_async(team: Team, idea: str, n_round: int = 5, send_to: str = "") -> List[TeamMessage]:
    """异步运行 Team（用于 FastAPI 端点）"""
    return await team.run(idea=idea, n_round=n_round, send_to=send_to)


def run_team_sync(team: Team, idea: str, n_round: int = 5, send_to: str = "") -> List[TeamMessage]:
    """同步运行 Team（用于命令行）"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(team.run(idea=idea, n_round=n_round, send_to=send_to))
    finally:
        loop.close()