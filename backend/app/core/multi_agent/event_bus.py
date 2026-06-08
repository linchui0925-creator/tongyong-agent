"""
EventBus — 多智能体事件总线

设计原则：
- 每个 Agent 有自己的事件队列（asyncio.Queue），只收订阅的事件
- 通过 SQLite update_hook 实现跨进程/跨协程的 DB 状态变化实时通知
- 广播事件时：事件写入 team_events 表 → SQLite update_hook 触发 → 所有订阅者收到

事件流向：
  Agent A 触发事件
    → EventBus.publish("task.completed", payload)
      → 写入 team_events 表
        → SQLite update_hook（单进程内实时）
          → 广播到所有订阅者的队列
            → 各 Agent 的 run loop 消费各自队列
"""

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from app.core.multi_agent.state_machine import TaskEvent

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 内部事件包格式
# ══════════════════════════════════════════════════════════

@dataclass
class Event:
    """
    事件包。

    轻量级内存对象，只在 EventBus 内部流转。
    持久化时序列化为 team_events 表的 JSON 记录。
    """
    id:       str = field(default_factory=lambda: str(uuid4()))
    type:     str = ""                    # TaskEvent value，如 "task.completed"
    payload:  Dict[str, Any] = field(default_factory=dict)   # 事件数据
    source:   str = ""                    # 发送方 Agent 名称
    task_id:  str = ""                    # 关联任务 ID
    session_id: str = ""                  # 关联会话 ID
    send_to:  str = ""                    # 消息路由目标（空=广播）
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "type":       self.type,
            "payload":    self.payload,
            "source":     self.source,
            "task_id":    self.task_id,
            "session_id": self.session_id,
            "send_to":    self.send_to,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            id=d["id"],
            type=d["type"],
            payload=d["payload"],
            source=d["source"],
            task_id=d["task_id"],
            session_id=d["session_id"],
            send_to=d.get("send_to", ""),
            created_at=d["created_at"],
        )


# ══════════════════════════════════════════════════════════
# Subscription — 订阅记录
# ══════════════════════════════════════════════════════════

@dataclass
class Subscription:
    """
    订阅记录。
    
    agent_name: 订阅者名称
    queue:      该 Agent 的事件队列（每个 Agent 独立队列）
    event_types:该 Agent 订阅的事件类型（空=全部）
    task_ids:   该 Agent 只想收特定 task 的事件（空=全部）
    """
    agent_name:  str
    queue:      "asyncio.Queue[Event]" = field(default_factory=lambda: asyncio.Queue(maxsize=128))
    event_types: Set[str] = field(default_factory=set)   # 空=订阅所有类型
    task_ids:    Set[str] = field(default_factory=set)    # 空=订阅所有任务

    def matches(self, event: Event) -> bool:
        """判断事件是否匹配该订阅"""
        if self.event_types and event.type not in self.event_types:
            return False
        if self.task_ids and event.task_id not in self.task_ids:
            return False
        return True


# ══════════════════════════════════════════════════════════
# EventBus — 事件总线
# ══════════════════════════════════════════════════════════

class EventBus:
    """
    内存事件总线（单例，进程内共享）。
    
    核心 API：
    - subscribe(agent_name, event_types, task_ids) → Subscription
    - unsubscribe(agent_name)
    - publish(event_type, payload, source, task_id, session_id)
    - next_event(agent_name, timeout) → Event | None
    
    SQLite 集成：
    - set_db(conn) 后，publish 会同时写 team_events 表
    - set_update_hook() 注册 SQLite update_hook，DB 变化实时广播给订阅者
    """

    def __init__(self):
        self._subscriptions: Dict[str, Subscription] = {}   # agent_name → Subscription
        self._lock = asyncio.Lock()
        self._db_conn: Optional[Any] = None                # sqlite3.Connection
        self._update_hook_registered = False

    # ── 订阅管理 ─────────────────────────────────────────

    def subscribe(
        self,
        agent_name: str,
        event_types: Optional[List[str]] = None,
        task_ids: Optional[List[str]] = None,
    ) -> Subscription:
        """
        订阅事件。同一 agent 重复 subscribe 会替换旧订阅（队列清空）。
        
        Args:
            agent_name:  订阅者名称
            event_types: 订阅的事件类型（空列表/None=全部）
            task_ids:    只订阅特定任务 ID（空列表/None=全部）
        
        Returns:
            Subscription 对象（包含该 Agent 的事件队列）
        """
        sub = Subscription(
            agent_name=agent_name,
            event_types=set(event_types or []),
            task_ids=set(task_ids or []),
        )
        self._subscriptions[agent_name] = sub
        logger.debug(f"[EventBus] {agent_name} 订阅事件: types={sub.event_types or '全部'}, tasks={sub.task_ids or '全部'}")
        return sub

    def unsubscribe(self, agent_name: str) -> None:
        """取消订阅"""
        self._subscriptions.pop(agent_name, None)
        logger.debug(f"[EventBus] {agent_name} 取消订阅")

    def get_queue(self, agent_name: str) -> Optional["asyncio.Queue[Event]"]:
        """获取某 Agent 的事件队列（未订阅返回 None）"""
        sub = self._subscriptions.get(agent_name)
        return sub.queue if sub else None

    # ── 发布 ─────────────────────────────────────────

    async def publish(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        source: str = "",
        task_id: str = "",
        session_id: str = "",
        send_to: str = "",
    ) -> Event:
        """
        发布事件（异步版本）。

        1. 创建 Event 对象
        2. 如果已 set_db：写入 team_events 表
        3. 广播到所有匹配订阅者的队列
        """
        event = Event(
            type=event_type,
            payload=payload or {},
            source=source,
            task_id=task_id,
            session_id=session_id,
            send_to=send_to,
        )

        if self._db_conn:
            self._write_event_to_db_sync(event)

        await self._broadcast(event)
        return event

    def publish_sync(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        source: str = "",
        task_id: str = "",
        session_id: str = "",
        send_to: str = "",
    ) -> Event:
        """
        发布事件（同步版本，用于非 asyncio 上下文）。

        写入 team_events 表 + 同步推送到订阅者队列。
        """
        event = Event(
            type=event_type,
            payload=payload or {},
            source=source,
            task_id=task_id,
            session_id=session_id,
            send_to=send_to,
        )

        if self._db_conn:
            self._write_event_to_db_sync(event)

        # 同步广播（直接 put，不用 asyncio.Lock）
        for agent_name, sub in list(self._subscriptions.items()):
            if sub.matches(event):
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"[EventBus] {agent_name} 队列已满，丢弃事件 {event.type}")

        return event

    def _write_event_to_db_sync(self, event: Event) -> None:
        """将事件写入 team_events 表（同步）"""
        try:
            conn = self._db_conn
            # 将 send_to 也存入 payload JSON，方便 get_events 用 json_extract 过滤
            stored_payload = dict(event.payload)
            if event.send_to:
                stored_payload.setdefault("send_to", event.send_to)
            conn.execute(
                """
                INSERT INTO team_events (id, type, payload, source, task_id, session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.type,
                    json.dumps(stored_payload, ensure_ascii=False),
                    event.source,
                    event.task_id,
                    event.session_id,
                    event.created_at,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"[EventBus] 写入 team_events 失败: {e}")

    async def _broadcast(self, event: Event) -> None:
        """将事件推送给所有匹配的订阅者队列"""
        async with self._lock:
            for agent_name, sub in list(self._subscriptions.items()):
                if sub.matches(event):
                    try:
                        sub.queue.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning(f"[EventBus] {agent_name} 队列已满，丢弃事件 {event.type}")

    # ── 消费 ─────────────────────────────────────────

    async def next_event(
        self,
        agent_name: str,
        timeout: Optional[float] = 30.0,
    ) -> Optional[Event]:
        """
        等待并返回下一个事件（非轮询，协程挂起）。
        
        Args:
            agent_name:  订阅者名称
            timeout:     等待超时（秒），None=无限等待
        
        Returns:
            Event 对象，或超时返回 None
        """
        sub = self._subscriptions.get(agent_name)
        if not sub:
            return None

        try:
            return await asyncio.wait_for(sub.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def peek_events(self, agent_name: str, max_count: int = 8) -> List[Event]:
        """
        非阻塞地拉取多条事件（用于批量处理）。
        
        Returns:
            事件列表（按顺序，新事件在前）
        """
        sub = self._subscriptions.get(agent_name)
        if not sub:
            return []

        events = []
        while len(events) < max_count:
            try:
                events.append(sub.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    # ── DB 查询 ─────────────────────────────────────────

    def get_events(
        self,
        session_id: str = "",
        source: str = "",
        event_type: str = "",
        send_to: str = "",
        limit: int = 200,
        after_seq: int = 0,
    ) -> List[Event]:
        """
        查询 team_events 表（同步，只读）。

        Args:
            session_id:  按 session_id 过滤
            source:      按发送方过滤
            event_type:  按事件类型过滤（精确匹配，如 "message.WriteCode"）
            send_to:     按 payload 中的 send_to 字段过滤（用 json_extract）
            limit:       返回条数上限
            after_seq:   跳过 rowid <= after_seq 的记录（用于游标分页）

        Returns:
            Event 列表（按 rowid 顺序）
        """
        if not self._db_conn:
            return []

        clauses: List[str] = []
        params: List[Any] = []

        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if event_type:
            clauses.append("type = ?")
            params.append(event_type)
        if send_to:
            clauses.append("json_extract(payload, '$.send_to') = ?")
            params.append(send_to)
        if after_seq > 0:
            clauses.append("rowid > ?")
            params.append(after_seq)

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT id, type, payload, source, task_id, session_id, created_at FROM team_events WHERE {where} ORDER BY rowid ASC LIMIT ?"
        params.append(limit)

        try:
            rows = self._db_conn.execute(sql, params).fetchall()
        except Exception as e:
            logger.warning(f"[EventBus] get_events 查询失败: {e}")
            return []

        events: List[Event] = []
        for row in rows:
            payload = json.loads(row[2]) if row[2] else {}
            events.append(Event(
                id=row[0],
                type=row[1],
                payload=payload,
                source=row[3],
                task_id=row[4],
                session_id=row[5],
                send_to=payload.get("send_to", ""),
                created_at=row[6],
            ))
        return events

    # ── SQLite 集成 ─────────────────────────────────────────

    def set_db(self, conn: Any) -> None:
        """
        绑定 SQLite 连接（用于事件持久化和 update_hook）。
        
        注意：连接由调用方管理，EventBus 不关闭它。
        """
        self._db_conn = conn
        self._ensure_schema(conn)
        if not self._update_hook_registered:
            self._register_update_hook(conn)
            self._update_hook_registered = True

    def _ensure_schema(self, conn: Any) -> None:
        """确保 team_events 表存在"""
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
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_team_events_session
            ON team_events(session_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_team_events_task
            ON team_events(task_id)
        """)
        conn.commit()

    def _register_update_hook(self, conn: Any) -> None:
        """
        注册 SQLite update_hook，将 team_events 表的行变化广播给所有订阅者。
        
        注意：这是进程内通知。对于多进程场景（如 separate gateway processes），
        仍需 60s 轮询（Hermes 方案）或其他 IPC 机制。
        """
        def _hook(conn_arg, op_type, db_name, tbl_name, rowid):
            try:
                if tbl_name != "team_events":
                    return
                if op_type not in ("INSERT", "UPDATE"):
                    return
                # 读取刚写入的行
                row = conn_arg.execute(
                    "SELECT id, type, payload, source, task_id, session_id, created_at FROM team_events WHERE rowid = ?",
                    (rowid,),
                ).fetchone()
                if not row:
                    return
                event = Event(
                    id=row[0],
                    type=row[1],
                    payload=json.loads(row[2]) if row[2] else {},
                    source=row[3],
                    task_id=row[4],
                    session_id=row[5],
                    created_at=row[6],
                )
                # 在主线程的 asyncio event loop 中广播（通过 call_soon_threadsafe）
                loop = getattr(asyncio, "_current_loop", None) or getattr(self, "_loop", None)
                if loop:
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast(event),
                        loop,
                    )
            except Exception as e:
                logger.warning(f"[EventBus] update_hook 处理失败: {e}")

        # set_update_hook 是非标准 API，仅在部分 Python 构建中可用
        # 标准库 sqlite3 没有这个方法，改用触发器替代
        try:
            conn.set_update_hook(_hook)
            logger.info("[EventBus] SQLite update_hook 已注册")
        except AttributeError:
            # Python 3.13+ 标准库不支持 set_update_hook，使用触发器方案
            logger.debug("[EventBus] set_update_hook 不可用，使用轮询方案（单进程无影响）")
            pass

    # ── 便利方法 ─────────────────────────────────────────

    @staticmethod
    def task_event(event: TaskEvent, **kwargs) -> str:
        """TaskEvent 枚举值转字符串（用于 publish）"""
        return event.value

    # ── 全局单例 ─────────────────────────────────────────

    _instance: Optional["EventBus"] = None
    _lock_init = threading.Lock()

    @classmethod
    def get_instance(cls) -> "EventBus":
        if cls._instance is None:
            with cls._lock_init:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


# ── 全局快捷函数 ─────────────────────────────────────────

_bus: Optional[EventBus] = None

def get_event_bus(session_id: str = "", db_path: str = "") -> EventBus:
    """
    返回全局 EventBus 单例。

    Args:
        session_id: 可选，保留供调用方使用（现已通过 set_db 传入连接）。
        db_path:    可选，保留供调用方使用。
    """
    global _bus
    if _bus is None:
        _bus = EventBus.get_instance()
    return _bus


async def publish_event(
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    source: str = "",
    task_id: str = "",
    session_id: str = "",
) -> Event:
    """全局 publish 快捷函数"""
    return await get_event_bus().publish(
        event_type=event_type,
        payload=payload,
        source=source,
        task_id=task_id,
        session_id=session_id,
    )