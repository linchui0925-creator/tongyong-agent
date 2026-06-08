"""
对话上下文管理器 - token 感知 + 自动压缩。

负责把 history 消息列表压缩到 max_tokens 限制内，保留关键信息。
被 AgentEngine._load_messages_to_context() 调用，作为 system prompt 注入链的
倒数第二段（"全量历史"）。
"""
from typing import List, Optional
from datetime import datetime
import json
from app.core.base import Message
import logging

logger = logging.getLogger(__name__)


class ContextManager:
    """
    对话上下文管理器，支持 token 感知和自动压缩。

    压缩策略：
    1. 保留系统消息（身份定义、约束等）
    2. 保留首尾消息对（最近的 user/assistant 对最重要）
    3. 保留 tool 消息（执行记录）
    4. 压缩中间的消息，保留关键信息
    """

    # token 估算：1 token ≈ 4 字符（中文更少）
    CHARS_PER_TOKEN = 4
    # 保留最近 N 轮完整对话
    KEEP_RECENT_ROUNDS = 3
    # 触发压缩的阈值（70% 的 max_tokens）
    COMPRESS_THRESHOLD = 0.7

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.messages: List[Message] = []
        self._token_estimate: Optional[int] = None

    def add_message(self, role: str, content: str) -> Message:
        message = Message(
            role=role,
            content=content,
            created_at=datetime.now().isoformat()
        )
        self.messages.append(message)
        self._token_estimate = None  # invalidate cache
        return message

    def get_messages(self) -> List[Message]:
        # 检查是否需要压缩
        if self._should_compress():
            self._compress()
        return self.messages

    def _estimate_tokens(self) -> int:
        """估算当前消息的总 token 数"""
        if self._token_estimate is not None:
            return self._token_estimate
        total_chars = sum(len(m.content) for m in self.messages)
        self._token_estimate = total_chars // self.CHARS_PER_TOKEN
        return self._token_estimate

    def _should_compress(self) -> bool:
        """判断是否需要压缩"""
        return self._estimate_tokens() > self.max_tokens * self.COMPRESS_THRESHOLD

    def _compress(self) -> None:
        """
        压缩上下文，保留关键信息。

        保留策略：
        1. system 消息全保留
        2. 最近的 KEEP_RECENT_ROUNDS 轮对话全保留
        3. 中间的消息：只保留 tool 调用的结果摘要
        """
        if len(self.messages) <= 10:
            return  # 消息太少，不压缩

        threshold = int(self.max_tokens * self.COMPRESS_THRESHOLD)
        logger.info(f"Context 压缩触发: 估算 {self._estimate_tokens()} tokens > 阈值 {threshold}")

        system_messages = [m for m in self.messages if m.role == "system"]
        other_messages = [m for m in self.messages if m.role != "system"]

        # 保留最近的 N 轮完整对话
        recent = []
        remaining = []
        if len(other_messages) > self.KEEP_RECENT_ROUNDS * 2:
            recent = other_messages[-self.KEEP_RECENT_ROUNDS * 2:]
            remaining = other_messages[:-self.KEEP_RECENT_ROUNDS * 2]
        else:
            remaining = other_messages

        # 对剩余消息进行摘要压缩
        compressed = []
        current_tokens = 0
        for msg in remaining:
            msg_tokens = len(msg.content) // self.CHARS_PER_TOKEN
            if current_tokens + msg_tokens < threshold // 2:
                # 可以保留
                if msg.role == "tool":
                    # tool 消息：保留 JSON 结构，截断 content 字段（供 MiniMax API 正确提取 tool_call_id）
                    try:
                        inner = json.loads(msg.content)
                        inner_content = inner.get("content", "")
                        inner["content"] = inner_content[:500] + ("..." if len(inner_content) > 500 else "")
                        compressed.append(Message(
                            role=msg.role,
                            content=json.dumps(inner, ensure_ascii=False),
                            created_at=msg.created_at
                        ))
                    except (json.JSONDecodeError, TypeError):
                        # JSON 解析失败时降级为纯文本截断
                        content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
                        compressed.append(Message(
                            role=msg.role,
                            content=f"[tool result] {content}",
                            created_at=msg.created_at
                        ))
                else:
                    compressed.append(msg)
                current_tokens += msg_tokens
            # 超过阈值的消息直接丢弃

        # 如果保留的最近消息以 tool 开头，说明前面的 assistant（含有 tool_calls）被截断了
        # 需要把那条 assistant 也保留，否则消息顺序会出问题
        if recent and recent[0].role == "tool" and remaining:
            last_remaining = remaining[-1]
            if last_remaining.role == "assistant":
                recent = [last_remaining] + recent

        self.messages = system_messages + compressed + recent
        self._token_estimate = None  # invalidate cache
        logger.info(f"Context 压缩完成: {len(self.messages)} 条消息")

    def get_context_str(self) -> str:
        return "\n".join([
            f"{msg.role}: {msg.content}"
            for msg in self.get_messages()
        ])

    def clear(self):
        self.messages = []
        self._token_estimate = None

    def should_compress(self) -> bool:
        """兼容旧接口"""
        return self._should_compress()

    def get_token_count(self) -> int:
        """获取当前 token 估算"""
        return self._estimate_tokens()