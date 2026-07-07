"""
LLM 配置 API — 模型管理与自由切换

提供完整的多提供商模型配置、切换、测试能力。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from app.config import settings
from app.llm.factory import get_available_providers, get_provider_info
from app.services.llm_manager import get_llm_manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
llm_manager = get_llm_manager()


# ── 数据模型 ──────────────────────────────────────────────

class ModelConfig(BaseModel):
    provider: str = Field(..., description="提供商标识，如 tongyi / openai / anthropic")
    api_key: Optional[str] = Field(None, description="API 密钥，为空则使用已有配置")
    api_endpoint: Optional[str] = Field(None, description="自定义 API 端点 URL，为空则使用默认")
    model: Optional[str] = Field(None, description="模型名称，为空则使用默认")
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1)
    top_p: Optional[float] = Field(None, ge=0, le=1)
    skip_test: bool = Field(False, description="跳过连接测试，直接切换")


class ApiKeyUpdate(BaseModel):
    provider: str = Field(..., description="提供商标识")
    api_key: str = Field(..., description="API 密钥")


class SavedModelEntry(BaseModel):
    provider: str = Field(..., description="提供商标识")
    model: str = Field(..., description="模型名称")
    api_key: Optional[str] = Field(None, description="API 密钥，为空则使用 provider/profile 已保存密钥")
    api_endpoint: Optional[str] = Field(None, description="API 端点")
    name: Optional[str] = Field(None, description="显示名称")


class CustomProviderModel(BaseModel):
    id: str = Field(..., description="模型 ID / API model name")
    name: Optional[str] = Field(None, description="显示名")
    enabled: bool = True
    supports_tools: Optional[bool] = None
    supports_vision: Optional[bool] = None
    supports_reasoning: Optional[bool] = None
    overrides: Dict[str, Any] = Field(default_factory=dict)


class CustomProviderConfig(BaseModel):
    id: Optional[str] = None
    name: str
    protocol: str = "openai_compatible"
    base_url: str
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    enabled: bool = True
    website: Optional[str] = None
    notes: Optional[str] = None
    icon: str = "⚙"
    color: str = "#7C3AED"
    request_config: Dict[str, Any] = Field(default_factory=dict)
    models: List[CustomProviderModel] = Field(default_factory=list)
    model_overrides: Dict[str, Any] = Field(default_factory=dict)


class CustomProviderTestConfig(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    request_config: Optional[Dict[str, Any]] = None


class ProviderInfo(BaseModel):
    id: str
    name: str
    icon: str
    color: str
    is_current: bool
    has_api_key: bool
    model: Optional[str] = None


class LLMFullConfig(BaseModel):
    default_provider: str
    available_providers: List[ProviderInfo]
    current: Dict[str, Any]
    api_keys: Dict[str, bool]


# 各提供商的已知模型（供前端选择）
PROVIDER_MODELS = {
    "tongyi": [
        "qwen-max", "qwen-plus", "qwen-turbo",
        "qwen-max-2025-01-25", "qwen-plus-2025-01-25",
        "qwen-turbo-2024-11-01", "qwen2.5-72b-instruct",
        "qwen2.5-32b-instruct", "qwen2.5-14b-instruct",
        "qwen2.5-7b-instruct", "qwen2.5-3b-instruct",
    ],
    "openai": [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
        "gpt-3.5-turbo", "o1", "o3-mini",
    ],
    "anthropic": [
        "claude-sonnet-4-20250514", "claude-sonnet-4", "claude-3-5-sonnet-latest",
        "claude-3-opus-latest", "claude-3-haiku-latest",
        "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
    ],
    "google": [
        "gemini-2.0-flash", "gemini-2.0-flash-lite",
        "gemini-1.5-pro", "gemini-1.5-flash",
        "gemini-1.5-pro-002", "gemini-1.5-flash-002",
    ],
    "zhipu": [
        "glm-4-plus", "glm-4", "glm-4-air", "glm-4-flash",
        "glm-4v-plus", "glm-4v",
    ],
    "baichuan": [
        "baichuan4-turbo", "baichuan4", "baichuan3-turbo",
    ],
    "wenxin": [
        "ERNIE-4.5-8K-Preview", "ERNIE-4.0-8K", "ERNIE-3.5-8K",
        "ERNIE-Speed-128K", "ERNIE-Lite-8K",
    ],
    "xfyun": [
        "4.0Ultra", "4.0Turbo", "3.5Max", "3.0Max",
        "lite", "general", "generalv3",
    ],
    "deepseek": [
        "deepseek-chat", "deepseek-reasoner",
    ],
    "yi": [
        "yi-large", "yi-large-turbo", "yi-medium", "yi-spark",
    ],
    "ollama": [
        "llama3.2", "llama3.1", "qwen2.5", "mistral",
        "deepseek-r1", "phi4", "gemma2", "codellama",
    ],
    "minimax": [
        "MiniMax-Text-01", "MiniMax-M1", "MiniMax-M2",
        "MiniMax-M2.1", "MiniMax-M2.5", "MiniMax-M2.7",
    ],
    "moonshot": [
        "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k",
    ],
    "stepfun": [
        "step-2-16k-nightly", "step-1-32k", "step-1-8k",
        "step-1-flash",
    ],
    "siliconflow": [
        "Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-14B-Instruct",
        "Qwen/Qwen2.5-32B-Instruct", "Qwen/Qwen2.5-72B-Instruct",
        "deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1",
        "meta-llama/Llama-3.3-70B-Instruct",
        "THUDM/glm-4-9b-chat",
    ],
    # W4-41 (2026-06-30): edgefn.net 聚合代理, 一个 key 走多模型
    # - GLM-4.5V: 当前 EdgeFn 控制台推荐示例模型
    # - GLM-5.2: 验证 OK (reasoning model, 原生 tool_calls)
    # - GLM-4-flash: 非 reasoning 备选, tool call 更稳
    # - deepseek-chat (V3): 非 reasoning, OpenAI 兼容, tool call 稳
    # - deepseek-v4-flash: reasoning, 走 reasoning_content 解析
    # - deepseek-v4-pro: 403 ModelNotAllowed (key 没权限, 选项保留)
    "edgefn": [
        "GLM-4.5V",
        "GLM-5.2",
        "GLM-4-flash",
        "deepseek-chat",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ],
}


# ═══════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════


@router.get("/config")
async def get_llm_config():
    """获取完整的 LLM 配置信息"""
    providers = llm_manager.get_all_providers_status()
    api_keys = {}
    for p in providers:
        api_keys[p["id"]] = bool(llm_manager.get_api_key(p["id"]))

    return LLMFullConfig(
        default_provider=settings.default_llm_provider,
        available_providers=[ProviderInfo(**p) for p in providers],
        current=llm_manager.get_current_config(),
        api_keys=api_keys,
    )


@router.get("/providers")
async def get_providers():
    """获取所有提供商及已知模型列表"""
    providers_data = llm_manager.get_all_providers_status()
    for p in providers_data:
        p_id = p["id"]
        known_models = PROVIDER_MODELS.get(p_id, [])
        p["models"] = known_models
    return {"providers": providers_data}


@router.get("/provider-profiles")
async def list_provider_profiles():
    """获取用户自定义供应商配置（API Key 脱敏）"""
    return {"providers": llm_manager.list_custom_providers()}


@router.post("/provider-profiles")
async def create_provider_profile(config: CustomProviderConfig):
    """创建或更新自定义供应商。"""
    try:
        item = llm_manager.upsert_custom_provider(config.model_dump())
        return {"success": True, "provider": item, "message": "供应商配置已保存"}
    except Exception as e:
        logger.error("保存自定义供应商失败: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/provider-profiles/{provider_id}")
async def update_provider_profile(provider_id: str, config: CustomProviderConfig):
    data = config.model_dump()
    data["id"] = provider_id
    try:
        item = llm_manager.upsert_custom_provider(data)
        return {"success": True, "provider": item, "message": "供应商配置已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/provider-profiles/{provider_id}")
async def delete_provider_profile(provider_id: str):
    ok = llm_manager.delete_custom_provider(provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail="供应商配置未找到")
    return {"success": True, "message": "供应商配置已删除"}


@router.post("/provider-profiles/{provider_id}/models/fetch")
async def fetch_provider_profile_models(provider_id: str, config: CustomProviderTestConfig = CustomProviderTestConfig()):
    """从 OpenAI-compatible /models 拉取模型列表。失败不代表 chat 不可用。"""
    provider = llm_manager.get_custom_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商配置未找到")
    try:
        if config.request_config is not None:
            provider["request_config"] = config.request_config
        if config.base_url:
            provider["base_url"] = config.base_url
        llm = llm_manager._custom_provider_to_llm(
            provider,
            api_key=config.api_key,
            model=config.model,
            api_endpoint=config.base_url,
        )
        models = await llm.fetch_models()
        return {"success": True, "models": models, "message": f"获取到 {len(models)} 个模型"}
    except Exception as e:
        return {"success": False, "models": [], "message": f"获取模型列表失败: {e}"}


@router.post("/provider-profiles/{provider_id}/test")
async def test_provider_profile(provider_id: str, config: CustomProviderTestConfig = CustomProviderTestConfig()):
    """测试自定义供应商 chat 可用性。"""
    provider = llm_manager.get_custom_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商配置未找到")
    if config.request_config is not None:
        provider["request_config"] = config.request_config
    if config.base_url:
        provider["base_url"] = config.base_url
    result = await llm_manager.test_connection(
        provider=provider_id,
        api_key=config.api_key,
        model=config.model,
        api_endpoint=config.base_url,
    )
    return result


@router.post("/provider-profiles/{provider_id}/test-tools")
async def test_provider_profile_tools(provider_id: str, config: CustomProviderTestConfig = CustomProviderTestConfig()):
    """测试自定义供应商是否能返回原生或 XML fallback 工具调用。"""
    provider = llm_manager.get_custom_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商配置未找到")
    try:
        if config.request_config is not None:
            provider["request_config"] = config.request_config
        if config.base_url:
            provider["base_url"] = config.base_url
        llm = llm_manager._custom_provider_to_llm(
            provider,
            api_key=config.api_key,
            model=config.model,
            api_endpoint=config.base_url,
        )
        from app.core.base import Message
        tools = [{
            "type": "function",
            "function": {
                "name": "diagnostic_echo",
                "description": "Echo a short diagnostic string.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }]
        response = await llm.chat([
            Message(role="user", content="Call diagnostic_echo with text set to ok. Do not answer in prose.")
        ], tools=tools)
        mode = "native_or_fallback" if response.has_tool_calls else "none"
        return {
            "success": response.has_tool_calls,
            "message": "工具调用测试成功" if response.has_tool_calls else "未返回工具调用",
            "tool_call_mode": mode,
            "tool_calls": [
                {"name": tc.tool_name, "arguments": tc.arguments}
                for tc in response.tool_calls
            ],
        }
    except Exception as e:
        return {"success": False, "message": f"工具调用测试失败: {e}", "tool_call_mode": "error"}


@router.get("/status")
async def get_model_status():
    """获取当前模型状态"""
    current = llm_manager.get_current_config()
    llm = llm_manager.get_current_llm()
    return {
        "current_provider": llm_manager.get_current_provider(),
        "current_model": llm_manager.get_current_model(),
        "is_available": llm.is_available() if llm else False,
        "providers": llm_manager.get_all_providers_status(),
    }


@router.post("/config")
async def update_llm_config(config: ModelConfig):
    """切换模型配置"""
    try:
        kwargs = {}
        if config.temperature is not None:
            kwargs["temperature"] = config.temperature
        if config.max_tokens is not None:
            kwargs["max_tokens"] = config.max_tokens
        if config.top_p is not None:
            kwargs["top_p"] = config.top_p
        if config.api_endpoint is not None:
            kwargs["api_endpoint"] = config.api_endpoint

        success = llm_manager.switch_model(
            provider=config.provider,
            api_key=config.api_key,
            model=config.model,
            **kwargs,
        )

        if success:
            return {
                "success": True,
                "message": f"已切换到 {config.provider}",
                "config": llm_manager.get_current_config(),
            }
        else:
            return {"success": False, "message": f"切换到 {config.provider} 失败"}
    except Exception as e:
        logger.error(f"更新 LLM 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/test")
async def test_llm_connection(config: ModelConfig):
    """测试模型连接"""
    try:
        result = await llm_manager.test_connection(
            provider=config.provider,
            api_key=config.api_key,
            model=config.model,
            api_endpoint=config.api_endpoint,
        )
        return result
    except Exception as e:
        return {"success": False, "message": f"测试失败: {e}"}


@router.post("/switch")
async def switch_model(config: ModelConfig):
    """切换模型（配置 + 可选连接测试）"""
    try:
        if not config.skip_test:
            test_result = await llm_manager.test_connection(
                provider=config.provider,
                api_key=config.api_key,
                model=config.model,
                api_endpoint=config.api_endpoint,
            )
            if not test_result["success"]:
                return {
                    "success": False,
                    "message": f"连接测试失败: {test_result.get('message', '')}",
                }

        kwargs = {}
        if config.temperature is not None:
            kwargs["temperature"] = config.temperature
        if config.max_tokens is not None:
            kwargs["max_tokens"] = config.max_tokens
        if config.top_p is not None:
            kwargs["top_p"] = config.top_p
        if config.api_endpoint is not None:
            kwargs["api_endpoint"] = config.api_endpoint

        ok = llm_manager.switch_model(
            provider=config.provider,
            api_key=config.api_key,
            model=config.model,
            **kwargs,
        )

        return {
            "success": ok,
            "message": f"已切换到 {config.provider} / {config.model or '(默认模型)'}",
            "config": llm_manager.get_current_config() if ok else None,
        }
    except Exception as e:
        logger.error(f"切换模型失败: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


@router.get("/current")
async def get_current_model():
    """获取当前模型信息"""
    config = llm_manager.get_current_config()
    custom_provider = llm_manager.get_custom_provider(llm_manager.get_current_provider())
    info = custom_provider or get_provider_info(llm_manager.get_current_provider()) or {}
    return {
        "provider": config["provider"],
        "name": info.get("name", config["provider"]),
        "icon": info.get("icon", "⚙" if custom_provider else ""),
        "color": info.get("color", "#7C3AED" if custom_provider else ""),
        "model": llm_manager.get_current_model(),
        "api_key_configured": config.get("api_key_configured", False),
        "provider_profile_id": config.get("provider_profile_id"),
    }


@router.post("/api-key")
async def update_api_key(body: ApiKeyUpdate):
    """更新指定提供商的 API 密钥"""
    if not body.api_key:
        raise HTTPException(status_code=400, detail="API 密钥不能为空")
    llm_manager.set_api_key(body.provider, body.api_key)
    return {"success": True, "message": f"{body.provider} API 密钥已更新"}


@router.get("/saved-models")
async def list_saved_models():
    """获取所有已保存的模型配置"""
    return {"models": llm_manager.get_saved_models()}


@router.post("/saved-models")
async def save_model_config(entry: SavedModelEntry):
    """保存模型配置"""
    try:
        model_id = llm_manager.add_saved_model(entry.model_dump())
        return {"success": True, "id": model_id, "message": "模型配置已保存"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/saved-models/{model_id}")
async def remove_saved_model(model_id: str):
    """删除已保存的模型配置"""
    ok = llm_manager.delete_saved_model(model_id)
    if not ok:
        raise HTTPException(status_code=404, detail="模型配置未找到")
    return {"success": True, "message": "已删除"}


@router.post("/saved-models/{model_id}/switch")
async def switch_to_saved_model(model_id: str):
    """切换到已保存的模型配置"""
    entry = llm_manager.get_saved_model_by_id(model_id)
    if not entry:
        raise HTTPException(status_code=404, detail="模型配置未找到")
    try:
        ok = llm_manager.switch_model(
            provider=entry["provider"],
            api_key=entry.get("api_key") if llm_manager.is_real_api_key(entry.get("api_key")) else None,
            model=entry.get("model"),
            api_endpoint=entry.get("api_endpoint"),
        )
        return {
            "success": ok,
            "message": f"已切换到 {entry['provider']} / {entry.get('model', '')}",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/models/{provider}")
async def get_provider_models(provider: str):
    """获取指定提供商支持的模型列表"""
    available = get_available_providers()
    if provider not in available:
        raise HTTPException(status_code=404, detail=f"提供商 {provider} 不可用")
    info = get_provider_info(provider) or {}
    return {
        "provider": provider,
        "name": info.get("name", provider),
        "icon": info.get("icon", ""),
        "color": info.get("color", ""),
        "models": PROVIDER_MODELS.get(provider, []),
        "has_api_key": bool(llm_manager.get_api_key(provider)),
    }
