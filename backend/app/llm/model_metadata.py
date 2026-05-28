"""
Model Metadata - 模型元数据、context length 和 token 估算工具

参考 Hermes agent/model_metadata.py 实现:
- context length 检测优先级: 实时API → models.dev → 硬编码 DEFAULT_CONTEXT_LENGTHS
- 支持 substring 匹配 (如 "grok-4.20" 匹配 "grok-4.20-0309-reasoning")
- provider 前缀剥离: "deepseek/deepseek-chat" → "deepseek-chat"
"""

import logging
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Provider 前缀（这些前缀会被剥离）
_PROVIDER_PREFIXES: frozenset[str] = frozenset({
    "openrouter", "anthropic", "openai", "gemini", "minimax", "minimax-cn",
    "deepseek", "zhipu", "baichuan", "moonshot", "kimi", "yi", "xai",
    "qwen", "dashscope", "aliyun", "siliconflow", "stepfun",
    "google", "google-gemini", "google-ai-studio",
})

# Ollama 风格 tag 模式（冒号后的部分不应被剥离）
_OLLAMA_TAG_PATTERN = re.compile(
    r"^(\d+\.?\d*b|latest|stable|q\d|fp?\d|instruct|chat|coder|vision|text)",
    re.IGNORECASE,
)

# Context length 探测层级（从大到小）
CONTEXT_PROBE_TIERS = [128_000, 64_000, 32_000, 16_000, 8_000]
DEFAULT_FALLBACK_CONTEXT = CONTEXT_PROBE_TIERS[0]
MINIMUM_CONTEXT_LENGTH = 32_000  # 最小可用context

# 默认 Context Lengths（2025年最新模型）
DEFAULT_CONTEXT_LENGTHS: Dict[str, int] = {
    # Anthropic Claude (2025年最新)
    "claude-opus-4-7": 1000000,
    "claude-opus-4.7": 1000000,
    "claude-opus-4-6": 1000000,
    "claude-sonnet-4-6": 1000000,
    "claude-opus-4.6": 1000000,
    "claude-sonnet-4.6": 1000000,
    "claude-opus-4-5-20251101": 200000,
    "claude-sonnet-4-5-20250929": 200000,
    "claude-opus-4-20250514": 200000,
    "claude-sonnet-4-20250514": 200000,
    "claude-haiku-4-5-20251001": 200000,
    "claude": 200000,
    # OpenAI GPT-5 (2025年)
    "gpt-5.4": 1050000,
    "gpt-5.4-pro": 1050000,
    "gpt-5.4-mini": 400000,
    "gpt-5.4-nano": 400000,
    "gpt-5.3-codex-spark": 128000,
    "gpt-5.3-codex": 128000,
    "gpt-5.3": 128000,
    "gpt-5.2-codex": 128000,
    "gpt-5.2": 128000,
    "gpt-5.1-codex": 128000,
    "gpt-5.1": 128000,
    "gpt-5": 400000,
    "gpt-4.1": 1047576,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4o-mini-jax": 128000,
    # Google Gemini (2025年)
    "gemini-3-pro-image-preview": 1048576,
    "gemini-3-pro-preview": 1048576,
    "gemini-3-flash-preview": 1048576,
    "gemini-3.1-pro-preview": 1048576,
    "gemini-3.1-flash-preview": 1048576,
    "gemini-3.1-flash-lite-preview": 131072,
    "gemini-3-pro": 1048576,
    "gemini-3-flash": 1048576,
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,
    "gemini-2.5-flash-lite": 131072,
    "gemini-2.0-ultra": 1048576,
    "gemini-2.0-flash": 131072,
    "gemini": 1048576,
    "gemma-4-31b-it": 256000,
    "gemma-4-26b-it": 256000,
    "gemma-4-31b": 256000,
    "gemma-4-26b": 256000,
    "gemma-3-12b": 131072,
    "gemma-3": 131072,
    "gemma-2-27b": 8192,
    "gemma-2": 8192,
    "gemma": 8192,
    # DeepSeek (2025年)
    "deepseek-v4": 128000,
    "deepseek-v3.2": 65536,
    "deepseek-v3": 128000,
    "deepseek-chat": 128000,
    "deepseek-reasoner": 128000,
    "deepseek-r1": 128000,
    "deepseek": 128000,
    # Qwen (2025年)
    "qwen3.6-plus": 131072,
    "qwen3-coder-plus": 1000000,
    "qwen3-coder-next": 1000000,
    "qwen3-coder": 262144,
    "qwen3.5-plus-02-15": 131072,
    "qwen3.5-plus": 131072,
    "qwen3.5-35b-a3b": 131072,
    "qwen3.5-397b-a17b": 131072,
    "qwen3": 131072,
    "qwen-plus-v2": 131072,
    "qwen-plus": 131072,
    "qwen-turbo": 131072,
    "qwen-max": 131072,
    "qwen": 131072,
    # MiniMax (2025年 - M2.7是最新)
    "minimax-m2.7": 204800,
    "minimax-m2.5": 204800,
    "minimax-m2.1": 204800,
    "minimax-m2": 204800,
    "minimax": 204800,
    "MiniMax-M2.7": 204800,
    "MiniMax-M2.5": 204800,
    "MiniMax-M2.1": 204800,
    "MiniMax-M2": 204800,
    # GLM / Z-ai (2025年)
    "glm-5.1": 202752,
    "glm-5": 202752,
    "glm-5v-turbo": 202752,
    "glm-5-turbo": 202752,
    "glm-4.7": 131072,
    "glm-4.6": 131072,
    "glm-4.5-flash": 131072,
    "glm-4": 131072,
    "glm": 202752,
    # xAI Grok (2025年)
    "grok-4.20-0309-reasoning": 2000000,
    "grok-4.20-0309-non-reasoning": 2000000,
    "grok-4.20": 2000000,
    "grok-4-1-fast": 2000000,
    "grok-4-fast": 2000000,
    "grok-4-0709": 256000,
    "grok-4": 256000,
    "grok-3": 131072,
    "grok-3-mini": 131072,
    "grok-3-mini-fast": 131072,
    "grok-2-vision": 8192,
    "grok-2-1212": 131072,
    "grok-2": 131072,
    "grok": 131072,
    # Kimi / Moonshot (2025年)
    "kimi-k2.5": 262144,
    "kimi-k2-thinking": 262144,
    "kimi-k2-turbo-preview": 262144,
    "kimi-k2-0905-preview": 262144,
    "kimi-k2": 262144,
    "kimi": 262144,
    "moonshot-v1-128k": 131072,
    "moonshot-v1-32k": 32768,
    "moonshot-v1-8k": 8192,
    "moonshot": 131072,
    # 小米 MiMo (2025年)
    "mimo-v2-pro": 1000000,
    "mimo-v2-omni": 256000,
    "mimo-v2-flash": 256000,
    "mimo-v2": 256000,
    # Nvidia
    "nemotron-3-super-120b-a12b": 131072,
    # Arcee
    "trinity-large-thinking": 262144,
    "trinity-large-preview": 262144,
    "trinity-mini": 32768,
    # Hugging Face
    "Qwen/Qwen3.5-397B-A17B": 131072,
    "Qwen/Qwen3.5-35B-A3B": 131072,
    "deepseek-ai/DeepSeek-V3.2": 65536,
    "deepseek-ai/DeepSeek-V3": 128000,
    "moonshotai/Kimi-K2.5": 262144,
    "moonshotai/Kimi-K2-Thinking": 262144,
    "MiniMaxAI/MiniMax-M2.5": 204800,
    "zai-org/GLM-5": 202752,
    "XiaomiMiMo/MiMo-V2-Flash": 256000,
    # OpenRouter 模型（通用）
    "openrouter/elephant-alpha": 262144,
}

# max_output 限制（部分模型有输出限制）
DEFAULT_MAX_OUTPUTS: Dict[str, int] = {
    "claude-opus-4-7": 128000,
    "claude-opus-4.6": 128000,
    "claude-sonnet-4-6": 64000,
    "gpt-5.4": 128000,
    "gpt-5": 64000,
    "gemini": 8192,
    "minimax": 131072,
}


def _strip_provider_prefix(model: str) -> str:
    """剥离 provider 前缀

    "deepseek/deepseek-chat" → "deepseek-chat"
    "qwen/qwen-plus" → "qwen-plus"
    "qwen3.5:27b" → "qwen3.5:27b" (保留 Ollama 格式)
    """
    if ":" not in model or model.startswith("http"):
        return model
    prefix, suffix = model.split(":", 1)
    prefix_lower = prefix.strip().lower()
    if prefix_lower in _PROVIDER_PREFIXES:
        if _OLLAMA_TAG_PATTERN.match(suffix.strip()):
            return model
        return suffix
    return model


def _normalize_model_id(model: str) -> str:
    """标准化 model ID 用于查找"""
    # 剥离 provider 前缀
    normalized = _strip_provider_prefix(model)
    # 转换为小写
    normalized = normalized.lower()
    return normalized


@dataclass
class ModelInfo:
    """模型元数据"""

    id: str                          # 原始模型ID
    name: str                        # 显示名称
    provider: str                    # provider ID

    # 能力
    reasoning: bool = False          # 支持推理/思考
    tool_call: bool = False          # 支持工具调用
    vision: bool = False             # 支持视觉/附件
    temperature: bool = False        # 支持 temperature
    structured_output: bool = False  # 支持 JSON schema / function calling

    # 限制
    context_window: int = 0           # context window 大小
    max_output: int = 0              # 最大输出 token

    # 成本（$/M tokens）
    cost_input: float = 0.0
    cost_output: float = 0.0

    def has_cost_data(self) -> bool:
        return self.cost_input > 0 or self.cost_output > 0

    def supports_vision(self) -> bool:
        return self.vision

    def format_capabilities(self) -> str:
        caps = []
        if self.reasoning:
            caps.append("reasoning")
        if self.tool_call:
            caps.append("tools")
        if self.vision:
            caps.append("vision")
        if self.structured_output:
            caps.append("structured output")
        return ", ".join(caps) if caps else "basic"


@dataclass
class ProviderInfo:
    """Provider 元数据"""

    id: str                    # provider ID
    name: str                  # 显示名称
    api_base: str              # API base URL
    default_model: str         # 默认模型
    env_vars: Tuple[str, ...]  # 环境变量名
    doc: str = ""              # 文档URL

    def supports(self, model_id: str) -> bool:
        """检查 provider 是否支持该模型"""
        return model_id in PROVIDER_MODELS.get(self.id, [])


# Provider 模型目录（2025年最新模型，参考 Hermes OPENROUTER_MODELS）
PROVIDER_MODELS: Dict[str, List[str]] = {
    "openai": [
        "gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano",
        "gpt-5.3-codex-spark", "gpt-5.3-codex", "gpt-5.3",
        "gpt-5.2", "gpt-5.1", "gpt-5",
        "gpt-4.1", "gpt-4o", "gpt-4o-mini",
    ],
    "anthropic": [
        "claude-opus-4-7", "claude-opus-4-6",
        "claude-sonnet-4-6", "claude-opus-4-5",
        "claude-sonnet-4-5", "claude-haiku-4-5",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v3.2",
        "deepseek-v3",
        "deepseek-v4",
    ],
    "minimax": [
        "MiniMax-M2.7",
        "MiniMax-M2.5",
        "MiniMax-M2.1",
        "MiniMax-M2",
    ],
    "qwen": [
        "qwen3.6-plus",
        "qwen3-coder-plus",
        "qwen3-coder-next",
        "qwen3-coder",
        "qwen3.5-plus",
        "qwen3.5-plus-02-15",
        "qwen3.5-35b-a3b",
        "qwen-plus-v2",
        "qwen-plus",
        "qwen-turbo",
        "qwen-max",
    ],
    "gemini": [
        "gemini-3-pro",
        "gemini-3-flash",
        "gemini-3-pro-image-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-ultra",
    ],
    "kimi": [
        "kimi-k2.5",
        "kimi-k2-thinking",
        "kimi-k2-turbo-preview",
        "kimi-k2-0905-preview",
        "kimi-k2",
    ],
    "moonshot": [
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ],
    "zhipu": [
        "glm-5.1",
        "glm-5",
        "glm-5v-turbo",
        "glm-5-turbo",
        "glm-4.7",
        "glm-4.6",
        "glm-4.5-flash",
        "glm-4",
    ],
    "baichuan": [
        "baichuan4",
        "baichuan3.5",
        "baichuan3",
    ],
    "yi": [
        "yi-large",
        "yi-medium",
        "yi-spark",
    ],
    "xai": [
        "grok-4.20",
        "grok-4.20-0309-reasoning",
        "grok-4.20-0309-non-reasoning",
        "grok-4-1-fast",
        "grok-4-fast",
        "grok-2-vision",
        "grok-2",
        "grok-3",
        "grok-3-mini",
    ],
    "xiaomi": [
        "mimo-v2-pro",
        "mimo-v2-omni",
        "mimo-v2-flash",
    ],
    "siliconflow": [
        "Qwen/Qwen2.5-7B-Instruct",
        "Qwen/Qwen2.5-14B-Instruct",
        "Qwen/Qwen2.5-32B-Instruct",
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-V3.2",
        "mistralai/Mistral-7B-Instruct",
        "mistralai/Mistral-8x7B-Instruct",
    ],
    "stepfun": [
        "step-2-16k",
        "step-2-32k",
        "step-3-32k",
        "step-3.5-flash",
    ],
    "arcee": [
        "trinity-large-thinking",
        "trinity-large-preview",
        "trinity-mini",
    ],
    "openrouter": [
        # 最新 OpenRouter 模型（来自 Hermes OPENROUTER_MODELS）
        "anthropic/claude-opus-4.7",
        "anthropic/claude-opus-4.6",
        "anthropic/claude-sonnet-4.6",
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-haiku-4.5",
        "qwen/qwen3.6-plus",
        "qwen/qwen3.5-plus-02-15",
        "qwen/qwen3.5-35b-a3b",
        "openai/gpt-5.4",
        "openai/gpt-5.4-mini",
        "openai/gpt-5.4-pro",
        "openai/gpt-5.4-nano",
        "openai/gpt-5.3-codex",
        "google/gemini-3-pro-image-preview",
        "google/gemini-3-flash-preview",
        "google/gemini-3.1-pro-preview",
        "google/gemini-3.1-flash-lite-preview",
        "minimax/minimax-m2.7",
        "minimax/minimax-m2.5",
        "z-ai/glm-5.1",
        "z-ai/glm-5v-turbo",
        "z-ai/glm-5-turbo",
        "moonshotai/kimi-k2.5",
        "x-ai/grok-4.20",
        "deepseek/deepseek-chat",
        "deepseek/deepseek-reasoner",
        "deepseek/deepseek-v3.2",
        "stepfun/step-3.5-flash",
        "nvidia/nemotron-3-super-120b-a12b",
        "arcee-ai/trinity-large-thinking",
        "openrouter/elephant-alpha",
    ],
    # HuggingFace (通过 SiliconFlow 等代理访问)
    "huggingface": [
        "Qwen/Qwen3.5-397B-A17B",
        "Qwen/Qwen3.5-35B-A3B",
        "deepseek-ai/DeepSeek-V3.2",
        "moonshotai/Kimi-K2.5",
        "MiniMaxAI/MiniMax-M2.5",
        "zai-org/GLM-5",
    ],
    # Bedrock (AWS)
    "bedrock": [
        "us.anthropic.claude-sonnet-4-6",
        "us.anthropic.claude-opus-4-6-v1",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "us.amazon.nova-pro-v1:0",
        "us.amazon.nova-lite-v1:0",
        "us.amazon.nova-micro-v1:0",
        "deepseek.v3.2",
        "us.meta.llama4-maverick-17b-instruct-v1:0",
        "us.meta.llama4-scout-17b-instruct-v1:0",
    ],
}


def get_model_info(model_id: str) -> Optional[ModelInfo]:
    """根据模型ID获取模型元信息"""
    normalized = _normalize_model_id(model_id)

    # 先在已知模型中查找
    for provider, models in PROVIDER_MODELS.items():
        if normalized in [m.lower() for m in models]:
            return ModelInfo(
                id=model_id,
                name=model_id,
                provider=provider,
                context_window=_get_context_length(normalized),
                max_output=_get_max_output(normalized),
            )

    # 尝试从 DEFAULT_CONTEXT_LENGTHS 匹配
    ctx = _get_context_length(normalized)
    if ctx > 0:
        # 推断 provider
        provider = _infer_provider(normalized)
        return ModelInfo(
            id=model_id,
            name=model_id,
            provider=provider,
            context_window=ctx,
            max_output=_get_max_output(normalized),
        )

    return None


def _get_context_length(model: str) -> int:
    """获取模型的 context length"""
    normalized = _normalize_model_id(model)

    # 精确匹配
    if normalized in DEFAULT_CONTEXT_LENGTHS:
        return DEFAULT_CONTEXT_LENGTHS[normalized]

    # 子串匹配（从长到短）
    for key in sorted(DEFAULT_CONTEXT_LENGTHS.keys(), key=len, reverse=True):
        if key in normalized:
            return DEFAULT_CONTEXT_LENGTHS[key]

    return DEFAULT_FALLBACK_CONTEXT


def _get_max_output(model: str) -> int:
    """获取模型的最大输出"""
    normalized = _normalize_model_id(model)

    if normalized in DEFAULT_MAX_OUTPUTS:
        return DEFAULT_MAX_OUTPUTS[normalized]

    for key in sorted(DEFAULT_MAX_OUTPUTS.keys(), key=len, reverse=True):
        if key in normalized:
            return DEFAULT_MAX_OUTPUTS[key]

    return 16384  # 默认 16K


def _infer_provider(model: str) -> str:
    """从模型名推断 provider"""
    normalized = model.lower()

    if "gpt" in normalized:
        return "openai"
    if "claude" in normalized:
        return "anthropic"
    if "deepseek" in normalized:
        return "deepseek"
    if "minimax" in normalized or "m2" in normalized:
        return "minimax"
    if "qwen" in normalized or "dashscope" in normalized:
        return "qwen"
    if "gemini" in normalized or "gemma" in normalized:
        return "gemini"
    if "moonshot" in normalized or "kimi" in normalized:
        return "moonshot"
    if "glm" in normalized or "zhipu" in normalized:
        return "zhipu"
    if "grok" in normalized or "xai" in normalized:
        return "xai"

    return "unknown"


def get_provider_models(provider: str) -> List[str]:
    """获取 provider 支持的模型列表"""
    return PROVIDER_MODELS.get(provider, [])


def is_model_supported(provider: str, model: str) -> bool:
    """检查 provider 是否支持该模型"""
    models = get_provider_models(provider)
    normalized_model = model.lower()
    return any(m.lower() == normalized_model for m in models)