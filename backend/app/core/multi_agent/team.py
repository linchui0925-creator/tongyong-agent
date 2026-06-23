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


# W4-9 P1-2 修复 (2026-06-21): 按辩位排序, judge 固定末尾, 未填 position 的兜底为 99
# 抽成 module-level helper 便于单测 (不依赖 Team/EventBusEnvironment fixture)
_DEBATE_POSITION_ORDER = {"first": 0, "second": 1, "third": 2, "fourth": 3, "judge": 4}


def sort_roles_by_debate_position(roles: List[TeamRole]) -> List[TeamRole]:
    """辩论模式按辩位排序: first < second < third < fourth < judge < (未填)"""
    return sorted(roles, key=lambda r: _DEBATE_POSITION_ORDER.get(r.debate_position, 99))


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

    # Pydantic v2: model_config 替代 v1 的 class Config (避免 PydanticDeprecatedSince20 警告)
    model_config = {"arbitrary_types_allowed": True}

    # ── Role 管理 ─────────────────────────────────────────

    def hire(self, role: TeamRole):
        """雇佣角色加入团队"""
        role.set_environment(self._env)
        self._roles[role.name] = role
        # 注册到 EventBusEnvironment（v2 新增）
        self._env.register_role(role)
        logger.info(f"[TEAM] 雇佣: {role.name} ({role.profile[:30]}...)")

    def _set(self, key: str, value):
        """
        设置 PrivateAttr 字段 (Pydantic v2 fix).

        Pydantic v2 中 `self._x = Y` 对 `PrivateAttr(default=...)` 静默失败,
        必须用 object.__setattr__ 绕过. 此方法封装此行为,
        所有 runtime state 修改都走它.
        """
        object.__setattr__(self, key, value)

    def fire(self, role_name: str):
        """移除角色 (同时从 scheduler 注销, v2 模式)"""
        if role_name in self._roles:
            self._env.unregister_role(role_name)
            del self._roles[role_name]
            # v2: 如果 scheduler 在跑, 也要注销
            sch = object.__getattribute__(self, "_scheduler") if hasattr(self, "_scheduler") else None
            if sch is not None and hasattr(sch, "_agents") and role_name in sch._agents:
                sch._agents.pop(role_name, None)
                logger.debug(f"[TEAM] 从 scheduler 注销: {role_name}")
            logger.info(f"[TEAM] 解雇: {role_name}")

    def get_role(self, name: str) -> Optional[TeamRole]:
        return self._roles.get(name)

    def list_roles(self) -> List[str]:
        return list(self._roles.keys())

    # ── 协作模式核心 ─────────────────────────────────────────

    async def _get_roles_for_round(self) -> List[TeamRole]:
        """
        根据模式返回本轮应执行的角色列表。

        Debate 模式：所有角色都参与（交替发言），并按 debate_position
          (first/second/third/fourth/judge) 排序 —— W4-9 P1-2 修复 2026-06-21。
          旧实现直接返回 _roles 插入顺序，UI 添加顺序可能与辩位顺序不一致
          (e.g. 先 hire fourth 再 hire first), 导致 judge 拿到的发言时间错乱。
        Pipeline/图路由模式：只返回收到新消息的角色。Worker 仅接收定向消息，
          Leader 通过连接图和 watch_actions 接收。
        """
        if self.mode == "debate":
            return sort_roles_by_debate_position(list(self._roles.values()))

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
        ⚠️ DEPRECATED (W4-20): round 轮次驱动, 由 Team 主循环管理 round,
        已被 run_v2_stream() 取代. run_v2_stream() 走 Scheduler 事件驱动,
        支持 Agent 主动 claim 任务 / 监听其他 Agent 完成 / 死信处理等.
        3 个月内迁移完成 (目标: 2026-09-22).
        调用方: 仅有 backend/app/api/hermes_routes.py 的旧 debate endpoint
        仍直接用这个, 新代码请用 run_v2_stream().
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
        # Pydantic v2 fix (W4-27): PrivateAttr 重赋值必须用 object.__setattr__
        self._set("_round", 0)
        self._set("_result_messages", [])
        self._set("_idle_count", 0)

        # 重置所有角色的已读游标到当前消息末尾，防止旧消息污染本轮
        current_seq = self._env.get_messages_count()
        for role_name in self._roles:
            self._env.mark_read(role_name, seq=current_seq)

        logger.info(f"[TEAM] 开始流式运行: {idea[:50]}... (mode={self.mode}, max {n_round} rounds, cursor_reset={current_seq})")

        # ── 初始消息：用户任务 ────────────────────────────
        # bug fix: 原代码要求 debate_side in ("positive","negative") 才收 start_msg，
        #   但 UI 允许未填阵营保存 → 全部跳过 → 0 消息死锁。改为全部辩手都收 (裁判也收以便观察)。
        if self.mode == "debate":
            for role in self._roles.values():
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

            self._set("_round", self._round + 1)

            round_system = new_message(
                content=f"[Round {self._round}]",
                role="system",
                sent_from="Team",
                metadata={"round": self._round},
            )
            await self._env.publish_async(round_system)
            yield round_system

            roles_this_round = await self._get_roles_for_round()

            if not roles_this_round:
                logger.info(f"[TEAM] 第 {self._round} 轮无角色需要执行，提前结束")
                break

            logger.info(f"[TEAM] ===== 第 {self._round} 轮 ({len(roles_this_round)} 个角色) =====")

            idle_this_round = True

            for role in roles_this_round:
                # Pydantic v2 fix + Bug fix (W4-27): 单角色异常不能杀全队
                try:
                    msg = await role.run(self._round)
                except Exception as e:
                    logger.exception(f"[TEAM] {role.name} 角色运行异常 (已隔离, 不影响其他角色): {e}")
                    err_msg = new_message(
                        content=f"[{role.name}] 运行异常: {type(e).__name__}: {e}",
                        role="system",
                        sent_from="Team",
                        cause_by="RoleError",
                        metadata={"error": True, "role": role.name, "round": self._round},
                    )
                    await self._env.publish_async(err_msg)
                    self._result_messages.append(err_msg)
                    yield err_msg
                    continue
                if msg:
                    idle_this_round = False
                    msg.metadata["round"] = self._round
                    await self._env.publish_async(msg)
                    self._result_messages.append(msg)
                    logger.info(f"[TEAM] {role.name}: {msg.content[:80]}...")
                    yield msg

            if idle_this_round:
                self._set("_idle_count", self._idle_count + 1)
                logger.debug(f"[TEAM] 空闲轮次 +1（总计 {self._idle_count}）")
                if self._idle_count >= 3:
                    logger.warning(f"[TEAM] 连续 {self._idle_count} 轮无产出，触发死循环保护，终止流水线")
                    break
            else:
                self._set("_idle_count", 0)

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
        # Pydantic v2 fix
        self._set("_round", 0)
        self._set("_result_messages", [])
        self._set("_idle_count", 0)

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

        # W4-27 fix: 角色 cursor 重置到当前 _msg_counter
        # 否则第二次 run_v2_stream 会把上次 run 的消息当新消息
        current_seq = self._env.get_messages_count()
        for role_name in self._roles:
            self._env.mark_read(role_name, seq=current_seq)

        # W4-27 fix: 分解 idea 为多个任务 (旧实现只入队 1 个 root task)
        # 简单分句分解: 按 . / ; / \n 拆, 每句 1 个 task; 如果只有 1 句, 用整段
        sub_ideas = self._decompose_idea(idea)
        logger.info(f"[TEAM v2] idea 分解: 1 → {len(sub_ideas)} 个子任务")

        # 第一个子任务是 root, 后续是依赖 root 的 subtask
        root_task = queue.enqueue(
            session_id=self._session_id,
            description=sub_ideas[0],
            task_type="root",
            created_by="user",
        )
        for sub in sub_ideas[1:]:
            # 注: TaskQueue.enqueue() 当前不支持 depends_on, 所以 subtask 无显式依赖
            # (Scheduler 仍会按 priority DESC, created_at ASC 顺序 claim, 跟 root 同 session)
            queue.enqueue(
                session_id=self._session_id,
                description=sub,
                task_type="subtask",
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

        # W4-27 fix: 实际订阅 EventBus 实时事件 (旧实现 await scheduler.run() 后才 yield, 阻塞 5min)
        # 方案: 启动 scheduler 后台任务, 同时订阅 EventBus 过滤 task.* 事件实时 yield
        from app.core.multi_agent.event_bus import get_event_bus
        bus = get_event_bus(self._session_id, self._db_path)
        last_event_seq = 0
        try:
            latest = bus.get_latest_event_seq(self._session_id)
            if latest:
                last_event_seq = latest
        except Exception:
            pass

        # 启动 scheduler 后台
        scheduler_task = asyncio.create_task(scheduler.run(max_seconds=n_round * 60))
        try:
            # 实时轮询 EventBus (100ms 间隔, 比旧实现 await 5min 好很多)
            import time as _time
            t0 = _time.monotonic()
            emitted_task_ids: set = set()
            while not scheduler_task.done():
                await asyncio.sleep(0.1)
                # 拉新事件
                try:
                    new_events = bus.get_events(
                        session_id=self._session_id,
                        after_seq=last_event_seq,
                        limit=50,
                    )
                except Exception:
                    new_events = []
                for ev in new_events:
                    last_event_seq = max(last_event_seq, ev.seq if hasattr(ev, "seq") else 0)
                    # 过滤 task.* 事件
                    if not ev.type.startswith("task."):
                        continue
                    task_id = ev.payload.get("task_id", "") if hasattr(ev, "payload") else ""
                    if task_id in emitted_task_ids:
                        continue
                    emitted_task_ids.add(task_id)
                    # 转 TeamMessage yield
                    if ev.type == "task.completed":
                        tm = new_message(
                            content=f"✓ 任务完成 [{ev.payload.get('assigned_to', '')}]: {ev.payload.get('result_summary', '')[:80] or 'done'}",
                            role="system", sent_from="Team",
                            cause_by="TaskCompleted",
                            metadata={"task_id": task_id, "result_summary": ev.payload.get("result_summary", "")},
                        )
                    elif ev.type == "task.failed":
                        tm = new_message(
                            content=f"✗ 任务失败 [{ev.payload.get('assigned_to', '')}]: {ev.payload.get('error', '')[:80]}",
                            role="system", sent_from="Team",
                            cause_by="TaskFailed",
                            metadata={"task_id": task_id, "error": ev.payload.get("error", "")},
                        )
                    else:
                        continue
                    await self._env.publish_async(tm)
                    self._result_messages.append(tm)
                    self._set("_round", self._round + 1)
                    yield tm
                # 兜底超时
                if _time.monotonic() - t0 > n_round * 60 + 5:
                    break

            # 兜底: scheduler 结束后, 补一次 list_tasks (防漏 yield)
            try:
                await scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
            all_tasks = scheduler.list_tasks()
            for t in all_tasks:
                tid = t.get("id", "")
                if tid in emitted_task_ids:
                    continue
                if t.get("state") == "completed":
                    tm = new_message(
                        content=f"[{t.get('assigned_to', '')}] ✓ 完成: {t.get('result_summary', '') or t.get('description', '')[:80]}",
                        role="system", sent_from="Team",
                        cause_by="TaskCompleted",
                        metadata={"task_id": tid, "result_summary": t.get("result_summary", "")},
                    )
                    await self._env.publish_async(tm)
                    self._result_messages.append(tm)
                    self._set("_round", self._round + 1)
                    yield tm
                elif t.get("state") == "failed":
                    tm = new_message(
                        content=f"✗ 任务失败 [{t.get('assigned_to', '')}]: {t.get('result_summary', '') or 'unknown'}",
                        role="system", sent_from="Team",
                        cause_by="TaskFailed",
                        metadata={"task_id": tid, "error": t.get("result_summary", "")},
                    )
                    await self._env.publish_async(tm)
                    self._result_messages.append(tm)
                    self._set("_round", self._round + 1)
                    yield tm
        finally:
            # 停止 Scheduler（同步方法）
            if not scheduler_task.done():
                scheduler_task.cancel()
                try:
                    await scheduler_task
                except (asyncio.CancelledError, Exception):
                    pass
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

    @staticmethod
    def _decompose_idea(idea: str) -> List[str]:
        """
        简单分句分解 idea → 子任务列表 (W4-27 引入)

        规则:
        - 按句号 . / 分号 ; / 问号 ? / 感叹号 ! / 换行 \n 拆
        - 过滤空段 / 长度 < 5 的噪音
        - 至少返回 1 个 (整段作为 1 个任务)

        未来可替换为 LLM decompose (用 LLM 把 idea 拆成有序子任务)
        """
        import re
        if not idea or not idea.strip():
            return ["(empty)"]
        parts = re.split(r"[.。;；?？！!\n]+", idea)
        parts = [p.strip() for p in parts if p.strip() and len(p.strip()) >= 3]
        return parts if parts else [idea.strip()]

    def summary(self) -> str:
        return (
            f"Team(name={self.name}, mode={self.mode}, status={self.status}, "
            f"roles={list(self._roles.keys())}, "
            f"session_id={self._session_id}, "
            f"round={self._round}, msgs={len(self._result_messages)})"
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