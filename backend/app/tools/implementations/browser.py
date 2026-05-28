"""
browser - 浏览器控制工具

支持两种模式：
1. playwright（默认）：Playwright headless，服务端运行，用户不可见
2. cdp：有头模式，通过 Chrome DevTools Protocol 连接用户本地 Chrome，
   用户可以看到真实浏览器窗口

CDP 模式下 Chrome 启动方式（需用户手动或通过 SSH 执行）：
  google-chrome --remote-debugging-port=9222 --no-first-run --no-default-browser-check
"""

import logging
import os
import threading
import asyncio
from typing import Optional
from pathlib import Path

from app.tools.registry import registry

logger = logging.getLogger(__name__)

# ── Playwright 实例池 ──────────────────────────────

_pw_lock = threading.Lock()
_pw_instances: dict = {}
"""Playwright headless 实例: {instance_key: {playwright, browser, page}}"""


# ── CDP 实例池 ───────────────────────────────────

_cdp_lock = threading.Lock()
_cdp_instances: dict = {}
"""CDP 有头实例: {instance_key: CDPClient}"""


def _get_instance_key(session_id: str = "") -> str:
    return session_id if session_id else "default"


# ── Playwright 实例管理 ──────────────────────────

async def _ensure_playwright(instance_key: str = "default"):
    with _pw_lock:
        inst = _pw_instances.get(instance_key)
        if inst is not None and inst.get("page") is not None:
            return inst["page"]

    expected_shell = Path.home() / "Library" / "Caches" / "ms-playwright" / "chromium_headless_shell-1169" / "chrome-mac" / "headless_shell"
    if not expected_shell.exists():
        raise RuntimeError(
            "Playwright 浏览器未安装或版本不匹配。"
            f"缺少可执行文件: {expected_shell}. "
            "请运行 `python -m playwright install chromium` 安装匹配的 Chromium。"
        )

    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
    except Exception as e:
        try:
            await pw.stop()
        except Exception:
            pass
        msg = str(e)
        lower = msg.lower()
        if "machportrendezvousserver" in lower or "permission denied (1100)" in lower:
            raise RuntimeError(
                "Playwright 浏览器启动被当前 macOS 运行环境阻止。"
                "这是系统权限/沙箱限制，不是浏览器缺失。"
                "如果需要继续浏览器任务，请改用 mode=cdp 连接用户本地可见 Chrome，"
                "或在非受限环境中启动后端。"
            ) from e
        raise

    with _pw_lock:
        old = _pw_instances.get(instance_key)
        if old is not None:
            try:
                await old["browser"].close()
            except Exception:
                pass
            try:
                await old["playwright"].stop()
            except Exception:
                pass
        _pw_instances[instance_key] = {
            "playwright": pw,
            "browser": browser,
            "page": page,
        }

    logger.info(f"Playwright 浏览器已启动（实例: {instance_key}）")
    return page


async def _close_playwright_instance(instance_key: str) -> bool:
    with _pw_lock:
        inst = _pw_instances.pop(instance_key, None)
    if inst is None:
        return False
    try:
        await inst["browser"].close()
    except Exception:
        pass
    try:
        await inst["playwright"].stop()
    except Exception:
        pass
    logger.info(f"Playwright 实例已关闭: {instance_key}")
    return True


async def _close_all_playwright():
    with _pw_lock:
        keys = list(_pw_instances.keys())
    for key in keys:
        await _close_playwright_instance(key)


# ── CDP 实例管理 ─────────────────────────────────

async def _ensure_cdp(instance_key: str = "default", cdp_url: str = ""):
    """
    通过 CDP 连接有头 Chrome。

    cdp_url 格式：
      ws://host:port/devtools/page/<pageId>
    例如：
      ws://localhost:9222/devtools/page/ABC123
    """
    with _cdp_lock:
        inst = _cdp_instances.get(instance_key)
        if inst is not None and getattr(inst, "_connected", False):
            return inst

    from app.tools.implementations.cdp import CDPClient
    import websockets
    import httpx
    import json as _json

    # 解析 CDP URL
    # 支持 ws://host:port/json 格式（通过 HTTP 获取第一个 page）
    if cdp_url.endswith("/json"):
        # ws://localhost:9222/json -> http://localhost:9222/json -> 取第一个 page 的 websocketDebuggerUrl
        client = CDPClient.__new__(CDPClient)
        client.host = cdp_url.replace("ws://", "").split(":")[0] if "://" in cdp_url else "localhost"
        client.port = int(cdp_url.split(":")[-1].split("/")[0]) if ":" in cdp_url else 9222
        client.page_id = None
        client.ws = None
        client._msg_id = 0
        client._responses = {}
        client._connected = False

        http_url = cdp_url.replace("ws://", "http://").replace("wss://", "https://")
        pages = []
        try:
            async with httpx.AsyncClient(timeout=10) as http_client:
                resp = await http_client.get(http_url)
                resp.raise_for_status()
                pages = resp.json()
        except Exception as e:
            raise RuntimeError(
                f"无法从 Chrome DevTools 列表接口获取页面信息: {http_url}。"
                "请确认 Chrome 已用 --remote-debugging-port=9222 启动，"
                "并且这个地址可以在本机访问。"
            ) from e

        if pages:
            page_info = next((p for p in pages if p.get("type") == "page"), pages[0])
            client.page_id = page_info.get("id")
            page_ws_url = page_info.get("webSocketDebuggerUrl")
            if not page_ws_url:
                host_part = cdp_url.replace("ws://", "").replace("wss://", "").split("/")[0]
                page_ws_url = f"ws://{host_part}/devtools/page/{client.page_id}"
            client.ws = await websockets.connect(page_ws_url, ping_interval=None)
            client._connected = True
        else:
            raise RuntimeError("Chrome 没有可用的 debuggable page")
    elif cdp_url:
        # 直接是 page WS URL
        client = CDPClient.__new__(CDPClient)
        client.host = ""
        client.port = 0
        client.page_id = cdp_url.split("/devtools/page/")[-1] if "/devtools/page/" in cdp_url else ""
        client.ws = await websockets.connect(cdp_url, ping_interval=None)
        client._msg_id = 0
        client._responses = {}
        client._connected = True
    else:
        raise ValueError("CDP mode 需要提供 cdp_url")

    with _cdp_lock:
        old = _cdp_instances.get(instance_key)
        if old is not None:
            try:
                await old.disconnect()
            except Exception:
                pass
        _cdp_instances[instance_key] = client

    logger.info(f"CDP 浏览器已连接（实例: {instance_key}, page: {client.page_id}）")
    return client


async def _close_cdp_instance(instance_key: str) -> bool:
    with _cdp_lock:
        inst = _cdp_instances.pop(instance_key, None)
    if inst is None:
        return False
    try:
        await inst.disconnect()
    except Exception:
        pass
    logger.info(f"CDP 实例已关闭: {instance_key}")
    return True


# ── 兼容的浏览器实例基类 ──────────────────────────

class BrowserMode:
    """统一 Playwright page 和 CDPClient 的操作接口"""

    def __init__(self, page, cdp_client: Optional["CDPClient"] = None):
        self._page = page  # Playwright page
        self._cdp = cdp_client  # CDPClient instance

    async def navigate(self, url: str) -> str:
        if self._cdp:
            await self._cdp.navigate(url)
            return f"已导航到: {url}"
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        title = await self._page.title()
        return f"已打开: {url}\n页面标题: {title}"

    async def click(self, selector: str) -> str:
        if self._cdp:
            await self._cdp.click(selector)
            return f"已点击: {selector}"
        await self._page.click(selector, timeout=10000)
        return f"已点击: {selector}"

    async def type_text(self, selector: str, text: str) -> str:
        if self._cdp:
            await self._cdp.type_text(selector, text)
            return f"已在 {selector} 输入: {text}"
        await self._page.fill(selector, text, timeout=10000)
        return f"已在 {selector} 输入: {text}"

    async def screenshot(self, path: str) -> str:
        if self._cdp:
            img_bytes = await self._cdp.screenshot()
            with open(path, "wb") as f:
                f.write(img_bytes)
            return f"截图已保存: {os.path.abspath(path)}"
        await self._page.screenshot(path=path, full_page=False)
        return f"截图已保存: {os.path.abspath(path)}"

    async def get_text(self, selector: str) -> str:
        if self._cdp:
            text = await self._cdp.get_text(selector)
            return text or f"未找到元素: {selector}"
        element = await self._page.query_selector(selector)
        if not element:
            return f"未找到元素: {selector}"
        content = await element.inner_text()
        if len(content) > 5000:
            content = content[:5000] + "\n...（内容过长，已截断）"
        return content

    async def get_page_content(self) -> str:
        if self._cdp:
            content = await self._cdp.get_page_text()
            if len(content) > 8000:
                content = content[:8000] + "\n...（内容过长，已截断）"
            return content
        content = await self._page.inner_text("body")
        if len(content) > 8000:
            content = content[:8000] + "\n...（内容过长，已截断）"
        return content

    async def scroll(self, selector: str = "") -> str:
        if self._cdp:
            await self._cdp.scroll(selector)
            return f"已滚动到: {selector}" if selector else "已向下滚动一屏"
        if selector:
            await self._page.evaluate(f'document.querySelector("{selector}")?.scrollIntoView()')
            return f"已滚动到: {selector}"
        await self._page.evaluate("window.scrollBy(0, window.innerHeight)")
        return "已向下滚动一屏"

    async def keypress(self, key: str) -> str:
        if self._cdp:
            await self._cdp.press_key(key)
            return f"已按键: {key}"
        key_map = {
            "Enter": "Enter", "Tab": "Tab", "Escape": "Escape",
            "ArrowUp": "ArrowUp", "ArrowDown": "ArrowDown",
            "ArrowLeft": "ArrowLeft", "ArrowRight": "ArrowRight",
            "Home": "Home", "End": "End",
        }
        mapped = key_map.get(key, key)
        await self._page.keyboard.press(mapped)
        return f"已按键: {key}"

    async def close(self):
        if self._cdp:
            await self._cdp.close()
        if self._page:
            await self._page.close()


# ── 统一的实例获取 ─────────────────────────────────

async def _get_browser_instance(instance_key: str = "default", mode: str = "playwright", cdp_url: str = ""):
    """
    获取浏览器实例，统一 Playwright 和 CDP。
    mode: "playwright"（默认headless）或 "cdp"（有头）
    cdp_url: CDP 模式下的 WebSocket URL
    """
    if mode == "cdp":
        cdp_client = await _ensure_cdp(instance_key, cdp_url)
        return BrowserMode(None, cdp_client)
    else:
        page = await _ensure_playwright(instance_key)
        return BrowserMode(page, None)


# ── 工具入口 ──────────────────────────────────────


async def browser_execute(
    action: str,
    url: str = "",
    selector: str = "",
    text: str = "",
    path: str = "screenshot.png",
    session_id: str = "",
    mode: str = "playwright",
    cdp_url: str = "",
    key: str = "",
) -> str:
    """
    浏览器控制入口。

    mode=playwright（默认）：Playwright headless，服务端运行
    mode=cdp：通过 CDP 连接 Chrome（需提前启动 Chrome debug mode）

    CDP Chrome 启动命令：
      macOS: /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222 --no-first-run --no-default-browser-check
      Linux: google-chrome --remote-debugging-port=9222 --no-first-run --no-default-browser-check
    """
    instance_key = _get_instance_key(session_id)

    try:
        if action == "close":
            if mode == "cdp":
                closed = await _close_cdp_instance(instance_key)
            else:
                closed = await _close_playwright_instance(instance_key)
            return "浏览器已关闭" if closed else "浏览器未启动"

        if action == "close_all":
            await _close_all_playwright()
            # CDP 的也关闭
            with _cdp_lock:
                cdp_keys = list(_cdp_instances.keys())
            for key in cdp_keys:
                await _close_cdp_instance(key)
            return "所有浏览器实例已关闭"

        browser = await _get_browser_instance(instance_key, mode, cdp_url)

        if action == "navigate":
            return await browser.navigate(url)
        elif action == "click":
            return await browser.click(selector)
        elif action == "type":
            return await browser.type_text(selector, text)
        elif action == "screenshot":
            return await browser.screenshot(path)
        elif action == "get_text":
            return await browser.get_text(selector)
        elif action == "get_page_content":
            return await browser.get_page_content()
        elif action == "scroll":
            return await browser.scroll(selector)
        elif action == "keypress":
            return await browser.keypress(key)
        else:
            return f"未知操作: {action}"
    except Exception as e:
        logger.error(f"浏览器操作失败: {e}", exc_info=True)
        return f"浏览器操作失败: {e}"


# ── Schema ────────────────────────────────────────


def _check_browser() -> bool:
    """检查 Playwright 是否可用"""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _check_playwright_alias() -> bool:
    """兼容别名也沿用同一实现"""
    return _check_browser()


BROWSER_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "操作类型",
            "enum": ["navigate", "click", "type", "keypress", "screenshot", "get_text", "get_page_content", "scroll", "close", "close_all"],
        },
        "url": {
            "type": "string",
            "description": "navigate 时必填，要打开的网页 URL",
        },
        "selector": {
            "type": "string",
            "description": "click/type/get_text/scroll 时可选，CSS 选择器",
        },
        "text": {
            "type": "string",
            "description": "type 时必填，要输入的文字",
        },
        "key": {
            "type": "string",
            "description": "keypress 时必填，按键名称（Enter/Tab/Escape/ArrowUp/ArrowDown/...）",
        },
        "path": {
            "type": "string",
            "description": "screenshot 时可选，截图保存路径，默认 'screenshot.png'",
        },
        "session_id": {
            "type": "string",
            "description": "会话标识，同一会话共享浏览器实例",
        },
        "mode": {
            "type": "string",
            "description": "浏览器模式。playwright=默认headless（服务端运行）；cdp=有头模式（连接用户本地 Chrome DevTools，用户可见窗口）",
            "enum": ["playwright", "cdp"],
            "default": "playwright",
        },
        "cdp_url": {
            "type": "string",
            "description": "mode=cdp 时必填，Chrome DevTools WebSocket URL，如 ws://localhost:9222/json",
        },
    },
    "required": ["action"],
}


registry.register(
    name="browser",
    toolset="browser",
    description=(
        "【浏览器自动化】\n\n"
        "通用网页操作入口。普通网页任务默认优先使用这个工具。\n\n"
        "浏览器控制工具，支持两种模式：\n"
        "1. playwright（默认）：headless，服务端运行，后台自动化\n"
        "2. cdp：有头模式，连接用户本地 Chrome DevTools，用户可见真实窗口\n\n"
        "mode=playwright（默认）：无需用户干预，适用于后台任务\n"
        "mode=cdp：用户需提前启动 Chrome，再用 cdp_url 建立连接\n\n"
        "支持操作：\n"
        "  navigate(url)       — 打开 URL\n"
        "  click(selector)     — 点击元素\n"
        "  type(selector,text) — 向元素输入文字\n"
        "  keypress(key)       — 按键（Enter/Tab/Escape/ArrowUp 等）\n"
        "  screenshot(path)    — 截图保存到本地路径\n"
        "  get_text(selector)  — 获取元素文本\n"
        "  get_page_content()  — 获取页面全部文本\n"
        "  scroll(selector?)   — 滚动页面或滚动到元素\n"
        "  close / close_all   — 关闭浏览器"
    ),
    schema=BROWSER_SCHEMA,
    handler=browser_execute,
    check_fn=_check_browser,
    emoji="🌐",
    parallel_mode="never",
)

registry.register(
    name="playwright",
    toolset="browser",
    description=(
        "【Playwright 浏览器自动化别名】\n\n"
        "这是 browser 工具的兼容别名。"
        "当用户明确提到 Playwright 或要求“调用 playwright 工具”时，优先使用这个工具名直接调用。\n"
        "底层仍复用 browser 的统一实现。\n\n"
        "默认行为：mode=playwright，服务端 headless 自动化。\n"
        "如果任务明确要求使用用户本地可见 Chrome 或已有登录态，可传 mode=cdp 与 cdp_url。\n\n"
        "支持操作：\n"
        "  navigate(url)       — 打开 URL\n"
        "  click(selector)     — 点击元素\n"
        "  type(selector,text) — 向元素输入文字\n"
        "  keypress(key)       — 按键（Enter/Tab/Escape/ArrowUp 等）\n"
        "  screenshot(path)    — 截图保存到本地路径\n"
        "  get_text(selector)  — 获取元素文本\n"
        "  get_page_content()  — 获取页面全部文本\n"
        "  scroll(selector?)   — 滚动页面或滚动到元素\n"
        "  close / close_all   — 关闭浏览器"
    ),
    schema=BROWSER_SCHEMA,
    handler=browser_execute,
    check_fn=_check_playwright_alias,
    emoji="🎭",
    parallel_mode="never",
)
