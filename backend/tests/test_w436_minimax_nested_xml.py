"""W4-36: 扩展 xml_tool_call_parser 支持 minimax 嵌套结构

LLM (典型 MiniMax-Text-01) 实际输出格式 (从 backend log 抓的真实片段):
    <minimax:tool_call>
    <write_file>
    path: hello.html
    content: <!DOCTYPE html>
    <html lang="zh-CN">
    <head>...<title>路明非の奇幻世界</title></head>
    <body><h1>路明非の奇幻世界</h1></body>
    </html>
    </invoke>   <-- 错配闭标签 (minimax 偶尔写错)
    <terminal>
    ls hello.html
    </terminal>
    </minimax:tool_call>

W4-32 parser 失败原因:
  1. 整段当单条 tool_call → 启发式成 terminal "path: hello.html" (错)
  2. 按 <name> 切子块 → 错把 HTML 标签 (<head> <title> <h1>) 当 tool_name
  3. key: value 按行只取首行 value → content 多行被截到 `<!DOCTYPE html>`

W4-36 修法:
  1. kind == "minimax" 时调 _parse_minimax_nested: 按已知工具名白名单定位子块
  2. body 不再按 < 切, 用 key: value 跨行解析 (新 key 才结束当前 value)
  3. 闭标签错配容忍: body 一直吃到下一个已知工具名或 </minimax:tool_call>
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 1. 嵌套 + 错配闭标签 (LLM 实际输出) ─────────────────────

def test_minimax_nested_write_file_with_html_content():
    """minimax 嵌套 + write_file body 含完整 HTML 多行 + 错配闭标签 </invoke>"""
    from app.llm.xml_tool_call_parser import parse_xml_tool_calls

    raw = """<minimax:tool_call>
<write_file>
path: hello.html
content: <!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>路明非の奇幻世界</title>
</head>
<body>
    <h1>路明非の奇幻世界</h1>
</body>
</html>
</invoke>
<terminal>
ls hello.html
</terminal>
</minimax:tool_call>"""

    calls, cleaned = parse_xml_tool_calls(raw)

    # 1. 抓到 2 个 tool_call
    assert len(calls) == 2, f"expected 2 calls, got {len(calls)}: {[(c.tool_name, c.arguments) for c in calls]}"

    # 2. 第一个是 write_file
    wf = calls[0]
    assert wf.tool_name == "write_file"
    assert wf.arguments["path"] == "hello.html"

    # 3. content 跨行完整 (含 <!DOCTYPE> <h1> 路明非 </html>)
    content = wf.arguments["content"]
    assert "<!DOCTYPE html>" in content
    assert "<html lang=\"zh-CN\">" in content
    assert "<title>路明非の奇幻世界</title>" in content
    assert "<h1>路明非の奇幻世界</h1>" in content
    assert "</html>" in content
    # 跨行保留 (不是被压平)
    assert "\n" in content, f"content not multi-line: {content!r}"

    # 4. 第二个是 terminal
    assert calls[1].tool_name == "terminal"
    assert "ls hello.html" in calls[1].arguments["command"]


# ── 2. 单个 tool_call (write_file only, no nesting) ──────────

def test_minimax_single_write_file():
    """单 write_file 块"""
    from app.llm.xml_tool_call_parser import parse_xml_tool_calls

    raw = """<minimax:tool_call>
<write_file>
path: index.html
content: <p>hi</p>
</invoke>
</minimax:tool_call>"""

    calls, _ = parse_xml_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"] == "index.html"
    assert "<p>hi</p>" in calls[0].arguments["content"]


# ── 3. 仅 terminal, 短 body ───────────────────────────────

def test_minimax_terminal_short_body():
    """单 terminal 块 + 错配闭标签 (</invoke>)"""
    from app.llm.xml_tool_call_parser import parse_xml_tool_calls

    raw = """<minimax:tool_call>
<terminal>
pwd
</invoke>
</minimax:tool_call>"""

    calls, _ = parse_xml_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].tool_name == "terminal"
    assert calls[0].arguments["command"] == "pwd"


# ── 4. 非 minimax 格式 (旧 W4-32 path) 仍工作 ──────────────

def test_w432_qwen_style_still_works():
    """Qwen 风格 <tool_call>...</tool_call> 仍走 W4-32 路径"""
    from app.llm.xml_tool_call_parser import parse_xml_tool_calls

    raw = """<tool_call>
{"name": "terminal", "arguments": {"command": "ls"}}
</tool_call>"""

    calls, _ = parse_xml_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].tool_name == "terminal"
    assert calls[0].arguments["command"] == "ls"


def test_w432_kimi_style_still_works():
    """Kimi 风格 <invoke name="..." arg=val> 仍走 W4-32 路径"""
    from app.llm.xml_tool_call_parser import parse_xml_tool_calls

    raw = """<invoke name="terminal" command="ls -la"></invoke>"""

    calls, _ = parse_xml_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].tool_name == "terminal"
    # Kimi attribute 风格: command="ls -la" 会被解析到 args
    assert calls[0].arguments.get("command") == "ls -la"


# ── 5. 普通文本 (无 XML 标签) 不被误抓 ───────────────────

def test_plain_text_returns_empty():
    from app.llm.xml_tool_call_parser import parse_xml_tool_calls

    raw = "你好世界, 我不会调用工具, 这是普通文本"
    calls, cleaned = parse_xml_tool_calls(raw)
    assert calls == []
    assert cleaned == raw


# ── 6. content 含 `key: value` 字符串但不是真 key ──────────

def test_html_content_with_colon_in_attrs():
    """HTML body 里有 `Content-Type: text/html` 这种真 key:value 不会被误当 tool args"""
    from app.llm.xml_tool_call_parser import parse_xml_tool_calls

    # 模拟 write_file content 里有 Content-Type 这种
    raw = """<minimax:tool_call>
<write_file>
path: style.css
content: /* comment */
body { Content-Type: text/html; }
</invoke>
</minimax:tool_call>"""

    calls, _ = parse_xml_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"] == "style.css"
    # content 含完整 CSS
    assert "body { Content-Type: text/html; }" in calls[0].arguments["content"]


# ── 7. 真实 end-to-end: MiniMaxLLM._parse_response 解析嵌套 ──

def test_minimax_parse_response_returns_tool_calls():
    """OpenAI 风格响应 + content 是嵌套 XML → MiniMaxLLM 解析出 tool_calls"""
    from app.llm.openai_compatible import MiniMaxLLM
    from app.llm.base import LLMResponse

    raw_content = """<minimax:tool_call>
<write_file>
path: demo.html
content: <h1>hi</h1>
</invoke>
</minimax:tool_call>"""

    api_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": raw_content,
                # 注意: 没有 tool_calls 字段, 模拟 minimax 不返回结构化调用
            }
        }]
    }

    llm = MiniMaxLLM(api_key="test")
    resp = llm._parse_response(api_response)

    assert isinstance(resp, LLMResponse)
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].tool_name == "write_file"
    assert resp.tool_calls[0].arguments["path"] == "demo.html"
    assert "<h1>hi</h1>" in resp.tool_calls[0].arguments["content"]
