"""
TeamSession - 团队会话持久化存储
使用独立的 SQLite 数据库存储团队会话状态
"""

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.multi_agent.message import TeamMessage
from app.core.multi_agent.role import TeamRole
from app.core.multi_agent.tool_permission import ToolPermission

logger = logging.getLogger(__name__)


class TeamSessionStore:
    """
    团队会话存储（SQLite）
    
    表结构:
    - team_sessions: 团队会话元数据
    - team_roles: 角色配置（不含运行时状态）
    - team_messages: 消息历史
    """
    
    def __init__(self, db_path: str = "./data/team_sessions.db"):
        self.db_path = db_path
        os.makedirs(Path(db_path).parent, exist_ok=True)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接（启用 WAL 模式 + 并发安全）"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_tables(self):
        conn = self._connect()
        c = conn.cursor()
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS team_sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'idle',
                config TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS team_roles (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                profile TEXT DEFAULT '',
                watch_actions TEXT DEFAULT '[]',
                action_types TEXT DEFAULT '[]',
                tool_permission TEXT DEFAULT '{}',
                llm_provider TEXT DEFAULT 'deepseek',
                llm_model TEXT DEFAULT '',
                opponent_name TEXT DEFAULT '',
                UNIQUE(session_id, name)
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS team_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT DEFAULT 'assistant',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sequence INTEGER,
                cause_by TEXT DEFAULT '',
                sent_from TEXT DEFAULT '',
                send_to TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}'
            )
        """)
        
        c.execute("CREATE INDEX IF NOT EXISTS idx_roles_session ON team_roles(session_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_msgs_session ON team_messages(session_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_msgs_sequence ON team_messages(session_id, sequence)")

        # 兼容性：新增列
        try:
            c.execute("ALTER TABLE team_roles ADD COLUMN action_configs TEXT DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE team_roles ADD COLUMN stance TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # 列已存在
        try:
            c.execute("ALTER TABLE team_roles ADD COLUMN upstream_roles TEXT DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE team_roles ADD COLUMN downstream_roles TEXT DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass

        # Agent 连接图
        c.execute("""
            CREATE TABLE IF NOT EXISTS team_connections (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                from_role TEXT NOT NULL,
                to_role TEXT NOT NULL,
                match_cause TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_conn_session ON team_connections(session_id)")

        # Agent 市场模板
        c.execute("""
            CREATE TABLE IF NOT EXISTS agent_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                profile TEXT DEFAULT '',
                category TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                watch_actions TEXT DEFAULT '[]',
                action_types TEXT DEFAULT '[]',
                action_configs TEXT DEFAULT '{}',
                tool_permission TEXT DEFAULT '{"allowed_tools":[],"denied_tools":[],"max_tool_turns":20}',
                llm_provider TEXT DEFAULT 'deepseek',
                llm_model TEXT DEFAULT '',
                opponent_name TEXT DEFAULT '',
                stance TEXT DEFAULT '',
                skills TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()
    
    def _row_to_session(self, row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "name": row[1],
            "status": row[2],
            "config": json.loads(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        }
    
    # ── Session CRUD ─────────────────────────────────────────
    
    def create_session(self, name: str, config: dict = None) -> Dict[str, Any]:
        """创建新的团队会话"""
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            "INSERT INTO team_sessions (id, name, status, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, name, "idle", json.dumps(config or {}), now, now)
        )
        conn.commit()
        conn.close()
        return {
            "id": session_id, "name": name, "status": "idle",
            "config": config or {}, "created_at": now, "updated_at": now
        }
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM team_sessions WHERE id = ?", (session_id,))
        row = c.fetchone()
        conn.close()
        return self._row_to_session(row) if row else None
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM team_sessions ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        return [self._row_to_session(r) for r in rows]
    
    def update_session_status(self, session_id: str, status: str):
        now = datetime.now().isoformat()
        conn = self._connect()
        c = conn.cursor()
        c.execute("UPDATE team_sessions SET status=?, updated_at=? WHERE id=?", (status, now, session_id))
        conn.commit()
        conn.close()
    
    def delete_session(self, session_id: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("DELETE FROM team_messages WHERE session_id=?", (session_id,))
        c.execute("DELETE FROM team_roles WHERE session_id=?", (session_id,))
        c.execute("DELETE FROM team_connections WHERE session_id=?", (session_id,))
        c.execute("DELETE FROM team_sessions WHERE id=?", (session_id,))
        conn.commit()
        conn.close()
    
    # ── Role CRUD ─────────────────────────────────────────
    
    def add_role(self, session_id: str, role: TeamRole) -> Dict[str, Any]:
        role_id = str(uuid.uuid4())
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            """INSERT INTO team_roles
               (id, session_id, name, profile, watch_actions, action_types, tool_permission,
                llm_provider, llm_model, opponent_name, action_configs, stance,
                upstream_roles, downstream_roles)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                role_id, session_id, role.name, role.profile,
                json.dumps(role.watch_actions),
                json.dumps(role.action_types),
                json.dumps(role.tool_permission.model_dump()),
                role.llm_provider, role.llm_model, role.opponent_name,
                json.dumps(role.action_configs),
                role.stance,
                json.dumps(role.upstream_roles),
                json.dumps(role.downstream_roles),
            )
        )
        conn.commit()
        conn.close()
        return {"id": role_id, "name": role.name, "session_id": session_id}
    
    def get_roles(self, session_id: str) -> List[TeamRole]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM team_roles WHERE session_id=?", (session_id,))
        rows = c.fetchall()
        conn.close()

        roles = []
        for r in rows:
            tool_perm_dict = json.loads(r[6])
            action_configs = json.loads(r[10]) if len(r) > 10 else {}
            stance = r[11] if len(r) > 11 else ""
            upstream_roles = json.loads(r[12]) if len(r) > 12 else []
            downstream_roles = json.loads(r[13]) if len(r) > 13 else []
            role = TeamRole(
                name=r[2], profile=r[3],
                watch_actions=json.loads(r[4]),
                action_types=json.loads(r[5]),
                action_configs=action_configs,
                tool_permission=ToolPermission(**tool_perm_dict),
                llm_provider=r[7], llm_model=r[8], opponent_name=r[9],
                stance=stance,
                upstream_roles=upstream_roles,
                downstream_roles=downstream_roles,
            )
            role.set_actions(role.action_types)
            roles.append(role)
        return roles
    
    def delete_role(self, session_id: str, role_name: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("DELETE FROM team_roles WHERE session_id=? AND name=?", (session_id, role_name))
        conn.commit()
        conn.close()

    def update_role(self, session_id: str, role_name: str, data: Dict[str, Any]) -> Optional[TeamRole]:
        """更新角色字段（profile, watch_actions, action_types, upstream_roles, downstream_roles 等）"""
        # 先检查角色存在
        existing = self.get_role_by_name(session_id, role_name)
        if not existing:
            return None

        conn = self._connect()
        c = conn.cursor()

        # 可更新字段
        simple_fields = {"profile", "llm_provider", "llm_model", "opponent_name", "stance"}
        json_fields = {"watch_actions", "action_types", "action_configs", "upstream_roles", "downstream_roles"}

        updates = []
        values = []
        for key, value in data.items():
            if key in simple_fields:
                updates.append(f"{key}=?")
                values.append(value)
            elif key in json_fields:
                updates.append(f"{key}=?")
                values.append(json.dumps(value))

        if not updates:
            conn.close()
            return self.get_role_by_name(session_id, role_name)

        values.append(session_id)
        values.append(role_name)
        c.execute(
            f"UPDATE team_roles SET {', '.join(updates)} WHERE session_id=? AND name=?",
            values
        )
        conn.commit()
        conn.close()

        return self.get_role_by_name(session_id, role_name)

    def get_role_by_name(self, session_id: str, role_name: str) -> Optional[TeamRole]:
        """按名称获取单个角色"""
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM team_roles WHERE session_id=? AND name=?", (session_id, role_name))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        tool_perm_dict = json.loads(row[6])
        action_configs = json.loads(row[10]) if len(row) > 10 else {}
        stance = row[11] if len(row) > 11 else ""
        upstream_roles = json.loads(row[12]) if len(row) > 12 else []
        downstream_roles = json.loads(row[13]) if len(row) > 13 else []
        role = TeamRole(
            name=row[2], profile=row[3],
            watch_actions=json.loads(row[4]),
            action_types=json.loads(row[5]),
            action_configs=action_configs,
            tool_permission=ToolPermission(**tool_perm_dict),
            llm_provider=row[7], llm_model=row[8], opponent_name=row[9],
            stance=stance,
            upstream_roles=upstream_roles,
            downstream_roles=downstream_roles,
        )
        role.set_actions(role.action_types)
        return role

    # ── Agent Marketplace CRUD ─────────────────────────────────────────

    def _row_to_template(self, row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "name": row[1],
            "profile": row[2],
            "category": row[3],
            "tags": json.loads(row[4]),
            "watch_actions": json.loads(row[5]),
            "action_types": json.loads(row[6]),
            "action_configs": json.loads(row[7]),
            "tool_permission": json.loads(row[8]),
            "llm_provider": row[9],
            "llm_model": row[10],
            "opponent_name": row[11],
            "stance": row[12],
            "skills": json.loads(row[13]),
            "created_at": row[14],
            "updated_at": row[15],
        }

    def create_template(self, data: Dict[str, Any]) -> Dict[str, Any]:
        template_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            """INSERT INTO agent_templates
               (id, name, profile, category, tags, watch_actions, action_types, action_configs,
                tool_permission, llm_provider, llm_model, opponent_name, stance, skills, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                template_id, data["name"], data.get("profile", ""),
                data.get("category", ""), json.dumps(data.get("tags", [])),
                json.dumps(data.get("watch_actions", [])),
                json.dumps(data.get("action_types", [])),
                json.dumps(data.get("action_configs", {})),
                json.dumps(data.get("tool_permission", {})),
                data.get("llm_provider", "deepseek"), data.get("llm_model", ""),
                data.get("opponent_name", ""), data.get("stance", ""),
                json.dumps(data.get("skills", [])),
                now, now,
            )
        )
        conn.commit()
        conn.close()
        return self.get_template(template_id)

    def list_templates(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM agent_templates ORDER BY updated_at DESC")
        rows = c.fetchall()
        conn.close()
        return [self._row_to_template(r) for r in rows]

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM agent_templates WHERE id=?", (template_id,))
        row = c.fetchone()
        conn.close()
        return self._row_to_template(row) if row else None

    def get_template_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM agent_templates WHERE name=?", (name,))
        row = c.fetchone()
        conn.close()
        return self._row_to_template(row) if row else None

    def update_template(self, template_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        now = datetime.now().isoformat()
        conn = self._connect()
        c = conn.cursor()
        # 只更新 data 中提供的字段
        fields = []
        values = []
        for key in ("name", "profile", "category", "llm_provider", "llm_model",
                     "opponent_name", "stance"):
            if key in data:
                fields.append(f"{key}=?")
                values.append(data[key])
        for json_key in ("tags", "watch_actions", "action_types", "action_configs",
                          "tool_permission", "skills"):
            if json_key in data:
                fields.append(f"{json_key}=?")
                values.append(json.dumps(data[json_key]))
        if not fields:
            conn.close()
            return self.get_template(template_id)
        fields.append("updated_at=?")
        values.append(now)
        values.append(template_id)
        c.execute(f"UPDATE agent_templates SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        conn.close()
        return self.get_template(template_id)

    def delete_template(self, template_id: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("DELETE FROM agent_templates WHERE id=?", (template_id,))
        conn.commit()
        conn.close()

    def list_template_categories(self) -> List[str]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT DISTINCT category FROM agent_templates WHERE category != '' ORDER BY category")
        rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows]

    # ── Connection CRUD ─────────────────────────────────────────

    def add_connection(self, session_id: str, from_role: str, to_role: str, match_cause: str = "") -> Dict[str, Any]:
        conn_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            "INSERT INTO team_connections (id, session_id, from_role, to_role, match_cause, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conn_id, session_id, from_role, to_role, match_cause, now)
        )
        conn.commit()
        conn.close()
        return {"id": conn_id, "session_id": session_id, "from_role": from_role, "to_role": to_role, "match_cause": match_cause}

    def get_connections(self, session_id: str) -> List[Dict[str, Any]]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM team_connections WHERE session_id=? ORDER BY created_at", (session_id,))
        rows = c.fetchall()
        conn.close()
        return [
            {"id": r[0], "session_id": r[1], "from_role": r[2], "to_role": r[3], "match_cause": r[4]}
            for r in rows
        ]

    def get_connections_for_role(self, session_id: str, role_name: str) -> List[Dict[str, Any]]:
        """获取某角色的所有出边（下游连接）"""
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM team_connections WHERE session_id=? AND from_role=? ORDER BY created_at",
            (session_id, role_name)
        )
        rows = c.fetchall()
        conn.close()
        return [
            {"id": r[0], "session_id": r[1], "from_role": r[2], "to_role": r[3], "match_cause": r[4]}
            for r in rows
        ]

    def delete_connection(self, session_id: str, from_role: str, to_role: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("DELETE FROM team_connections WHERE session_id=? AND from_role=? AND to_role=?", (session_id, from_role, to_role))
        conn.commit()
        conn.close()

    def delete_connections_for_role(self, session_id: str, role_name: str):
        """删除角色所有相关连接（删除角色时调用）"""
        conn = self._connect()
        c = conn.cursor()
        c.execute("DELETE FROM team_connections WHERE session_id=? AND (from_role=? OR to_role=?)", (session_id, role_name, role_name))
        conn.commit()
        conn.close()

    def update_role_connections(self, session_id: str, *role_names: str):
        """根据 team_connections 表同步更新指定角色的 upstream/downstream 字段"""
        conn = self._connect()
        c = conn.cursor()

        # 读取 session 所有连接
        c.execute("SELECT from_role, to_role FROM team_connections WHERE session_id=?", (session_id,))
        edges = c.fetchall()

        # 计算每个角色的上下游
        from collections import defaultdict
        upstream_map: Dict[str, set] = defaultdict(set)
        downstream_map: Dict[str, set] = defaultdict(set)
        for from_role, to_role in edges:
            downstream_map[from_role].add(to_role)
            upstream_map[to_role].add(from_role)

        # 确定要更新的角色
        if not role_names:
            # 获取 session 中所有角色
            c.execute("SELECT name FROM team_roles WHERE session_id=?", (session_id,))
            role_names = tuple(r[0] for r in c.fetchall())
        elif len(role_names) == 1:
            role_names = (role_names[0],)

        for name in role_names:
            up = json.dumps(sorted(upstream_map.get(name, [])))
            down = json.dumps(sorted(downstream_map.get(name, [])))
            c.execute(
                "UPDATE team_roles SET upstream_roles=?, downstream_roles=? WHERE session_id=? AND name=?",
                (up, down, session_id, name)
            )

        conn.commit()
        conn.close()

    # ── Message CRUD ─────────────────────────────────────────
    
    def add_message(self, session_id: str, msg: TeamMessage):
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            """INSERT INTO team_messages
               (id, session_id, role, content, created_at, sequence, cause_by, sent_from, send_to, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.id, session_id, msg.role, msg.content, msg.created_at,
                msg.sequence, msg.cause_by, msg.sent_from, msg.send_to,
                json.dumps(msg.metadata)
            )
        )
        conn.commit()
        conn.close()
    
    def get_messages(self, session_id: str) -> List[TeamMessage]:
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM team_messages WHERE session_id=? ORDER BY sequence ASC",
            (session_id,)
        )
        rows = c.fetchall()
        conn.close()
        
        msgs = []
        for r in rows:
            msgs.append(TeamMessage(
                id=r[0], role=r[2], content=r[3], created_at=r[4],
                sequence=r[5], cause_by=r[6], sent_from=r[7], send_to=r[8],
                metadata=json.loads(r[9]), session_id=session_id
            ))
        return msgs
    
    def clear_messages(self, session_id: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("DELETE FROM team_messages WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()