#!/usr/bin/env python3
"""
Playwright MCP 服务器 - 符合 Model Context Protocol 标准
暴露浏览器自动化工具能力
"""
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, Browser, Page

# 全局浏览器实例
_playwright = None
_browser = None
_pages: Dict[str, Page] = {}  # instance_key -> Page

async def _ensure_browser():
    global _playwright, _browser
    if not _playwright:
        _playwright = await async_playwright().start()
    if not _browser:
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
    return _browser

async def handle_navigate(params: Dict[str, Any]) -> Dict[str, Any]:
    """打开网页"""
    url = params["url"]
    instance_key = params.get("instance_key", "default")
    browser = await _ensure_browser()
    
    if instance_key in _pages:
        page = _pages[instance_key]
    else:
        page = await browser.new_page()
        _pages[instance_key] = page
    
    await page.goto(url, wait_until="domcontentloaded")
    title = await page.title()
    return {"success": True, "title": title, "url": page.url}

async def handle_screenshot(params: Dict[str, Any]) -> Dict[str, Any]:
    """截图，返回base64编码的图片"""
    instance_key = params.get("instance_key", "default")
    full_page = params.get("full_page", False)
    
    if instance_key not in _pages:
        return {"success": False, "error": "浏览器实例未启动，请先调用 navigate 打开网页"}
    
    page = _pages[instance_key]
    screenshot = await page.screenshot(full_page=full_page, type="png", encoding="base64")
    return {"success": True, "screenshot_base64": screenshot}

async def handle_click(params: Dict[str, Any]) -> Dict[str, Any]:
    """点击元素"""
    instance_key = params.get("instance_key", "default")
    selector = params["selector"]
    force = params.get("force", False)
    
    if instance_key not in _pages:
        return {"success": False, "error": "浏览器实例未启动，请先调用 navigate 打开网页"}
    
    page = _pages[instance_key]
    await page.click(selector, force=force)
    return {"success": True}

async def handle_fill(params: Dict[str, Any]) -> Dict[str, Any]:
    """填写表单"""
    instance_key = params.get("instance_key", "default")
    selector = params["selector"]
    value = params["value"]
    
    if instance_key not in _pages:
        return {"success": False, "error": "浏览器实例未启动，请先调用 navigate 打开网页"}
    
    page = _pages[instance_key]
    await page.fill(selector, value)
    return {"success": True}

async def handle_text(params: Dict[str, Any]) -> Dict[str, Any]:
    """获取页面纯文本内容"""
    instance_key = params.get("instance_key", "default")
    
    if instance_key not in _pages:
        return {"success": False, "error": "浏览器实例未启动，请先调用 navigate 打开网页"}
    
    page = _pages[instance_key]
    content = await page.text_content("body") or ""
    return {"success": True, "content": content[:5000]}  # 限制返回长度

async def handle_eval(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行JS脚本"""
    instance_key = params.get("instance_key", "default")
    script = params["script"]
    
    if instance_key not in _pages:
        return {"success": False, "error": "浏览器实例未启动，请先调用 navigate 打开网页"}
    
    page = _pages[instance_key]
    result = await page.evaluate(script)
    return {"success": True, "result": str(result)}

async def handle_close(params: Dict[str, Any]) -> Dict[str, Any]:
    """关闭浏览器实例"""
    instance_key = params.get("instance_key", "default")
    close_all = params.get("close_all", False)
    
    if close_all:
        for page in _pages.values():
            await page.close()
        _pages.clear()
        if _browser:
            await _browser.close()
            global _browser
            _browser = None
        if _playwright:
            await _playwright.stop()
            global _playwright
            _playwright = None
        return {"success": True, "message": "所有浏览器实例已关闭"}
    
    if instance_key in _pages:
        await _pages[instance_key].close()
        del _pages[instance_key]
        return {"success": True, "message": "浏览器实例已关闭"}
    
    return {"success": False, "error": "浏览器实例不存在"}

# MCP 工具定义
_TOOLS = [
    {
        "name": "browser_navigate",
        "description": "打开指定网页，需要提供完整URL",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要打开的网页URL，必须是http/https开头"},
                "instance_key": {"type": "string", "description": "浏览器实例标识，用于多会话隔离，默认default"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_screenshot",
        "description": "对当前页面截图，返回PNG图片的base64编码",
        "parameters": {
            "type": "object",
            "properties": {
                "instance_key": {"type": "string", "description": "浏览器实例标识，默认default"},
                "full_page": {"type": "boolean", "description": "是否截取完整长页面，默认false"}
            }
        }
    },
    {
        "name": "browser_click",
        "description": "点击页面上的元素",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS选择器，指定要点击的元素"},
                "instance_key": {"type": "string", "description": "浏览器实例标识，默认default"},
                "force": {"type": "boolean", "description": "是否强制点击，忽略元素可见性检查，默认false"}
            },
            "required": ["selector"]
        }
    },
    {
        "name": "browser_fill",
        "description": "填写表单输入框",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS选择器，指定要填写的输入框"},
                "value": {"type": "string", "description": "要填写的内容"},
                "instance_key": {"type": "string", "description": "浏览器实例标识，默认default"}
            },
            "required": ["selector", "value"]
        }
    },
    {
        "name": "browser_text",
        "description": "获取当前页面的纯文本内容（最多返回5000字符）",
        "parameters": {
            "type": "object",
            "properties": {
                "instance_key": {"type": "string", "description": "浏览器实例标识，默认default"}
            }
        }
    },
    {
        "name": "browser_eval",
        "description": "在当前页面执行JavaScript脚本",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "要执行的JS代码"},
                "instance_key": {"type": "string", "description": "浏览器实例标识，默认default"}
            },
            "required": ["script"]
        }
    },
    {
        "name": "browser_close",
        "description": "关闭浏览器实例",
        "parameters": {
            "type": "object",
            "properties": {
                "instance_key": {"type": "string", "description": "要关闭的浏览器实例标识，默认default"},
                "close_all": {"type": "boolean", "description": "是否关闭所有实例并释放所有资源，默认false"}
            }
        }
    }
]

# 处理函数映射
_HANDLERS = {
    "browser_navigate": handle_navigate,
    "browser_screenshot": handle_screenshot,
    "browser_click": handle_click,
    "browser_fill": handle_fill,
    "browser_text": handle_text,
    "browser_eval": handle_eval,
    "browser_close": handle_close
}

async def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """处理MCP JSON-RPC请求"""
    method = request.get("method")
    params = request.get("params", {})
    request_id = request.get("id")
    
    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "server": {
                        "name": "playwright-mcp",
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {}
                    }
                }
            }
        
        elif method == "list_tools":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": _TOOLS
                }
            }
        
        elif method == "call_tool":
            tool_name = params.get("name")
            tool_params = params.get("arguments", {})
            
            if tool_name not in _HANDLERS:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"未知工具: {tool_name}"}
                }
            
            result = await _HANDLERS[tool_name](tool_params)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False)
                        }
                    ]
                }
            }
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"未知方法: {method}"}
            }
    
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": f"执行失败: {str(e)}"}
        }

async def main():
    """MCP服务器主循环，通过stdin/stdout通信"""
    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            
            line = line.strip()
            if not line:
                continue
            
            request = json.loads(line)
            response = await handle_request(request)
            print(json.dumps(response, ensure_ascii=False), flush=True)
        
        except Exception as e:
            print(json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"请求解析失败: {str(e)}"}
            }), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
