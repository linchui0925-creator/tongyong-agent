"""
P1-4 W4-25: AskPendingStore SQLite 持久化 + 多进程共享
"""

import os
import shutil
import tempfile
import time
import pytest


@pytest.fixture
def store_path(tmp_path):
    """每个 test 用独立 db 文件"""
    return str(tmp_path / "ask_pending.db")


def test_basic_set_get_pop(store_path):
    """基本 set/get/pop"""
    from app.core.ask_store import AskPendingStore
    s = AskPendingStore(db_path=store_path, ttl_seconds=60)
    s.set("q1", {"question": "Q?", "choices": ["a", "b"], "user_response": None})
    assert "q1" in s
    assert len(s) == 1
    e = s.get("q1")
    assert e["question"] == "Q?"
    assert e["choices"] == ["a", "b"]
    popped = s.pop("q1")
    assert popped["question"] == "Q?"
    assert "q1" not in s


def test_overwrite_same_id(store_path):
    """同名覆盖"""
    from app.core.ask_store import AskPendingStore
    s = AskPendingStore(db_path=store_path, ttl_seconds=60)
    s.set("q1", {"user_response": "v1"})
    s.set("q1", {"user_response": "v2"})
    assert s.get("q1")["user_response"] == "v2"
    assert len(s) == 1


def test_expired_returns_none(store_path):
    """过期 entry 返 None 并清理"""
    from app.core.ask_store import AskPendingStore
    s = AskPendingStore(db_path=store_path, ttl_seconds=1)
    s.set("q1", {"x": 1})
    time.sleep(1.2)
    assert s.get("q1") is None
    assert "q1" not in s
    # DB 里也清掉了
    assert len(s) == 0


def test_multi_process_sharing(store_path):
    """2 个 store 实例 (模拟 2 worker) 共享数据"""
    from app.core.ask_store import AskPendingStore
    worker1 = AskPendingStore(db_path=store_path, ttl_seconds=60)
    worker2 = AskPendingStore(db_path=store_path, ttl_seconds=60)

    # worker1 写入
    worker1.set("q1", {"question": "from w1", "user_response": None})
    # worker2 立即能读
    assert "q1" in worker2
    e = worker2.get("q1")
    assert e["question"] == "from w1"

    # worker2 更新
    e["user_response"] = "w2 answer"
    worker2.set("q1", e)
    # worker1 看到
    assert worker1.get("q1")["user_response"] == "w2 answer"

    # worker2 弹出
    popped = worker2.pop("q1")
    assert popped["user_response"] == "w2 answer"
    # worker1 看到已删
    assert "q1" not in worker1


def test_getitem_raises_keyerror(store_path):
    """__getitem__ 跟 dict 兼容, 缺失抛 KeyError"""
    from app.core.ask_store import AskPendingStore
    s = AskPendingStore(db_path=store_path, ttl_seconds=60)
    with pytest.raises(KeyError):
        _ = s["nope"]


def test_pop_default(store_path):
    """pop 缺失返 default"""
    from app.core.ask_store import AskPendingStore
    s = AskPendingStore(db_path=store_path, ttl_seconds=60)
    assert s.pop("nope") is None
    assert s.pop("nope", "fallback") == "fallback"


def test_cleanup_expired(store_path):
    """cleanup_expired 清过期"""
    from app.core.ask_store import AskPendingStore
    s = AskPendingStore(db_path=store_path, ttl_seconds=1)
    s.set("q1", {})
    s.set("q2", {})
    s.set("q3", {})  # 这个不动
    time.sleep(1.1)
    s.set("q3", {})  # 重新 set, 刷新 created_at
    n = s.cleanup_expired()
    assert n == 2
    assert "q3" in s
    assert "q1" not in s


def test_unicode_payload(store_path):
    """Unicode payload 正常存取 (中文 question)"""
    from app.core.ask_store import AskPendingStore
    s = AskPendingStore(db_path=store_path, ttl_seconds=60)
    s.set("q1", {"question": "你想做什么?", "choices": ["聊天", "写代码"]})
    e = s.get("q1")
    assert e["question"] == "你想做什么?"
    assert e["choices"] == ["聊天", "写代码"]


def test_singleton_default():
    """get_ask_pending_store() 是单例"""
    from app.core.ask_store import get_ask_pending_store
    s1 = get_ask_pending_store()
    s2 = get_ask_pending_store()
    assert s1 is s2


def test_ask_uses_store_not_memory():
    """ask.py 用 SQLite store 替代 agent_engine._ask_pending 内存 dict"""
    import inspect
    from app.tools.implementations import ask
    src = inspect.getsource(ask)
    # 删 docstring 后查
    code_only = "\n".join(l for l in src.split("\n") if not l.strip().startswith(('"""', "'", "#")))
    # 代码里不应再访问 agent_engine._ask_pending
    assert "agent_engine._ask_pending" not in code_only, \
        "ask.py 代码里不应再用 agent_engine._ask_pending (P1-4)"
    # 用了 store
    assert "get_ask_pending_store" in src or "AskPendingStore" in src


def test_agent_engine_uses_store():
    """AgentEngine.__init__ 用 store 初始化 _ask_pending"""
    import inspect
    from app.core import agent
    src = inspect.getsource(agent.AgentEngine.__init__)
    assert "get_ask_pending_store" in src, \
        "AgentEngine._ask_pending 应当用 store (P1-4)"
    # 不应再硬编码 dict 字面量
    assert "_ask_pending: Dict[str, dict] = {}" not in src
