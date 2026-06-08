"""
Team - Multi-Agent 编排引擎（v2 版本）

支持两种协作模式：
- pipeline（统一图路由模式）: 按 agent 连接图（upstream/downstream）自动路由消息，
  多 action 角色（如 Leader）可基于内部状态自主推进流水线
- debate（辩论）: 两个角色交替发言，互为对手

v1 → v2 改动：
- Environment → EventBusEnvironment（SQLite WAL + EventBus 事件驱动）
- run_stream() 保留，但内部使用 EventBusEnvironment
- 新增 run_v2_stream()：全事件驱动，交给 Scheduler 管理 Agent 生命周期
- 不再有 _task_queue（List[str]），任务管理交给 TaskQueue
"""

import asyncio
import time
from typing import Dict, List, Optional, Set, Any, AsyncGenerator, Callable
from datetime import datetime
from pydantic import BaseModel, Field, PrivateAttr
import logging

from app.core.multi_agent.message import TeamMessage, new_message
from app.core.multi_agent.role import TeamRole, RoleContext
from app.core.multi_agent.environment import EventBusEnvironment
from app.core.multi_agent.scheduler import Scheduler

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

    v2 新增：run_v2_stream() — 全事件驱动，交给 Scheduler 管理 Agent 生命周期。
    """

    # ── 持久化字段 ─────────────────────────────────────────
    name: str = "Team"
    mode: str = "pipeline"  # pipeline | debate
    status: str = "idle"    # idle | running | completed | error | stopped | timeout
    investment: float = 3.0
    timeout: int = 0        # 超时秒数，0=不限制

    # ── 运行时字段（不持久化）────────────────────────────────
    _roles: Dict[str, TeamRole] = PrivateAttr(default_factory=dict)
    _env: EventBusEnvironment = PrivateAttr(default=None)
    _scheduler: Optional[Scheduler] = PrivateAttr(default=None)
    _round: int = PrivateAttr(default=0)
    _result_messages: List[TeamMessage] = PrivateAttr(default_factory=list)
    _task_queue: List[str] = PrivateAttr(default_factory=list)  # 剩余子任务队列（Leader 分析后填充）
    _idle_count: int = PrivateAttr(default=0)
    _session_id: str = PrivateAttr(default="default")

    def __init__(self, session_id: str = "default", db_path: str = "./data/team_sessions.db", **data):
        super().__init__(**data)
        # v2: EventBusEnvironment（替代旧的 in-memory Environment）
        object.__setattr__(self, "_env", EventBusEnvironment(session_id=session_id, db_path=db_path, team=self))
        object.__setattr__(self, "_scheduler", None)
        object.__setattr__(self, "_session_id", session_id)
        object.__setattr__(self, "_db_path", db_path)
        object.__setattr__(self, "_result_messages", [])
        object.__setattr__(self, "_task_queue", [])
        object.__setattr__(self, "_idle_count", 0)
        object.__setattr__(self, "_round", 0)

    class Config:
        arbitrary_types_allowed = True

    # ── Role 管理 ─────────────────────────────────────────

    def hire(self, role: TeamRole):
        """雇佣角色加入团队"""
        role.set_environment(self._env)
        self._roles[role.name] = role
        # 注册到 EventBusEnvironment（v2 新增）
        self._env.register_role(role)
        logger.info(f"[TEAM] 雇佣: {role.name} ({role.profile[:30]}...)")

    def fire(self, role_name: str):
        """移除角色"""
        if role_name in self._roles:
            self._env.unregister_role(role_name)
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

        # 图路由模式：仅返回有新消息的角色（observe 读取 EventBus）
        result: List[TeamRole] = []
        for role in self._roles.values():
            news = await role.observe()
            if news:
                result.append(role)
        return result

    # ── 流式运行（v2 — EventBus 消息驱动，保留旧接口）───────

    async def run_stream(
        self, idea: str, n_round: int = 5, send_to: str = ""
    ) -> AsyncGenerator[TeamMessage, None]:
        """
        流式运行团队协作流程，每生成一条消息立即 yield。

        Pipeline/图路由模式：按连接图 + watch_actions 自动路由，多 action 角色自主推进
        Debate 模式：所有角色交替发言，按 pair 分组

        v2 改动：Environment 改为 EventBusEnvironment，消息发布到 SQLite WAL + EventBus。
        内部循环逻辑保持不变（向后兼容）。
        """
        if self.status == "running":
            logger.warning("[TEAM] 已在运行中，忽略重复调用")
            return

        self.status = "running"
        self._round = 0
        self._result_messages = []
        self._idle_count = 0

        # 重置所有角色的已读游标到当前消息末尾，防止旧消息污染本轮
        current_seq = self._env.get_messages_count()
        for role_name in self._roles:
            self._env.mark_read(role_name, seq=current_seq)

        logger.info(f"[TEAM] 开始流式运行: {idea[:50]}... (mode={self.mode}, max {n_round} rounds, cursor_reset={current_seq})")

        # ── 初始消息：用户任务 ────────────────────────────
        if self.mode == "debate":
            for role in self._roles.values():
                if getattr(role, "debate_side", "") in ("positive", "negative"):
                    start_msg = new_message(
                        content=idea,
                        role="user",
                        sent_from="user",
                        send_to=role.name,
                        cause_by="UserRequirement",
                    )
                    await self._env.publish_async(start_msg)
                    self._result_messages.append(start_msg)
                    yield start_msg
        else:
            start_msg = new_message(
                content=idea,
                role="user",
                sent_from="user",
                send_to=send_to or "Leader",
                cause_by="UserRequirement",
            )
            await self._env.publish_async(start_msg)
            self._result_messages.append(start_msg)
            yield start_msg

        # ── 主循环 ────────────────────────────────────────
        max_iterations = max(n_round * 4, 20)
        iteration = 0
        _start_time = time.monotonic()

        while iteration < max_iterations:
            iteration += 1

            if self.status == "stopped":
                logger.info("[TEAM] 收到停止信号，终止流水线")
                break

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
            await self._env.publish_async(round_system)
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
                    await self._env.publish_async(msg)
                    self._result_messages.append(msg)
                    logger.info(f"[TEAM] {role.name}: {msg.content[:80]}...")
                    yield msg

            if idle_this_round:
                self._idle_count += 1
                logger.debug(f"[TEAM] 空闲轮次 +1（总计 {self._idle_count}）")
                if self._idle_count >= 3:
                    logger.warning(f"[TEAM] 连续 {self._idle_count} 轮无产出，触发死循环保护，终止流水线")
                    break
            else:
                self._idle_count = 0

            if self._round >= n_round:
                if self._idle_count > 0:
                    logger.info(f"[TEAM] 达到指定轮次上限 {n_round} 且空闲，终止流水线")
                    break
                logger.debug(f"[TEAM] 轮次上限 {n_round} 但还有活跃任务，继续执行")

            await asyncio.sleep(0.05)

        if self.status == "running":
            self.status = "completed"
        logger.info(f"[TEAM] 运行结束 (status={self.status})，共 {len(self._result_messages)} 条消息")

    # ── v2: 全事件驱动（Scheduler 管理 Agent 生命周期）───────

    async def run_v2_stream(
        self,
        idea: str,
        n_round: int = 5,
        send_to: str = "",
        max_concurrent: int = 4,
        task_ttl: int = 300,
    ) -> AsyncGenerator[TeamMessage, None]:
        """
        v2 全事件驱动流式运行。

        流程：
        1. 根据 idea 分解任务（decompose）→ TaskQueue 入队
        2. 创建 Scheduler 并注册所有 Agent Role
        3. Scheduler.run_stream() 事件驱动执行
        4. 将 Scheduler 的事件流转为 TeamMessage yield

        与 run_stream() 的区别：
        - run_stream(): Team 管理 round 循环，每个 role 在循环中依次执行
        - run_v2_stream(): Scheduler 管理事件驱动循环，Agent 自己 claim/execute/complete 任务
        """
        if self.status == "running":
            logger.warning("[TEAM] 已在运行中，忽略重复调用")
            return

        self.status = "running"
        self._round = 0
        self._result_messages = []
        self._idle_count = 0

        logger.info(f"[TEAM] v2 开始流式运行: {idea[:50]}... (Scheduler, max_concurrent={max_concurrent})")

        # 初始化 Scheduler
        from app.core.multi_agent.task_queue import TaskQueue

        db_path = self._db_path
        queue = TaskQueue(db_path)
        queue.init()  # 幂等建表

        scheduler = Scheduler(
            session_id=self._session_id,
            db_path=db_path,
            max_concurrent=max_concurrent,
            claim_ttl_seconds=task_ttl,
        )
        object.__setattr__(self, "_scheduler", scheduler)

        # 注册所有 Agent Role 到 Scheduler
        for role in self._roles.values():
            scheduler.register_agent(role)
            # 同时注册到 EventBusEnvironment（run_v2_stream 也通过 env 收集消息）
            self._env.register_role(role)

        # 发布初始任务
        root_task = queue.enqueue(
            session_id=self._session_id,
            description=idea,
            task_type="root",
            created_by="user",
        )

        # 发布系统启动消息
        start_msg = new_message(
            content=f"[Scheduler v2] 任务已入队: {idea[:80]}...",
            role="system",
            sent_from="Team",
            cause_by="SystemStartup",
            metadata={"task_id": root_task.id, "round": 0},
        )
        await self._env.publish_async(start_msg)
        yield start_msg

        # 收集 Scheduler 事件，转为 TeamMessage yield
        try:
            # Scheduler.run() 是普通 async 函数，事件通过 EventBus 广播
            # 我们订阅 EventBus 收集 task.completed 等事件
            results = await scheduler.run(max_seconds=n_round * 60)

            # Scheduler.run() 结束后，从队列中汇总所有已完成任务
            all_tasks = scheduler.list_tasks()
            self._round = len([t for t in all_tasks if t.get("state") in ("completed", "failed")])

            for t in all_tasks:
                if t.get("state") == "completed":
                    msg = new_message(
                        content=f"[{t.get('assigned_to', '')}] ✓ 完成: {t.get('result_summary', '') or t.get('description', '')[:80]}",
                        role="system",
                        sent_from="Team",
                        cause_by="TaskCompleted",
                        metadata={"task_id": t.get("id", ""), "result_summary": t.get("result_summary", "")},
                    )
                    await self._env.publish_async(msg)
                    yield msg
                elif t.get("state") == "failed":
                    msg = new_message(
                        content=f"✗ 任务失败 [{t.get('assigned_to', '')}]: {t.get('result_summary', '') or 'unknown'}",
                        role="system",
                        sent_from="Team",
                        cause_by="TaskFailed",
                        metadata={"task_id": t.get("id", ""), "error": t.get("result_summary", "")},
                    )
                    await self._env.publish_async(msg)
                    yield msg
        finally:
            # 停止 Scheduler（同步方法）
            scheduler.stop()
            object.__setattr__(self, "_scheduler", None)

        if self.status == "running":
            self.status = "completed"
        logger.info(f"[TEAM] v2 运行结束 (status={self.status})")

    # ── 运行入口 ─────────────────────────────────────────

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
        # 停止 Scheduler（如果正在运行）
        sch = object.__getattribute__(self, "_scheduler") if hasattr(self, "_scheduler") else None
        if sch is not None:
            sch.stop()

    def summary(self) -> str:
        return (
            f"Team(name={self.name}, mode={self.mode}, status={self.status}, "
            f"roles={list(self._roles.keys())}, "
            f"session_id={self._session_id})"
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