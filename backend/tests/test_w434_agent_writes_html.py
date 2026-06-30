"""W4-34 端到端: agent 能写 HTML 文件 + 启 HTTP server + curl 验证

覆盖:
1. mock LLM 决策 write_file → 真实 write_file_tool 写文件 → 读回验证内容
2. mock LLM 决策 terminal background 启 http.server → 真实起 → curl 200 + HTML 内容
3. (能力) write_file + terminal 组合 → agent 一次对话完成 "写 + 预览" 全流程

不依赖真实外网, 用 mock LLM 驱动 AgentEngine 完整 ReAct 循环, 验证
- AgentEngine.stream_chat 真调 tool_mgr.execute() (非 mock)
- tool 真写文件 / 真启 server
- 端到端 data flow 通
"""
import asyncio
import os
import socket
import sys
import time
from contextlib import closing
from unittest.mock import MagicMock, AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _can_bind_local_port() -> bool:
    """检测当前环境是否允许 bind 127.0.0.1 端口 (sandbox 默认禁)"""
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(("127.0.0.1", 0))
            return True
    except (PermissionError, OSError):
        return False


needs_network = pytest.mark.skipif(
    not _can_bind_local_port(),
    reason="sandbox 阻 bind 端口 (PermissionError); 真实环境 (lsof -iTCP:8000 可用) 才能跑此测试",
)


def _free_port() -> int:
    """找当前空闲端口 (避免 hardcode 跟现有 backend 撞)"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_tool_call(tool_name: str, arguments: dict, call_id: str = "tc-1"):
    """构造 LLMResponse.tool_calls 列表项: 真实 ToolCallResult (非 MagicMock)"""
    from app.llm.base import ToolCallResult
    return ToolCallResult(
        tool_name=tool_name,
        arguments=arguments,
        tool_call_id=call_id,
    )


def _make_llm_response(content: str, tool_calls=None, usage=None):
    """构造 LLMResponse (真实对象, 让 agent.py:1330 的 dict 转换能正常走)"""
    from app.llm.base import LLMResponse
    return LLMResponse(content=content, tool_calls=tool_calls or [], usage=usage or {})


def _build_engine(fake_llm):
    """构造一个最小可跑 AgentEngine, 真实调工具链"""
    from app.core.agent import AgentEngine
    from app.core.context import ContextManager

    fake_storage = MagicMock()
    fake_storage.get_messages = AsyncMock(return_value=[])
    fake_storage.add_message = AsyncMock()
    fake_storage.clear_session = AsyncMock()

    engine = AgentEngine(llm=fake_llm)
    engine.memory_storage = fake_storage
    engine.vector_store = MagicMock()
    engine.vector_store.search = AsyncMock(return_value=[])
    engine.context = ContextManager()
    return engine


# ═════════════════════════════════════════════════════════
# Test 1: agent 写 HTML 文件 (核心能力)
# ═════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_agent_writes_html_file_and_content_verified(tmp_path):
    """端到端: mock LLM 决策 write_file → 真实写文件 → 读回验证"""
    html_path = tmp_path / "hello.html"
    html_content = """<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>路明非的冒险</title>
</head>
<body>
    <h1>路明非の奇幻世界</h1>
    <p>路明非在卡塞尔学院的故事 —— 魔法数字 4711</p>
    <button onclick="alert('路明非')">点击</button>
</body>
</html>
"""

    call_count = [0]
    def fake_chat(messages, tools=None):
        call_count[0] += 1
        if call_count[0] == 1:
            # 第 1 轮: LLM 决定写文件
            return _make_llm_response(
                "我先写一个 HTML 页面",
                tool_calls=[_make_tool_call(
                    "write_file",
                    {"path": str(html_path), "content": html_content},
                    "tc-write",
                )],
            )
        # 第 2 轮: 写完, 给最终答复
        return _make_llm_response(
            f"已写入 {html_path}, 共 {len(html_content)} 字符"
        )

    fake_llm = MagicMock()
    fake_llm.initialize = AsyncMock(return_value=True)
    fake_llm.get_embedding = AsyncMock(return_value=[0.0] * 8)
    fake_llm.chat = AsyncMock(side_effect=fake_chat)

    engine = _build_engine(fake_llm)

    # 跑完整 ReAct 循环
    outputs = []
    tool_events = []
    async for ev in engine.stream_chat(session_id="s-write", message="写一个 hello.html"):
        outputs.append(ev)
        if ev.get("type") in ("tool_start", "tool_complete", "tool_error"):
            tool_events.append((ev["type"], ev.get("tool_name", "?")))

    # 1. 文件真存在
    assert html_path.exists(), f"file not created: {html_path}"

    # 2. 文件内容真匹配 (字节级)
    on_disk = html_path.read_text(encoding="utf-8")
    assert on_disk == html_content, (
        f"file content mismatch.\n"
        f"  expected len={len(html_content)}, got len={len(on_disk)}"
    )

    # 3. tool 真被调了 (start + complete)
    assert ("tool_start", "write_file") in tool_events, f"no write_file start: {tool_events}"
    assert ("tool_complete", "write_file") in tool_events, f"no write_file complete: {tool_events}"

    # 4. LLM 被调了 2 次 (写文件 + 给答复)
    assert call_count[0] == 2, f"expected 2 llm calls, got {call_count[0]}"

    # 5. 最终答复进了 outputs
    final_texts = [ev.get("content", "") for ev in outputs if ev.get("type") == "content"]
    assert any("已写入" in t for t in final_texts), f"final answer not in stream: {final_texts}"


# ═════════════════════════════════════════════════════════
# Test 2: agent 写 HTML + 启 HTTP server + curl 验证
# ═════════════════════════════════════════════════════════

@needs_network
@pytest.mark.asyncio
async def test_agent_writes_html_then_serves_via_http_and_curl_200(tmp_path):
    """完整 '写 + 启 server + 验证可访问' 端到端"""
    import urllib.request

    html_path = tmp_path / "index.html"
    html_content = "<!DOCTYPE html><html><body><h1>靖江 — 路明非的魔法数字 4711</h1></body></html>"
    port = _free_port()
    server_log = tmp_path / "server.log"

    rounds = []

    def fake_chat(messages, tools=None):
        rounds.append(len(rounds) + 1)
        if len(rounds) == 1:
            return _make_llm_response(
                "写文件",
                tool_calls=[_make_tool_call(
                    "write_file",
                    {"path": str(html_path), "content": html_content},
                    "tc-write",
                )],
            )
        if len(rounds) == 2:
            # 后台启 server, python3 在 _ALLOWED_COMMANDS 白名单
            cmd = (
                f"python3 -m http.server {port} --bind 127.0.0.1 "
                f"1>{server_log} 2>&1"
            )
            return _make_llm_response(
                "起 server",
                tool_calls=[_make_tool_call(
                    "terminal",
                    {"command": cmd, "background": True},
                    "tc-serve",
                )],
            )
        # round 3: 给最终答复
        return _make_llm_response(
            f"已在 http://127.0.0.1:{port}/ 提供预览, 写完 {html_path}"
        )

    fake_llm = MagicMock()
    fake_llm.initialize = AsyncMock(return_value=True)
    fake_llm.get_embedding = AsyncMock(return_value=[0.0] * 8)
    fake_llm.chat = AsyncMock(side_effect=fake_chat)

    engine = _build_engine(fake_llm)

    try:
        async for _ in engine.stream_chat(session_id="s-serve", message="写 html 并启 server"):
            pass

        # 1. 文件真存在
        assert html_path.exists()

        # 2. 等 server 起来 (max 5s)
        deadline = time.time() + 5
        url = f"http://127.0.0.1:{port}/index.html"
        up = False
        last_err = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    body = resp.read().decode("utf-8")
                    if resp.status == 200 and "路明非" in body:
                        up = True
                        break
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.2)

        if not up:
            log = server_log.read_text() if server_log.exists() else "(no log)"
            pytest.fail(
                f"server 5s 内未起 on {url} (last err: {last_err})\n"
                f"server log:\n{log}"
            )

        # 3. 3 轮 LLM 决策都跑了
        assert len(rounds) == 3, f"expected 3 rounds, got {len(rounds)}"

    finally:
        # 清理: 杀 python http.server 子进程
        os.system(f"lsof -nP -iTCP:{port} -sTCP:LISTEN -t 2>/dev/null | xargs -r kill -9 2>/dev/null")
        await asyncio.sleep(0.2)


# ═════════════════════════════════════════════════════════
# Test 3: 工具链直接调用 — 不走 LLM, 验证 write_file 工具本身
# ═════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_write_file_tool_writes_html_directly(tmp_path):
    """直接调 write_file_tool 工具, 验证工具本身能写 HTML"""
    from app.tools.implementations.file_tools import write_file_tool
    from app.tools.registry import discover_builtin_tools

    # 触发工具注册
    discover_builtin_tools()

    html_path = tmp_path / "direct.html"
    html_content = "<!DOCTYPE html><body><h1>直接调工具写 HTML</h1></body>"

    result = await write_file_tool(path=str(html_path), content=html_content)
    assert html_path.exists()
    assert "已写入" in result
    assert html_path.read_text(encoding="utf-8") == html_content
