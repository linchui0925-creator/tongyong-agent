"""W4-39: DeepSeekLLM reasoning model XML 兜底 + reasoning_content fallback"""
import pytest
from app.llm.openai_compatible import DeepSeekLLM
from app.llm.base import LLMResponse


def test_deepseek_reasoning_content_used_when_content_empty():
    """content 空 + reasoning_content 有内容 → 用 reasoning_content"""
    llm = DeepSeekLLM(api_key="test")
    result = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "reasoning_content": "你好, 我是 deepseek 推理模型",
            }
        }]
    }
    resp = llm._parse_response(result)
    assert resp.content == "你好, 我是 deepseek 推理模型"
    assert not resp.has_tool_calls


def test_deepseek_xml_tool_call_fallback():
    """content 里有 <minimax:tool_call> XML 但 tool_calls=[] → 路径 B 解析"""
    llm = DeepSeekLLM(api_key="test")
    result = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": """<minimax:tool_call>
<write_file>
path: /tmp/hello.html
content: <h1>路明非の奇幻世界</h1>
</write_file>
</minimax:tool_call>""",
                "tool_calls": [],
            }
        }]
    }
    resp = llm._parse_response(result)
    assert resp.has_tool_calls, f"expected tool_calls, got {resp}"
    assert resp.tool_calls[0].tool_name == "write_file"
    assert resp.tool_calls[0].arguments["path"] == "/tmp/hello.html"
    assert "<h1>路明非の奇幻世界</h1>" in resp.tool_calls[0].arguments["content"]


def test_deepseek_thinking_stripped_and_tool_call_extracted():
    """content 包含 <think>...</think> 包裹 + 工具调用"""
    llm = DeepSeekLLM(api_key="test")
    result = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": """<think>用户让我写文件, 我需要用 write_file 工具</think>
<minimax:tool_call>
<write_file>
path: x.html
content: <p>hi</p>
</write_file>
</minimax:tool_call>""",
                "tool_calls": [],
            }
        }]
    }
    resp = llm._parse_response(result)
    assert resp.has_tool_calls
    assert resp.tool_calls[0].tool_name == "write_file"
    assert "<think>" not in resp.content


def test_deepseek_standard_tool_calls_still_works():
    """message.tool_calls 有内容 → 路径 A 仍然工作"""
    llm = DeepSeekLLM(api_key="test")
    result = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "tc1",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": '{"path": "a.html", "content": "<p>hi</p>"}',
                    }
                }],
            }
        }]
    }
    resp = llm._parse_response(result)
    assert resp.has_tool_calls
    assert resp.tool_calls[0].tool_name == "write_file"
    assert resp.tool_calls[0].arguments["path"] == "a.html"


def test_deepseek_no_fallback_when_both_empty():
    """content + reasoning_content 都空 → 返回空, 不假动作"""
    llm = DeepSeekLLM(api_key="test")
    result = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
            }
        }]
    }
    resp = llm._parse_response(result)
    assert resp.content == ""
    assert not resp.has_tool_calls
