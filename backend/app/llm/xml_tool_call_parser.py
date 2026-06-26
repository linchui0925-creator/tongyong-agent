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

    返回 close tag 的 **起始** 位置 (而不是结束), caller 切片时:
      inner = content[after_open : close_start]
      remaining = content[:start] + content[close_start + len(close_tag) :]
    """
    idx = content.find(close_tag, start)
    if idx == -1:
        return -1
    return idx


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
        else:
            parsed = _parse_inner(inner, None)
        remaining = remaining[:start] + remaining[end_idx + len(close_tag):]
        if parsed is None:
            continue
        name, args = parsed
        out.append(ToolCallResult(
            tool_name=name,
            arguments=args,
            tool_call_id=f"xml_{kind}_{len(out)}",
        ))

    return out, remaining


def has_xml_tool_call(content: str) -> bool:
    """快速检测: 文本里是否含已知的工具调用 XML 标签 (用于日志/告警)"""
    if not content:
        return False
    if "<" not in content and "[" not in content:
        return False
    return _OPEN_RE.search(content) is not None
