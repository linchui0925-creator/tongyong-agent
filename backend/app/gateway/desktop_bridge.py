"""
DesktopBridge - WebSocket 代理让后端命令穿过前端到用户 macOS

架构：
  Backend Agent → WebSocket → Frontend → 用户 macOS 执行 → 结果返回

前端连接时携带认证信息（session_token），后端通过 WebSocket 发命令，
前端在用户本机执行后返回结果。

支持两类远程执行：
1. AppleScript / 系统命令（macOS）
2. CDP browser 操作（通过 browser.py 的 CDP 模式）
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

router = APIRouter(tags=["desktop"])


class DesktopBridgeServer:
    """
    服务端：管理所有前端 WebSocket 连接，转发命令到对应连接。
    """

    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}  # session_id -> websocket
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, ws: WebSocket):
        async with self._lock:
            old = self._connections.get(session_id)
            if old and old.client_state == WebSocketState.CONNECTED:
                try:
                    await old.close()
                except Exception:
                    pass
            await ws.accept()
            self._connections[session_id] = ws
            logger.info(f"[DesktopBridge] 前端连接: session_id={session_id}")

    async def disconnect(self, session_id: str):
        async with self._lock:
            self._connections.pop(session_id, None)
            logger.info(f"[DesktopBridge] 前端断开: session_id={session_id}")

    async def send_command(self, session_id: str, command: dict) -> Optional[dict]:
        """向指定 session 的前端发送命令，等待执行结果"""
        ws = self._connections.get(session_id)
        if not ws or ws.client_state != WebSocketState.CONNECTED:
            return {"status": "error", "message": "前端未连接"}

        try:
            await ws.send_json({"type": "desktop_cmd", **command})
        except Exception as e:
            logger.error(f"[DesktopBridge] 发送命令失败: {e}")
            return {"status": "error", "message": str(e)}

        # 等待结果（前端回复 type=desktop_result）
        try:
            # 超时 60s
            result = await asyncio.wait_for(ws.receive_json(), timeout=60)
            return result
        except asyncio.TimeoutError:
            return {"status": "error", "message": "执行超时（60s）"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def broadcast(self, message: dict):
        """广播消息到所有连接的前端（用于通知）"""
        async with self._lock:
            for ws in list(self._connections.values()):
                if ws.client_state == WebSocketState.CONNECTED:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        pass


# 全局单例
_bridge = DesktopBridgeServer()


@router.websocket("/ws/desktop/{session_id}")
async def desktop_websocket(ws: WebSocket, session_id: str):
    """
    前端 WebSocket 连接端点。

    连接建立后，前端处于等待命令状态。
    后端通过 send_command() 向前端推送命令，前端执行后返回结果。

    消息格式：
      前端 → 后端：{"type": "desktop_result", "cmd_id": "...", "status": "success", "result": "..."}
      后端 → 前端：{"type": "desktop_cmd", "cmd_id": "...", "action": "osascript", "script": "..."}
    """
    await _bridge.connect(session_id, ws)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "desktop_result":
                # 前端主动上报结果（暂时不需要，前端回复 await send_command 即可）
                logger.debug(f"[DesktopBridge] 前端结果: {data}")

            elif msg_type == "ping":
                await ws.send_json({"type": "pong", "time": data.get("time")})

            else:
                logger.warning(f"[DesktopBridge] 未知消息类型: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"[DesktopBridge] WebSocket 断开: session_id={session_id}")
    except Exception as e:
        logger.error(f"[DesktopBridge] WebSocket 错误: {e}", exc_info=True)
    finally:
        await _bridge.disconnect(session_id)


@router.post("/api/desktop/execute")
async def desktop_execute(
    session_id: str,
    action: str,
    params: Optional[dict] = None,
):
    """
    HTTP 接口：后端 Agent 执行 desktop 命令。

    后端 Agent 调用此接口，将命令转发给已连接的前端代理执行。
    适用于 browser 有头模式（CDP）和 desktop 工具。

    Params:
      session_id: 前端会话 ID（用于定位 WebSocket 连接）
      action: desktop / browser_cdp
      params: 执行参数

    Returns:
      {"status": "success", "result": "..."} 或 {"status": "error", "message": "..."}
    """
    params = params or {}

    if action == "desktop":
        # desktop 工具走 AppleScript/syscommand
        from app.tools.implementations.desktop import desktop_execute as _desktop_exec
        try:
            result = await _desktop_exec(**params)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif action == "browser_cdp":
        # browser CDP 模式：复用 desktop WebSocket 代理 CDP 命令
        # params 应包含 cdp_url, action, 和 action 参数
        cdp_url = params.get("cdp_url")
        browser_action = params.get("browser_action", "navigate")
        browser_params = params.get("browser_params", {})

        if not cdp_url:
            return {"status": "error", "message": "browser_cdp 需要 cdp_url"}

        # 通过 WebSocket 让前端帮忙执行 CDP
        cmd = {
            "cmd_id": f"cdp_{session_id}_{browser_action}",
            "action": "browser_cdp",
            "cdp_url": cdp_url,
            "browser_action": browser_action,
            "browser_params": browser_params,
        }
        result = await _bridge.send_command(session_id, cmd)
        return result

    else:
        return {"status": "error", "message": f"未知 action: {action}"}