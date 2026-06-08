"""
Environment - Multi-Agent 消息总线（v2 版本）

职责：
- 发布/订阅事件（EventBus）
- 存储已发布消息到 team_events 表
- 按角色过滤并推送消息
- 支持广播和定向发送两种路由模式

v1（内存）→ v2（SQLite WAL + EventBus）：
- publish() → event_bus.publish() + DB 记录
- get_messages_for_role() → event_bus.get_events() + 路由过滤
- 不再维护 in-memory messages 列表，所有消息持久化到 team_events 表
"""

from typing import Dict, List, Set, Optional, TYPE_CHECKING, Callable
from collections import defaultdict
import logging
import asyncio
import sqlite3

from app.core.multi_agent.message import TeamMessage, new_message
from app.core.multi_agent.event_bus import get_event_bus, Event

if TYPE_CHECKING:
    from app.core.multi_agent.role import TeamRole

logger = logging.getLogger(__name__)


class EventBusEnvironment:
    """
    v2 环境/消息总线 — 基于 EventBus 的事件驱动架构。

    与旧 Environment 的区别：
    - 消息不再存内存，而是发布到 EventBus + 写入 team_events 表
    - observe() 读取 EventBus 事件，不再从内存列表过滤
    - 保留了与 Role 的接口兼容性（publish / get_messages_for_role / mark_read）
    - 支持广播（send_to=""）和定向（send_to=role_name）两种路由
    """

    def __init__(
        self,
        session_id: str,
        db_path: str,
        team=None,
    ):
        self._session_id = session_id
        self._db_path = db_path
        self._team = team  # 反向引用 Team（供 DistributeTaskAction 等访问）

        # EventBus 实例（单例）
        self._eb = get_event_bus(session_id, db_path)

        # 初始化 DB 连接（EventBus 需要它来持久化事件）
        if not self._eb._db_conn:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            self._eb.set_db(conn)

        # 按角色追踪已读事件索引（防止重复处理导致死循环）
        self._role_cursors: Dict[str, int] = {}

        # 消息计数器（生成 sequence）
        self._msg_counter = 0

        # 角色 → watch_actions 映射（由 Team.hire() 填充）
        self._role_watch_actions: Dict[str, List[str]] = {}
        self._role_upstream: Dict[str, List[str]] = {}
        self._role_downstream: Dict[str, List[str]] = {}
        self._role_action_count: Dict[str, int] = {}

    # ── Role 注册（Team.hire 时调用）─────────────────────────

    def register_role(self, role: "TeamRole"):
        """注册角色信息（由 Team.hire 调用）"""
        self._role_watch_actions[role.name] = role.watch_actions
        self._role_upstream[role.name] = role.upstream_roles
        self._role_downstream[role.name] = role.downstream_roles
        self._role_action_count[role.name] = len(role.actions)
        logger.debug(f"[ENV] 注册角色: {role.name}, watch={role.watch_actions}, upstream={role.upstream_roles}")

    def unregister_role(self, role_name: str):
        """注销角色"""
        self._role_watch_actions.pop(role_name, None)
        self._role_upstream.pop(role_name, None)
        self._role_downstream.pop(role_name, None)
        self._role_action_count.pop(role_name, None)

    # ── 消息发布 ────────────────────────────────────────────

    def publish(self, msg: TeamMessage):
        """
        发布消息到 EventBus + 写入 team_events 表。

        对应旧的 self.messages.append(msg)。
        """
        self._msg_counter += 1
        if msg.sequence is None:
            msg.sequence = self._msg_counter

        target = msg.send_to or "广播"
        preview = msg.content[:60].replace("\n", " ")
        logger.info(f"[ENV] ➡ {msg.sent_from} → {target}: {preview}...")

        # 同步写入 DB（在主线程/FastAPI 调用时用同步接口）
        self._eb.publish_sync(
            event_type=f"message.{msg.cause_by}",
            payload={
                "id": msg.id,
                "content": msg.content,
                "sent_from": msg.sent_from,
                "send_to": msg.send_to or "",
                "cause_by": msg.cause_by,
                "metadata": msg.metadata or {},
                "sequence": msg.sequence,
            },
            source=msg.sent_from,
            task_id=msg.metadata.get("task_id", ""),
            session_id=self._session_id,
            send_to=msg.send_to,
        )

    async def publish_async(self, msg: TeamMessage):
        """异步发布（用于 asyncio context）"""
        self._msg_counter += 1
        if msg.sequence is None:
            msg.sequence = self._msg_counter

        target = msg.send_to or "广播"
        preview = msg.content[:60].replace("\n", " ")
        logger.info(f"[ENV] ➡ {msg.sent_from} → {target}: {preview}...")

        await self._eb.publish(
            event_type=f"message.{msg.cause_by}",
            payload={
                "id": msg.id,
                "content": msg.content,
                "sent_from": msg.sent_from,
                "send_to": msg.send_to or "",
                "cause_by": msg.cause_by,
                "metadata": msg.metadata or {},
                "sequence": msg.sequence,
            },
            source=msg.sent_from,
            task_id=msg.metadata.get("task_id", ""),
            session_id=self._session_id,
            send_to=msg.send_to,
        )

    # ── 消息读取 ────────────────────────────────────────────

    def get_messages_for_role(self, role: "TeamRole") -> List[TeamMessage]:
        """
        获取该角色监听范围内的新消息（仅返回尚未读过的消息）。

        过滤逻辑与旧 Environment 一致：
        1. 定向消息（send_to == role.name）: 总是送达
        2. Worker（单 action）: 仅接收定向消息
        3. Leader（多 action）: 来自邻居的广播 + watch_actions 过滤的广播
        """
        cursor = self._role_cursors.get(role.name, 0)

        # 从 DB 读取该 session 的所有消息（不做 send_to 过滤，由下方路由逻辑处理）
        events = self._eb.get_events(
            session_id=self._session_id,
            limit=200,
            after_seq=cursor,
        )

        # 补充：邻居广播（来自 upstream/downstream 的广播消息）
        # 这需要读所有消息再过滤，较昂贵；仅在必要时调用
        connected_set = set(self._role_upstream.get(role.name, [])) | set(self._role_downstream.get(role.name, []))
        is_worker = self._role_action_count.get(role.name, 1) <= 1

        messages: List[TeamMessage] = []
        for ev in events:
            # Worker 只接收定向发给自己的消息（不接收广播和定向给别人的）
            if is_worker:
                if (ev.send_to or "") == role.name:
                    msg = self._event_to_message(ev)
                    messages.append(msg)
                continue

            # 定向消息：总是送达
            if (ev.send_to or "") == role.name:
                msg = self._event_to_message(ev)
                messages.append(msg)
                continue

            # 邻居广播：无视 watch_actions 送达
            if (ev.send_to or "") == "" and ev.source in connected_set:
                msg = self._event_to_message(ev)
                messages.append(msg)
                continue

            # 其他广播：用 watch_actions 过滤
            watch = self._role_watch_actions.get(role.name, [])
            cause_by = ev.type.replace("message.", "")
            if cause_by in watch or not watch:
                msg = self._event_to_message(ev)
                messages.append(msg)

        return messages

    async def get_messages_for_role_async(self, role: "TeamRole") -> List[TeamMessage]:
        """异步版本"""
        return self.get_messages_for_role(role)

    def _event_to_message(self, ev: Event) -> TeamMessage:
        """将 Event 转换为 TeamMessage"""
        return TeamMessage(
            id=ev.payload.get("id", ""),
            content=ev.payload.get("content", ""),
            sent_from=ev.payload.get("sent_from", ""),
            send_to=ev.payload.get("send_to", ""),
            cause_by=ev.payload.get("cause_by", ""),
            metadata=ev.payload.get("metadata", {}),
            sequence=ev.payload.get("sequence"),
        )

    # ── 观察者（Role.observe 调用）────────────────────────────

    async def observe(self, role: "TeamRole") -> List[TeamMessage]:
        """
        Role.observe() 的入口：获取角色尚未处理的新消息。
        与 get_messages_for_role() 相同，但命名为 observe 以匹配 Role 接口。
        """
        return self.get_messages_for_role(role)

    # ── 已读游标 ────────────────────────────────────────────

    def mark_read(self, role_name: str, seq: int = None):
        """
        将该角色的已读游标推进。
        seq 为 None 时推进到最新消息末尾。
        """
        if seq is not None:
            self._role_cursors[role_name] = seq
        else:
            # 推进到最新 sequence
            self._role_cursors[role_name] = self._msg_counter

    # ── 批量查询 API（兼容旧接口）─────────────────────────────

    def get_all_messages(self) -> List[TeamMessage]:
        """获取所有已发布消息（按 sequence 排序）"""
        events = self._eb.get_events(session_id=self._session_id, limit=10000)
        return [self._event_to_message(e) for e in sorted(events, key=lambda e: e.payload.get("sequence", 0))]

    def get_messages_by_sender(self, sender: str) -> List[TeamMessage]:
        """获取某个发送者的所有消息"""
        events = self._eb.get_events(session_id=self._session_id, source=sender, limit=10000)
        return [self._event_to_message(e) for e in events]

    def get_messages_by_cause(self, cause_by: str) -> List[TeamMessage]:
        """获取某个 Action 触发的所有消息"""
        events = self._eb.get_events(session_id=self._session_id, event_type=f"message.{cause_by}", limit=10000)
        return [self._event_to_message(e) for e in events]

    def get_round_messages(self, round_num: int) -> List[TeamMessage]:
        """获取第 N 轮的所有消息"""
        all_msgs = self.get_all_messages()
        return [m for m in all_msgs if m.metadata.get("round") == round_num]

    def get_messages_count(self) -> int:
        """获取消息总数（用于游标计算）"""
        return self._msg_counter

    # ── 工具方法 ────────────────────────────────────────────

    def summary(self) -> str:
        """返回环境摘要（兼容旧接口）"""
        return f"EventBusEnvironment(session={self._session_id}, roles={list(self._role_watch_actions.keys())})"

    def cleanup(self, keep_recent: int = 100):
        """
        清理旧消息（v2 暂不实现，team_events 表持久化）。
        保留此接口以兼容旧代码。
        """
        logger.debug(f"[ENV] cleanup({keep_recent}) — v2 不需要内存清理，消息在 DB 中")

    def has_role(self, name: str) -> bool:
        """检查角色是否已注册"""
        return name in self._role_watch_actions

    def get_watch_actions(self, role_name: str) -> List[str]:
        """获取角色的 watch_actions"""
        return self._role_watch_actions.get(role_name, [])


# ── 向后兼容别名（旧代码若 import Environment 就继续用）─────────
Environment = EventBusEnvironment