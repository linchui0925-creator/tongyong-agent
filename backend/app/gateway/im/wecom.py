"""
企业微信 (WeCom) Adapter — Phase 3 占位 stub

完整实现在 Phase 3 展开, Phase 0 只做最小占位让 manager 加载
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.gateway.im.base import IMPlatformAdapter
from app.gateway.im.models import IMMessageEvent, IMResponse

logger = logging.getLogger(__name__)

try:
    from wechatpy import WeChatClient
    from wechatpy.crypto import WeChatCipher
    WECHATPY_AVAILABLE = True
except ImportError:
    WECHATPY_AVAILABLE = False
    WeChatClient = None  # type: ignore
    WeChatCipher = None  # type: ignore


def check_wecom_requirements() -> bool:
    return WECHATPY_AVAILABLE


class WeComAdapter(IMPlatformAdapter):
    """企业微信 adapter (Phase 3 stub)"""

    platform_name = "wecom"
    SEND_RATE_LIMIT = 20  # 企业微信限流 20条/分 严控

    async def _do_connect(self) -> bool:
        """Phase 3 实现: 启动 webhook 服务器"""
        logger.warning("[wecom] Phase 3 stub — 尚未实现")
        return False

    async def _do_disconnect(self) -> None:
        pass

    async def _do_send(self, chat_id: str, text: str) -> IMResponse:
        return IMResponse(success=False, error="wecom 尚未实现 (Phase 3)")

    def _extract_event(self, raw: Any) -> Optional[IMMessageEvent]:
        return None
