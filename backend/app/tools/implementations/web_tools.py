"""
web_tools - 网页搜索与内容提取工具

提供 web_search（网页搜索）和 web_extract（网页内容提取）能力。
"""

import logging
import re
from typing import Optional

import httpx

from app.tools.registry import registry

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 50_000


def _check_web() -> bool:
    """Web 工具总是可用"""
    return True


# ═══════════════════════════════════════════════════════════
# web_search — 借助 DuckDuckGo 搜索
# ═══════════════════════════════════════════════════════════

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词",
        },
        "max_results": {
            "type": "integer",
            "description": "最大返回结果数（默认 5）",
            "default": 5,
        },
    },
    "required": ["query"],
}

# Use duckduckgo's lite version for simple searches
_DDG_URL = "https://html.duckduckgo.com/html/"


async def web_search_tool(query: str, max_results: int = 5) -> str:
    if not query.strip():
        return "搜索关键词不能为空"

    max_results = min(max_results, 20)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _DDG_URL,
                data={"q": query},
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
                follow_redirects=True,
            )
            resp.raise_for_status()
    except httpx.TimeoutException:
        return "搜索请求超时"
    except httpx.HTTPStatusError as e:
        return f"搜索服务暂时不可用（HTTP {e.response.status_code}）"
    except Exception as e:
        return f"搜索失败: {e}"

    # 从 HTML 中提取结果
    html = resp.text
    results = _parse_ddg_results(html)

    if not results:
        return f"未找到 '{query}' 的相关结果"

    lines = [f"🔎 搜索结果: {query}\n"]
    for i, (title, url, snippet) in enumerate(results[:max_results], 1):
        lines.append(f"{i}. {title}")
        lines.append(f"   {url}")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines).strip()


def _parse_ddg_results(html: str):
    """解析 DuckDuckGo HTML 搜索结果"""
    results = []
    # 查找结果块: <a rel="nofollow" class="result__a" href="...">title</a>
    # 以及 <a class="result__snippet">snippet</a>
    pattern = re.compile(
        r'<a\s+rel="nofollow"\s+class="result__a"\s+href="(.*?)".*?>(.*?)</a>.*?'
        r'<a\s+class="result__snippet".*?>(.*?)</a>',
        re.DOTALL,
    )
    for match in pattern.finditer(html):
        url = match.group(1)
        title = re.sub(r"<.*?>", "", match.group(2)).strip()
        snippet = re.sub(r"<.*?>", "", match.group(3)).strip()
        if title and url:
            results.append((title, url, snippet))
    return results


# ═══════════════════════════════════════════════════════════
# web_extract — 获取网页文本内容
# ═══════════════════════════════════════════════════════════

WEB_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "要提取内容的网页 URL",
        },
        "max_chars": {
            "type": "integer",
            "description": f"最大返回字符数（默认 {_MAX_CONTENT_CHARS}）",
            "default": _MAX_CONTENT_CHARS,
        },
    },
    "required": ["url"],
}


async def web_extract_tool(url: str, max_chars: int = _MAX_CONTENT_CHARS) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    max_chars = min(max_chars, _MAX_CONTENT_CHARS)

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
            )
            resp.raise_for_status()
    except httpx.TimeoutException:
        return f"访问超时: {url}"
    except httpx.HTTPStatusError as e:
        return f"HTTP 错误 {e.response.status_code}: {url}"
    except Exception as e:
        return f"访问失败: {e}"

    # 提取纯文本
    text = _html_to_text(resp.text)

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...（内容过长，已截断至 {max_chars} 字符）"

    return f"📄 {url}\n\n{text}"


def _html_to_text(html: str) -> str:
    """简易 HTML 转纯文本"""
    # 移除 script/style
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 移除 HTML 标签
    text = re.sub(r"<[^>]+>", "", html)
    # 解码 HTML 实体
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    # 合并空白
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


# ═══════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════

registry.register(
    name="web_search",
    toolset="web",
    description="搜索互联网。输入关键词，返回标题、链接和摘要。适合查找最新信息、文档、新闻等。",
    schema=WEB_SEARCH_SCHEMA,
    handler=web_search_tool,
    check_fn=_check_web,
    emoji="🔍",
    parallel_mode="safe",
)

registry.register(
    name="web_extract",
    toolset="web",
    description="获取网页内容并提取纯文本。适合查看文章、文档页面等。",
    schema=WEB_EXTRACT_SCHEMA,
    handler=web_extract_tool,
    check_fn=_check_web,
    emoji="📄",
    max_result_size_chars=_MAX_CONTENT_CHARS,
    parallel_mode="safe",
)
