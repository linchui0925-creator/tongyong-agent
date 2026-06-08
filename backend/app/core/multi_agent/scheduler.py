"""
Scheduler — 多智能体调度器

替代 Team.run_stream() 的轮次循环，改为事件驱动的任务调度。

核心设计：
- Scheduler 是事件驱动的调度器，不做轮次循环
- 每个 Agent 是独立的 asyncio Task，监听 EventBus
- TaskQueue 作为共享状态（SQLite WAL），所有 Agent 共享
- EventBus 广播事件，触发 Agent 的任务认领和执行
- 图拓扑由 task_links 表驱动，parent done → child auto promote

架构对比：
  旧（轮次驱动）:
    while rounds < max:
      for role in roles:
        if role.has_news():
          msg = await role.act()
          env.publish(msg)
          yield msg
      await asyncio.sleep(0.05)

  新（事件驱动）:
    while True:
      event = await event_bus.next_event(agent_name)
      if event.type == "task.pending":
        task = task_queue.claim(task_id, agent_name)
        if task:
          ctx = await ExecutionContext.create(...)
          result = await ctx.execute()
          task_queue.complete(task_id, agent_name, result.summary)
          event_bus.publish("task.completed", ...)

与 Hermes kanban 的区别：
- Hermes: 每个 profile gateway 各自跑 dispatcher（多进程开销）
- 这里: 单进程 asyncio，中心化 Scheduler，无重复 polling
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.multi_agent.state_machine import TaskEvent, TaskState
from app.core.multi_agent.event_bus import get_event_bus, Event
from app.core.multi_agent.task_queue import TaskQueue, TaskRecord, DEFAULT_CLAIM_TTL_SECONDS
from app.core.multi_agent.workspace import get_workspace, WorkspaceManager
from app.core.multi_agent.execution_context import TaskExecutionContext
from app.core.multi_agent.role import TeamRole

logger = logging.getLogger(__name__)

# Agent 空闲超时（秒），超时后自动 reclaim
AGENT_IDLE_TIMEOUT_SECONDS = 300

# 调度器心跳间隔（秒）
SCHEDULER_HEARTBEAT_SECONDS = 1.0

# 最大并发 Agent Task 数
MAX_CONCURRENT_AGENTS = 4


# ══════════════════════════════════════════════════════════
# AgentTask — 单个 Agent 的执行任务
# ══════════════════════════════════════════════════════════

@dataclass
class AgentTask:
    """
    单个 Agent 的运行时任务记录。
    
    每个被调度执行的 Agent 角色对应一个 AgentTask 实例。
    """
    role: TeamRole
    task_record: Optional[TaskRecord] = None
    ctx: Optional[TaskExecutionContext] = None
    state: str = "idle"       # idle | running | waiting_event | done | error
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    error: str = ""

    @property
    def is_active(self) -> bool:
        return self.state in ("idle", "running", "waiting_event")


# ══════════════════════════════════════════════════════════
# Scheduler — 事件驱动调度器
# ══════════════════════════════════════════════════════════

class Scheduler:
    """
    事件驱动调度器。
    
    核心职责：
    1. 初始化：根据 requirement 分解任务，创建任务图
    2. 调度：管理 Agent 生命周期，启动/停止/恢复 Agent Task
    3. 监听 EventBus：根据事件自动触发任务认领、执行、完成
    4. 图推进：当父任务完成时，自动 promote 子任务
    
    不做（由 Agent/Action 自己做）：
    - LLM 调用（由 TaskExecutionContext 封装）
    - 工具执行（由 TaskExecutionContext.execute_tool()）
    - 消息路由（由 Environment 继续处理）
    
    使用示例：
    
        scheduler = Scheduler(
            session_id="s_001",
            db_path="./data/team_sessions.db",
        )
        
        # 注册 Agent
        scheduler.register_agent(role, event_types=["task.claimed", "task.completed", "task.failed"])
        
        # 初始化任务（分解需求）
        await scheduler.initialize(requirement="实现用户登录功能")
        
        # 启动调度器（事件驱动循环）
        await scheduler.run()
    """

    def __init__(
        self,
        session_id: str,
        db_path: str = "./data/team_sessions.db",
        max_concurrent: int = MAX_CONCURRENT_AGENTS,
        claim_ttl_seconds: int = DEFAULT_CLAIM_TTL_SECONDS,
    ):
        self.session_id = session_id
        self.db_path = db_path
        self.max_concurrent = max_concurrent
        self.claim_ttl_seconds = claim_ttl_seconds

        self._queue = TaskQueue(db_path)
        self._bus = get_event_bus()
        self._bus.set_db(self._queue._connect())

        # Agent 注册表: agent_name → AgentTask
        self._agents: Dict[str, AgentTask] = {}
        # 并发限制信号量
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # 根任务 ID（流水线的第一个任务）
        self._root_task_id: str = ""
        # 运行状态
        self._running = False
        # Agent Task 列表（用于并发管理）
        self._agent_tasks: List[asyncio.Task] = []

    # ── Agent 注册 ─────────────────────────────────────────

    def register_agent(self, role: TeamRole) -> None:
        """
        注册 Agent 角色到调度器。
        
        Args:
            role: TeamRole 实例（必须已设置 name）
        """
        if role.name in self._agents:
            logger.warning(f"[Scheduler] Agent {role.name} 已注册，跳过")
            return
        self._agents[role.name] = AgentTask(role=role)
        logger.info(f"[Scheduler] 注册 Agent: {role.name}")

    def unregister_agent(self, agent_name: str) -> None:
        """取消注册 Agent"""
        self._agents.pop(agent_name, None)
        logger.info(f"[Scheduler] 取消注册 Agent: {agent_name}")

    # ── 初始化：任务分解 ─────────────────────────────────────────

    async def initialize(
        self,
        requirement: str,
        root_agent: str = "Leader",
        decompose_llm: Any = None,
    ) -> str:
        """
        初始化：创建根任务并分解子任务。
        
        Args:
            requirement: 用户需求
            root_agent:  根任务创建者（默认 Leader）
            decompose_llm: 可选的 LLM 实例（用于自动分解）
        
        Returns:
            root_task_id
        """
        root_task = self._queue.enqueue(
            session_id=self.session_id,
            description=requirement[:500],
            task_type="root",
            created_by=root_agent,
            priority=100,
            input_summary=requirement[:500],
        )
        self._root_task_id = root_task.id
        logger.info(f"[Scheduler] 创建根任务: {root_task.id}")

        # 自动分解（如果提供了 LLM）
        if decompose_llm:
            subtasks = await self._decompose_requirement(
                requirement, decompose_llm
            )
            parent_id = root_task.id
            for i, subtask_desc in enumerate(subtasks):
                subtask = self._queue.enqueue(
                    session_id=self.session_id,
                    description=subtask_desc,
                    task_type="subtask",
                    created_by=root_agent,
                    priority=90 - i,
                    input_summary=subtask_desc[:500],
                )
                self._queue.link(parent_id, subtask.id)
                logger.info(f"[Scheduler] 子任务: {subtask.id} → {subtask_desc[:50]}")

        return root_task.id

    async def _decompose_requirement(
        self,
        requirement: str,
        llm: Any,
    ) -> List[str]:
        """使用 LLM 将需求分解为子任务列表"""
        prompt = f"""将以下需求分解为具体的子任务列表（每个子任务一行，不超过 5 个）：

需求：{requirement}

请只返回子任务描述列表，每行一个，不要其他文字。"""
        try:
            response = await llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            lines = [
                line.strip()
                for line in response.content.strip().split("\n")
                if line.strip()
            ]
            return lines[:5]
        except Exception as e:
            logger.warning(f"[Scheduler] 自动分解失败: {e}")
            return [requirement[:200]]

    # ── 主循环 ─────────────────────────────────────────

    async def run(self, max_seconds: float = 0) -> Dict[str, Any]:
        """
        启动调度器主循环（事件驱动）。
        
        Args:
            max_seconds: 最大运行时间（秒），0=不限制
        
        Returns:
            运行结果统计
        """
        if self._running:
            logger.warning("[Scheduler] 已在运行中，忽略重复调用")
            return {"status": "already_running"}

        self._running = True
        t0 = time.monotonic()
        stats = {"tasks_completed": 0, "tasks_failed": 0, "events_processed": 0}

        logger.info(
            f"[Scheduler] 启动调度器 (session={self.session_id}, "
            f"max_concurrent={self.max_concurrent})"
        )

        try:
            while self._running:
                # 超时检查
                elapsed = time.monotonic() - t0
                if max_seconds > 0 and elapsed > max_seconds:
                    logger.info(f"[Scheduler] 达到最大运行时间 {max_seconds}s，退出")
                    break

                # 扫描过期 claim（reclaim）
                reclaimed = self._queue.reclaim(self.session_id)
                if reclaimed > 0:
                    logger.info(f"[Scheduler] reclaim 回收了 {reclaimed} 个过期 claim")

                # 发布心跳事件（触发 Agent 检查自己的任务）
                now_iso = datetime.now(timezone.utc).isoformat()
                await self._bus.publish(
                    event_type="scheduler.heartbeat",
                    payload={"elapsed": elapsed, "timestamp": now_iso},
                    source="Scheduler",
                    session_id=self.session_id,
                )

                # 为每个 idle Agent 分发 ready 任务
                await self._dispatch_ready_tasks()

                # 等待下一个心跳（协程挂起，不占用 CPU）
                await asyncio.sleep(SCHEDULER_HEARTBEAT_SECONDS)

                stats["events_processed"] += 1

        except asyncio.CancelledError:
            logger.info("[Scheduler] 被 CancelledError 中止")
        finally:
            self._running = False

        return stats

    async def _dispatch_ready_tasks(self) -> None:
        """
        为每个 idle Agent 分发一个 ready 任务。
        
        分发策略：
        1. 获取所有 pending 且无 claim 的任务（按 priority DESC, created_at ASC）
        2. 对每个 idle Agent，依次尝试 claim 最优先的任务
        3. claim 成功后启动 asyncio Task 执行
        """
        # 获取当前所有 idle Agent
        idle_agents = [
            (name, at)
            for name, at in self._agents.items()
            if at.state == "idle"
        ]
        if not idle_agents:
            return

        # 获取 ready 任务
        ready_tasks = self._queue.get_ready(self.session_id, limit=20)
        if not ready_tasks:
            return

        # 贪婪分发：每个 Agent 最多一个任务
        for task in ready_tasks:
            if not idle_agents:
                break

            # 找优先级最高的 idle Agent
            agent_name, agent_task = idle_agents.pop(0)

            # 尝试 claim → start（CLAIMED → RUNNING）
            record = self._queue.claim(task.id, agent_name, self.claim_ttl_seconds)
            if not record:
                continue
            record = self._queue.start(task.id, agent_name)
            if not record:
                continue

            # 启动 Agent 执行协程
            agent_task.task_record = record
            agent_task.state = "running"
            agent_task.started_at = datetime.now(timezone.utc).isoformat()

            # 并发控制（信号量）
            coro = self._run_agent_task(agent_name, agent_task)
            task = asyncio.create_task(self._with_semaphore(coro, agent_task))
            self._agent_tasks.append(task)

            logger.info(
                f"[Scheduler] 分发任务 {task.id} → {agent_name} "
                f"(描述: {task.description[:50]}...)"
            )

    async def _with_semaphore(
        self,
        coro,
        agent_task: AgentTask,
    ) -> None:
        """用信号量包装协程，控制并发"""
        async with self._semaphore:
            try:
                await coro
            except Exception as e:
                logger.error(f"[Scheduler] Agent {agent_task.role.name} 执行异常: {e}")

    async def _run_agent_task(self, agent_name: str, agent_task: AgentTask) -> None:
        """
        运行单个 Agent Task。
        
        流程：
        1. 获取 LLM 和 tool_mgr
        2. 创建 TaskExecutionContext
        3. 执行任务（ctx.execute）
        4. 更新 TaskQueue（complete/fail）
        5. 发布事件
        6. 广播图拓扑（parent done → promote children）
        """
        role = agent_task.role
        record = agent_task.task_record
        if not record:
            return

        task_id = record.id
        logger.info(f"[Scheduler] Agent {agent_name} 开始执行任务 {task_id}")

        try:
            # 获取 LLM 和 tool_mgr
            from app.core.multi_agent.actions.base import _get_llm_for_role
            from app.tools.manager import get_tool_manager

            llm = _get_llm_for_role(role)
            tool_mgr = get_tool_manager()

            if not llm:
                logger.error(f"[Scheduler] Agent {agent_name} 无法获取 LLM")
                self._queue.fail(task_id, agent_name, "LLM not available")
                agent_task.state = "error"
                agent_task.error = "LLM not available"
                return

            # 创建执行上下文
            ctx = await TaskExecutionContext.create(
                task_id=task_id,
                session_id=self.session_id,
                agent_name=agent_name,
                llm=llm,
                tool_mgr=tool_mgr,
                db_path=self.db_path,
            )
            agent_task.ctx = ctx

            # 构造 prompt（从 workspace input 或 record.input_summary）
            from app.core.multi_agent.workspace import get_workspace
            ws = get_workspace(task_id, create=False)
            if ws and ws.exists("input", "requirement.md"):
                prompt = ws.read("input", "requirement.md")
            else:
                prompt = record.input_summary or record.description

            # 执行（带超时保护）
            result = await asyncio.wait_for(
                ctx.execute(
                    prompt=prompt,
                    system_prompt=role.build_system_prompt(),
                ),
                timeout=300.0,
            )

            # 写结果到 workspace
            if result.workspace_path:
                ws_out = get_workspace(task_id, create=False)
                if ws_out:
                    ws_out.write(
                        "output",
                        "result.md",
                        f"# 执行结果\n\n{result.response}\n\n## 工具调用\n{result.tool_summary}",
                    )

            # 更新任务状态
            if result.success:
                self._queue.complete(
                    task_id,
                    agent_name,
                    result_summary=f"success:{result.response[:200]}",
                )
                agent_task.state = "done"
                logger.info(f"[Scheduler] 任务 {task_id} 完成")

                # 发布 completed 事件（触发图拓扑更新）
                await self._bus.publish(
                    event_type=TaskEvent.COMPLETED.value,
                    payload={
                        "task_id":    task_id,
                        "agent":      agent_name,
                        "result_summary": result.response[:200],
                        "workspace_path": result.workspace_path,
                    },
                    source=agent_name,
                    task_id=task_id,
                    session_id=self.session_id,
                )

                # 图拓扑推进：promote 子任务
                promoted = self._queue.promote(task_id)
                if promoted > 0:
                    logger.info(f"[Scheduler] 任务 {task_id} 完成，promote {promoted} 个子任务")
            else:
                self._queue.fail(task_id, agent_name, result.error or "execution failed")
                agent_task.state = "error"
                agent_task.error = result.error or "unknown"

        except asyncio.TimeoutError:
            logger.warning(f"[Scheduler] Agent {agent_name} 执行超时")
            self._queue.fail(task_id, agent_name, "execution timeout")
            agent_task.state = "error"
            agent_task.error = "timeout"

        except Exception as e:
            logger.error(f"[Scheduler] Agent {agent_name} 执行异常: {e}", exc_info=True)
            self._queue.fail(task_id, agent_name, str(e))
            agent_task.state = "error"
            agent_task.error = str(e)

        finally:
            agent_task.ended_at = datetime.now(timezone.utc).isoformat()
            # 重置 Agent 状态为 idle
            if agent_name in self._agents:
                self._agents[agent_name].state = "idle"

    # ── 停止 ─────────────────────────────────────────

    def stop(self) -> None:
        """主动停止调度器"""
        logger.info("[Scheduler] 收到停止信号")
        self._running = False
        # 取消所有正在运行的 Agent 任务
        for task in self._agent_tasks:
            if not task.done():
                task.cancel()
        self._agent_tasks.clear()

    # ── 状态查询 ─────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """返回调度器状态统计"""
        queue_stats = self._queue.stats(self.session_id)
        agent_states = {name: at.state for name, at in self._agents.items()}
        return {
            "session_id":   self.session_id,
            "running":      self._running,
            "root_task_id": self._root_task_id,
            "queue_stats":  queue_stats,
            "agent_states": agent_states,
        }

    def list_tasks(self, states: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """列出当前任务"""
        records = self._queue.list_by_session(self.session_id, states=states)
        return [r.to_dict() for r in records]

    def __repr__(self) -> str:
        return f"<Scheduler session={self.session_id} running={self._running}>"