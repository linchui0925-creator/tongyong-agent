"""
IM Gateway 管理 API — 给运维 / 调试用
"""

from fastapi import APIRouter, HTTPException

from app.gateway.im import im_gateway_manager

router = APIRouter(prefix="/api/im", tags=["im-gateway"])


@router.get("/status")
async def get_im_status():
    """所有 IM 平台连接状态"""
    return im_gateway_manager.get_status()


@router.get("/health")
async def im_health():
    """IM Gateway 健康检查 — 是否有任何平台连接成功"""
    status = im_gateway_manager.get_status()
    if not status["started"]:
        return {"healthy": False, "reason": "not started"}
    connected = [p for p, info in status["platforms"].items() if info["connected"]]
    return {
        "healthy": len(connected) > 0,
        "connected": connected,
        "total_platforms": len(status["platforms"]),
    }
