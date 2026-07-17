"""
Ask pending 存储 (P1-4 W4-25)

替代 AgentEngine._ask_pending 内存 dict, 用 SQLite 持久化以支持
多 worker (uvicorn --workers>1) 部署共享状态.

API 跟 dict 兼容, 最小化调用方改动.
"""

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
from app.paths import data_path

logger = logging.getLogger(__name__)

# 默认 TTL: 1 小时 (ask 问题应当秒级答, 但允许 user 关闭浏览器再回来)
DEFAULT_TTL_SECONDS = 3600


class AskPendingStore:
    """SQLite 持久化的 ask pending 存储 (W4-25 P1-4)

    用法:
        store = AskPendingStore()
        store.set(qid, {"question": ..., "choices": [...], "user_response": None})
        entry = store.get(qid)
        if qid in store: ...
        store.pop(qid)
    """

    def __init__(self, db_path: str = data_path("ask_pending.db"), ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self._local = threading.local()
        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """每个线程一个连接 (避免 sqlite3 'SQLite objects created in a thread' 错)"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_schema(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ask_pending (
                    question_id TEXT PRIMARY KEY,
                    payload     TEXT NOT NULL,
                    created_at  REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ask_created_at
                ON ask_pending (created_at)
            """)
            conn.commit()
        logger.info(f"[AskPendingStore] 初始化: {self.db_path} (TTL={self.ttl_seconds}s)")

    def get(self, question_id: str) -> Optional[dict]:
        """读 entry, 过期返回 None (并直接 DELETE, 避免 get→pop→get 递归)"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT payload, created_at FROM ask_pending WHERE question_id = ?",
                (question_id,),
            ).fetchone()
            if row is None:
                return None
            # 过期检查: 直接 DELETE, 不调 self.pop (会循环)
            if time.time() - row["created_at"] > self.ttl_seconds:
                conn.execute("DELETE FROM ask_pending WHERE question_id = ?", (question_id,))
                conn.commit()
                return None
            return json.loads(row["payload"])

    def set(self, question_id: str, entry: dict) -> None:
        """写 entry (覆盖式)"""
        payload = json.dumps(entry, ensure_ascii=False)
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO ask_pending (question_id, payload, created_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(question_id) DO UPDATE SET
                     payload=excluded.payload,
                     created_at=excluded.created_at""",
                (question_id, payload, time.time()),
            )
            conn.commit()

    def pop(self, question_id: str, default=None):
        """读 + 删. default: 找不到时返回 (跟 dict.pop 兼容)."""
        entry = self.get(question_id)
        if entry is None:
            return default
        with self._get_conn() as conn:
            conn.execute("DELETE FROM ask_pending WHERE question_id = ?", (question_id,))
            conn.commit()
        return entry

    def __setitem__(self, qid: str, entry: dict) -> None:
        self.set(qid, entry)

    def __getitem__(self, qid: str) -> dict:
        entry = self.get(qid)
        if entry is None:
            raise KeyError(qid)
        return entry

    def __contains__(self, qid: str) -> bool:
        return self.get(qid) is not None

    def __len__(self) -> int:
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM ask_pending").fetchone()["n"]

    def cleanup_expired(self) -> int:
        """清理过期 entry, 返回删除条数. 可在 lifespan startup 调一次."""
        cutoff = time.time() - self.ttl_seconds
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM ask_pending WHERE created_at < ?", (cutoff,))
            n = cur.rowcount
            conn.commit()
        if n:
            logger.info(f"[AskPendingStore] 清理 {n} 条过期 ask_pending")
        return n


# 模块级单例 (跨 worker 共享, 因为 SQLite 文件在共享磁盘)
_default_store: Optional[AskPendingStore] = None


def get_ask_pending_store() -> AskPendingStore:
    """获取默认 ask_pending store 单例"""
    global _default_store
    if _default_store is None:
        _default_store = AskPendingStore()
    return _default_store
