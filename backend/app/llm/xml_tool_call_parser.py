"""
XML 工具调用兜底解析器 — 修复 W4-32 minimax 等 provider 幻觉 bug

背景 (2026-06-25 反馈):
  - 部分 LLM (典型如 MiniMax-Text-01) 不在 message.tool_calls 字段返回结构化调用
  - 而是把工具调用以 **XML 文本** 形式塞进 message.content, 例如:
      可以！我来帮你安装:
        <minimax:tool_call>pip install requests -q</minimax:tool_call>
  - 旧实现只读 message["tool_calls"], 拿不到 → 把整段当 assistant 文本回复,
    看起来像 LLM "只会说不会做"。

修法:
  1. 在 LLMResponse 解析层做兜底: 拿到 content 后先用本模块扫一遍 XML 标签
  2. 命中 → 转成 ToolCallResult 列表, content 清空/剥离
  3. 不命中 → 原文透传, 行为不变
  4. 上游 system prompt 也同步强化 (system_prompt.py), 显式禁止 XML 形式

支持的 XML 标签模式 (按 kind 区分):
  - <minimax:tool_call>...</minimax:tool_call>     (minimax 私有)
  - <tool_call>...</tool_call>                       (Qwen/通用)
  - <function_calls>...</function_calls>            (Hermes/Mistral)
  - <invoke name="...">...</invoke>                 (Kimi/Moonshot)
  - [TOOL_CALL]...[/TOOL_CALL]                       (Anthropic legacy)
  - <tool_use>...</tool_use>                        (Bedrock)

单条结构:
  - JSON 风格 (优先): {"name": "terminal", "arguments": {"command": "ls"}}
  - 属性式 (Kimi):      name=terminal command="ls -la"
"""
from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from app.llm.base import ToolCallResult


# ── 标签模式定义: (open_pattern, close_tag, kind) ─────────────────────
_TAG_PATTERNS: List[Tuple[str, str, str]] = [
    (r"<minimax:tool_call[^>]*>", "</minimax:tool_call>", "minimax"),
    (r"<tool_call>", "</tool_call>", "qwen"),
    (r"<function_calls[^>]*>", "</function_calls>", "hermes"),
    (r"<invoke\s+name=\"[^\"]+\"[^>]*>", "</invoke>", "kimi"),
    (r"\[TOOL_CALL\]", "[/TOOL_CALL]", "anthropic"),
    (r"<tool_use[^>]*>", "</tool_use>", "bedrock"),
]


# W4-46: 已知工具名 (跟 app.tools.registry 一致), LLM 直接用工具名当 tag
# 典型: <read_file>hello.html</read_file> / <terminal>pwd</terminal>
#       <write_file>path: foo.py\ncontent: ...</write_file>
_KNOWN_TOOL_NAMES = sorted({
    "read_file", "write_file", "terminal", "browser", "playwright",
    "glob", "grep", "ls", "search_files", "patch",
    "web_search", "web_extract", "load_skill", "skill_list", "skill_view",
    "ask", "delegate_task", "desktop", "adb",
})
_TOOL_TAG_RE = re.compile(
    r"<(" + "|".join(re.escape(n) for n in _KNOWN_TOOL_NAMES) + r")[^>]*>"
)


def _close_tag_for(name: str) -> str:
    return "</" + name + ">"


def _find_tool_tag_open(content):
    """W4-46: 找 <tool_name>...</tool_name> 形式, tool_name 是已知工具名.
    返回 (start, after_open, open_tag, tool_name) 或 None
    """
    m = _TOOL_TAG_RE.search(content)
    if not m:
        return None
    return m.start(), m.end(), m.group(0), m.group(1)


def _find_tool_tag_close(content, start, tool_name):
    """W4-46: 找 </tool_name> 起始位置, 找不到 -1"""
    pattern = "</" + re.escape(tool_name) + ">"
    m = re.search(pattern, content[start:])
    return start + m.start() if m else -1


def _parse_tool_tag_body(tool_name, body):
    """W4-46: 解析 <tool_name>body</tool_name> 的 body.
    启发式:
    - JSON: {"path": "x"} → 直接用
    - 多行 key: value:  按 _parse_kv_block 解析 (write_file 常见)
    - 单行 → 按工具名映射成 path / command / url / query 等
    """
    body = body.strip()
    if not body:
        return None
    # 路径 1: JSON
    if body.startswith("{") and body.endswith("}"):
        try:
            obj = json.loads(body)
            if isinstance(obj, dict) and obj.get("name"):
                return obj["name"], obj.get("arguments", {})
        except json.JSONDecodeError:
            pass
    # 路径 2: key: value 多行 (write_file 常见 path: / content:)
    if ":" in body and "\n" in body:
        kv = _parse_kv_block(body)
        if kv and len(kv) >= 1:
            return tool_name, kv
    # 路径 3: 单行 → 按工具名映射
    first_line = body.splitlines()[0].strip() if body.splitlines() else ""
    if tool_name == "read_file":
        return tool_name, {"path": first_line}
    if tool_name == "write_file":
        return tool_name, {"path": first_line, "content": body}
    if tool_name == "terminal":
        return tool_name, {"command": body}
    if tool_name in ("glob", "grep", "ls", "search_files"):
        return tool_name, {"pattern": first_line}
    if tool_name in ("web_search", "web_extract"):
        return tool_name, {"query": first_line, "url": first_line}
    if tool_name == "load_skill":
        return tool_name, {"name": first_line}
    if tool_name in ("skill_list", "skill_view"):
        return tool_name, {"name": first_line}
    if tool_name == "ask":
        return tool_name, {"question": body}
    if tool_name == "delegate_task":
        return tool_name, {"task": body}
    if tool_name in ("browser", "playwright", "desktop", "adb"):
        return tool_name, {"action": first_line}
    return tool_name, {"input": body}


_OPEN_RE = re.compile(
    "|".join(f"(?P<{kind}>{pat})" for pat, _, kind in _TAG_PATTERNS)
)


def _find_open(content: str) -> Optional[Tuple[int, int, str, str]]:
    """返回 (start, end, open_tag, kind) 或 None"""
    m = _OPEN_RE.search(content)
    if not m:
        return None
    for _, _, kind in _TAG_PATTERNS:
        if m.group(kind) is not None:
            return m.start(kind), m.end(kind), m.group(kind), kind
    return None


def _find_close(content: str, start: int, close_tag: str) -> int:
    """从 start 找 close_tag, 返回其起始位置; 找不到返回 -1

    W4-37 修: 找不到精确 close 时, 试 minimax 容错 (闭标签写错的常见情况,
    e.g. </minimax:_call> 少 "tool"). 通用 fallback 任意 </minimax:...> 闭标签.
    返回 close tag 的 **起始** 位置 (而不是结束), caller 切片时:
      inner = content[after_open : close_start]
      remaining = content[:start] + content[close_start + len(close_tag) :]
    """
    idx = content.find(close_tag, start)
    if idx != -1:
        return idx
    # W4-37 容错: minimax 闭标签写错时 (如 </minimax:_call>), 试任意 </minimax:...>
    if close_tag == "</minimax:tool_call>":
        import re as _re
        m = _re.search(r"</minimax:[^>]*>", content[start:])
        if m:
            return start + m.start()
    return -1


# ── 单条内容解析 ──────────────────────────────────────────────────────
_ATTR_RE = re.compile(
    r'(?P<key>[a-zA-Z_][a-zA-Z0-9_.\-]*)\s*=\s*'
    r'(?:"(?P<dq>[^"]*)"|\'(?P<sq>[^\']*)\'|(?P<bare>[^\s,;>]+))'
)

_ARG_KV_RE = re.compile(
    r'(?P<key>[a-zA-Z_][a-zA-Z0-9_.\-]*)\s*=\s*'
    r'(?:"(?P<dq>[^"]*)"|\'(?P<sq>[^\']*)\'|(?P<bare>[^\s,;]+))'
)




def _parse_kimi_open_tag(open_tag: str, inner: str) -> Optional[Tuple[str, dict]]:
    """Kimi 风格 <invoke name="x" arg1=v1 arg2="v2">body</invoke>

    工具名 + 参数都从 open tag 的 attrs 抽, body 当 fallback (整段 bash 命令时用)
    """
    # 1) name=
    m = re.search(r'name\s*=\s*"([^"]+)"', open_tag)
    name = m.group(1) if m else None
    # 2) 其他 attrs → args (排除 name)
    args: dict = {}
    for am in _ATTR_RE.finditer(open_tag):
        key = am.group("key")
        if key in ("name",):
            continue
        val = am.group("dq") or am.group("sq") or am.group("bare") or ""
        if val.lower() in ("true", "false"):
            val = val.lower() == "true"
        else:
            try:
                if "." in val:
                    val = float(val)
                else:
                    val = int(val)
            except ValueError:
                pass
        args[key] = val
    # 3) body 非空时追加 (Kimi 偶尔在 body 里塞 JSON)
    if inner.strip():
        body_args = _parse_inner(inner, name)
        if body_args:
            _, body_d = body_args
            args.update(body_d)
    if name is None:
        return None
    return name, args


def _parse_kv_block(body: str) -> dict:
    r"""解析 body 里的 `key: value` 行为 arguments dict (W4-36 改: value 跨行)

    minimax 嵌套子块 body 形如:
        path: hello.html
        content: <!DOCTYPE html>
        <html lang="zh-CN">
        <head>...
        </h1>
        </body>
        </html>

    v1 按行只取首行 value → content 被截到 `<!DOCTYPE html>`.
    v2: value 跨行, 直到下一行匹配 `^[a-zA-Z_]\w*:\s` 模式 (新 key) 或段尾.
    """
    args: dict = {}
    # key: 模式: 单词开头 + 冒号 + 空白
    key_re = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$")
    current_key: Optional[str] = None
    current_val: List[str] = []

    def _flush():
        nonlocal current_key, current_val
        if current_key is None:
            return
        val = "\n".join(current_val).strip() if current_val else ""
        if val:
            if val.lower() in ("true", "false"):
                val = val.lower() == "true"
            args[current_key] = val

    for line in body.splitlines():
        stripped = line.lstrip()
        km = key_re.match(stripped)
        # 判 key 条件: 1) 匹配 key: 模式, 2) 行首 (无缩进) 才是 key
        if km and not line[:len(line) - len(stripped)]:
            _flush()
            current_key = km.group(1)
            current_val = [km.group(2)] if km.group(2) else []
        else:
            # 续行
            if current_key is not None:
                current_val.append(line.rstrip())
    _flush()
    return args


def _parse_minimax_nested(inner: str) -> List[Tuple[str, dict]]:
    """W4-36 加: 解析 minimax 嵌套结构 (v2: 已知工具名白名单)

    inner 形如 (LLM 实际输出):
        <write_file>
        path: hello.html
        content: <!DOCTYPE html>...<h1>...</h1>...</html>
        </invoke>
        <terminal>
        ls hello.html
        </terminal>

    W4-32 parser 把整段当单条 tool_call, 启发式成 terminal "path: hello.html" -> 错.
    v1 实现按 `<...>` 切子块, 错把 HTML 标签 (<head> <title> <h1>) 当成 tool_name.
    v2 (W4-36): 用**已知工具名白名单**定位子块起始, body 不再按 `<` 切, 用 key: value 解析.
    闭标签错配 (<write_file>...</invoke>) 自然处理: body 吃到下一个已知工具名或 </minimax:tool_call>.
    """
    if not inner or not inner.strip():
        return []

    # 已知工具名白名单 (跟 ToolRegistry 同步, 加新工具时同步更新)
    _KNOWN_TOOLS = frozenset({
        "write_file", "read_file", "patch", "search_files", "ls", "glob",
        "terminal", "browser", "ask", "delegate_task", "skill_view",
        "load_skill", "desktop", "cdp", "mcp", "grep", "web_search",
        "web_fetch", "memory", "imagegen",
    })

    out: List[Tuple[str, dict]] = []
    open_re = re.compile(
        r"<(" + "|".join(re.escape(t) for t in _KNOWN_TOOLS) + r")>",
    )
    matches = list(open_re.finditer(inner))
    if not matches:
        return []

    for i, m in enumerate(matches):
        name = m.group(1)
        body_start = m.end()
        # body 终点: 下一个 <known_tool> 起始, 或 </minimax:tool_call>, 或段尾
        if i + 1 < len(matches):
            body_end = matches[i + 1].start()
        else:
            close = inner.find("</minimax:tool_call>", body_start)
            body_end = close if close != -1 else len(inner)
        body = inner[body_start:body_end].strip()
        # 去掉尾部错配闭标签
        body = re.sub(r"</\w+>\s*$", "", body).strip()
        if not body:
            continue
        # 解析 body: 优先 key: value 块
        args = _parse_kv_block(body)
        if not args:
            if name == "terminal":
                first_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
                args = {"command": first_line} if first_line else {}
            else:
                args = {"raw": body}
        out.append((name, args))
    return out


def _parse_inner(inner: str, fallback_name: Optional[str]) -> Optional[Tuple[str, dict]]:
    """把标签内部文本解析成 (tool_name, arguments)

    优先 JSON, 退路 Kimi 属性式, 最后启发式: 整段是 bash → 映射到 terminal
    """
    s = inner.strip()
    if not s:
        return None

    # 路径 1: JSON
    if s.startswith("{") and s.endswith("}"):
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            name = data.get("name") or data.get("tool_name") or data.get("function") or fallback_name
            if not name:
                return None
            args = data.get("arguments")
            if args is None:
                args = data.get("args") or data.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            if not isinstance(args, dict):
                args = {"value": args}
            return name, args
        return None

    # 路径 2: Kimi 属性式
    name = fallback_name
    args: dict = {}
    for m in _ARG_KV_RE.finditer(s):
        key = m.group("key")
        val = m.group("dq") or m.group("sq") or m.group("bare") or ""
        if key in ("name", "tool", "tool_name") and name is None:
            name = val
        else:
            if val.lower() in ("true", "false"):
                val = val.lower() == "true"
            else:
                try:
                    if "." in val:
                        val = float(val)
                    else:
                        val = int(val)
                except ValueError:
                    pass
            args[key] = val
    if name is None:
        first_line = next((ln.strip() for ln in s.splitlines() if ln.strip()), "")
        if not first_line:
            return None
        # 启发: 整行都是 shell 命令 → 映射到 terminal
        return "terminal", {"command": first_line}
    return name, args


# ── 主入口 ────────────────────────────────────────────────────────────
def parse_xml_tool_calls(content: str) -> Tuple[List[ToolCallResult], str]:
    """从 content 中抽取 XML 工具调用, 返回 (tool_calls, 清理后 content)

    解析失败的块不抛异常, 整段保留在 cleaned_content 里, 避免误伤。
    """
    if not content:
        return [], content
    # 快速过滤: 既没 < 也没 [ 的纯文本直接放行
    if "<" not in content and "[" not in content:
        return [], content

    out: List[ToolCallResult] = []
    remaining = content

    # 最多 16 次防呆, 避免病态输入死循环
    for _ in range(16):
        # W4-46: 优先识别 <tool_name>...</tool_name> 形式 (read_file / terminal / write_file)
        # 在 _find_open 之前 — 因为 <read_file> 跟已知 wrapper tag 冲突, 但内容是路径
        tool_hit = _find_tool_tag_open(remaining)
        if tool_hit:
            t_start, t_after_open, t_open_tag, t_tool_name = tool_hit
            t_close = _find_tool_tag_close(remaining, t_after_open, t_tool_name)
            if t_close != -1:
                t_body = remaining[t_after_open:t_close]
                t_parsed = _parse_tool_tag_body(t_tool_name, t_body)
                if t_parsed:
                    t_name, t_args = t_parsed
                    out.append(ToolCallResult(
                        tool_name=t_name,
                        arguments=t_args,
                        tool_call_id=f"xml_tool_{len(out)}",
                    ))
                    remaining = remaining[:t_start] + remaining[t_close + len(_close_tag_for(t_tool_name)):]
                    continue
        hit = _find_open(remaining)
        if not hit:
            break
        start, after_open, open_tag, kind = hit
        close_tag = next(c for _, c, k in _TAG_PATTERNS if k == kind)
        end_idx = _find_close(remaining, after_open, close_tag)
        if end_idx == -1:
            break

        inner = remaining[after_open:end_idx]
        # Kimi 风格: 工具名 + 参数都可能在 open tag 的 attrs 里, body 经常为空
        # Hermes 风格: function_calls 里直接嵌 <invoke ...>...</invoke>
        if kind == "kimi":
            parsed = _parse_kimi_open_tag(open_tag, inner)
            parsed_list = [parsed] if parsed else []
        elif kind == "minimax":
            # W4-36 三路 fallback 兼容 W4-32 老格式 + LLM 实际嵌套格式:
            # 1. 平展 JSON:  <minimax:tool_call>{"name": "x", ...}</minimax:tool_call>
            # 2. 平展 bash:  <minimax:tool_call>pip install requests -q</minimax:tool_call>
            #    (启发式: 无 < 标签, 整段当 terminal command)
            # 3. 嵌套子块:  <minimax:tool_call><write_file>...</write_file>...</minimax:tool_call>
            inner_stripped = inner.strip()
            if inner_stripped.startswith("{"):
                # 路径 1: 平展 JSON
                flat = _parse_inner(inner, None)
                parsed_list = [flat] if flat else []
            elif "<" not in inner_stripped:
                # 路径 2: 平展 bash → terminal
                first_line = next((ln.strip() for ln in inner_stripped.splitlines() if ln.strip()), "")
                parsed_list = [("terminal", {"command": first_line})] if first_line else []
            else:
                # 路径 3: 嵌套子块 (W4-36 新支持)
                parsed_list = _parse_minimax_nested(inner)
        else:
            parsed = _parse_inner(inner, None)
            parsed_list = [parsed] if parsed else []
        remaining = remaining[:start] + remaining[end_idx + len(close_tag):]
        if not parsed_list:
            continue
        for name, args in parsed_list:
            out.append(ToolCallResult(
                tool_name=name,
                arguments=args,
                tool_call_id=f"xml_{kind}_{len(out)}",
            ))

    return out, remaining


def has_xml_tool_call(content: str) -> bool:
    """快速检测: 文本里是否含已知的工具调用 XML 标签 (用于日志/告警)

    W4-46: 同时检测 <tool_name>...</tool_name> 形式
    """
    if not content:
        return False
    if "<" not in content and "[" not in content:
        return False
    if _OPEN_RE.search(content) is not None:
        return True
    if _TOOL_TAG_RE.search(content) is not None:
        return True
    return False
