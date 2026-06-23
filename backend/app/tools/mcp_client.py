"""
mcp_client - Model Context Protocol 客户端

支持 stdio 传输（command + args）和 HTTP 传输（url）。
从配置发现 MCP 服务器，动态注册其工具到 registry。

配置示例 (config.py):
    mcp_servers:
      filesystem:
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        env: {}
      github:
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_..."

W4-14 (2026-06-22) 修复 (MCP 生命周期 / 跨 loop future 泄漏):
  - 旧实现 _response_futures 只存 future, 不记它所属的事件循环
  - 当 MCP server 进程崩溃 (read loop 退出), 挂起的 future 永远 hang,
    即使有 60s wait_for 兜底, 实际体验是调试地狱
  - 旧实现 shutdown_mcp_tools 先 kill 进程再 stop loop, 顺序错误,
    跨 loop future 残留导致 _mcp_loop.stop() 后 wait_for 才能拿到异常
  - 旧实现 _handle_message 在 _mcp_loop 上调用 future.set_result,
    但 future 可能在 FastAPI 主 loop 创建 (set_result 跨 loop 在 3.12+ 不安全)
  - 旧实现 discover_mcp_tools 用 daemon thread + 新 event loop,
    与 FastAPI lifespan 分离, 部署多 worker 时每个 worker 都启 MCP 进程

  本次修复:
  1. _response_futures 改为 (loop, future) 元组, 记录 future 所属 loop
  2. _handle_message 用 future_loop.call_soon_threadsafe(set_result/set_exception)
  3. 新增 _fail_pending(reason): 一次性 fail 所有挂起 future, 避免 hang
  4. _read_loop 退出时 (正常 EOF / 异常 / 进程死) 自动 fail pending
  5. close() 先 fail pending 再 kill 进程
  6. shutdown_mcp_tools 顺序: close clients (内部 fail+kill) → stop loop → join thread
  7. 新增 discover_mcp_tools_async: 给 FastAPI lifespan 用, 不再 daemon thread
  8. 主 loop 模式下 (async 入口) 共享 FastAPI 的 loop, 多 worker 各自启一份仍是
     已知限制, 文档化为 P2 follow-up (需要外部 lock 或共享缓存)
"""

import asyncio
import json
import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── MCP 配置（从 settings 读取）───────────────────────────

def _get_mcp_config() -> Dict[str, Dict]:
    """从配置读取 MCP 服务器列表"""
    try:
        from app.config import settings
        return getattr(settings, "mcp_servers", {}) or {}
    except Exception:
        return {}


# ── MCP JSON-RPC 协议 ─────────────────────────────────

class MCPClient:
    """单个 MCP 服务器的客户端连接"""

    def __init__(self, name: str, server_config: Dict):
        self.name = name
        self.server_config = server_config
        self.process: Optional[subprocess.Popen] = None
        self.request_id = 0
        self._lock = threading.Lock()
        # W4-14: 元组 (loop, future), 记录 future 所属 loop 便于跨 loop 安全 set_result
        self._response_futures: Dict[int, Tuple[asyncio.AbstractEventLoop, asyncio.Future]] = {}
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        # W4-14: client 自己的事件循环 (initialize 时由调用方 loop 注入, 后续 _handle_message 用它)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 工具注册名 → schema
        self._tools: Dict[str, Dict] = {}

    def _next_id(self) -> int:
        with self._lock:
            self.request_id += 1
            return self.request_id

    def _send_raw(self, msg: dict):
        """发送原始 JSON 消息到 MCP 服务器

        W4-11 MCP 修复 2026-06-21:
          - 旧实现 process 未启动时静默 return, 调用方 future 永远不返回
            (要等 60s 超时, 且错误信息为零, 调试极困难)
          - 修复: 主动抛 RuntimeError, 让 _send_request 的 wait_for 立即失败
        """
        if not self.process or self.process.stdin is None:
            raise RuntimeError(
                f"MCP {self.name}: 进程未启动或 stdin 不可用, 无法发送消息 "
                f"(method={msg.get('method', '?')})"
            )
        line = json.dumps(msg, ensure_ascii=False)
        # Popen(text=True) 后 stdin 是 TextIOWrapper, 可直接 write str
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def _read_loop(self):
        """在后台线程读取 MCP 服务器响应

        W4-14: 循环退出时 (EOF / 异常 / 进程死) 必须 fail pending futures,
        否则调用方 _send_request 的 future 永远不返回 (要等满 60s 兜底)
        """
        if not self.process or not self.process.stdout:
            return
        loop = self._loop
        if loop is None:
            return

        exit_reason = "read loop ended (no reason captured)"
        try:
            for line in self.process.stdout:
                if not self._running:
                    exit_reason = "client closed"
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # 调度到 asyncio 事件循环，忽略返回的 Future（异步处理，无需等待）
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_message(msg), loop
                    )
                except Exception as e:
                    logger.debug(f"MCP {self.name} 消息调度失败: {e}")
        except Exception as e:
            exit_reason = f"read loop exception: {e}"
            logger.debug(f"MCP {self.name} read loop ended: {e}")
        else:
            if self._running:
                # 进程意外退出 (read loop 正常结束但客户端还在运行) → MCP 死了
                exit_reason = "MCP process exited (stdout EOF while client running)"
        finally:
            # W4-14: 关键: 不管什么原因退出, 都要 fail pending futures,
            # 否则 60s wait_for 兜底前调用方一直 hang
            self._fail_pending(exit_reason)

    def _fail_pending(self, reason: str):
        """一次性 fail 所有挂起的 response futures

        W4-14 新增: 解决 "MCP 进程死了, future 永远 hang 60s" 的问题
        跨 loop 安全: 用 future 自己的 loop.call_soon_threadsafe(set_exception, ...)
        """
        if not self._response_futures:
            return
        exc = ConnectionError(f"MCP {self.name}: {reason}")
        # popitem 避免在迭代中修改 dict
        for req_id, (floop, future) in list(self._response_futures.items()):
            if future.done():
                self._response_futures.pop(req_id, None)
                continue
            try:
                floop.call_soon_threadsafe(future.set_exception, exc)
            except RuntimeError:
                # loop 已关闭 (例如 shutdown_mcp_tools 已 stop _mcp_loop),
                # 退化到直接 set_exception (Python 3.10+ 跨 loop set 仍可用)
                try:
                    future.set_exception(exc)
                except Exception:
                    pass
            self._response_futures.pop(req_id, None)
        logger.debug(f"MCP {self.name} failed {len(self._response_futures)} pending futures: {reason}")

    async def _handle_message(self, msg: dict):
        """处理 MCP 响应消息

        W4-14: 必须在 future 自己的 loop 上 set_result/set_exception,
        不能在 self._loop 上直接调 (跨 loop 跨线程不安全)
        """
        msg_id = msg.get("id")
        if msg_id is not None and msg_id in self._response_futures:
            future_loop, future = self._response_futures.pop(msg_id)
            if future.done():
                return
            if "error" in msg:
                exc = Exception(msg["error"].get("message", str(msg["error"])))
                future_loop.call_soon_threadsafe(future.set_exception, exc)
            else:
                future_loop.call_soon_threadsafe(future.set_result, msg.get("result"))

    async def _send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """发送 JSON-RPC 请求并等待响应

        W4-11 MCP 修复:
          - 用 get_running_loop() 替代 deprecated get_event_loop() (Python 3.12+)
          - _send_raw 抛错时清理 future, 避免 _response_futures 字典泄漏
        W4-14 MCP 修复:
          - 把调用方 loop 与 future 一起存, 便于 _handle_message 跨 loop 安全 resolve
        """
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()  # W4-11: 替代 get_event_loop (deprecated)
        future = loop.create_future()
        # W4-14: 记下 future 所属 loop
        self._response_futures[req_id] = (loop, future)

        try:
            self._send_raw(msg)  # 旧实现此处 raise 会导致 future 残留
        except Exception:
            # 发送失败: 清理 future 防泄漏, 再抛
            self._response_futures.pop(req_id, None)
            raise

        try:
            return await asyncio.wait_for(future, timeout=60.0)
        except asyncio.TimeoutError:
            self._response_futures.pop(req_id, None)
            raise TimeoutError(f"MCP {self.name} request '{method}' timed out")

    async def initialize(self) -> bool:
        """初始化 MCP 会话，返回是否成功

        W4-14: 此方法必须在调用方的事件循环里 await (推荐 FastAPI lifespan 用
        discover_mcp_tools_async), self._loop 会绑定到当前 running loop,
        后续 _handle_message 都在此 loop 上调度
        """
        try:
            # 启动进程
            cmd = self.server_config.get("command", "")
            args = self.server_config.get("args", [])
            env = dict(self.server_config.get("env", {}) or {})
            # 继承当前环境变量
            import os
            for k, v in os.environ.items():
                if k not in env:
                    env[k] = v

            startup_timeout = self.server_config.get("startup_timeout", 30)

            self.process = subprocess.Popen(
                [cmd] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,   # W4-11 MCP 修复: text mode 简化 JSON-RPC line protocol,
                             #   旧 binary mode + str write 会 TypeError
            )

            # 设置事件循环 — 绑定到当前 running loop (W4-14 改进: 之前是任意 loop 都行,
            # 现在显式取 running loop, 配合 async 入口)
            self._loop = asyncio.get_running_loop()
            self._running = True

            # 启动读取线程
            self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._read_thread.start()

            # 等待进程启动
            await asyncio.sleep(0.5)
            if self.process.poll() is not None:
                stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
                logger.error(f"MCP {self.name} process exited immediately: {stderr[:500]}")
                return False

            # 发送 initialize
            result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "tongyong-agent",
                    "version": "1.0.0",
                },
            })
            logger.info(f"MCP {self.name} initialized: {result}")

            # 发送 initialized 通知
            self._send_raw({"jsonrpc": "2.0", "method": "notifications/initialized"})

            # 获取工具列表
            await self._load_tools()
            return True

        except Exception as e:
            logger.error(f"MCP {self.name} initialization failed: {e}")
            self.close()
            return False

    async def _load_tools(self):
        """从 MCP 服务器获取工具列表"""
        try:
            result = await self._send_request("tools/list")
            tools = result.get("tools", []) if result else []
            for tool in tools:
                name = tool.get("name", "")
                if not name:
                    continue
                # 注册到 registry，toolset = "mcp-{server_name}"
                self._register_tool(tool)
            logger.info(f"MCP {self.name} loaded {len(tools)} tools: {[t.get('name') for t in tools]}")
        except Exception as e:
            logger.warning(f"MCP {self.name} failed to load tools: {e}")

    def _register_tool(self, tool_def: Dict):
        """将 MCP 工具注册到 registry"""
        from app.tools.registry import registry

        name = tool_def.get("name", "")
        description = tool_def.get("description", "")
        input_schema = tool_def.get("inputSchema", {})

        # 包装 handler
        # W4-18 修复: 改用 **arguments 跟其他 tool 约定一致 (tool manager 调 handler(**arguments))
        # 旧签名 mcp_handler(args: Dict) 跟 ToolRegistry.execute 的 entry.handler(**arguments) 不兼容
        # — LLM 传 {"text": "hi"} 时, 旧实现会被调成 mcp_handler(text="hi") 直接 TypeError
        async def mcp_handler(task_id: str = "default", **arguments) -> str:
            # 移除 task_id (内部使用), 剩下的就是 MCP server 实际收到的 arguments
            arguments.pop("task_id", None)
            try:
                result = await self._send_request("tools/call", {
                    "name": name,
                    "arguments": arguments,
                })
                if isinstance(result, dict):
                    content = result.get("content", [])
                    if isinstance(content, list):
                        texts = []
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                texts.append(c.get("text", ""))
                        return "\n".join(texts)
                    return json.dumps(result, ensure_ascii=False)
                return str(result)
            except Exception as e:
                return json.dumps({"error": f"MCP {self.name}/{name} call failed: {e}"})

        toolset = f"mcp-{self.name}"
        schema = {
            "name": name,
            "description": description,
            "parameters": input_schema or {"type": "object", "properties": {}},
        }

        registry.register(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=mcp_handler,
            is_async=True,
            description=description,
            emoji="🔌",
            parallel_mode="never",
        )
        self._tools[name] = tool_def

    def close(self):
        """关闭 MCP 连接

        W4-14 修复顺序:
          1. fail pending (调用方 future 立即收到 ConnectionError, 不再 hang 60s)
          2. 置 _running=False 让 _read_loop 退出
          3. terminate / kill 进程
        """
        # 1. 先 fail pending — 必须在 kill 进程前, 否则 read loop 退出时
        #    跨 loop future 状态不一致
        self._fail_pending("client closed")
        # 2. 置位让 _read_loop 退出
        self._running = False
        # 3. kill 进程
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass


# ── 全局 MCP 客户端管理 ─────────────────────────────────

# 两种模式的客户端存储:
# - _mcp_clients: 同步入口 (daemon thread 模式) 用, 保留向后兼容
# - _async_mcp_clients: 异步入口 (FastAPI lifespan 模式) 用
_mcp_clients: Dict[str, MCPClient] = {}
_mcp_loop: Optional[asyncio.AbstractEventLoop] = None
_mcp_thread: Optional[threading.Thread] = None

_async_mcp_clients: Dict[str, MCPClient] = {}


def _run_mcp_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def _discover_mcp_async_in_loop(client_dict: Dict[str, MCPClient]):
    """在调用方当前事件循环中初始化所有 MCP 服务器

    W4-14 重构: 把 _mcp_clients / _async_mcp_clients 两个存储作为参数传入,
    同一段初始化逻辑给两种入口共用
    """
    config = _get_mcp_config()
    if not config:
        logger.debug("No MCP servers configured")
        return

    for server_name, server_config in config.items():
        client = MCPClient(server_name, server_config)
        client_dict[server_name] = client
        success = await client.initialize()
        if not success:
            logger.warning(f"MCP server '{server_name}' failed to initialize, skipping")


async def discover_mcp_tools_async():
    """异步入口: 推荐在 FastAPI lifespan 里调用

    W4-14 新增: 与 discover_mcp_tools() 区别:
      - 用 FastAPI 的 event loop, 不开 daemon thread
      - 多 worker 部署每个 worker 仍会启自己的 MCP 进程 (已知限制, P2 follow-up)
      - 进程 crash 时 _fail_pending 让调用方立即拿到 ConnectionError
        而不是等 60s wait_for
    """
    if _async_mcp_clients:
        # 幂等: 已初始化过, 跳过 (便于 lifespan 重入)
        logger.debug("MCP tools already discovered (async), skipping")
        return
    await _discover_mcp_async_in_loop(_async_mcp_clients)
    logger.info(f"MCP discovery (async) complete: {len(_async_mcp_clients)} servers")


async def shutdown_mcp_tools_async():
    """异步入口的关闭: 在 FastAPI lifespan teardown 调用"""
    global _async_mcp_clients
    for client in _async_mcp_clients.values():
        client.close()
    _async_mcp_clients.clear()


def discover_mcp_tools():
    """发现并初始化所有配置的 MCP 服务器（同步入口, 向后兼容）

    W4-14: 推荐改用 discover_mcp_tools_async() (FastAPI lifespan 友好)。
    本函数保留是因为旧版测试 / 脚本可能还在 import, 内部用 daemon thread +
    新 event loop 隔离 MCP 生命周期。
    """
    global _mcp_loop, _mcp_thread

    if _mcp_clients:
        # 幂等: 已初始化过, 跳过
        logger.debug("MCP tools already discovered (sync), skipping")
        return

    config = _get_mcp_config()
    if not config:
        return

    try:
        loop = asyncio.new_event_loop()
        _mcp_loop = loop
        _mcp_thread = threading.Thread(target=_run_mcp_loop, args=(loop,), daemon=True)
        _mcp_thread.start()

        # 在新事件循环中运行初始化
        future = asyncio.run_coroutine_threadsafe(
            _discover_mcp_async_in_loop(_mcp_clients), loop
        )
        future.result(timeout=30)
        logger.info(f"MCP discovery (sync) complete: {len(_mcp_clients)} servers")
    except Exception as e:
        logger.warning(f"MCP discovery (sync) failed: {e}")


def shutdown_mcp_tools():
    """关闭所有 MCP 连接 (同步入口, 向后兼容)

    W4-14 修复顺序:
      1. close 每个 client (内部: fail pending → terminate → wait)
      2. 清空 client dict
      3. stop _mcp_loop (call_soon_threadsafe 安全跨线程)
      4. join daemon thread (5s 超时, 不阻塞 shutdown)
      5. 清空全局变量
    """
    global _mcp_clients, _mcp_loop, _mcp_thread

    # 1. close clients (内部已 fail pending + kill 进程)
    for client in list(_mcp_clients.values()):
        try:
            client.close()
        except Exception as e:
            logger.debug(f"close MCP client {client.name} failed: {e}")
    _mcp_clients.clear()

    # 2. stop loop
    if _mcp_loop is not None:
        try:
            _mcp_loop.call_soon_threadsafe(_mcp_loop.stop)
        except RuntimeError:
            # loop 已关闭, 忽略
            pass
        _mcp_loop = None

    # 3. join daemon thread (避免主进程退出时还有 dangling thread)
    if _mcp_thread is not None:
        _mcp_thread.join(timeout=5)
        _mcp_thread = None
