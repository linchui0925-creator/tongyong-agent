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
"""

import asyncio
import json
import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        self._response_futures: Dict[int, asyncio.Future] = {}
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
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
        """在后台线程读取 MCP 服务器响应"""
        if not self.process or not self.process.stdout:
            return
        loop = self._loop
        if loop is None:
            return

        try:
            for line in self.process.stdout:
                if not self._running:
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
            logger.debug(f"MCP {self.name} read loop ended: {e}")

    async def _handle_message(self, msg: dict):
        """处理 MCP 响应消息"""
        msg_id = msg.get("id")
        if msg_id is not None and msg_id in self._response_futures:
            future = self._response_futures.pop(msg_id)
            if "error" in msg:
                future.set_exception(Exception(msg["error"].get("message", str(msg["error"]))))
            else:
                future.set_result(msg.get("result"))

    async def _send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """发送 JSON-RPC 请求并等待响应

        W4-11 MCP 修复:
          - 用 get_running_loop() 替代 deprecated get_event_loop() (Python 3.12+)
          - _send_raw 抛错时清理 future, 避免 _response_futures 字典泄漏
        """
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()  # W4-11: 替代 get_event_loop (deprecated)
        future = loop.create_future()
        self._response_futures[req_id] = future

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
        """初始化 MCP 会话，返回是否成功"""
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

            # 设置事件循环
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
        async def mcp_handler(args: Dict, task_id: str = "default") -> str:
            try:
                result = await self._send_request("tools/call", {
                    "name": name,
                    "arguments": args,
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
        """关闭 MCP 连接"""
        self._running = False  # 先置位让 _read_loop 退出
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        # W4-11 MCP 修复: 末尾的 self._running = False 重复且误导 (close 后实例不应再被用)


# ── 全局 MCP 客户端管理 ─────────────────────────────────

_mcp_clients: Dict[str, MCPClient] = {}
_mcp_loop: Optional[asyncio.AbstractEventLoop] = None
_mcp_thread: Optional[threading.Thread] = None


def _run_mcp_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def _discover_mcp_async():
    """在已有事件循环中初始化所有 MCP 服务器"""
    global _mcp_clients

    config = _get_mcp_config()
    if not config:
        logger.debug("No MCP servers configured")
        return

    for server_name, server_config in config.items():
        client = MCPClient(server_name, server_config)
        _mcp_clients[server_name] = client
        success = await client.initialize()
        if not success:
            logger.warning(f"MCP server '{server_name}' failed to initialize, skipping")


def discover_mcp_tools():
    """发现并初始化所有配置的 MCP 服务器（同步入口）"""
    global _mcp_loop, _mcp_thread

    config = _get_mcp_config()
    if not config:
        return

    try:
        loop = asyncio.new_event_loop()
        _mcp_loop = loop
        _mcp_thread = threading.Thread(target=_run_mcp_loop, args=(loop,), daemon=True)
        _mcp_thread.start()

        # 在新事件循环中运行初始化
        async def init_all():
            await _discover_mcp_async()

        future = asyncio.run_coroutine_threadsafe(init_all(), loop)
        future.result(timeout=30)
        logger.info(f"MCP discovery complete: {len(_mcp_clients)} servers")
    except Exception as e:
        logger.warning(f"MCP discovery failed: {e}")


def shutdown_mcp_tools():
    """关闭所有 MCP 连接"""
    global _mcp_clients, _mcp_loop
    for client in _mcp_clients.values():
        client.close()
    _mcp_clients.clear()
    if _mcp_loop:
        _mcp_loop.call_soon_threadsafe(_mcp_loop.stop)
        _mcp_loop = None
