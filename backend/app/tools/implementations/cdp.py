"""
cdp - Chrome DevTools Protocol 封装

通过 CDP 控制 Chrome 浏览器，支持有头模式。
可用于远程 Chrome（通过 SSH 隧道）或本地 Chrome debug port。

Chrome 启动命令：
  google-chrome --remote-debugging-port=9222 --no-first-run --no-default-browser-check

CDP WebSocket 端点格式：
  ws://host:9222/devtools/page/<pageId>
"""

import asyncio
import json
import logging
from typing import Any, Optional, Dict
import websockets

logger = logging.getLogger(__name__)

CDP_WS_PATH = "/devtools/page/"


class CDPClient:
    """
    Chrome DevTools Protocol 客户端

    用法：
    async with CDPClient("localhost", 9222) as client:
        await client.navigate("https://baidu.com")
        await client.click("#su")
        screenshot = await client.screenshot()
        text = await client.get_text("title")
    """

    def __init__(self, host: str, port: int, page_id: Optional[str] = None):
        self.host = host
        self.port = port
        self.page_id = page_id
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._msg_id = 0
        self._responses: Dict[int, Any] = {}
        self._connected = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    async def connect(self):
        """连接到 Chrome debug port，获取 page_id"""
        uri = f"ws://{self.host}:{self.port}/json"
        logger.info(f"[CDP] 连接到 {uri}")

        self.ws = await websockets.connect(uri, ping_interval=None)
        self._connected = True

        # 获取已有的 page 或创建新 page
        if self.page_id:
            # 使用指定 page
            self.ws_page = await websockets.connect(
                f"ws://{self.host}:{self.port}{CDP_WS_PATH}{self.page_id}",
                ping_interval=None
            )
            await self._close_ws(self.ws)  # 关闭 json endpoint
            self.ws = self.ws_page
        else:
            # 获取第一个 page
            try:
                # 尝试连接已存在的 page
                async with asyncio.timeout(2):
                    pages_data = await self.ws.recv()
                pages = json.loads(pages_data)
                if pages:
                    # 取第一个可用 page
                    page_info = next((p for p in pages if p.get("type") == "page"), pages[0])
                    self.page_id = page_info.get("id")
                    self.ws_page = await websockets.connect(
                        f"ws://{self.host}:{self.port}{CDP_WS_PATH}{self.page_id}",
                        ping_interval=None
                    )
                    await self._close_ws(self.ws)
                    self.ws = self.ws_page
                    logger.info(f"[CDP] 已连接到 page: {self.page_id}")
                else:
                    # 创建新 page
                    await self.ws.send(json.dumps({"id": self._next_id(), "method": "Target.createTarget", "params": {"url": "about:blank"}}))
                    resp = await self.ws.recv()
                    data = json.loads(resp)
                    self.page_id = data.get("result", {}).get("targetId")
                    self.ws_page = await websockets.connect(
                        f"ws://{self.host}:{self.port}{CDP_WS_PATH}{self.page_id}",
                        ping_interval=None
                    )
                    await self._close_ws(self.ws)
                    self.ws = self.ws_page
            except Exception as e:
                logger.warning(f"[CDP] 无法获取 page list: {e}，创建新 page")
                await self.ws.send(json.dumps({"id": self._next_id(), "method": "Target.createTarget", "params": {"url": "about:blank"}}))
                resp = await self.ws.recv()
                data = json.loads(resp)
                self.page_id = data.get("result", {}).get("targetId")
                self.ws_page = await websockets.connect(
                    f"ws://{self.host}:{self.port}{CDP_WS_PATH}{self.page_id}",
                    ping_interval=None
                )
                await self._close_ws(self.ws)
                self.ws = self.ws_page

    async def _close_ws(self, ws):
        try:
            await ws.close()
        except Exception:
            pass

    async def disconnect(self):
        self._connected = False
        if self.ws:
            await self._close_ws(self.ws)
            self.ws = None

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _send(self, method: str, params: Optional[dict] = None) -> Any:
        """发送 CDP 命令并等待响应"""
        if not self.ws:
            raise RuntimeError("WebSocket 未连接")
        msg_id = self._next_id()
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        await self.ws.send(json.dumps(msg, ensure_ascii=False))

        # 等待对应 id 的响应
        while True:
            try:
                resp_raw = await asyncio.wait_for(self.ws.recv(), timeout=30)
                resp = json.loads(resp_raw)
                if resp.get("id") == msg_id:
                    if "error" in resp:
                        raise CDPError(f"CDP error: {resp['error']}")
                    return resp.get("result")
            except asyncio.TimeoutError:
                raise CDPError(f"CDP 命令超时: {method}")

    async def _broadcast(self, method: str, params: Optional[dict] = None):
        """发送 CDP 命令不等待响应（事件）"""
        if not self.ws:
            raise RuntimeError("WebSocket 未连接")
        msg = {"method": method}
        if params:
            msg["params"] = params
        await self.ws.send(json.dumps(msg, ensure_ascii=False))

    # ── 基础操作 ────────────────────────────────────────────

    async def navigate(self, url: str) -> str:
        """导航到 URL"""
        result = await self._send("Page.navigate", {"url": url})
        frame_id = result.get("frameId", "") if result else ""
        # 等待页面加载
        await self.wait_load_state("load")
        logger.info(f"[CDP] 已导航到: {url} (frameId={frame_id})")
        return frame_id

    async def screenshot(self, full_page: bool = False) -> bytes:
        """截图"""
        result = await self._send("Page.captureScreenshot", {
            "format": "png",
            "quality": 80,
            "captureBeyondViewport": full_page,
        })
        import base64
        return base64.b64decode(result)

    async def click(self, selector: str) -> None:
        """点击 CSS 选择器指定的元素"""
        # 先获取元素位置
        box = await self._get_bounding_box(selector)
        if not box:
            raise CDPError(f"元素不存在: {selector}")
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        await self._broadcast("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": x,
            "y": y,
        })
        await asyncio.sleep(0.05)
        await self._broadcast("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        })
        await asyncio.sleep(0.05)
        await self._broadcast("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        })
        logger.info(f"[CDP] 点击元素: {selector} ({x:.0f}, {y:.0f})")

    async def type_text(self, selector: str, text: str, press_enter: bool = False) -> None:
        """聚焦并输入文本到选择器指定的元素"""
        # 先点击聚焦
        box = await self._get_bounding_box(selector)
        if not box:
            raise CDPError(f"元素不存在: {selector}")
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        await self._broadcast("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        })
        await self._broadcast("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        })
        await asyncio.sleep(0.1)
        # 输入文本
        for char in text:
            await self._broadcast("Input.dispatchKeyEvent", {
                "type": "keyRawPressed",
                "text": char,
                "key": char,
            })
            await asyncio.sleep(0.01)
        if press_enter:
            await self.press_key("Enter")
        logger.info(f"[CDP] 输入文本: {text[:20]}... 到 {selector}")

    async def press_key(self, key: str) -> None:
        """按下一个键"""
        key_map = {
            "Enter": "Enter",
            "Tab": "Tab",
            "Escape": "Escape",
            "Backspace": "Backspace",
            "ArrowUp": "ArrowUp",
            "ArrowDown": "ArrowDown",
            "ArrowLeft": "ArrowLeft",
            "ArrowRight": "ArrowRight",
            "Home": "Home",
            "End": "End",
            "PageUp": "PageUp",
            "PageDown": "PageDown",
        }
        mapped = key_map.get(key, key)
        await self._broadcast("Input.dispatchKeyEvent", {
            "type": "keyPressed",
            "key": mapped,
            "code": f"Key{mapped}" if mapped not in ["Enter", "Tab", "Escape"] else f"{mapped}Key",
        })
        await self._broadcast("Input.dispatchKeyEvent", {
            "type": "keyReleased",
            "key": mapped,
        })

    async def get_text(self, selector: str) -> str:
        """获取元素文本内容"""
        result = await self._send("Runtime.callFunctionOn", {
            "functionDeclaration": f"""
function() {{
  var el = document.querySelector('{selector}');
  return el ? el.innerText : null;
}}
            """,
        })
        return result or ""

    async def get_page_text(self) -> str:
        """获取页面所有文本"""
        result = await self._send("Runtime.evaluate", {
            "expression": "document.body.innerText",
            "returnByValue": True,
        })
        return result.get("value", "") if result else ""

    async def scroll(self, selector: Optional[str] = None, delta_y: int = 300) -> None:
        """滚动页面"""
        if selector:
            box = await self._get_bounding_box(selector)
            if box:
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            else:
                x, y = 0, 0
        else:
            x, y = 0, 0
        await self._broadcast("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": 0,
            "deltaY": delta_y,
        })

    async def evaluate(self, js: str) -> Any:
        """执行 JS 表达式"""
        result = await self._send("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })
        return result.get("value") if result else None

    async def get_element_attribute(self, selector: str, attr: str) -> Optional[str]:
        """获取元素的某个属性"""
        result = await self._send("Runtime.callFunctionOn", {
            "functionDeclaration": f"""
function() {{
  var el = document.querySelector('{selector}');
  return el ? el.getAttribute('{attr}') : null;
}}
            """,
        })
        return result

    async def wait_load_state(self, state: str = "load", timeout: float = 30) -> None:
        """等待页面加载状态"""
        try:
            asyncio.wait_for(self._wait_for_event(f"Page.loadEventFired" if state == "load" else "DOM.contentLoaded"), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[CDP] 等待 {state} 超时")
        except Exception as e:
            logger.warning(f"[CDP] 等待 {state} 出错: {e}")

    async def _get_bounding_box(self, selector: str) -> Optional[dict]:
        """获取元素的边界框"""
        try:
            result = await self._send("Runtime.callFunctionOn", {
                "functionDeclaration": f"""
function() {{
  var el = document.querySelector('{selector}');
  if (!el) return null;
  var r = el.getBoundingClientRect();
  return {{ x: r.left, y: r.top, width: r.width, height: r.height }};
}}
                """,
            })
            return result
        except Exception:
            return None

    async def _wait_for_event(self, event_name: str) -> None:
        """等待指定 CDP 事件（内部用，不直接暴露）"""
        while True:
            resp_raw = await self.ws.recv()
            resp = json.loads(resp_raw)
            if resp.get("method") == event_name:
                return

    async def close(self) -> None:
        """关闭当前 page"""
        if self.page_id:
            try:
                await self._send("Target.closeTarget", {"targetId": self.page_id})
            except Exception:
                pass
            self.page_id = None


class CDPError(Exception):
    """CDP 操作错误"""
    pass


# ── 便捷工厂函数 ────────────────────────────────────────────

async def create_cdp_client(host: str = "localhost", port: int = 9222) -> CDPClient:
    """创建 CDP 客户端并连接到第一个可用 page"""
    client = CDPClient(host, port)
    await client.connect()
    return client


async def screenshot_url(url: str, host: str = "localhost", port: int = 9222) -> bytes:
    """截图指定 URL（CDP 直连方式）"""
    async with CDPClient(host, port) as client:
        await client.navigate(url)
        return await client.screenshot()
