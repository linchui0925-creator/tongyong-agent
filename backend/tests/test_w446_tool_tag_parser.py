"""W4-46: <tool_name>...</tool_name> 格式 XML 工具调用解析"""
import pytest
from app.llm.xml_tool_call_parser import parse_xml_tool_calls, has_xml_tool_call


def test_read_file_bare():
    """用户实测: <read_file> hello.html </read_file>"""
    calls, cleaned = parse_xml_tool_calls("让我先看看内容。\n<read_file> hello.html </read_file>")
    assert len(calls) == 1
    assert calls[0].tool_name == "read_file"
    assert calls[0].arguments == {"path": "hello.html"}
    assert "read_file" not in cleaned
    assert "让我先看看" in cleaned


def test_read_file_no_spaces():
    calls, _ = parse_xml_tool_calls("<read_file>hello.html</read_file>")
    assert calls[0].tool_name == "read_file"
    assert calls[0].arguments == {"path": "hello.html"}


def test_read_file_multiline():
    calls, _ = parse_xml_tool_calls("<read_file>\nhello.html\n</read_file>")
    assert calls[0].tool_name == "read_file"
    assert calls[0].arguments == {"path": "hello.html"}


def test_terminal_single_command():
    calls, _ = parse_xml_tool_calls("<terminal>pwd && ls</terminal>")
    assert calls[0].tool_name == "terminal"
    assert calls[0].arguments == {"command": "pwd && ls"}


def test_terminal_multiline():
    calls, _ = parse_xml_tool_calls("<terminal>cd /tmp\nls -la</terminal>")
    assert calls[0].tool_name == "terminal"
    assert "cd /tmp" in calls[0].arguments["command"]


def test_write_file_kv():
    calls, _ = parse_xml_tool_calls("<write_file>path: foo.py\ncontent: print(1)\n</write_file>")
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"] == "foo.py"
    assert calls[0].arguments["content"] == "print(1)"


def test_write_file_no_kv():
    calls, _ = parse_xml_tool_calls("<write_file>foo.py\nprint(1)\n</write_file>")
    assert calls[0].tool_name == "write_file"
    assert calls[0].arguments["path"] == "foo.py"
    assert "print(1)" in calls[0].arguments["content"]


def test_glob_pattern():
    calls, _ = parse_xml_tool_calls("<glob>*.py</glob>")
    assert calls[0].tool_name == "glob"
    assert calls[0].arguments == {"pattern": "*.py"}


def test_grep_pattern():
    calls, _ = parse_xml_tool_calls("<grep>TODO</grep>")
    assert calls[0].tool_name == "grep"
    assert calls[0].arguments == {"pattern": "TODO"}


def test_load_skill():
    calls, _ = parse_xml_tool_calls("<load_skill>writing-plans</load_skill>")
    assert calls[0].tool_name == "load_skill"
    assert calls[0].arguments == {"name": "writing-plans"}


def test_web_search():
    calls, _ = parse_xml_tool_calls("<web_search>rust async</web_search>")
    assert calls[0].tool_name == "web_search"
    assert calls[0].arguments["query"] == "rust async"


def test_ask():
    calls, _ = parse_xml_tool_calls("<ask>选择 A 还是 B?</ask>")
    assert calls[0].tool_name == "ask"
    assert "A 还是 B" in calls[0].arguments["question"]


def test_multiple_tool_tags():
    """多个 tool tag 一起"""
    content = "先 read 再 ls\n<read_file>a.txt</read_file>\n<ls>*.py</ls>"
    calls, cleaned = parse_xml_tool_calls(content)
    names = [c.tool_name for c in calls]
    assert "read_file" in names
    assert "ls" in names


def test_unknown_tool_name_not_matched():
    """未知 tool 名 → 不解析, 保留原文"""
    content = "<random_thing>foo</random_thing>"
    calls, cleaned = parse_xml_tool_calls(content)
    assert calls == []
    assert "<random_thing>foo</random_thing>" in cleaned


def test_html_tag_not_matched():
    """HTML 标签 (不是已知 tool) → 不解析"""
    content = "<div>some content</div>"
    calls, cleaned = parse_xml_tool_calls(content)
    assert calls == []


def test_mixed_wrapper_and_tool_tag():
    """minimax wrapper 里嵌 tool tag (W4-36 嵌套)"""
    content = '<minimax:tool_call>\n<read_file>foo.py</read_file>\n</minimax:tool_call>'
    calls, _ = parse_xml_tool_calls(content)
    names = [c.tool_name for c in calls]
    assert "read_file" in names


def test_has_xml_tool_call_detects_tool_tag():
    assert has_xml_tool_call("prefix <read_file>x</read_file>") is True
    assert has_xml_tool_call("plain text") is False
    assert has_xml_tool_call("<h1>title</h1>") is False  # h1 不是 tool
