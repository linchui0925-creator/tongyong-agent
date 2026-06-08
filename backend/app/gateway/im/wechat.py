"""
微信服务号 (WeChat Official Account) Adapter — Phase 4 占位 stub
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.gateway.im.base import IMPlatformAdapter
from app.gateway.im.models import IMMessageEvent, IMResponse

logger = logging.getLogger(__name__)

try:
    from wechatpy import WeChatClient
    WECHATPY_AVAILABLE = True
except ImportError:
    WECHATPY_AVAILABLE = False
    WeChatClient = None  # type: ignore


def check_wechat_requirements() -> bool:
    return WECHATPY_AVAILABLE


class WeChatAdapter(IMPlatformAdapter):
    """微信服务号 adapter (Phase 4 stub)"""

    platform_name = "wechat"
    SEND_RATE_LIMIT = 5  # 公众号客服消息 5/s

    async def _do_connect(self) -> bool:
        logger.warning("[wechat] Phase 4 stub — 尚未实现")
        return False

    async def _do_disconnect(self) -> None:
        pass

    async def _do_send(self, chat_id: str, text: str) -> IMResponse:
        return IMResponse(success=False, error="wechat 尚未实现 (Phase 4)")

    def _extract_event(self, raw: Any) -> Optional[IMMessageEvent]:
        return None
