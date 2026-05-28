"""
LLM工厂模块 - 管理多提供商LLM实例
支持动态注册新提供商和获取LLM实例
"""
from typing import Dict, Type, Optional
from app.config import settings

AVAILABLE_PROVIDERS = [
    "tongyi",        # 阿里云通义千问
    "openai",        # OpenAI GPT系列
    "anthropic",     # Claude
    "google",        # Gemini
    "zhipu",         # 智谱AI ChatGLM
    "baichuan",      # 百川智能
    "wenxin",        # 百度文心
    "xfyun",         # 讯飞星火
    "deepseek",      # DeepSeek
    "yi",            # 零一万物
    "ollama",        # 本地Ollama (开源模型)
    "minimax",       # MiniMax（稀宇科技）
    "moonshot",      # Moonshot / 月之暗面 (Kimi)
    "stepfun",       # 阶跃星辰
    "siliconflow",   # 硅基流动
]

_PROVIDER_REGISTRY: Dict[str, Type] = {}


def _register_default_providers():
    """注册默认提供商"""
    global _PROVIDER_REGISTRY

    try:
        from app.llm.tongyi import TongyiLLM
        _PROVIDER_REGISTRY["tongyi"] = TongyiLLM
    except ImportError:
        pass

    try:
        from app.llm.openai import OpenAILLM
        _PROVIDER_REGISTRY["openai"] = OpenAILLM
    except ImportError:
        pass

    try:
        from app.llm.anthropic import AnthropicLLM
        _PROVIDER_REGISTRY["anthropic"] = AnthropicLLM
    except ImportError:
        pass

    try:
        from app.llm.gemini import GeminiLLM
        _PROVIDER_REGISTRY["google"] = GeminiLLM
    except ImportError:
        pass

    try:
        from app.llm.chatglm import ChatGLMLLM
        _PROVIDER_REGISTRY["zhipu"] = ChatGLMLLM
    except ImportError:
        pass

    try:
        from app.llm.baichuan import BaichuanLLM
        _PROVIDER_REGISTRY["baichuan"] = BaichuanLLM
    except ImportError:
        pass

    try:
        from app.llm.wenxin import WenxinLLM
        _PROVIDER_REGISTRY["wenxin"] = WenxinLLM
    except ImportError:
        pass

    try:
        from app.llm.xfyun import XfyunLLM
        _PROVIDER_REGISTRY["xfyun"] = XfyunLLM
    except ImportError:
        pass

    # OpenAI 兼容系列（通用实现）
    try:
        from app.llm.openai_compatible import (
            DeepSeekLLM, YiLLM, MiniMaxLLM, MoonshotLLM,
            StepfunLLM, SiliconFlowLLM,
        )
        _PROVIDER_REGISTRY["deepseek"] = DeepSeekLLM
        _PROVIDER_REGISTRY["yi"] = YiLLM
        _PROVIDER_REGISTRY["minimax"] = MiniMaxLLM
        _PROVIDER_REGISTRY["moonshot"] = MoonshotLLM
        _PROVIDER_REGISTRY["stepfun"] = StepfunLLM
        _PROVIDER_REGISTRY["siliconflow"] = SiliconFlowLLM
    except ImportError:
        pass

    try:
        from app.llm.ollama import OllamaLLM
        _PROVIDER_REGISTRY["ollama"] = OllamaLLM
    except ImportError:
        pass


_register_default_providers()


def get_llm(provider: str = None, api_key: str = None, model: str = None):
    """获取LLM实例"""
    provider = provider or settings.default_llm_provider

    if provider in _PROVIDER_REGISTRY:
        llm_class = _PROVIDER_REGISTRY[provider]
        api_key = api_key or _get_default_api_key(provider)
        llm = llm_class(api_key)
        if model:
            llm.model = model
        return llm

    raise ValueError(f"不支持的LLM提供商: {provider}")


def _get_default_api_key(provider: str) -> Optional[str]:
    """获取提供商的默认API Key"""
    key_map = {
        "tongyi": settings.tongyi_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "google": settings.google_api_key,
        "zhipu": settings.zhipu_api_key,
        "baichuan": settings.baichuan_api_key,
        "wenxin": settings.wenxin_api_key,
        "xfyun": settings.xfyun_api_key,
        "deepseek": settings.deepseek_api_key,
        "yi": settings.yi_api_key,
        "minimax": settings.minimax_api_key,
        "moonshot": settings.moonshot_api_key,
        "stepfun": settings.stepfun_api_key,
        "siliconflow": settings.siliconflow_api_key,
    }
    return key_map.get(provider)


def get_available_providers():
    """获取可用的LLM提供商列表"""
    available = []
    for p in AVAILABLE_PROVIDERS:
        if p in _PROVIDER_REGISTRY:
            available.append(p)
    return available


def register_provider(name: str, llm_class: Type):
    """注册新的LLM提供商"""
    global AVAILABLE_PROVIDERS, _PROVIDER_REGISTRY
    if name not in AVAILABLE_PROVIDERS:
        AVAILABLE_PROVIDERS.append(name)
    _PROVIDER_REGISTRY[name] = llm_class


def get_provider_info(provider: str) -> Optional[Dict]:
    """获取提供商信息"""
    info_map = {
        "tongyi": {"name": "通义千问", "icon": "🐰", "color": "#FF6A00"},
        "openai": {"name": "OpenAI", "icon": "🤖", "color": "#10A37F"},
        "anthropic": {"name": "Anthropic Claude", "icon": "🤖", "color": "#CC785C"},
        "google": {"name": "Google Gemini", "icon": "🔷", "color": "#4285F4"},
        "zhipu": {"name": "智谱AI ChatGLM", "icon": "🔵", "color": "#4A90E2"},
        "baichuan": {"name": "百川智能", "icon": "🌊", "color": "#00D4AA"},
        "wenxin": {"name": "百度文心", "icon": "🟢", "color": "#3300FF"},
        "xfyun": {"name": "讯飞星火", "icon": "🔴", "color": "#FF4444"},
        "deepseek": {"name": "DeepSeek", "icon": "🔻", "color": "#0066FF"},
        "yi": {"name": "零一万物", "icon": "🌟", "color": "#FFD700"},
        "ollama": {"name": "Ollama本地", "icon": "🦙", "color": "#FF9A00"},
        "minimax": {"name": "MiniMax", "icon": "🎯", "color": "#7C3AED"},
        "moonshot": {"name": "月之暗面 (Kimi)", "icon": "🌙", "color": "#FF6B9D"},
        "stepfun": {"name": "阶跃星辰", "icon": "⭐", "color": "#00C9A7"},
        "siliconflow": {"name": "硅基流动", "icon": "💎", "color": "#1890FF"},
    }
    return info_map.get(provider)
