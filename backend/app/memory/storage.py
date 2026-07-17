"""
关系型记忆存储 - raw sqlite3 薄封装（不用 ORM）。

5 张表：sessions / messages / memories / settings / evaluations。
- raw sqlite3 是有意选择：避免 SQLAlchemy async 复杂 + 启动开销。
- profile_id 参数化路径：./data/tongyong.db（default） vs
  ./data/hermes/profiles/{id}/tongyong.db（多 profile）。
- 所有 API 是同步的；上层 AgentEngine / 路由 用 run_in_executor 包成异步。

被使用方：
  - AgentEngine (core/agent.py)：sessions + messages CRUD
  - MemoryAPI (api/memory.py)：memories + settings CRUD
  - EvaluationAPI (api/evaluation.py)：evaluations 表
"""
import sqlite3
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.core.base import Session, Message, Memory
import os
import json
import logging
from app.paths import data_path

logger = logging.getLogger(__name__)

class MemoryStorage:
    def __init__(self, db_path: str = None, profile_id: str = "default"):
        # 支持profile_id参数化路径
        if profile_id and profile_id != "default" and db_path is None:
            self.db_path = data_path("hermes", "profiles", profile_id, "tongyong.db")
        elif db_path:
            self.db_path = db_path
        else:
            self.db_path = data_path("tongyong.db")
        self.profile_id = profile_id
        os.makedirs(os.path.dirname(self.db_path) or data_path(), exist_ok=True)
        self.init_tables()

    def init_tables(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        
        # 添加 sequence 列（如果不存在）- 用于会话内消息排序
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN sequence INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # 列已存在
        
        # 创建会话序列号的索引（如果不存在）
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_sequence ON messages(session_id, sequence)")
        except sqlite3.OperationalError:
            pass
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER DEFAULT 1,
                session_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                vector_id TEXT,
                version INTEGER DEFAULT 1
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_settings (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                UNIQUE(session_id, key)
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_time ON messages(session_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_session_id ON memories(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_settings_session_id ON memory_settings(session_id)")

        # 记忆版本历史表 - 追踪每次变更
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER DEFAULT 1,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id)
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_versions_id ON memory_versions(memory_id)")

        conn.commit()
        conn.close()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    async def create_session(self, name: str) -> Session:
        from uuid import uuid4
        session = Session(
            id=str(uuid4()),
            name=name,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session.id, session.name, session.created_at, session.updated_at)
        )
        conn.commit()
        conn.close()

        return session
    
    async def get_sessions(self) -> List[Session]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, created_at, updated_at FROM sessions ORDER BY updated_at DESC")
        rows = cursor.fetchall()
        conn.close()

        return [
            Session(id=row[0], name=row[1], created_at=row[2], updated_at=row[3])
            for row in rows
        ]
    
    async def update_session(self, session_id: str, name: str) -> Optional[Session]:
        """更新会话名称
        
        Args:
            session_id: 会话ID
            name: 新会话名称
            
        Returns:
            Optional[Session]: 更新后的会话
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            "UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?",
            (name, now, session_id)
        )
        
        if cursor.rowcount == 0:
            conn.close()
            return None
        
        cursor.execute(
            "SELECT id, name, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        
        if row:
            return Session(
                id=row[0], name=row[1], created_at=row[2], updated_at=row[3]
            )
        return None
    
    async def add_message(self, session_id: str, role: str, content: str) -> Message:
        """添加消息到会话"""
        import threading
        lock = getattr(self, '_message_lock', None)
        if lock is None:
            self._message_lock = threading.Lock()
            lock = self._message_lock
        
        with lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM messages WHERE session_id = ?",
                (session_id,)
            )
            max_seq = cursor.fetchone()[0]
            next_seq = max_seq + 1
            created_at = datetime.now().isoformat()
            
            cursor.execute(
                "INSERT INTO messages (session_id, role, content, created_at, sequence) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, created_at, next_seq)
            )
            message_id = cursor.lastrowid
            cursor.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (created_at, session_id)
            )
            conn.commit()
            conn.close()
            
            message = Message(
                id=message_id,
                session_id=session_id,
                role=role,
                content=content,
                created_at=created_at,
                sequence=next_seq
            )
            
            logger.debug(f"添加消息: id={message_id}, sequence={next_seq}, role={role}")
            return message
    
    async def get_messages(self, session_id: str) -> List[Message]:
        """获取会话的所有消息（按序列号排序）
        
        Args:
            session_id: 会话ID
            
        Returns:
            List[Message]: 消息列表，按 sequence 升序排列
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, session_id, role, content, created_at, sequence FROM messages WHERE session_id = ? ORDER BY sequence ASC",
            (session_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            Message(
                id=row[0],
                session_id=row[1],
                role=row[2],
                content=row[3],
                created_at=row[4],
                sequence=row[5]
            )
            for row in rows
        ]
    
    async def get_previous_message(self, session_id: str, current_sequence: int) -> Optional[Message]:
        """获取指定消息的上一条消息
        
        Args:
            session_id: 会话ID
            current_sequence: 当前消息的序列号
            
        Returns:
            Optional[Message]: 上一条消息，如果没有则返回 None
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, session_id, role, content, created_at, sequence 
               FROM messages 
               WHERE session_id = ? AND sequence < ? 
               ORDER BY sequence DESC 
               LIMIT 1""",
            (session_id, current_sequence)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Message(
                id=row[0],
                session_id=row[1],
                role=row[2],
                content=row[3],
                created_at=row[4],
                sequence=row[5]
            )
        return None
    
    async def get_last_user_message(self, session_id: str) -> Optional[Message]:
        """获取会话的最后一条用户消息
        
        Args:
            session_id: 会话ID
            
        Returns:
            Optional[Message]: 最后一条用户消息
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, session_id, role, content, created_at, sequence 
               FROM messages 
               WHERE session_id = ? AND role = 'user' 
               ORDER BY sequence DESC 
               LIMIT 1""",
            (session_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Message(
                id=row[0],
                session_id=row[1],
                role=row[2],
                content=row[3],
                created_at=row[4],
                sequence=row[5]
            )
        return None
    
    async def get_message_by_sequence(self, session_id: str, sequence: int) -> Optional[Message]:
        """根据序列号获取指定消息
        
        Args:
            session_id: 会话ID
            sequence: 消息序列号
            
        Returns:
            Optional[Message]: 指定序列号的消息
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, session_id, role, content, created_at, sequence 
               FROM messages 
               WHERE session_id = ? AND sequence = ?""",
            (session_id, sequence)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Message(
                id=row[0],
                session_id=row[1],
                role=row[2],
                content=row[3],
                created_at=row[4],
                sequence=row[5]
            )
        return None
    
    async def add_memory(self, memory: Memory) -> Memory:
        now = datetime.now().isoformat()
        if not memory.created_at:
            memory.created_at = now
        memory.updated_at = memory.updated_at or now
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memories (id, type, content, importance, session_id, created_at, updated_at, vector_id, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (memory.id, memory.type, memory.content, memory.importance, memory.session_id, memory.created_at, memory.updated_at, memory.vector_id, memory.version)
        )
        conn.commit()
        conn.close()
        
        return memory
    
    async def get_memories(self, session_id: Optional[str] = None) -> List[Memory]:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if session_id:
            cursor.execute(
                "SELECT id, type, content, importance, session_id, created_at, updated_at, vector_id, version FROM memories WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,)
            )
        else:
            cursor.execute(
                "SELECT id, type, content, importance, session_id, created_at, updated_at, vector_id, version FROM memories ORDER BY created_at DESC"
            )
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            Memory(id=row[0], type=row[1], content=row[2], importance=row[3], session_id=row[4], created_at=row[5], updated_at=row[6], vector_id=row[7], version=row[8])
            for row in rows
        ]
    
    async def update_memory(self, memory_id: str, content: str, importance: Optional[int] = None) -> Optional[Memory]:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        # 获取当前版本信息（before update）
        cursor.execute(
            "SELECT content, importance, version FROM memories WHERE id = ?",
            (memory_id,)
        )
        current = cursor.fetchone()
        if not current:
            conn.close()
            return None

        old_content, old_importance, old_version = current

        if importance is not None:
            cursor.execute(
                "UPDATE memories SET content = ?, importance = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                (content, importance, now, memory_id)
            )
        else:
            cursor.execute(
                "UPDATE memories SET content = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                (content, now, memory_id)
            )

        # 存档旧版本到版本历史表
        cursor.execute(
            "INSERT INTO memory_versions (memory_id, content, importance, version, created_at) VALUES (?, ?, ?, ?, ?)",
            (memory_id, old_content, old_importance, old_version, now)
        )
        
        cursor.execute(
            "SELECT id, type, content, importance, session_id, created_at, updated_at, vector_id, version FROM memories WHERE id = ?",
            (memory_id,)
        )
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        
        if row:
            return Memory(
                id=row[0], type=row[1], content=row[2], importance=row[3],
                session_id=row[4], created_at=row[5], updated_at=row[6],
                vector_id=row[7], version=row[8]
            )
        return None
    
    async def delete_memory(self, memory_id: str) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0
    
    async def search_memories_by_type(self, session_id: str, memory_type: str) -> List[Memory]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, type, content, importance, session_id, created_at, updated_at, vector_id, version FROM memories WHERE session_id = ? AND type = ? ORDER BY created_at DESC",
            (session_id, memory_type)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            Memory(id=row[0], type=row[1], content=row[2], importance=row[3], session_id=row[4], created_at=row[5], updated_at=row[6], vector_id=row[7], version=row[8])
            for row in rows
        ]
    
    async def add_setting(self, session_id: str, key: str, value: str, setting_type: str = "string") -> Dict[str, Any]:
        from uuid import uuid4
        now = datetime.now().isoformat()
        setting_id = str(uuid4())
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO memory_settings (id, session_id, key, value, type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (setting_id, session_id, key, value, setting_type, now, now)
        )
        conn.commit()
        conn.close()
        
        return {
            "id": setting_id,
            "session_id": session_id,
            "key": key,
            "value": value,
            "type": setting_type,
            "created_at": now,
            "updated_at": now
        }
    
    async def get_setting(self, session_id: str, key: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, session_id, key, value, type, created_at, updated_at FROM memory_settings WHERE session_id = ? AND key = ?",
            (session_id, key)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "session_id": row[1],
                "key": row[2],
                "value": row[3],
                "type": row[4],
                "created_at": row[5],
                "updated_at": row[6]
            }
        return None
    
    async def get_all_settings(self, session_id: str) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, session_id, key, value, type, created_at, updated_at FROM memory_settings WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "id": row[0],
                "session_id": row[1],
                "key": row[2],
                "value": row[3],
                "type": row[4],
                "created_at": row[5],
                "updated_at": row[6]
            }
            for row in rows
        ]
    
    async def update_setting(self, session_id: str, key: str, value: str) -> Optional[Dict[str, Any]]:
        now = datetime.now().isoformat()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE memory_settings SET value = ?, updated_at = ? WHERE session_id = ? AND key = ?",
            (value, now, session_id, key)
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if affected > 0:
            return await self.get_setting(session_id, key)
        return None
    
    async def delete_setting(self, session_id: str, key: str) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memory_settings WHERE session_id = ? AND key = ?", (session_id, key))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0
    
    async def get_memory_versions(self, memory_id: str) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        # 获取当前版本
        cursor.execute(
            "SELECT id, type, content, importance, session_id, created_at, updated_at, vector_id, version FROM memories WHERE id = ?",
            (memory_id,)
        )
        current = cursor.fetchone()

        # 获取历史版本
        cursor.execute(
            "SELECT content, importance, version, created_at FROM memory_versions WHERE memory_id = ? ORDER BY version ASC",
            (memory_id,)
        )
        history_rows = cursor.fetchall()

        conn.close()

        versions = []
        # 历史版本
        for row in history_rows:
            versions.append({
                "content": row[0],
                "importance": row[1],
                "version": row[2],
                "created_at": row[3],
                "type": "history",
            })

        # 当前版本
        if current:
            versions.append({
                "id": current[0],
                "type": current[1],
                "content": current[2],
                "importance": current[3],
                "session_id": current[4],
                "created_at": current[5],
                "updated_at": current[6],
                "vector_id": current[7],
                "version": current[8],
            })

        return versions
    
    async def delete_session(self, session_id: str):
        """删除会话及其所有关联数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM memory_settings WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info(f"删除会话及其数据: {session_id}")
        return affected > 0

    async def clear_messages(self, session_id: str):
        """清空会话的所有消息"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        messages_deleted = cursor.rowcount
        cursor.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id)
        )
        session_updated = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info(f"清空会话消息: {session_id}")
        return messages_deleted > 0 or session_updated > 0
