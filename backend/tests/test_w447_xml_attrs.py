"""W4-47: XML 属性风格 <key>value</key> 解析 (用户实测样本)

W4-46 漏了 GLM-5.2 / deepseek-v4-flash 实际输出:
    文本说明 + <write_file><NL><path>...</path><NL><content>...</content><NL></write_file>
旧 parser 把 <path>hello.html</path> 整段当 path value,
结果 path="<path>hello.html</path>" -> 工具失败 -> agent 装执行.

修法: 加 _parse_xml_attrs 提取 <key>...</key>, 在 _parse_tool_tag_body 路径 2 优先用.
"""
import pytest
from app.llm.xml_tool_call_parser import parse_xml_tool_calls, _parse_xml_attrs


NL = chr(10)


def test_user_write_file_hello_html():
    """W4-47: 用户实测 <write_file><path>hello.html</path><content>...</content></write_file>"""
    s = (
        "抱歉让你等了!直接给你写一个路明非主题的奇幻世界网页。" + NL + NL
        + "<write_file>" + NL
        + "<path>hello.html</path>" + NL
        + "<content><!DOCTYPE html>" + NL
        + "<html lang=zh-CN>" + NL
        + "<head><title>路明非の奇幻世界</title></head>" + NL
        + "<body><h1>路明非の奇幻世界</h1></body>" + NL
        + "</html>" + NL
        + "</content>" + NL
        + "</write_file>"
    )
    calls, cleaned = parse_xml_tool_calls(s)
    assert len(calls) == 1
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"] == "hello.html"
    assert "路明非の奇幻世界" in calls[0].arguments["content"]
    assert "写一个路明非主题" in cleaned
    assert "<write_file>" not in cleaned


def test_user_read_file_hello_html():
    """W4-47: <read_file><path>hello.html</path></read_file>"""
    s = (
        "让我先看看 `hello.html` 的实际内容。" + NL + NL
        + "<read_file>" + NL
        + "<path>hello.html</path>" + NL
        + "</read_file>"
    )
    calls, cleaned = parse_xml_tool_calls(s)
    assert len(calls) == 1
    assert calls[0].tool_name == "read_file"
    assert calls[0].arguments == {"path": "hello.html"}
    assert "让我先看看" in cleaned
    assert "<read_file>" not in cleaned


def test_user_skill_view_frontend():
    """W4-47: <skill_view><name>frontend-design</name></skill_view>"""
    s = (
        "好的,让我先加载前端设计技能,给你写一个高质量的页面。" + NL + NL
        + "<skill_view>" + NL
        + "<name>frontend-design</name>" + NL
        + "</skill_view>"
    )
    calls, cleaned = parse_xml_tool_calls(s)
    assert len(calls) == 1
    assert calls[0].tool_name == "skill_view"
    assert calls[0].arguments == {"name": "frontend-design"}


def test_user_write_simple_html():
    """W4-47: 用户 simple.html 样本"""
    s = (
        "好的,我在 `simple.html` 中添加一个可点击的链接。" + NL + NL
        + "<write_file>" + NL
        + "<path>simple.html</path>" + NL
        + "<content><!DOCTYPE html><html><body><h1>你好,世界</h1>"
        + '<p><a href="https://example.com">点击打开示例链接</a></p>'
        + "</body></html>" + NL
        + "</content>" + NL
        + "</write_file>"
    )
    calls, _ = parse_xml_tool_calls(s)
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"] == "simple.html"
    assert "https://example.com" in calls[0].arguments["content"]


def test_multi_tool_mixed_in_text():
    """W4-47: 一段 content 多个 tool call"""
    s = (
        "先看看文件。" + NL + NL
        + "<read_file>" + NL
        + "<path>hello.html</path>" + NL
        + "</read_file>" + NL + NL
        + "再写一个新的。" + NL + NL
        + "<write_file>" + NL
        + "<path>new.html</path>" + NL
        + "<content><h1>New</h1>" + NL
        + "</content>" + NL
        + "</write_file>"
    )
    calls, cleaned = parse_xml_tool_calls(s)
    assert len(calls) == 2
    assert calls[0].tool_name == "read_file"
    assert calls[0].arguments["path"] == "hello.html"
    assert calls[1].tool_name == "write_file"
    assert calls[1].arguments["path"] == "new.html"
    assert "先看看" in cleaned
    assert "再写一个" in cleaned


def test_xml_attrs_excludes_known_tool_names():
    """已知工具名不能当 key (避免误把 wrapper 当 attribute)"""
    args = _parse_xml_attrs("<path>foo.html</path>")
    assert args == {"path": "foo.html"}


def test_xml_attrs_multiline_content():
    """content 跨多行也能正确解析"""
    s = (
        "<write_file>" + NL
        + "<path>test.html</path>" + NL
        + "<content>" + NL
        + "<!DOCTYPE html>" + NL
        + "<html>" + NL
        + "<body><h1>Hello</h1></body>" + NL
        + "</html>" + NL
        + "</content>" + NL
        + "</write_file>"
    )
    calls, _ = parse_xml_tool_calls(s)
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"] == "test.html"
    assert "<!DOCTYPE html>" in calls[0].arguments["content"]
    assert "<h1>Hello</h1>" in calls[0].arguments["content"]


def test_backward_kv_style():
    """老 path: / content: kv 格式仍能工作"""
    s = "<write_file>path: foo.py\ncontent: print(1)\n</write_file>"
    calls, _ = parse_xml_tool_calls(s)
    assert calls[0].arguments["path"] == "foo.py"
    assert calls[0].arguments["content"] == "print(1)"


def test_backward_kv_style_with_html_tag_content():
    """老 kv 格式里的 HTML 标签不能被 XML attrs 误当参数。"""
    s = (
        "<write_file>\n"
        "path: /tmp/hello.html\n"
        "content: <h1>路明非の奇幻世界</h1>\n"
        "</write_file>"
    )
    calls, _ = parse_xml_tool_calls(s)
    assert calls[0].arguments["path"] == "/tmp/hello.html"
    assert calls[0].arguments["content"] == "<h1>路明非の奇幻世界</h1>"


def test_backward_single_line():
    """单行 <read_file>hello.html</read_file> 仍能工作"""
    s = "<read_file>hello.html</read_file>"
    calls, _ = parse_xml_tool_calls(s)
    assert calls[0].arguments == {"path": "hello.html"}


def test_backward_minimax_wrapper():
    """老 minimax 风格 wrapper 不受影响"""
    s = (
        "<minimax:tool_call>" + NL
        + "<terminal>ls -la</terminal>" + NL
        + "</minimax:tool_call>"
    )
    calls, _ = parse_xml_tool_calls(s)
    assert len(calls) == 1
    assert calls[0].tool_name == "terminal"
    assert "ls -la" in calls[0].arguments["command"]


def test_unclosed_tool_call_function_expression():
    """W4-48: TongYong 实测 <tool_call>terminal(command="...") 无闭合标签。"""
    s = (
        "先看项目结构。"
        "<tool_call>terminal(command=\"find . -maxdepth 3 -name 'package.json' "
        "-not -path '*/node_modules/*' | head -5\")"
    )
    calls, cleaned = parse_xml_tool_calls(s)
    assert len(calls) == 1
    assert calls[0].tool_name == "terminal"
    assert "find . -maxdepth 3" in calls[0].arguments["command"]
    assert "<tool_call>" not in cleaned
    assert "先看项目结构" in cleaned


def test_unclosed_tool_call_arg_key_value_write_file_with_tsx():
    """W4-48: TongYong 实测 <tool_call>write_file + arg_key/arg_value 大段 TSX。"""
    tsx = (
        "import React, { useRef } from 'react';" + NL + NL
        + "export function GestureParticlesPanel() {" + NL
        + "  return (" + NL
        + "    <section className=\"gesture-shell\">" + NL
        + "      <canvas ref={useRef<HTMLCanvasElement>(null)} />" + NL
        + "      <button aria-label=\"pinch mode\">Pinch</button>" + NL
        + "    </section>" + NL
        + "  );" + NL
        + "}" + NL
    )
    s = (
        "我会直接写入组件文件。" + NL
        + "<tool_call>write_file" + NL
        + "<arg_key>path</arg_key>" + NL
        + "<arg_value>/Users/linc/Documents/tongyong-agent/frontend/src/components/GestureParticles/GestureParticlesPanel.tsx</arg_value>" + NL
        + "<arg_key>content</arg_key>" + NL
        + "<arg_value>" + tsx + "</arg_value>"
    )
    calls, cleaned = parse_xml_tool_calls(s)
    assert len(calls) == 1
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"].endswith("GestureParticlesPanel.tsx")
    assert "<canvas ref={useRef<HTMLCanvasElement>(null)} />" in calls[0].arguments["content"]
    assert "<section className=\"gesture-shell\">" in calls[0].arguments["content"]
    assert "<tool_call>" not in cleaned
    assert "我会直接写入组件文件" in cleaned


def test_tool_call_arg_key_value_with_closing_tag_and_following_text():
    """W4-48: arg_key/arg_value 格式如果有闭合标签, 只剥离工具块并保留后续文本。"""
    s = (
        "执行写入:" + NL
        + "<tool_call>write_file" + NL
        + "<arg_key>path</arg_key><arg_value>frontend/src/demo.tsx</arg_value>" + NL
        + "<arg_key>content</arg_key><arg_value><div data-mode=\"circle\">OK</div></arg_value>" + NL
        + "</tool_call>" + NL
        + "然后我会运行 npm build。"
    )
    calls, cleaned = parse_xml_tool_calls(s)
    assert len(calls) == 1
    assert calls[0].arguments == {
        "path": "frontend/src/demo.tsx",
        "content": '<div data-mode="circle">OK</div>',
    }
    assert "<tool_call>" not in cleaned
    assert "执行写入" in cleaned
    assert "然后我会运行 npm build" in cleaned


def test_tool_call_arg_key_value_unclosed_final_content():
    """W4-48: 大段 content 被截断、缺 </arg_value> 时仍保留 path+content。"""
    s = (
        "<tool_call>write_file" + NL
        + "<arg_key>path</arg_key><arg_value>frontend/src/GestureParticles/gestureRecognizer.ts</arg_value>" + NL
        + "<arg_key>content</arg_key><arg_value>export const x = '<canvas>'" + NL
        + "export const y = 2"
    )
    calls, cleaned = parse_xml_tool_calls(s)
    assert len(calls) == 1
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"].endswith("gestureRecognizer.ts")
    assert "export const x = '<canvas>'" in calls[0].arguments["content"]
    assert "export const y = 2" in calls[0].arguments["content"]
    assert cleaned == ""


def test_tool_call_arg_key_value_write_file_missing_required_args_is_not_emitted():
    """W4-48: 缺 path/content 的 write_file 不应变成无效工具调用。"""
    s = "<tool_call>write_file<arg_key>content</arg_key><arg_value>only content</arg_value>"
    calls, cleaned = parse_xml_tool_calls(s)
    assert calls == []
    assert "<tool_call>write_file" in cleaned
