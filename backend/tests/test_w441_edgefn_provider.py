"""W4-41: edgefn.net provider — 智谱 GLM / DeepSeek 聚合"""
import pytest
from app.llm.edgefn import EdgeFnLLM
from app.llm.factory import _PROVIDER_REGISTRY, get_llm


def test_edgefn_registered():
    """edgefn 在 factory registry 里"""
    assert "edgefn" in _PROVIDER_REGISTRY
    assert _PROVIDER_REGISTRY["edgefn"] is EdgeFnLLM


def test_edgefn_default_endpoint_and_model():
    """edgefn 默认 api_base 是 edgefn.net, 默认模型是 GLM-4.5V (W5-2 起)"""
    llm = EdgeFnLLM(api_key="test")
    assert llm.api_base == "https://api.edgefn.net/v1"
    assert llm.model == "GLM-4.5V"


def test_edgefn_custom_model():
    """通过 model 参数切到 deepseek"""
    llm = EdgeFnLLM(api_key="test", model="deepseek-v4-flash")
    assert llm.model == "deepseek-v4-flash"
    assert llm.api_base == "https://api.edgefn.net/v1"  # 端点不变, 只切 model


def test_edgefn_parses_tool_calls_native():
    """GLM-5.2 实测响应: content 空 + tool_calls 完整 → 解析成功"""
    llm = EdgeFnLLM(api_key="test")
    result = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",  # reasoning model 真实空
                "reasoning_content": "User wants hello.html, I'll call write_file",
                "tool_calls": [{
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": '{"path": "/tmp/hello.html", "content": "<h1>hi</h1>"}',
                    }
                }],
            }
        }]
    }
    resp = llm._parse_response(result)
    assert resp.has_tool_calls
    assert resp.tool_calls[0].tool_name == "write_file"
    assert resp.tool_calls[0].arguments["path"] == "/tmp/hello.html"
    assert resp.tool_calls[0].arguments["content"] == "<h1>hi</h1>"


def test_edgefn_reasoning_content_as_content_fallback():
    """content 空 + reasoning_content 有 + 0 tool_calls → 用 reasoning_content 兜底"""
    llm = EdgeFnLLM(api_key="test")
    result = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "reasoning_content": "这是推理内容, 没有工具调用",
            }
        }]
    }
    resp = llm._parse_response(result)
    assert not resp.has_tool_calls
    assert "这是推理内容" in resp.content


def test_edgefn_xml_fallback_also_works():
    """reasoning model 也可能输出 minimax 风格 XML (跟 W4-39 一致)"""
    llm = EdgeFnLLM(api_key="test")
    result = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": """<minimax:tool_call>
<write_file>
path: /tmp/x.html
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


def test_get_llm_returns_edgefn_instance():
    """通过 factory.get_llm 拿到 EdgeFnLLM"""
    llm = get_llm("edgefn", "sk-test", "GLM-5.2")
    assert isinstance(llm, EdgeFnLLM)
    assert llm.model == "GLM-5.2"
