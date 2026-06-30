"""W4-34: provider function call 适配的 CI gate

静态扫描所有注册的 LLM provider, 验证:
1. chat(messages, tools=) 签名接收 tools 参数
2. chat() 实际把 tools 灌进 HTTP body
3. _parse_response() 解析 OpenAI 格式的 tool_calls 字段

任何 provider 三项之一缺失 = 测试失败, 防止历史回归 (W4-34 audit fix)。

排除项:
- AnthropicLLM: 走 Anthropic 原生 tools 协议 (非 OpenAI 兼容), W4-35 处理
- GeminiLLM: 走 Gemini functionDeclarations 协议, W4-35 处理
- OpenAILLM: 走 official SDK, tools 在 SDK 内部处理, 不在源码里
- TongyiLLM: 双模式, _chat_compatible 走 tools, 这里仅看类层
"""
import inspect

import pytest

from app.llm.factory import _PROVIDER_REGISTRY
from app.llm.base import BaseLLM


# W4-34 明确豁免 (待 W4-35 修)
_EXEMPT_FROM_TOOLS = {"anthropic", "google", "openai", "tongyi"}


def _walk_mro_sources(klass, method_name):
    """沿 MRO 收集方法实际生效的源码 (含基类), 用于审计私有覆盖"""
    sources = []
    for cls in klass.__mro__:
        if method_name in cls.__dict__:
            try:
                sources.append((cls.__name__, inspect.getsource(cls.__dict__[method_name])))
            except (OSError, TypeError):
                pass
    return sources


@pytest.mark.parametrize("provider_name", sorted(_PROVIDER_REGISTRY.keys()))
def test_chat_accepts_tools_kwarg(provider_name):
    """chat() 签名必须接 tools= 形参 (BaseLLM 抽象已规定)"""
    cls = _PROVIDER_REGISTRY[provider_name]
    sig = inspect.signature(cls.chat)
    assert "tools" in sig.parameters, (
        f"{provider_name}.chat() 签名缺少 tools 形参 "
        f"(实际: {list(sig.parameters)})"
    )


@pytest.mark.parametrize("provider_name", sorted(_PROVIDER_REGISTRY.keys()))
def test_chat_body_contains_tools(provider_name):
    """chat() 实现必须把 tools 实际灌进 HTTP body (排除已知豁免)"""
    if provider_name in _EXEMPT_FROM_TOOLS:
        pytest.skip(f"{provider_name} 走非 OpenAI 协议, 见 W4-35")
    cls = _PROVIDER_REGISTRY[provider_name]
    sources = _walk_mro_sources(cls, "chat")
    assert sources, f"{provider_name} 找不到 chat() 实现"
    # 基类 + 子类合并, 看是否提到 body[...] = tools
    combined = "\n".join(src for _, src in sources)
    assert 'body["tools"]' in combined or "body['tools']" in combined, (
        f"{provider_name}.chat() 没把 tools 灌进 body:\n{combined[:500]}"
    )


@pytest.mark.parametrize("provider_name", sorted(_PROVIDER_REGISTRY.keys()))
def test_parse_response_reads_tool_calls(provider_name):
    """_parse_response() 或 chat() 必须从 message.tool_calls 读出 tool_call 列表 (排除已知豁免)"""
    if provider_name in _EXEMPT_FROM_TOOLS:
        pytest.skip(f"{provider_name} 走非 OpenAI 协议, 见 W4-35")
    cls = _PROVIDER_REGISTRY[provider_name]
    sources = _walk_mro_sources(cls, "_parse_response")
    combined = "\n".join(src for _, src in sources)
    if not sources:
        # 某些 provider 在 chat() 内 inline 解析 (如 MiniMaxLLM)
        chat_sources = _walk_mro_sources(cls, "chat")
        combined = "\n".join(src for _, src in chat_sources)
    assert "tool_calls" in combined, (
        f"{provider_name} 没有解析 message.tool_calls 字段"
    )


def test_basellm_contract_includes_tools():
    """BaseLLM 抽象层 chat() 必须保留 tools 形参 (防误改)"""
    sig = inspect.signature(BaseLLM.chat)
    assert "tools" in sig.parameters
    # 基类是 abstract, tools 默认 None 表示不传
    assert sig.parameters["tools"].default is None
