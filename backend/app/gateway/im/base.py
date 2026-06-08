"""
IMPlatformAdapter — IM 平台适配器抽象基类

设计要点（仿 hermes-agent `gateway/platforms/base.py`）：
- 6 个核心方法: connect / disconnect / send / send_typing / handle_message / get_chat_info
- 业务逻辑（鉴权、profile 路由、SSE 消费）由基类实现，子类只需关心"平台协议"
- handle_message 是入口，handle_webhook 是 webhook 模式的可选入口
- send 内部做长度切分，子类只需关心"怎么调用平台 API 发一条"

为什么这样切分：
- 飞书 / 微信 各自 SDK 完全不同，但"发消息 / 收消息"语义一样
- 集中处理鉴权、profile 路由、session 管理，避免每个平台重写
- 子类只负责：解析平台事件 → IMMessageEvent；调用平台 API 发文本
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional

from app.gateway.im.models import (
    IMMessageEvent,
    IMPlatformConfig,
    IMResponse,
)

logger = logging.getLogger(__name__)

# agent_engine 单例在 main.py 启动时注入
# 子类在 process() 内调用 _stream_chat() 间接使用
_agent_engine_ref: Dict[str, Any] = {}


def set_agent_engine(engine: Any) -> None:
    """main.py 启动时调用一次，把 AgentEngine 注入到 IM 层"""
    _agent_engine_ref["engine"] = engine
    logger.info("[IMGateway] AgentEngine 已注入")


def get_agent_engine() -> Any:
    return _agent_engine_ref.get("engine")


class IMPlatformAdapter(ABC):
    """
    IM 平台抽象基类

    子类必须实现:
        _do_connect()        - 平台连接（WebSocket 启动 / webhook 注册）
        _do_disconnect()     - 平台断开
        _do_send()           - 平台 API 发送一条文本
        _extract_event()     - 平台原始 payload → IMMessageEvent

    子类可选重写:
        _do_send_typing()    - 默认 no-op（部分平台无 typing 概念）
        _do_get_chat_info()  - 默认返回 dict
        _do_handle_webhook() - Webhook 模式入口
    """

    # ── 类属性 — 子类必须覆盖 ──
    platform_name: str = ""  # "feishu" / "wecom" / "wechat"

    def __init__(self, config: IMPlatformConfig):
        self.config = config
        self._connected: bool = False
        self._send_semaphore: Optional[asyncio.Semaphore] = None
        # session_id 管理: chat_id → session_id
        self._session_map: Dict[str, str] = {}
        # 任务清理
        self._tasks: List[asyncio.Task] = []

    # ── 公开方法（基类实现业务逻辑，子类不要重写） ──

    async def connect(self) -> bool:
        """连接 IM 平台（启动 WebSocket / 注册 webhook）"""
        if self._connected:
            logger.warning(f"[{self.platform_name}] 已连接，重复 connect 忽略")
            return True
        try:
            ok = await self._do_connect()
            self._connected = ok
            # IM 平台普遍有发送频率限制 (飞书 50/s, 微信 100/min)，用 semaphore 兜底
            self._send_semaphore = asyncio.Semaphore(self._get_send_rate_limit())
            return ok
        except Exception as e:
            logger.error(f"[{self.platform_name}] connect 失败: {e}", exc_info=True)
            return False

    async def disconnect(self) -> None:
        """断开 IM 平台（停 WebSocket / 关 webhook）"""
        if not self._connected:
            return
        # 取消所有进行中的 handle_message 任务
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        try:
            await self._do_disconnect()
        except Exception as e:
            logger.error(f"[{self.platform_name}] disconnect 失败: {e}", exc_info=True)
        self._connected = False

    async def send(self, chat_id: str, text: str) -> IMResponse:
        """发送文本消息（自动切分长消息）"""
        if not self._connected:
            return IMResponse(success=False, error=f"{self.platform_name} 未连接")
        if not text:
            return IMResponse(success=True)  # 空消息直接成功 no-op
        # 长消息切分
        chunks = self._split_text(text, max_len=self.config.max_message_length)
        last_resp: Optional[IMResponse] = None
        for chunk in chunks:
            if self._send_semaphore:
                async with self._send_semaphore:
                    last_resp = await self._do_send(chat_id, chunk)
            else:
                last_resp = await self._do_send(chat_id, chunk)
            if not last_resp.success:
                # 一条失败就停
                return last_resp
        return last_resp or IMResponse(success=True)

    async def send_typing(self, chat_id: str) -> None:
        """发送 typing 提示（部分平台不支持，no-op 默认）"""
        try:
            await self._do_send_typing(chat_id)
        except Exception as e:
            # typing 失败不影响主流程
            logger.debug(f"[{self.platform_name}] typing 失败: {e}")

    async def handle_message(self, event: IMMessageEvent) -> None:
        """
        处理入站消息 — 业务逻辑集中处

        流程:
            1. 鉴权 (白名单)
            2. 群聊必须 @ bot 才处理
            3. 解析 profile
            4. 调 agent engine stream_chat
            5. SSE chunk → IM 消息推送
        """
        # 1. 鉴权
        if not self.config.is_user_allowed(event.user_id):
            logger.info(f"[{self.platform_name}] 拒绝未授权用户: {event.user_id}")
            return

        # 2. 群聊 @ bot 门控
        if event.chat_type == "group" and not event.mentioned_bot:
            return

        # 3. 解析 profile
        profile = self.config.resolve_profile(event.user_id)

        # 4. 启动后台 task 处理（让 handle_message 立即返回，不阻塞 adapter 事件循环）
        task = asyncio.create_task(self._process_event(event, profile))
        self._tasks.append(task)

        def _cleanup(t: asyncio.Task) -> None:
            try:
                self._tasks.remove(t)
            except ValueError:
                pass

        task.add_done_callback(_cleanup)

    async def _process_event(self, event: IMMessageEvent, profile: str) -> None:
        """实际跑 agent + 推消息的逻辑"""
        chat_id = event.chat_id
        session_id = self._get_or_create_session(chat_id)

        # typing 反馈
        await self.send_typing(chat_id)

        # 调 agent engine
        try:
            buffer = ""           # content 累积
            last_send = 0.0        # 上次 send 的时间戳（流式节流）
            min_interval = 0.8     # 最小间隔 (s) — 防止触发 IM 限流

            async for chunk in self._stream_chat(
                message=event.text,
                session_id=session_id,
                profile=profile,
            ):
                chunk_type = chunk.get("type", "")

                if chunk_type == "content":
                    buffer += chunk.get("content", "")
                    # 节流: 累积到一定长度 或 间隔 0.8s 才发
                    now = asyncio.get_event_loop().time()
                    if len(buffer) >= 80 or (now - last_send) >= min_interval or chunk.get("done"):
                        if buffer:
                            resp = await self.send(chat_id, buffer)
                            buffer = ""
                            last_send = now
                            if not resp.success:
                                logger.error(f"[{self.platform_name}] send 失败: {resp.error}")

                elif chunk_type == "tool_start" and self.config.show_tool_calls:
                    name = chunk.get("name", "")
                    await self.send(chat_id, f"🔧 {name} ...")

                elif chunk_type == "tool_complete" and self.config.show_tool_calls:
                    name = chunk.get("name", "")
                    elapsed = chunk.get("elapsed", 0)
                    await self.send(chat_id, f"✅ {name} ({elapsed:.1f}s)")

                elif chunk_type == "tool_error" and self.config.show_tool_calls:
                    name = chunk.get("name", "")
                    err = chunk.get("error", "")
                    await self.send(chat_id, f"❌ {name}: {err[:200]}")

                elif chunk_type == "thinking_delta" and self.config.show_thinking:
                    # 默认折叠 thinking — 不发到 IM
                    pass

                elif chunk_type == "progress":
                    # 进度事件：只更新 typing，不发文本
                    await self.send_typing(chat_id)

                elif chunk_type == "done":
                    # 最后 flush
                    if buffer:
                        await self.send(chat_id, buffer)
                        buffer = ""
                    break

                elif chunk_type == "error":
                    err = chunk.get("message", "未知错误")
                    await self.send(chat_id, f"❌ 出错了: {err[:500]}")
                    break

            # 最终总结
            if buffer:
                await self.send(chat_id, buffer)

        except asyncio.CancelledError:
            logger.info(f"[{self.platform_name}] 任务被取消: chat={chat_id}")
            raise
        except Exception as e:
            logger.error(f"[{self.platform_name}] 处理消息异常: {e}", exc_info=True)
            try:
                await self.send(chat_id, f"❌ 出错了: {str(e)[:500]}")
            except Exception:
                pass

    async def _stream_chat(
        self,
        message: str,
        session_id: str,
        profile: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调 agent engine 的 stream_chat — 子类可重写以注入 profile 路由

        默认: 直接调注入的 AgentEngine
        """
        engine = get_agent_engine()
        if engine is None:
            yield {"type": "error", "message": "AgentEngine 未初始化"}
            return
        try:
            async for chunk in engine.stream_chat(
                session_id=session_id,
                message=message,
                use_memory=True,
            ):
                yield chunk
        except Exception as e:
            yield {"type": "error", "message": str(e)}

    # ── 抽象方法 — 子类必须实现 ──

    @abstractmethod
    async def _do_connect(self) -> bool: ...

    @abstractmethod
    async def _do_disconnect(self) -> None: ...

    @abstractmethod
    async def _do_send(self, chat_id: str, text: str) -> IMResponse: ...

    @abstractmethod
    def _extract_event(self, raw: Any) -> Optional[IMMessageEvent]:
        """平台原始 payload → IMMessageEvent — 同步方法（adapter 在事件回调里同步构建）"""
        ...

    # ── 可选重写方法（带默认实现） ──

    async def _do_send_typing(self, chat_id: str) -> None:
        """默认 no-op（部分平台无 typing 概念）"""
        return None

    async def _do_get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """默认返回基础信息"""
        return {"chat_id": chat_id, "platform": self.platform_name}

    async def handle_webhook(self, request_body: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        """
        Webhook 模式入口 — 默认返回 403（仅 WebSocket 模式的子类可重写）
        """
        return {"code": -1, "msg": f"{self.platform_name} 不支持 webhook 模式"}

    # ── 内部辅助 ──

    def _get_send_rate_limit(self) -> int:
        """每秒发送上限 — 飞书 50/s, 微信 100/min ≈ 2/s"""
        return getattr(self, "SEND_RATE_LIMIT", 10)

    def _split_text(self, text: str, max_len: int) -> List[str]:
        """长文本切分 — 按 max_len 切（按行优先，避免断字）"""
        if len(text) <= max_len:
            return [text]
        chunks: List[str] = []
        remaining = text
        while len(remaining) > max_len:
            # 找最近的换行符
            cut_at = remaining.rfind("\n", 0, max_len)
            if cut_at < max_len // 2:
                cut_at = max_len  # 没找到就硬切
            chunks.append(remaining[:cut_at])
            remaining = remaining[cut_at:].lstrip("\n")
        if remaining:
            chunks.append(remaining)
        return chunks

    def _get_or_create_session(self, chat_id: str) -> str:
        """chat_id → session_id 映射（持久化后续可放 redis）"""
        if chat_id not in self._session_map:
            # 格式: im-{platform}-{chat_id} 让用户能区分 IM session vs Web session
            self._session_map[chat_id] = f"im-{self.platform_name}-{chat_id}-{uuid.uuid4().hex[:8]}"
        return self._session_map[chat_id]
