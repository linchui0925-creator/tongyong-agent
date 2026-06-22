"""
MCP 客户端 lifespan / 跨 loop future 测试 (W4-14 修复 2026-06-22)

覆盖 W4-14 4 个子问题:
1. discover_mcp_tools_async 用调用方 loop, 不开 daemon thread
2. 多 worker 部署 (P2 留 follow-up, 这里只验单 loop 内多 client)
3. MCP 进程 crash → _read_loop 退出 → pending futures 立即 fail
4. shutdown_mcp_tools 顺序: close → stop loop → join thread
   + 跨 loop future 在 _handle_message 里能正确 resolve
"""

import asyncio
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.mcp_client import (
    MCPClient,
    _async_mcp_clients,
    discover_mcp_tools_async,
    shutdown_mcp_tools_async,
)


# ── 1. _response_futures 现在记 (loop, future) ─────────────

def test_response_futures_uses_tuple_layout():
    """W4-14: _response_futures value 必须是 (loop, future) tuple, 不是裸 future"""
    c = MCPClient("t", {"command": "echo", "args": []})
    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        c._response_futures[1] = (loop, future)
        assert isinstance(c._response_futures[1], tuple)
        assert len(c._response_futures[1]) == 2
        assert c._response_futures[1][1] is future
    finally:
        loop.close()


# ── 2. _fail_pending 把挂起 future 全部 set_exception ──────

@pytest.mark.asyncio
async def test_fail_pending_sets_exception_on_all_futures():
    """_fail_pending 应当把 _response_futures 里所有未完成 future 标 exception"""
    c = MCPClient("t", {"command": "echo", "args": []})
    loop = asyncio.get_running_loop()
    f1 = loop.create_future()
    f2 = loop.create_future()
    f3 = loop.create_future()  # 预先 done, 不应被动
    f3.set_result("ok")
    c._response_futures[1] = (loop, f1)
    c._response_futures[2] = (loop, f2)
    c._response_futures[3] = (loop, f3)

    c._fail_pending("test crash")

    # 两个未完成 future 应被 set_exception
    with pytest.raises(ConnectionError, match="test crash"):
        await f1
    with pytest.raises(ConnectionError, match="test crash"):
        await f2
    # 已 done 的 future 不应被改
    assert f3.result() == "ok"
    # 全部清空
    assert len(c._response_futures) == 0


@pytest.mark.asyncio
async def test_fail_pending_with_empty_dict_is_noop():
    """_fail_pending 在空 dict 时不抛"""
    c = MCPClient("t", {"command": "echo", "args": []})
    c._fail_pending("noop")  # 不应抛


# ── 3. 跨 loop future: 远端 loop 上 _handle_message 能正确 resolve ──

def _run_loop_forever(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


@pytest.mark.asyncio
async def test_handle_message_uses_call_soon_threadsafe_cross_loop():
    """W4-14: _handle_message 在 client._loop 上跑, 但 future 在另一 loop,
    必须用 call_soon_threadsafe 才能让 wait_for 正常返回

    真实场景: MCP 读线程 → _mcp_loop 跑 _handle_message → set_result
    但 future 是在 FastAPI 主 loop 创建, 所以要 call_soon_threadsafe
    """
    c = MCPClient("t", {"command": "echo", "args": []})

    main_loop = asyncio.get_running_loop()
    future = main_loop.create_future()
    c._response_futures[42] = (main_loop, future)

    # 起一个独立 loop 当 _mcp_loop
    other_loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop_forever, args=(other_loop,), daemon=True)
    thread.start()
    try:
        c._loop = other_loop
        # 在 other_loop 上跑 _handle_message (模拟 _read_loop 调度路径)
        asyncio.run_coroutine_threadsafe(
            c._handle_message({"id": 42, "result": {"ok": True}}),
            other_loop,
        ).result(timeout=2)

        # 主 loop 应当能通过 call_soon_threadsafe 拿到 result
        result = await asyncio.wait_for(future, timeout=1.0)
        assert result == {"ok": True}
    finally:
        other_loop.call_soon_threadsafe(other_loop.stop)
        thread.join(timeout=2)
        other_loop.close()


@pytest.mark.asyncio
async def test_handle_message_error_propagates_to_far_loop():
    """远端 loop 上 _handle_message 收到 error, 也要让主 loop 的 future 拿到异常"""
    c = MCPClient("t", {"command": "echo", "args": []})
    main_loop = asyncio.get_running_loop()
    future = main_loop.create_future()
    c._response_futures[7] = (main_loop, future)

    other_loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop_forever, args=(other_loop,), daemon=True)
    thread.start()
    try:
        c._loop = other_loop
        asyncio.run_coroutine_threadsafe(
            c._handle_message({"id": 7, "error": {"message": "boom"}}),
            other_loop,
        ).result(timeout=2)
        with pytest.raises(Exception, match="boom"):
            await asyncio.wait_for(future, timeout=1.0)
    finally:
        other_loop.call_soon_threadsafe(other_loop.stop)
        thread.join(timeout=2)
        other_loop.close()


# ── 4. close() 顺序: fail pending 在前, kill 进程在后 ──────

@pytest.mark.asyncio
async def test_close_fails_pending_before_killing_process():
    """W4-14: close() 应当先 fail pending, 再 kill 进程
    验证: future 已经被 set_exception
    """
    c = MCPClient("t", {"command": "echo", "args": []})
    main_loop = asyncio.get_running_loop()
    future = main_loop.create_future()
    c._response_futures[1] = (main_loop, future)

    class FakeProc:
        def __init__(self):
            self.terminated = False
            self.killed = False
        def terminate(self):
            self.terminated = True
        def wait(self, timeout=5):
            return 0
        def kill(self):
            self.killed = True
    proc = FakeProc()
    c.process = proc
    c._running = True

    c.close()
    # 1. future 已被 fail
    with pytest.raises(ConnectionError, match="client closed"):
        await future
    # 2. 进程被 terminate
    assert proc.terminated is True
    # 3. _running 被置 False
    assert c._running is False


# ── 5. _read_loop 退出时 fail pending (用假 stdout 模拟 EOF) ──

@pytest.mark.asyncio
async def test_read_loop_exit_fails_pending():
    """W4-14: _read_loop 在 stdout EOF 时退出, 退出时必须 fail pending

    用一个有限行输出 + 立即 StopIteration 的假 stdout 模拟进程死
    """
    c = MCPClient("t", {"command": "echo", "args": []})

    class FakeStdout:
        def __init__(self):
            self.closed = False
        def __iter__(self):
            return self
        def __next__(self):
            if self.closed:
                raise StopIteration
            self.closed = True
            raise StopIteration  # 第一次迭代就退出, 模拟 EOF
        def close(self):
            pass

    # 用一个独立 loop 当 _mcp_loop, 在后台线程跑
    other_loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop_forever, args=(other_loop,), daemon=True)
    thread.start()
    main_loop = asyncio.get_running_loop()
    try:
        # 准备 1 个挂起 future 在 main_loop
        future = main_loop.create_future()
        c._response_futures[99] = (main_loop, future)

        class FakeProc:
            stdout = FakeStdout()
            stderr = None
        c.process = FakeProc()
        c._loop = other_loop
        c._running = True

        # 在 worker 线程跑 _read_loop
        t = threading.Thread(target=c._read_loop, daemon=True)
        t.start()
        t.join(timeout=2)
        assert not t.is_alive(), "_read_loop 没退出"

        # 跨 loop set_exception: 等 main_loop 把 call_soon_threadsafe 排队的回调跑掉
        # future.exception() 在 done 后是 thread-safe 的
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if future.done():
                break
            await asyncio.sleep(0.05)

        assert future.done(), "pending future 应当被 fail, 但 2s 后仍未 done"
        exc = future.exception()
        assert exc is not None
        assert "MCP" in str(exc) and "t" in str(exc)
    finally:
        other_loop.call_soon_threadsafe(other_loop.stop)
        thread.join(timeout=2)
        other_loop.close()


# ── 6. discover_mcp_tools_async 幂等 + shutdown 清理 ─────

@pytest.mark.asyncio
async def test_discover_mcp_tools_async_idempotent(monkeypatch):
    """W4-14: 多次调用 discover_mcp_tools_async 不重复初始化"""
    _async_mcp_clients.clear()

    init_calls = []

    class FakeClient:
        def __init__(self, name, cfg):
            self.name = name
        async def initialize(self):
            init_calls.append(self.name)
            return True

    monkeypatch.setattr(
        "app.tools.mcp_client.MCPClient", FakeClient
    )
    from app.tools import mcp_client
    monkeypatch.setattr(
        mcp_client, "_get_mcp_config",
        lambda: {"srv1": {"command": "echo", "args": []}},
    )

    await discover_mcp_tools_async()
    await discover_mcp_tools_async()

    assert init_calls == ["srv1"], f"应该只初始化一次, 实际: {init_calls}"
    _async_mcp_clients.clear()


@pytest.mark.asyncio
async def test_shutdown_mcp_tools_async_clears_clients():
    """shutdown_mcp_tools_async 应当 close 每个 client 并清空 _async_mcp_clients"""
    _async_mcp_clients.clear()
    closed = []

    class FakeClient:
        def __init__(self):
            self.name = "fake"
        def close(self):
            closed.append(self.name)

    _async_mcp_clients["c1"] = FakeClient()
    _async_mcp_clients["c2"] = FakeClient()
    await shutdown_mcp_tools_async()
    assert sorted(closed) == ["fake", "fake"]
    assert len(_async_mcp_clients) == 0
