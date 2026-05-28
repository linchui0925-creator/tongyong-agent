"""
Gateway Profile Management API

提供Profile的CRUD操作和激活/测试功能。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.gateway.config import Profile
from app.gateway.profile_manager import profile_manager
from app.services.llm_manager import get_llm_manager
from app.llm.model_metadata import get_model_info, get_provider_models

router = APIRouter(prefix="/api/gateway", tags=["gateway-profiles"])

# ── Request Models ───────────────────────────────────────────


class ProfileCreate(BaseModel):
    name: str
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_endpoint: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    max_tool_rounds: int = 10
    is_default: bool = False


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_endpoint: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    max_tool_rounds: Optional[int] = None
    is_default: Optional[bool] = None


def _mask_api_key(profile: Profile) -> dict:
    """脱敏API key"""
    data = profile.model_dump()
    key = data.get("api_key", "")
    if key and len(key) > 8:
        data["api_key"] = key[:4] + "****" + key[-4:]
    elif key:
        data["api_key"] = "****"
    return data


# ── Endpoints ───────────────────────────────────────────────


@router.get("/profiles")
async def list_gateway_profiles():
    """列出所有profiles"""
    profiles = profile_manager.list_profiles()
    active_id = profile_manager.get_active_profile_id()

    return {
        "profiles": [
            {**_mask_api_key(p), "is_active": p.id == active_id}
            for p in profiles
        ],
        "active_profile_id": active_id,
    }


@router.post("/profiles")
async def create_gateway_profile(profile: ProfileCreate):
    """创建新profile"""
    profile_id = uuid.uuid4().hex[:12]

    new_profile = Profile(
        id=profile_id,
        name=profile.name,
        provider=profile.provider,
        model=profile.model,
        api_key=profile.api_key,
        api_endpoint=profile.api_endpoint,
        temperature=profile.temperature,
        max_tokens=profile.max_tokens,
        top_p=profile.top_p,
        max_tool_rounds=profile.max_tool_rounds,
        is_default=profile.is_default,
    )

    created = profile_manager.create_profile(new_profile)

    if profile.is_default:
        profile_manager.set_active_profile(profile_id)

    return {"success": True, "profile": _mask_api_key(created)}


@router.get("/profiles/active")
async def get_active_profile():
    """获取当前激活的profile"""
    profile = profile_manager.get_active_profile()
    if not profile:
        return {"profile": None, "message": "No active profile"}
    return {"profile": _mask_api_key(profile)}


@router.get("/profiles/{profile_id}")
async def get_gateway_profile(profile_id: str):
    """获取指定profile"""
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"profile": _mask_api_key(profile)}


@router.put("/profiles/{profile_id}")
async def update_gateway_profile(profile_id: str, updates: ProfileUpdate):
    """更新profile"""
    update_data = updates.model_dump(exclude_none=True)
    updated = profile_manager.update_profile(profile_id, update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"success": True, "profile": _mask_api_key(updated)}


@router.delete("/profiles/{profile_id}")
async def delete_gateway_profile(profile_id: str):
    """删除profile"""
    ok = profile_manager.delete_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"success": True, "message": "Profile deleted"}


@router.post("/profiles/{profile_id}/activate")
async def activate_gateway_profile(profile_id: str):
    """激活指定profile"""
    ok = profile_manager.set_active_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"success": True, "active_profile_id": profile_id}


@router.post("/profiles/{profile_id}/test")
async def test_gateway_profile(profile_id: str):
    """测试profile的LLM连接"""
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    llm_mgr = get_llm_manager(profile_id)
    result = await llm_mgr.test_connection(
        provider=profile.provider,
        api_key=profile.api_key,
        model=profile.model,
        api_endpoint=profile.api_endpoint,
    )
    return result


@router.get("/profiles/{profile_id}/models")
async def list_profile_models(profile_id: str):
    """获取profile支持的模型列表"""
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    models = get_provider_models(profile.provider)
    model_list = []
    for model_id in models:
        info = get_model_info(model_id)
        model_list.append({
            "id": model_id,
            "name": model_id,
            "context_window": info.context_window if info else 0,
            "max_output": info.max_output if info else 0,
            "capabilities": info.format_capabilities() if info else "basic",
        })

    return {
        "provider": profile.provider,
        "models": model_list,
    }


# ── Gateway Management Endpoints ────────────────────────────────────────


@router.get("/gateways")
async def list_gateways():
    """列出所有Profile网关状态"""
    from app.gateway.gateway_manager import get_gateway_manager
    gm = get_gateway_manager()
    return {"gateways": gm.list_gateways()}


@router.get("/gateways/{profile_id}")
async def get_gateway_status(profile_id: str):
    """获取指定Profile的网关状态"""
    from app.gateway.gateway_manager import get_gateway_manager
    gm = get_gateway_manager()
    status = gm.get_gateway_status(profile_id)
    if not status:
        return {"profile_id": profile_id, "is_running": False}
    return status


@router.post("/gateways/{profile_id}/start")
async def start_gateway(profile_id: str):
    """启动指定Profile的独立网关"""
    from app.gateway.gateway_manager import get_gateway_manager

    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    gm = get_gateway_manager()
    # 分配端口
    port = profile_manager.allocate_port(profile_id)
    result = await gm.start_gateway(profile_id, port)

    if result.get("success"):
        # 更新profile的端口
        profile_manager.update_profile(profile_id, {"gateway_port": port})

    return result


@router.post("/gateways/{profile_id}/stop")
async def stop_gateway(profile_id: str):
    """停止指定Profile的独立网关"""
    from app.gateway.gateway_manager import get_gateway_manager

    gm = get_gateway_manager()
    result = await gm.stop_gateway(profile_id)

    if result.get("success"):
        profile_manager.release_port(profile_id)

    return result


@router.post("/gateways/{profile_id}/restart")
async def restart_gateway(profile_id: str):
    """重启指定Profile的独立网关"""
    from app.gateway.gateway_manager import get_gateway_manager

    gm = get_gateway_manager()
    result = await gm.restart_gateway(profile_id)
    return result