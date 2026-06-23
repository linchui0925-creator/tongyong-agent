"""
P2-3 W4-23: langchain_agent checkpointer 恢复 + system message 去重
"""

import pytest


def test_is_persistent_default_when_session_id():
    """session_id != None 时, is_persistent 应为 True (W4-23 改回)"""
    import inspect
    from app.core import langchain_agent
    src = inspect.getsource(langchain_agent)
    # 不应再硬编码 False
    assert "is_persistent = False" not in src, "W4-23: 硬编码 is_persistent=False 已修"
    # session_id 路径下默认 True
    assert "is_persistent = session_id is not None" in src, \
        "应当 session_id 路径默认 True"


def test_chat_history_skips_system_messages():
    """chat_history 构造时跳过 system messages (W4-23 修法)"""
    import inspect
    from app.core import langchain_agent
    src = inspect.getsource(langchain_agent)
    # 找 chat_history 构造区段
    assert "跳过 system messages" in src or "W4-23 P2-3" in src, \
        "chat_history 应当注释说明跳过 system messages"
    # 验证源里实际有 continue (跳过 system)
    section = src[src.find("构建 chat history"):src.find("构建 chat history") + 2000]
    # 在 chat_history 构造里, 看到 role == "system" 应当 continue 而不是 append
    assert 'role == "system":\n            continue' in section, \
        "role==system 应当 continue, 不 append SystemMessage"


def test_session_id_none_still_ephemeral():
    """session_id=None 仍走 ephemeral (不污染持久化)"""
    import inspect
    from app.core import langchain_agent
    src = inspect.getsource(langchain_agent)
    # is_persistent = session_id is not None
    #   → session_id=None 时 False, 走 ephemeral
    #   → session_id != None 时 True, 走 checkpointer
    assert "is_persistent = session_id is not None" in src


def test_w3b_temporary_fallback_comment_removed():
    """W3-B 临时回退注释应当替换成 W4-23 修复说明"""
    import inspect
    from app.core import langchain_agent
    src = inspect.getsource(langchain_agent)
    # 旧注释 "W3-B：临时改走 ephemeral" 不应再出现
    assert "W3-B" not in src or "W3-B 临时改走 ephemeral" not in src, \
        "W3-B 临时回退注释应当更新到 W4-23"
    # 新注释应当有 W4-23
    assert "W4-23" in src and "P2-3" in src, "应当有 W4-23 P2-3 注释"
