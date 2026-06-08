"""
Gateway 子包：OpenAI-兼容网关 + 多 profile 路由 + IM 通道。
"""

from app.gateway.openai_api import router as openai_router
from app.gateway.config import GatewaySettings

__all__ = ["openai_router", "GatewaySettings"]
