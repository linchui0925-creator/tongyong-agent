"""
网关认证模块 - Bearer Token 认证
"""

import hmac
import logging
from fastapi import Request, HTTPException, status
from app.gateway.config import GatewaySettings

logger = logging.getLogger(__name__)

# 全局配置引用，由路由器初始化时设置
_settings: GatewaySettings | None = None


def init_auth(settings: GatewaySettings):
    global _settings
    _settings = settings


async def verify_api_key(request: Request) -> None:
    """验证 Bearer Token API 密钥（FastAPI Dependency）"""
    if _settings is None or not _settings.api_key:
        return  # 未配置密钥，全部放行（仅限本地）

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:].strip()
    if not hmac.compare_digest(token, _settings.api_key):
        logger.warning(f"无效 API 密钥尝试: {token[:8]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
