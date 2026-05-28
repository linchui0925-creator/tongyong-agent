"""
Environment - Multi-Agent 消息总线
Team 与 Role 之间的中介层，负责消息路由和过滤
"""

from typing import Dict, List, Set, Optional, TYPE_CHECKING
from collections import defaultdict
import logging

from app.core.multi_agent.message import TeamMessage

if TYPE_CHECKING:
    from app.core.multi_agent.role import TeamRole

logger = logging.getLogger(__name__)


class Environment:
    """
    环境/消息总线

    职责:
    - 存储所有已发布消息
    - 根据 Role 的 watch_actions 过滤并推送消息
    - 支持广播和定向发送两种路由模式
    - 反向引用 Team（供 Action 访问 _task_queue 等状态）
    - 按角色追踪已读消息，防止死循环
    """

    def __init__(self, team: "Team" = None):
        # 全局消息列表
        self.messages: List[TeamMessage] = []
        # 已发布消息 ID（用于去重）
        self._published_ids: Set[str] = set()
        # 消息计数器
        self._msg_counter = 0
        # 反向引用 Team（供 DistributeTaskAction 等访问 _task_queue）
        self._team: "Team" = team
        # 按角色追踪已读消息索引（防止重复处理导致死循环）
        self._role_cursors: Dict[str, int] = {}

    def publish(self, msg: TeamMessage):
        """发布消息到环境"""
        if msg.id in self._published_ids:
            logger.debug(f"[ENV] 消息已存在，跳过: {msg.id}")
            return

        self._msg_counter += 1
        if msg.sequence is None:
            msg.sequence = self._msg_counter

        self._published_ids.add(msg.id)
        self.messages.append(msg)

        target = msg.send_to or "广播"
        preview = msg.content[:60].replace("\n", " ")
        logger.info(f"[ENV] ➡ {msg.sent_from} → {target}: {preview}...")

    def get_messages_for_role(self, role: "TeamRole") -> List[TeamMessage]:
        """
        获取该角色监听范围内的新消息（仅返回尚未读过的消息，不更新游标）

        过滤逻辑（按优先级）:
        1. 定向消息（send_to == role.name）: 总是送达
        2. 只拥有一个 action 的角色（Worker，如 Coder/Tester/Reviewer）:
           **仅接收定向消息**，不响应任何广播。这确保 Worker 只在被明确分配任务时才行动。
        3. 多 action 角色（Leader）：保留以下额外路由规则：
           a. 来自连接图中任一邻居 Agent（upstream/downstream）的广播: 无视 watch_actions 送达
           b. 其他广播消息: cause_by 必须在 watch_actions 列表中（或 watch_actions 为空）
        4. 仅返回截至上次读取后发布的新消息（防止重复处理导致死循环）
        """
        cursor = self._role_cursors.get(role.name, 0)
        unread: List[TeamMessage] = []

        # 判断是否为单 action Worker 角色
        is_worker = len(role.actions) <= 1

        for i in range(cursor, len(self.messages)):
            msg = self.messages[i]

            # 1. 定向消息：总是送达
            if msg.send_to == role.name:
                unread.append(msg)
                continue

            # Worker 不接收任何广播消息
            if is_worker:
                continue

            # 多 action 角色（Leader）的额外路由规则：
            # 2. 来自邻居 Agent（连接图边）：无视 watch_actions 送达
            connected_set = set(role.upstream_roles) | set(role.downstream_roles)
            if msg.send_to == "" and msg.sent_from in connected_set:
                unread.append(msg)
                continue

            # 3. 其他广播消息：用 watch_actions 过滤
            if msg.send_to == "":
                if msg.cause_by in role.watch_actions or not role.watch_actions:
                    unread.append(msg)

        return unread

    def mark_read(self, role_name: str):
        """
        将该角色的已读游标推进到最新消息末尾。
        仅在角色实际完成 action 执行后调用（防止 peek 操作误消费）。
        """
        self._role_cursors[role_name] = len(self.messages)
    
    def get_all_messages(self) -> List[TeamMessage]:
        """获取所有已发布消息（按 sequence 排序）"""
        return sorted(self.messages, key=lambda m: m.sequence or 0)
    
    def get_messages_by_sender(self, sender: str) -> List[TeamMessage]:
        """获取某个发送者的所有消息"""
        return [m for m in self.messages if m.sent_from == sender]
    
    def get_messages_by_cause(self, cause_by: str) -> List[TeamMessage]:
        """获取某个 Action 触发的所有消息"""
        return [m for m in self.messages if m.cause_by == cause_by]
    
    def get_round_messages(self, round_num: int) -> List[TeamMessage]:
        """获取第 N 轮的所有消息（基于消息 metadata 中的 round 标签）"""
        return [
            m for m in self.messages
            if m.metadata.get("round") == round_num
        ]
    
    def summary(self) -> str:
        msgs = self.get_all_messages()
        senders = set(m.sent_from for m in msgs)
        return f"Environment(messages={len(msgs)}, senders={senders})"