"""
System prompt 注入顺序回归测试 (W4-8 P0-1 修复 2026-06-21)

覆盖范围：
- chat() / stream_chat() / stream_chat_langchain() 三处入口的 inject 顺序
- 期望最终顺序: [base_prompt, USER.md, MEMORY.md, domain, ...]
- 旧版 bug 顺序 (base → memory → domain) 实际产生 [domain, USER, MEMORY, base]

历史:
- agent.py:198-249 三段 inject 全用 messages.insert(0, ...), 最后调用的反而排最前
- 旧版调用顺序: base → memory → domain, 实际最终顺序 = [domain, USER, MEMORY, base]
- 与 _inject_base_system_prompt 的注释 "确保 LLM 看到的第一条就是它" 完全相反
- W4-8 修复: 反转调用顺序, 验证 base 真正落在 messages[0]
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.base import Message
from app.core.context import ContextManager


# ── Fixtures ─────────────────────────────────────────

BASE_MARKER = "<<<BASE_PROMPT>>>"
USER_MARKER = "<<<USER_PROFILE>>>"
MEMORY_MARKER = "<<<LONG_TERM_MEMORY>>>"
DOMAIN_MARKER = "<<<DOMAIN_PROMPT>>>"


def make_engine_for_test():
    """构造一个最小可用的 AgentEngine (只测 inject 顺序, 不需要 LLM/memory)"""
    from app.core.agent import AgentEngine
    engine = AgentEngine.__new__(AgentEngine)
    engine.context = ContextManager()
    engine.llm = None
    engine.memory_storage = None
    engine.vector_store = None
    engine._constraint_engine = None
    engine._cli_executor = None
    engine._ask_pending = {}
    return engine


# ── 1. 单 inject 函数行为 ─────────────────────────

def test_inject_base_uses_insert_zero():
    """_inject_base_system_prompt 把 base 放在 messages[0]"""
    engine = make_engine_for_test()
    engine.context.add_message("user", "历史 user 消息")
    engine.context.add_message("assistant", "历史 assistant 消息")

    with patch("app.core.system_prompt.get_system_prompt", return_value=BASE_MARKER):
        engine._inject_base_system_prompt()

    assert engine.context.messages[0].role == "system"
    assert engine.context.messages[0].content == BASE_MARKER
    assert engine.context.messages[1].content == "历史 user 消息"


def test_inject_memory_user_first_then_memory():
    """
    _inject_memory 顺序: 先插 MEMORY, 再插 USER → 最终 [USER, MEMORY, ...]
    (USER.md 是更个性化的, 放在 MEMORY.md 之前)
    """
    engine = make_engine_for_test()

    fake_mfm = MagicMock()
    fake_mfm.read_memory.return_value = MEMORY_MARKER
    fake_mfm.read_user.return_value = USER_MARKER

    async def run():
        with patch("app.hermes.memory_file.MemoryFileManager", return_value=fake_mfm):
            await engine._inject_memory("s1")

    asyncio.run(run())

    sys_msgs = [m for m in engine.context.messages if m.role == "system"]
    assert len(sys_msgs) == 2
    assert sys_msgs[0].content == f"[用户偏好]\n{USER_MARKER}"
    assert sys_msgs[1].content == f"[长期事实记忆]\n{MEMORY_MARKER}"


def test_inject_domain_uses_insert_zero():
    """_ensure_domain_prompts 把 domain 放在 messages[0]"""
    engine = make_engine_for_test()
    engine.context.add_message("user", "old")

    fake_integrator = MagicMock()
    fake_integrator.get_all.return_value = DOMAIN_MARKER
    fake_integrator.get_domain_keys.return_value = ["identity", "personality"]

    with patch("app.domains.get_integrator", return_value=fake_integrator):
        asyncio.run(engine._ensure_domain_prompts("s1"))

    assert engine.context.messages[0].content == DOMAIN_MARKER
    assert engine.context.messages[1].content == "old"


# ── 2. 三函数组合: 正确顺序 (W4-8 修复后) ─────────────────────────

def test_correct_call_order_base_lands_at_position_zero():
    """
    修复后顺序: domain → memory → base
    期望最终 messages[0] = base_prompt (LLM 第一眼看到)

    模拟 chat() 入口的调用序列 (W4-8 P0-1 修复后):
        await self._ensure_domain_prompts(session_id)
        await self._inject_memory(session_id)
        self._inject_base_system_prompt()
    """
    engine = make_engine_for_test()

    fake_mfm = MagicMock()
    fake_mfm.read_memory.return_value = MEMORY_MARKER
    fake_mfm.read_user.return_value = USER_MARKER
    fake_integrator = MagicMock()
    fake_integrator.get_all.return_value = DOMAIN_MARKER
    fake_integrator.get_domain_keys.return_value = ["identity"]

    async def run():
        with patch("app.core.system_prompt.get_system_prompt", return_value=BASE_MARKER), \
             patch("app.hermes.memory_file.MemoryFileManager", return_value=fake_mfm), \
             patch("app.domains.get_integrator", return_value=fake_integrator):
            # 正确顺序: domain → memory → base
            await engine._ensure_domain_prompts("s1")
            await engine._inject_memory("s1")
            engine._inject_base_system_prompt()

    asyncio.run(run())

    sys_msgs = [m for m in engine.context.messages if m.role == "system"]
    assert len(sys_msgs) == 4
    # 关键断言: base 必须在最前
    assert sys_msgs[0].content == BASE_MARKER, (
        f"期望 base_prompt 在 messages[0], 实际 = {sys_msgs[0].content[:50]}"
    )
    assert sys_msgs[1].content == f"[用户偏好]\n{USER_MARKER}"
    assert sys_msgs[2].content == f"[长期事实记忆]\n{MEMORY_MARKER}"
    assert sys_msgs[3].content == DOMAIN_MARKER


# ── 3. 三函数组合: 旧版 bug 顺序 (防止回归) ─────────────────────────

def test_legacy_call_order_is_buggy():
    """
    旧版 chat() 调用顺序: base → memory → domain
    实际最终顺序 = [domain, USER, MEMORY, base] ← base 被压到最底!

    本测试 **故意** 用旧版顺序, 验证它产生错误的顺序, 防止有人 "优化" 回旧顺序。
    """
    engine = make_engine_for_test()

    fake_mfm = MagicMock()
    fake_mfm.read_memory.return_value = MEMORY_MARKER
    fake_mfm.read_user.return_value = USER_MARKER
    fake_integrator = MagicMock()
    fake_integrator.get_all.return_value = DOMAIN_MARKER
    fake_integrator.get_domain_keys.return_value = ["identity"]

    async def run():
        with patch("app.core.system_prompt.get_system_prompt", return_value=BASE_MARKER), \
             patch("app.hermes.memory_file.MemoryFileManager", return_value=fake_mfm), \
             patch("app.domains.get_integrator", return_value=fake_integrator):
            # ⚠️ 故意使用旧版顺序
            engine._inject_base_system_prompt()
            await engine._inject_memory("s1")
            await engine._ensure_domain_prompts("s1")

    asyncio.run(run())

    sys_msgs = [m for m in engine.context.messages if m.role == "system"]
    # 旧版顺序产生: [domain, USER, MEMORY, base]
    assert sys_msgs[0].content == DOMAIN_MARKER
    assert sys_msgs[1].content == f"[用户偏好]\n{USER_MARKER}"
    assert sys_msgs[2].content == f"[长期事实记忆]\n{MEMORY_MARKER}"
    assert sys_msgs[3].content == BASE_MARKER

    # 关键: 旧版顺序 base 不在位置 0
    assert sys_msgs[0].content != BASE_MARKER, (
        "旧版顺序不应当让 base 落在 position 0 "
        "(如果通过, 说明 insert(0) 行为变化, 需重新审查)"
    )


# ── 4. 空数据场景 ─────────────────────────

def test_base_prompt_with_empty_user_and_memory_still_first():
    """即使 USER.md / MEMORY.md 为空, base 也必须落在 position 0"""
    engine = make_engine_for_test()

    fake_mfm = MagicMock()
    fake_mfm.read_memory.return_value = ""
    fake_mfm.read_user.return_value = ""
    fake_integrator = MagicMock()
    fake_integrator.get_all.return_value = ""
    fake_integrator.get_domain_keys.return_value = []

    async def run():
        with patch("app.core.system_prompt.get_system_prompt", return_value=BASE_MARKER), \
             patch("app.hermes.memory_file.MemoryFileManager", return_value=fake_mfm), \
             patch("app.domains.get_integrator", return_value=fake_integrator):
            await engine._ensure_domain_prompts("s1")
            await engine._inject_memory("s1")
            engine._inject_base_system_prompt()

    asyncio.run(run())

    sys_msgs = [m for m in engine.context.messages if m.role == "system"]
    assert len(sys_msgs) == 1
    assert sys_msgs[0].content == BASE_MARKER


def test_empty_base_prompt_does_not_pollute_context():
    """base_prompt 拿不到时 (get_system_prompt 返回空), 不应插入空 system 消息"""
    engine = make_engine_for_test()

    with patch("app.core.system_prompt.get_system_prompt", return_value=""):
        engine._inject_base_system_prompt()

    assert all(m.role != "system" for m in engine.context.messages)


# ── 5. env_prompt 追加在末尾, 不影响头部顺序 ─────────────────────────

def test_env_prompt_appends_without_disturbing_head_order():
    """
    add_message("system", env_prompt) 追加到末尾, 不应打乱头部三段顺序。
    (chat() 入口的真实流程: inject 三段 → env_prompt → 历史)
    """
    engine = make_engine_for_test()

    fake_mfm = MagicMock()
    fake_mfm.read_memory.return_value = MEMORY_MARKER
    fake_mfm.read_user.return_value = USER_MARKER
    fake_integrator = MagicMock()
    fake_integrator.get_all.return_value = DOMAIN_MARKER
    fake_integrator.get_domain_keys.return_value = ["identity"]

    async def run():
        with patch("app.core.system_prompt.get_system_prompt", return_value=BASE_MARKER), \
             patch("app.hermes.memory_file.MemoryFileManager", return_value=fake_mfm), \
             patch("app.domains.get_integrator", return_value=fake_integrator):
            await engine._ensure_domain_prompts("s1")
            await engine._inject_memory("s1")
            engine._inject_base_system_prompt()
            # env_prompt 通过 add_message 追加
            engine.context.add_message("system", "<<<ENV_PROMPT>>>")
            # 加载历史 (用 add_message)
            engine.context.add_message("user", "历史 user")
            engine.context.add_message("assistant", "历史 assistant")

    asyncio.run(run())

    msgs = engine.context.messages
    assert msgs[0].content == BASE_MARKER
    assert msgs[1].content == f"[用户偏好]\n{USER_MARKER}"
    assert msgs[2].content == f"[长期事实记忆]\n{MEMORY_MARKER}"
    assert msgs[3].content == DOMAIN_MARKER
    assert msgs[4].content == "<<<ENV_PROMPT>>>"
    assert msgs[5].content == "历史 user"
    assert msgs[6].content == "历史 assistant"
