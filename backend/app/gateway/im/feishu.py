"""
飞书 (Feishu / Lark) Adapter

Phase 1 实现 — 完整 WebSocket + Webhook 模式

设计参考:
- hermes-agent gateway/platforms/feishu.py (80K 字符)
- 飞书开放平台 SDK: lark-oapi
- 飞书事件订阅: https://open.feishu.cn/document/server-docs/event-subscription-guide/overview

依赖:
    pip install lark-oapi>=1.2.0

环境变量（通过 config.extra 传入）:
    app_id:               飞书应用 App ID
    app_secret:           飞书应用 App Secret
    verification_token:   事件订阅验证 Token (Webhook 模式需要)
    encrypt_key:          事件加密 Key (Webhook 模式 + 加密传输需要)
    domain:               "feishu" / "lark" / "larksuite" (默认 feishu)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from app.gateway.im.base import IMPlatformAdapter
from app.gateway.im.models import IMMessageEvent, IMResponse

logger = logging.getLogger(__name__)

# 飞书 SDK 可选依赖 — 不在 requirements.txt 强制要求
try:
    import lark_oapi as lark
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False
    lark = None  # type: ignore[assignment]


def check_feishu_requirements() -> bool:
    """检查 lark-oapi 是否安装"""
    return LARK_AVAILABLE


class FeishuAdapter(IMPlatformAdapter):
    """飞书 adapter"""

    platform_name = "feishu"
    SEND_RATE_LIMIT = 50  # 飞书 API 限流 50次/秒

    def __init__(self, config):
        super().__init__(config)
        # 从 extra 取飞书私有配置
        extra = config.extra
        self.app_id: str = extra.get("app_id", "")
        self.app_secret: str = extra.get("app_secret", "")
        self.verification_token: str = extra.get("verification_token", "")
        self.encrypt_key: str = extra.get("encrypt_key", "")
        domain = extra.get("domain", "feishu")
        # domain 常量 — SDK 未装时用字符串兜底
        if LARK_AVAILABLE and lark is not None:
            self.domain = (
                lark.FEISHU_DOMAIN if domain == "feishu" else
                lark.LARK_DOMAIN if domain == "lark" else
                "https://open.larksuite.com"  # larksuite
            )
        else:
            # SDK 未装时: 不让 __init__ 崩 — connect 时会检查
            self.domain = (
                "https://open.feishu.cn" if domain == "feishu" else
                "https://open.larksuite.com" if domain == "lark" else
                "https://open.larksuite.com"
            )

        # 飞书 max_message_length: 4KB 文本 / 富文本 30KB
        self.config.max_message_length = min(self.config.max_message_length, 4000)

        # WebSocket client
        self._ws_client: Optional[Any] = None
        # Webhook 路由注册表
        self._webhook_handlers = []

    # ── IMPlatformAdapter 抽象方法实现 ──

    async def _do_connect(self) -> bool:
        """启动 WebSocket 长连接 — 飞书官方推荐方式

        注意: lark SDK 在模块级 (client.py:30-33) 调 asyncio.get_event_loop()
        获取的 loop 是当前线程 loop — uvicorn 主线程有 loop 时, module-level
        这个 loop 就指向主 loop, 后续 SDK 内部 start() 调 run_until_complete
        会报 "event loop is already running"。

        解法: 在 import lark_oapi.ws.client 后, 手动把 module-level 'loop'
        替换成新 loop (那个 loop 就只属于 SDK daemon 线程)。
        """
        if not self.app_id or not self.app_secret:
            logger.error("[feishu] app_id / app_secret 未配置")
            return False

        if not LARK_AVAILABLE:
            logger.error("[feishu] lark-oapi 未安装: pip install lark-oapi")
            return False

        # 注册事件处理
        handler = (
            EventDispatcherHandler.builder("", self.verification_token)
            .register_p2_im_message_receive_v1(self._on_message_ws)
            .build()
        )

        # ── 关键: 把 lark SDK module-level 的 loop 替换成新 loop ──
        # lark_oapi.ws.client 顶层 `loop = asyncio.get_event_loop()` 是进程级
        # 单例, uvicorn 进程里它会指向 uvicorn 主 loop, 跑 start() 会冲突
        import asyncio
        import lark_oapi.ws.client as _lark_ws_client
        new_loop = asyncio.new_event_loop()
        _lark_ws_client.loop = new_loop
        # 后续 daemon 线程启动时还得 set 这个 loop 为线程当前 loop
        # (Python asyncio.run 在线程里会 set, 但 start() 没 asyncio.run,
        #  用的是 module-level loop 变量 run_until_complete — 已替换)

        # 构造飞书 WS client
        self._ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )

        # 启独立线程跑 SDK — 线程里 set module-level 那个 new_loop 为当前线程 loop
        import threading
        def _run_in_new_loop():
            asyncio.set_event_loop(new_loop)
            try:
                self._ws_client.start()
            except Exception as e:
                logger.error(f"[feishu] SDK start 线程异常: {e}", exc_info=True)

        self._ws_thread = threading.Thread(
            target=_run_in_new_loop,
            name=f"feishu-ws-{self.app_id[:8]}",
            daemon=True,
        )
        self._ws_thread.start()
        logger.info(f"[feishu] WebSocket 线程已启动: app_id={self.app_id}, thread={self._ws_thread.name}")
        # 短延迟让 SDK 有时间建立连接
        await asyncio.sleep(0.3)
        return self._ws_thread.is_alive()

    async def _do_disconnect(self) -> None:
        """停止 WebSocket 线程"""
        # lark SDK 没有显式 stop, daemon=True 线程在主进程退出时被杀
        # 主进程退出时 disconnect 调到这里 — 实际不需做什么
        if hasattr(self, "_ws_thread") and self._ws_thread:
            logger.info(f"[feishu] WebSocket 线程 daemon={self._ws_thread.daemon} alive={self._ws_thread.is_alive()}")
        self._ws_client = None
        logger.info("[feishu] WebSocket 已标记停止 (daemon 线程随进程退出)")

    async def _do_send(self, chat_id: str, text: str) -> IMResponse:
        """调用飞书 API 发文本消息"""
        if not LARK_AVAILABLE:
            return IMResponse(success=False, error="lark-oapi 未安装")
        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )
            # 构造 client
            client = lark.Client.builder() \
                .app_id(self.app_id) \
                .app_secret(self.app_secret) \
                .domain(self.domain) \
                .build()

            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": text}))
                    .build()
                )
                .build()
            )
            resp = await client.im.v1.message.acreate(req)
            if resp.success():
                msg_id = resp.data.message_id if resp.data else ""
                return IMResponse(success=True, message_id=msg_id, raw=resp.data.__dict__ if resp.data else None)
            else:
                return IMResponse(success=False, error=f"飞书 API 错误: code={resp.code} msg={resp.msg}")
        except Exception as e:
            logger.error(f"[feishu] send 异常: {e}", exc_info=True)
            return IMResponse(success=False, error=str(e))

    async def _do_send_typing(self, chat_id: str) -> None:
        """飞书支持 reaction: 添加 'Typing' 表情"""
        # 简化: 飞书 reaction API 需要 message_id, 流程复杂
        # 这里先 no-op, 后续可扩展
        return None

    def _extract_event(self, raw: Any) -> Optional[IMMessageEvent]:
        """飞书原始事件 → IMMessageEvent (Phase 1 实现在 ws 回调里直接构造)"""
        # WebSocket 模式: 在 _on_message_ws 直接构造, 不走这里
        return None

    # ── WebSocket 事件回调 ──

    def _on_message_ws(self, data: Any) -> None:
        """
        飞书 WebSocket 事件回调 (lark_oapi 同步调用)

        不能 await — 用 asyncio.run_coroutine_threadsafe 调度到主 loop
        """
        try:
            event = data.event
            sender = event.sender
            message = event.message
            sender_id = sender.sender_id.open_id if sender and sender.sender_id else ""
            chat_id = message.chat_id
            chat_type = message.chat_type  # "p2p" / "group"
            message_id = message.message_id

            # 提取文本
            text = self._parse_message_content(message)

            # 群聊 @ bot 门控
            mentioned_bot = True
            if chat_type == "group" and message.mentions:
                bot_open_id = self._get_bot_open_id()
                mentioned_bot = any(m.id.open_id == bot_open_id for m in message.mentions if m.id)
                # 剥离 @bot 部分
                if mentioned_bot:
                    text = self._strip_mention(text)

            im_event = IMMessageEvent(
                platform="feishu",
                chat_id=chat_id,
                chat_type="group" if chat_type == "group" else "direct",
                user_id=sender_id,
                text=text,
                mentioned_bot=mentioned_bot,
                message_id=message_id,
                timestamp=message.create_time if hasattr(message, "create_time") else 0,
                raw=data,
            )

            # 调度到主 event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.handle_message(im_event), loop
                )
            else:
                # 测试场景: loop 没在跑
                logger.warning("[feishu] event loop 未运行，事件被丢弃")
        except Exception as e:
            logger.error(f"[feishu] _on_message_ws 异常: {e}", exc_info=True)

    # ── Webhook 模式 ──

    async def handle_webhook(self, request_body: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        """
        Webhook 入口 — FastAPI 路由调用

        处理:
            1. URL verification 挑战
            2. 加密验证 (verification_token / encrypt_key)
            3. 解析事件 → handle_message
        """
        # 1. URL 验证
        if request_body.get("type") == "url_verification":
            return {"challenge": request_body.get("challenge", "")}

        # 2. token 验证
        if self.verification_token:
            token = request_body.get("token", "")
            if token != self.verification_token:
                logger.warning("[feishu] webhook token 验证失败")
                return {"code": -1, "msg": "token 错误"}

        # 3. 解析事件
        # 注: 加密模式还需要 decrypt, Phase 1 先做明文
        header = request_body.get("header", {})
        event_type = header.get("event_type", "")

        if event_type == "im.message.receive_v1":
            event = request_body.get("event", {})
            message = event.get("message", {})
            sender = event.get("sender", {})

            sender_id = sender.get("sender_id", {}).get("open_id", "")
            chat_id = message.get("chat_id", "")
            chat_type = message.get("chat_type", "p2p")
            message_id = message.get("message_id", "")

            text = self._parse_message_content(message)
            mentioned_bot = True
            if chat_type == "group":
                mentions = message.get("mentions", [])
                bot_open_id = self._get_bot_open_id()
                mentioned_bot = any(m.get("id", {}).get("open_id") == bot_open_id for m in mentions)
                if mentioned_bot:
                    text = self._strip_mention(text)

            im_event = IMMessageEvent(
                platform="feishu",
                chat_id=chat_id,
                chat_type="group" if chat_type == "group" else "direct",
                user_id=sender_id,
                text=text,
                mentioned_bot=mentioned_bot,
                message_id=message_id,
                timestamp=message.get("create_time", 0),
                raw=request_body,
            )
            await self.handle_message(im_event)
            return {"code": 0}

        return {"code": 0, "msg": "ignored"}

    # ── 辅助方法 ──

    def _parse_message_content(self, message: Any) -> str:
        """解析飞书消息 content (JSON 字符串) → 纯文本"""
        try:
            if hasattr(message, "content"):
                content_str = message.content
            elif isinstance(message, dict):
                content_str = message.get("content", "{}")
            else:
                return ""
            content = json.loads(content_str) if isinstance(content_str, str) else content_str
            # text 类型直接取 text 字段
            if content.get("text"):
                return content["text"]
            # 其他类型暂不支持
            return f"[{content.get('msg_type', 'unknown')} 消息暂不支持]"
        except Exception as e:
            logger.debug(f"[feishu] 解析消息内容失败: {e}")
            return ""

    def _strip_mention(self, text: str) -> str:
        """剥离 @bot 提及前缀 — 飞书格式: '@_user_1 实际文本'"""
        import re
        return re.sub(r"@_user_\d+\s*", "", text).strip()

    def _get_bot_open_id(self) -> str:
        """
        获取 bot 自己的 open_id (在自身 app 上下文中)

        飞书文档: 调用 /bot/v3/info 获取
        """
        # 缓存到 self 上避免重复查询
        if not hasattr(self, "_bot_open_id"):
            self._bot_open_id = ""
            try:
                if LARK_AVAILABLE:
                    from lark_oapi.api.application.v6 import GetApplicationRequest
                    client = lark.Client.builder() \
                        .app_id(self.app_id) \
                        .app_secret(self.app_secret) \
                        .domain(self.domain) \
                        .build()
                    req = GetApplicationRequest.builder().app_id(self.app_id).build()
                    resp = client.application.v6.app.aget(req)
                    if resp.success() and resp.data and resp.data.app:
                        self._bot_open_id = getattr(resp.data.app, "app_id", "") or ""
            except Exception as e:
                logger.debug(f"[feishu] 获取 bot open_id 失败: {e}")
        return self._bot_open_id
