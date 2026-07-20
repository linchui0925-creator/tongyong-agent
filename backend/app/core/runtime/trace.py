"""Runtime trace 框架 (W5-7)

一次 chat 请求 = 一个 trace, 内部每个关键步骤 (LLM 调用 / 工具调用 / 压缩 /
子 agent) = 一个 span。trace_id / span_id 通过 contextvars 传播, 因此深层的
工具代码无需显式接参就能挂到当前 span 下。

落库: SQLite (data/runtime_trace.db), 自建表 (照搬 ask_store 的 IF NOT EXISTS
模式), 不依赖 m001 migration runner。

开关: configure_runtime(enabled=...) 或 settings.runtime_trace_enabled。
关闭时 start_trace/start_span 仍返回可用的 id (供日志/SSE 关联), 但不落库、
不建连接, 保证零开销。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.paths import data_path

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────

@dataclass
class Trace:
    trace_id: str
    session_id: Optional[str]
    name: str
    start_ts: float
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    span_id: str
    trace_id: str
    parent_id: Optional[str]
    name: str
    start_ts: float
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: Optional[str] = None
    end_ts: Optional[float] = None

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_ts is None:
            return None
        return round((self.end_ts - self.start_ts) * 1000, 3)


# ── contextvars ──────────────────────────────────

_CURRENT_TRACE: ContextVar[Optional[Trace]] = ContextVar("runtime_trace", default=None)
_CURRENT_SPAN: ContextVar[Optional[Span]] = ContextVar("runtime_span", default=None)


def current_trace_id() -> Optional[str]:
    tr = _CURRENT_TRACE.get()
    return tr.trace_id if tr else None


def current_span_id() -> Optional[str]:
    sp = _CURRENT_SPAN.get()
    return sp.span_id if sp else None


# ── SQLite 落库 ──────────────────────────────────

class TraceStore:
    """线程安全的 trace/span SQLite 存储 (每线程一连接)。"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or data_path("runtime_trace.db")
        self._local = threading.local()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_schema(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runtime_traces (
                    trace_id    TEXT PRIMARY KEY,
                    session_id  TEXT,
                    name        TEXT NOT NULL,
                    start_ts    REAL NOT NULL,
                    end_ts      REAL,
                    status      TEXT DEFAULT 'ok',
                    attributes  TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runtime_spans (
                    span_id     TEXT PRIMARY KEY,
                    trace_id    TEXT NOT NULL,
                    parent_id   TEXT,
                    name        TEXT NOT NULL,
                    start_ts    REAL NOT NULL,
                    end_ts      REAL,
                    duration_ms REAL,
                    status      TEXT DEFAULT 'ok',
                    error       TEXT,
                    attributes  TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_spans_trace ON runtime_spans(trace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_traces_session ON runtime_traces(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_traces_start ON runtime_traces(start_ts)")
            conn.execute("CREATE TABLE IF NOT EXISTS runtime_plans (plan_id TEXT PRIMARY KEY, goal TEXT NOT NULL, steps_json TEXT NOT NULL, created_ts REAL NOT NULL)")

    # ── 写 ──
    def save_trace(self, trace: Trace) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runtime_traces (trace_id, session_id, name, start_ts, attributes) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (trace.trace_id, trace.session_id, trace.name, trace.start_ts,
                     json.dumps(trace.attributes, ensure_ascii=False)),
                )
        except Exception as e:  # 落库失败绝不能影响主流程
            logger.debug(f"save_trace failed: {e}")

    def finish_trace(self, trace_id: str, end_ts: float, status: str = "ok") -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE runtime_traces SET end_ts = ?, status = ? WHERE trace_id = ?",
                    (end_ts, status, trace_id),
                )
        except Exception as e:
            logger.debug(f"finish_trace failed: {e}")

    def save_span(self, span: Span) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runtime_spans "
                    "(span_id, trace_id, parent_id, name, start_ts, end_ts, duration_ms, status, error, attributes) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (span.span_id, span.trace_id, span.parent_id, span.name, span.start_ts,
                     span.end_ts, span.duration_ms, span.status, span.error,
                     json.dumps(span.attributes, ensure_ascii=False)),
                )
        except Exception as e:
            logger.debug(f"save_span failed: {e}")

    # ── 读 ──
    def get_spans(self, trace_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runtime_spans WHERE trace_id = ? ORDER BY start_ts ASC",
                (trace_id,),
            ).fetchall()
        return [self._row_to_span(r) for r in rows]

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM runtime_traces WHERE trace_id = ?", (trace_id,)
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["attributes"] = json.loads(data.get("attributes") or "{}")
        return data

    def list_traces(self, session_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT t.*, (SELECT COUNT(*) FROM runtime_spans s WHERE s.trace_id = t.trace_id) AS span_count "
                    "FROM runtime_traces t WHERE t.session_id = ? ORDER BY t.start_ts DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT t.*, (SELECT COUNT(*) FROM runtime_spans s WHERE s.trace_id = t.trace_id) AS span_count "
                    "FROM runtime_traces t ORDER BY t.start_ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["attributes"] = json.loads(d.get("attributes") or "{}")
            out.append(d)
        return out

    # ── Plan 持久化 (W5-8) ─────────────────────
    def save_plan(self, plan_id: str, goal: str, steps: list) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runtime_plans (plan_id, goal, steps_json, created_ts) "
                    "VALUES (?, ?, ?, ?)",
                    (plan_id, goal, json.dumps(steps, ensure_ascii=False), time.time()),
                )
        except Exception as e:
            logger.debug(f"save_plan failed: {e}")

    def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM runtime_plans WHERE plan_id = ?", (plan_id,)
                ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["steps"] = json.loads(d.pop("steps_json", "[]"))
            return d
        except Exception as e:
            logger.debug(f"get_plan failed: {e}")
            return None

    def update_plan_step(self, plan_id: str, index: int, status: str, result: Optional[str] = None) -> None:
        try:
            plan = self.get_plan(plan_id)
            if not plan:
                return
            for s in plan["steps"]:
                if s["index"] == index:
                    s["status"] = status
                    if result is not None:
                        s["result"] = result
                    break
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE runtime_plans SET steps_json = ? WHERE plan_id = ?",
                    (json.dumps(plan["steps"], ensure_ascii=False), plan_id),
                )
        except Exception as e:
            logger.debug(f"update_plan_step failed: {e}")

    def purge_older_than(self, cutoff_ts: float) -> int:
        with self._get_conn() as conn:
            old = conn.execute(
                "SELECT trace_id FROM runtime_traces WHERE start_ts < ?", (cutoff_ts,)
            ).fetchall()
            ids = [r["trace_id"] for r in old]
            for tid in ids:
                conn.execute("DELETE FROM runtime_spans WHERE trace_id = ?", (tid,))
            conn.execute("DELETE FROM runtime_traces WHERE start_ts < ?", (cutoff_ts,))
        return len(ids)

    @staticmethod
    def _row_to_span(r: sqlite3.Row) -> Dict[str, Any]:
        d = dict(r)
        d["attributes"] = json.loads(d.get("attributes") or "{}")
        return d


# ── 全局 runtime 配置 ─────────────────────────────

_STORE: Optional[TraceStore] = None
_ENABLED: bool = False
_LOCK = threading.Lock()


def configure_runtime(store: Optional[TraceStore] = None, enabled: bool = True) -> None:
    """初始化全局 runtime trace。lifespan / 测试调用。"""
    global _STORE, _ENABLED
    with _LOCK:
        _ENABLED = bool(enabled)
        if store is not None:
            _STORE = store
        elif _STORE is None and enabled:
            _STORE = TraceStore()


def reset_runtime() -> None:
    """测试隔离用: 复位全局状态 + contextvars。"""
    global _STORE, _ENABLED
    with _LOCK:
        _STORE = None
        _ENABLED = False
    try:
        _CURRENT_TRACE.set(None)
        _CURRENT_SPAN.set(None)
    except Exception:
        pass


def is_enabled() -> bool:
    return _ENABLED and _STORE is not None


def get_store() -> Optional[TraceStore]:
    return _STORE


# ── 公共 API ─────────────────────────────────────

def _new_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def start_trace(session_id: Optional[str] = None, name: str = "chat",
                attributes: Optional[Dict[str, Any]] = None,
                trace_id: Optional[str] = None) -> Iterator[Trace]:
    now = time.time()
    tid = trace_id or _new_id()
    trace = Trace(
        trace_id=tid,
        session_id=session_id,
        name=name,
        start_ts=now,
        attributes=attributes or {},
    )
    # root span: 代表整条 trace 的耗时。作为 span 落库以便时间线展示,
    # 但不设为 _CURRENT_SPAN, 因此第一层 start_span 的 parent_id 为 None。
    root = Span(
        span_id=_new_id(),
        trace_id=tid,
        parent_id=None,
        name=name,
        start_ts=now,
        attributes=attributes or {},
    )
    tok_tr = _CURRENT_TRACE.set(trace)
    tok_sp = _CURRENT_SPAN.set(None)
    if is_enabled():
        _STORE.save_trace(trace)
    status = "ok"
    try:
        yield trace
    except Exception:
        status = "error"
        raise
    finally:
        root.end_ts = time.time()
        root.status = status
        if is_enabled():
            _STORE.save_span(root)
            _STORE.finish_trace(trace.trace_id, root.end_ts, status)
        _CURRENT_SPAN.reset(tok_sp)
        _CURRENT_TRACE.reset(tok_tr)


@contextmanager
def start_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Iterator[Span]:
    trace = _CURRENT_TRACE.get()
    parent = _CURRENT_SPAN.get()
    trace_id = trace.trace_id if trace else current_trace_id() or _new_id()
    span = Span(
        span_id=_new_id(),
        trace_id=trace_id,
        parent_id=parent.span_id if parent else None,
        name=name,
        start_ts=time.time(),
        attributes=attributes or {},
    )
    tok = _CURRENT_SPAN.set(span)
    try:
        yield span
        span.status = span.status or "ok"
    except Exception as e:
        span.status = "error"
        span.error = f"{type(e).__name__}: {e}"[:500]
        raise
    finally:
        span.end_ts = time.time()
        if is_enabled():
            _STORE.save_span(span)
        _CURRENT_SPAN.reset(tok)


def record_span(name: str, duration_ms: float, status: str = "ok",
                error: Optional[str] = None,
                attributes: Optional[Dict[str, Any]] = None) -> None:
    """记录一个已完成的 span (调用方自己计时, 无需 with)。"""
    if not is_enabled():
        return
    trace = _CURRENT_TRACE.get()
    parent = _CURRENT_SPAN.get()
    now = time.time()
    span = Span(
        span_id=_new_id(),
        trace_id=trace.trace_id if trace else (current_trace_id() or _new_id()),
        parent_id=parent.span_id if parent else None,
        name=name,
        start_ts=now - (duration_ms / 1000.0),
        attributes=attributes or {},
        status=status,
        error=error,
        end_ts=now,
    )
    _STORE.save_span(span)
