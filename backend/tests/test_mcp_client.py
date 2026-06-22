"""
MCP 客户端回归测试 (W4-11 修复 2026-06-21)

覆盖范围：
- _send_raw 进程未启动时必须 raise (旧实现 silent return, future 永远 hang)
- _send_request 使用 get_running_loop (替代 deprecated get_event_loop)
- _send_request 发送失败时清理 future (避免 _response_futures 字典泄漏)
- close() 不重复设 _running (避免误导 + daemon thread 早退)

历史:
- mcp_client.py 旧实现 Popen(text=False) 后 stdin.write(str) → TypeError, MCP 永远不通
- _send_raw 静默 return + future 不清理 → 调试地狱 (要等 60s 超时才知道 send 失败)
"""

import asyncio
import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.mcp_client import MCPClient


# ── 1. _send_raw 必须抛错而不是 silent ──────────────────────

def test_send_raw_raises_runtime_error_when_process_not_started():
    """_send_raw 在 process 未启动时必须 raise, 不能 silent return"""
    c = MCPClient("test", {"command": "echo", "args": []})
    # process 是 None
    with pytest.raises(RuntimeError) as exc_info:
        c._send_raw({"jsonrpc": "2.0", "method": "ping"})
    assert "test" in str(exc_info.value)
    assert "ping" in str(exc_info.value)


def test_send_raw_raises_when_process_exists_but_stdin_dead():
    """进程在但 stdin 不可用时也要 raise (边界)"""
    c = MCPClient("test", {"command": "echo", "args": []})
    # 模拟 process 存在但 stdin 是 None
    class FakeProc:
        stdin = None
        stdout = None
    c.process = FakeProc()
    with pytest.raises(RuntimeError):
        c._send_raw({"jsonrpc": "2.0", "method": "initialize"})


# ── 2. _send_request 用 get_running_loop (无 deprecation) ─────

@pytest.mark.asyncio
async def test_send_request_does_not_warn_deprecation():
    """_send_request 应当用 get_running_loop, 旧实现 get_event_loop() 在 3.12+ 弃用"""
    c = MCPClient("test", {"command": "echo", "args": []})
    with warnings.catch_warnings():
        # 把 DeprecationWarning 转成 error, 任何 deprecation 都会让测试 fail
        warnings.simplefilter("error", DeprecationWarning)
        try:
            await c._send_request("initialize")
        except RuntimeError:
            # 预期会 raise (因为 process 没启动), 关键是不要触发 DeprecationWarning
            pass


# ── 3. _send_request 发送失败时清理 future (无泄漏) ──────────

@pytest.mark.asyncio
async def test_send_request_cleans_up_future_on_send_failure():
    """_send_raw 抛错时 _response_futures 字典里不该残留 future"""
    c = MCPClient("test", {"command": "echo", "args": []})
    # process 是 None → _send_raw 抛 RuntimeError
    try:
        await c._send_request("tools/list")
    except RuntimeError:
        pass
    # 关键: _response_futures 应当被清空, 不留死 future
    assert len(c._response_futures) == 0, (
        f"发送失败后 _response_futures 未清理, 残留: {list(c._response_futures.keys())}"
    )


# ── 4. close() 行为 (smoke test) ─────────────────────────

def test_close_sets_running_false_once():
    """close() 应当把 _running 置 False, 且只置一次 (旧实现末尾重复了)"""
    c = MCPClient("test", {"command": "echo", "args": []})
    c._running = True
    c.process = None  # 不实际启动
    c.close()
    assert c._running is False


def test_close_handles_no_process():
    """process=None 时 close() 不应抛错"""
    c = MCPClient("test", {"command": "echo", "args": []})
    c.process = None
    c.close()  # 不应抛


# ── 5. Popen 必须用 text=True (binary mode + str write 必 TypeError) ──

def test_initialize_uses_text_mode():
    """initialize() 必须用 Popen(text=True), 否则 _send_raw 必 TypeError"""
    import inspect
    src = inspect.getsource(MCPClient.initialize)
    assert "text=True" in src, "MCPClient.initialize 仍用 text=False, _send_raw 必 TypeError"
    assert "text=False" not in src, "MCPClient.initialize 残留 text=False"


# ── 6. _send_request 的 future 清理 (timeout 路径已经覆盖, 这里再锁一次) ──

@pytest.mark.asyncio
async def test_send_request_future_cleanup_on_send_exception():
    """验证 _send_request 在 _send_raw 抛错时, _response_futures 保持空"""
    c = MCPClient("test", {"command": "echo", "args": []})
    # 在调用前 sanity check
    assert len(c._response_futures) == 0
    try:
        await c._send_request("any_method")
    except RuntimeError:
        pass
    # 关键断言: 不留 future
    assert len(c._response_futures) == 0, (
        f"_response_futures leak: {list(c._response_futures.keys())}"
    )
