"""
健康检查路由 (P2-1 W4-22)

从 main.py 抽出的 /, /health, /ready 三个端点.
"""

import time
from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/")
async def root(request: Request):
    """API 根路径"""
    from app.config import settings
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": "1.0.0",
        "docs": "/docs" if settings.debug else "disabled",
    }


@router.get("/health")
async def health(request: Request):
    """健康检查端点"""
    engine = request.app.extra.get("agent_engine")
    llm = engine.llm if engine else None
    return {
        "status": "ok",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "llm": {
            "status": "initialized" if llm else "unavailable",
            "provider": type(llm).__name__ if llm else None,
        },
        "memory": {
            "sessions": len(await engine.get_sessions()) if (engine and engine.memory_storage) else 0
        },
    }


@router.get("/ready")
async def ready(request: Request):
    """就绪检查端点"""
    engine = request.app.extra.get("agent_engine")
    checks = {
        "agent_engine": engine is not None,
        "llm": engine.llm is not None if engine else False,
        "memory_storage": engine.memory_storage is not None if engine else False,
        "vector_store": engine.vector_store is not None if engine else False,
    }
    return {"ready": all(checks.values()), "checks": checks}
