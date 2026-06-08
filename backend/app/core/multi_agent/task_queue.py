"""
TaskQueue — 多智能体 SQLite 任务队列

基于 SQLite WAL 的共享任务队列，支持：
- 原子 claim + TTL（防抢）
- 自动 reclaim（超时回收）
- 状态转换（complete/reject/fail）
- 依赖图 + 子任务自动 promote
- 图拓扑驱动并行

核心逻辑（移植自 Hermes kanban）：
- claim 用 BEGIN IMMEDIATE + UPDATE ... WHERE claim_lock IS NULL OR claim_lock != self
- promote 用 WITH RECURSIVE recompute 递归提升子任务
- reclaim 扫描 claim_expires < now 的过期 claim
"""

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.core.multi_agent.state_machine import (
    TaskState, TaskEvent, TransitionError,
    LEGAL_TRANSITIONS, STATE_LABELS,
)

logger = logging.getLogger(__name__)

# 默认 TTL = 5 分钟（秒）
DEFAULT_CLAIM_TTL_SECONDS = 300

# reclaim 扫描间隔（秒）
RECLAIM_SCAN_INTERVAL_SECONDS = 60


# ══════════════════════════════════════════════════════════
# TaskRecord — 数据库行对象
# ══════════════════════════════════════════════════════════

class TaskRecord:
    """任务数据库记录（内存表示）"""

    __slots__ = (
        "id", "session_id", "state", "task_type", "description",
        "assigned_to", "created_by", "workspace_path",
        "input_summary", "result_summary",
        "claim_lock", "claim_expires",
        "priority", "created_at", "updated_at",
        "started_at", "completed_at",
    )

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k, ""))

    @property
    def is_terminal(self) -> bool:
        return TaskState(self.state) in {TaskState.COMPLETED}

    @property
    def state_obj(self) -> TaskState:
        return TaskState(self.state)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self) -> str:
        return f"<TaskRecord {self.id} state={self.state} assigned_to={self.assigned_to}>"


# ══════════════════════════════════════════════════════════
# TaskQueue — 任务队列
# ══════════════════════════════════════════════════════════

class TaskQueue:
    """
    SQLite 任务队列。
    
    所有 Agent 共享同一个队列，通过 WAL + 原子 claim 实现并发安全。
    
    核心操作：
    - enqueue:       新建任务（pending）
    - claim:         Agent 原子认领任务
    - start:         开始执行（running）
    - complete:      标记完成（completed）
    - reject:        业务拒绝（rejected）
    - fail:          执行异常（failed）
    - reclaim:       扫描并回收过期 claim
    - promote:       提升子任务为 ready
    - link:         建立父子依赖关系
    - get_ready:     获取当前可执行的任务
    - get_for_agent: 获取某 Agent 被认领的任务
    
    不做：
    - 不实现消息传递（由 EventBus + TeamMessage 处理）
    - 不实现调度（由 Scheduler 处理）
    """

    def __init__(self, db_path: str = "./data/team_sessions.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._local = threading.local()

    def init(self) -> None:
        """
        初始化数据库表（创建 tasks / task_links / team_events 表）。
        幂等操作，重复调用安全。
        与 TeamSessionStore.init() 共用同一数据库时保证顺序：
            1. TeamSessionStore.init() 先调用（建 sessions/roles/messages 等表）
            2. TaskQueue.init() 再调用（建 tasks/task_links/team_events 表）
        """
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id              TEXT PRIMARY KEY,
                session_id     TEXT NOT NULL DEFAULT '',
                state          TEXT NOT NULL DEFAULT 'pending',
                task_type      TEXT NOT NULL DEFAULT '',
                description    TEXT NOT NULL DEFAULT '',
                assigned_to    TEXT NOT NULL DEFAULT '',
                created_by     TEXT NOT NULL DEFAULT '',
                workspace_path TEXT NOT NULL DEFAULT '',
                input_summary  TEXT NOT NULL DEFAULT '',
                result_summary TEXT NOT NULL DEFAULT '',
                claim_lock     TEXT,
                claim_expires  TEXT,
                priority       INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                started_at     TEXT NOT NULL DEFAULT '',
                completed_at   TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_state   ON tasks(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_links (
                id         TEXT PRIMARY KEY,
                parent_id  TEXT NOT NULL,
                child_id   TEXT NOT NULL,
                link_type  TEXT NOT NULL DEFAULT 'blocks',
                created_at TEXT NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (child_id)  REFERENCES tasks(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_links_parent ON task_links(parent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_links_child  ON task_links(child_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS team_events (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL,
                payload     TEXT NOT NULL DEFAULT '{}',
                source      TEXT NOT NULL DEFAULT '',
                task_id     TEXT NOT NULL DEFAULT '',
                session_id  TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON team_events(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task    ON team_events(task_id)")
        conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """获取线程局部长连接"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    # ── 基础 CRUD ─────────────────────────────────────────

    def enqueue(
        self,
        session_id: str,
        description: str,
        task_type: str = "",
        created_by: str = "",
        priority: int = 0,
        input_summary: str = "",
        workspace_path: str = "",
    ) -> TaskRecord:
        """
        创建新任务（初始状态 pending）。
        
        Returns:
            TaskRecord
        """
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self._connect()
        conn.execute(
            """
            INSERT INTO tasks
                (id, session_id, state, task_type, description, assigned_to, created_by,
                 workspace_path, input_summary, result_summary, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id, session_id, TaskState.PENDING.value, task_type,
                description, "", created_by,
                workspace_path, input_summary, "", priority, now, now,
            ),
        )
        conn.commit()

        return self.get(task_id)

    def get(self, task_id: str) -> Optional[TaskRecord]:
        """根据 ID 获取任务"""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def list_by_session(
        self,
        session_id: str,
        states: Optional[List[str]] = None,
        assigned_to: str = "",
        limit: int = 100,
    ) -> List[TaskRecord]:
        """列出某会话的任务"""
        conn = self._connect()
        query = "SELECT * FROM tasks WHERE session_id = ?"
        params: List[Any] = [session_id]

        if states:
            placeholders = ",".join(["?"] * len(states))
            query += f" AND state IN ({placeholders})"
            params.extend(states)

        if assigned_to:
            query += " AND assigned_to = ?"
            params.append(assigned_to)

        query += " ORDER BY priority DESC, created_at ASC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def _row_to_record(self, row: sqlite3.Row) -> TaskRecord:
        cols = [
            "id", "session_id", "state", "task_type", "description",
            "assigned_to", "created_by", "workspace_path",
            "input_summary", "result_summary",
            "claim_lock", "claim_expires",
            "priority", "created_at", "updated_at",
            "started_at", "completed_at",
        ]
        kwargs = dict(zip(cols, row))
        return TaskRecord(**kwargs)

    # ── claim / start ─────────────────────────────────────────

    def claim(
        self,
        task_id: str,
        agent_name: str,
        ttl_seconds: int = DEFAULT_CLAIM_TTL_SECONDS,
    ) -> Optional[TaskRecord]:
        """
        原子认领任务。
        
        使用 BEGIN IMMEDIATE + 条件 UPDATE 保证同一任务只被一个 Agent 认领。
        已过期的 claim（claim_expires < now）自动释放。
        
        Args:
            task_id:     任务 ID
            agent_name:  认领者名称
            ttl_seconds: claim 有效期
        
        Returns:
            TaskRecord（认领成功）或 None（任务已被认领或不存在）
        """
        now = datetime.now(timezone.utc).isoformat()
        expires = datetime.now(timezone.utc).isoformat()

        conn = self._connect()

        # 清理已过期的 claim（先释放再认领）
        conn.execute(
            """
            UPDATE tasks
            SET claim_lock = NULL, claim_expires = NULL, assigned_to = ''
            WHERE claim_expires IS NOT NULL AND claim_expires < ?
            """,
            (now,),
        )

        # 原子认领：只有 claim_lock 为 NULL 或已过期，才允许更新
        cursor = conn.execute(
            """
            UPDATE tasks
            SET state = ?,
                claim_lock = ?,
                claim_expires = datetime(?, '+' || ? || ' seconds'),
                assigned_to = ?,
                updated_at = ?
            WHERE id = ?
              AND state = ?
              AND (claim_lock IS NULL OR claim_expires < ?)
            """,
            (
                TaskState.CLAIMED.value,  # state = ?
                agent_name,                # claim_lock = ?
                now, ttl_seconds,         # claim_expires = datetime(?, '+' || ? || ' seconds')
                agent_name,               # assigned_to = ?
                now,                      # updated_at = ?
                task_id,
                TaskState.PENDING.value,  # WHERE state = ?
                now,                      # WHERE claim_expires < ?
            ),
        )

        if cursor.rowcount == 0:
            conn.commit()
            return None

        conn.commit()
        return self.get(task_id)

    def start(self, task_id: str, agent_name: str) -> Optional[TaskRecord]:
        """
        开始执行任务（pending/claimed → running）。
        
        Returns:
            TaskRecord（成功）或 None（无权执行或状态不允许）
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        cursor = conn.execute(
            """
            UPDATE tasks
            SET state = ?, assigned_to = ?, updated_at = ?, started_at = ?
            WHERE id = ?
              AND state IN (?, ?)
              AND claim_lock = ?
            """,
            (
                TaskState.RUNNING.value,
                agent_name,
                now, now,
                task_id,
                TaskState.PENDING.value,
                TaskState.CLAIMED.value,
                agent_name,
            ),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get(task_id)

    # ── complete / reject / fail ─────────────────────────────────────────

    def complete(
        self,
        task_id: str,
        agent_name: str,
        result_summary: str = "",
    ) -> Optional[TaskRecord]:
        """
        标记任务完成（running → completed）。
        
        Returns:
            TaskRecord 或 None
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        cursor = conn.execute(
            """
            UPDATE tasks
            SET state = ?, result_summary = ?, updated_at = ?, completed_at = ?,
                claim_lock = NULL, claim_expires = NULL
            WHERE id = ? AND state IN (?, ?) AND claim_lock = ?
            """,
            (
                TaskState.COMPLETED.value,
                result_summary,
                now, now,
                task_id,
                TaskState.CLAIMED.value,
                TaskState.RUNNING.value,
                agent_name,
            ),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get(task_id)

    def reject(
        self,
        task_id: str,
        agent_name: str,
        reason: str = "",
    ) -> Optional[TaskRecord]:
        """
        业务拒绝（running → rejected）。
        
        Returns:
            TaskRecord 或 None
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        cursor = conn.execute(
            """
            UPDATE tasks
            SET state = ?, result_summary = ?, updated_at = ?,
                claim_lock = NULL, claim_expires = NULL
            WHERE id = ? AND state = ? AND claim_lock = ?
            """,
            (
                TaskState.REJECTED.value,
                f"rejected: {reason}",
                now,
                task_id,
                TaskState.RUNNING.value,
                agent_name,
            ),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get(task_id)

    def fail(
        self,
        task_id: str,
        agent_name: str,
        error: str = "",
    ) -> Optional[TaskRecord]:
        """
        标记执行异常（running → failed）。
        
        Returns:
            TaskRecord 或 None
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        cursor = conn.execute(
            """
            UPDATE tasks
            SET state = ?, result_summary = ?, updated_at = ?,
                claim_lock = NULL, claim_expires = NULL
            WHERE id = ? AND state = ? AND claim_lock = ?
            """,
            (
                TaskState.FAILED.value,
                f"failed: {error}",
                now,
                task_id,
                TaskState.RUNNING.value,
                agent_name,
            ),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get(task_id)

    def reclaim(
        self,
        session_id: str,
        reason: str = "ttl_expired",
    ) -> int:
        """
        扫描并回收会话内所有已过期的 claim。
        
        Args:
            session_id: 会话 ID
            reason:    回收原因（记录到 result_summary）
        
        Returns:
            回收的任务数量
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()

        # 找出所有已过期的 claim
        rows = conn.execute(
            """
            SELECT id FROM tasks
            WHERE session_id = ?
              AND claim_expires IS NOT NULL
              AND claim_expires < ?
              AND state IN (?, ?)
            """,
            (session_id, now, TaskState.CLAIMED.value, TaskState.RUNNING.value),
        ).fetchall()

        count = 0
        for (task_id,) in rows:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET state = ?, claim_lock = NULL, claim_expires = NULL,
                    assigned_to = '', result_summary = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskState.RECLAIMED.value,
                    f"reclaimed: {reason}",
                    now,
                    task_id,
                ),
            )
            if cursor.rowcount > 0:
                count += 1

        conn.commit()
        if count > 0:
            logger.info(f"[TaskQueue] reclaim 回收了 {count} 个任务")
        return count

    # ── 依赖图：link / promote ─────────────────────────────────────────

    def link(self, parent_id: str, child_id: str, link_type: str = "subtask") -> bool:
        """
        建立父子依赖关系（parent done → child 自动 promote）。
        
        Returns:
            True（新建成功）或 False（已存在或无权）
        """
        link_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO task_links (id, parent_id, child_id, link_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (link_id, parent_id, child_id, link_type, now),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_children(self, parent_id: str) -> List[TaskRecord]:
        """获取某任务的直接子任务"""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT t.* FROM tasks t
            JOIN task_links l ON t.id = l.child_id
            WHERE l.parent_id = ?
            ORDER BY t.created_at
            """,
            (parent_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_parents(self, child_id: str) -> List[TaskRecord]:
        """获取某任务的所有父任务"""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT t.* FROM tasks t
            JOIN task_links l ON t.id = l.parent_id
            WHERE l.child_id = ?
            """,
            (child_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def promote(self, parent_id: str) -> int:
        """
        当父任务完成时，递归提升所有子任务为 pending（可被认领）。
        
        移植自 Hermes kanban 的 recompute 逻辑：
        WITH RECURSIVE descendants AS (...)
        
        Returns:
            被提升的子任务数量
        """
        conn = self._connect()

        # 递归找出所有 descendant 任务（子、孙、曾孙...）
        cursor = conn.execute(
            """
            WITH RECURSIVE descendants AS (
                SELECT child_id, state FROM task_links JOIN tasks ON child_id = id WHERE parent_id = ?
                UNION ALL
                SELECT l.child_id, t.state FROM task_links l JOIN tasks t ON l.child_id = t.id
                JOIN descendants d ON d.child_id = l.parent_id WHERE t.state = ?
            )
            SELECT child_id FROM descendants WHERE state = ?
            """,
            (parent_id, TaskState.RECLAIMED.value, TaskState.RECLAIMED.value),
        )

        child_ids = [r[0] for r in cursor.fetchall()]
        if not child_ids:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join(["?"] * len(child_ids))
        cursor2 = conn.execute(
            f"""
            UPDATE tasks
            SET state = ?, claim_lock = NULL, claim_expires = NULL,
                assigned_to = '', updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [TaskState.PENDING.value, now] + child_ids,
        )
        conn.commit()
        count = cursor2.rowcount
        if count > 0:
            logger.info(f"[TaskQueue] promote 提升了 {count} 个子任务: {child_ids}")
        return count

    # ── 查询 ─────────────────────────────────────────

    def get_ready(self, session_id: str, limit: int = 10) -> List[TaskRecord]:
        """获取当前可认领的任务（pending，无 claim）"""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE session_id = ? AND state = ? AND claim_lock IS NULL
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            (session_id, TaskState.PENDING.value, limit),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_claimed_by(self, session_id: str, agent_name: str) -> List[TaskRecord]:
        """获取某 Agent 当前认领的所有任务"""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE session_id = ? AND claim_lock = ?
            ORDER BY claim_expires ASC
            """,
            (session_id, agent_name),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_active(self, session_id: str) -> List[TaskRecord]:
        """获取会话内所有活跃任务（pending/claimed/running）"""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE session_id = ?
              AND state IN (?, ?, ?)
            ORDER BY priority DESC, created_at ASC
            """,
            (
                session_id,
                TaskState.PENDING.value,
                TaskState.CLAIMED.value,
                TaskState.RUNNING.value,
            ),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    # ── 统计 ─────────────────────────────────────────

    def stats(self, session_id: str) -> Dict[str, int]:
        """返回各状态的计数"""
        conn = self._connect()
        rows = conn.execute(
            "SELECT state, COUNT(*) FROM tasks WHERE session_id = ? GROUP BY state",
            (session_id,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def update_workspace(self, task_id: str, workspace_path: str) -> None:
        """更新任务的 workspace 路径"""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        conn.execute(
            "UPDATE tasks SET workspace_path = ?, updated_at = ? WHERE id = ?",
            (workspace_path, now, task_id),
        )
        conn.commit()