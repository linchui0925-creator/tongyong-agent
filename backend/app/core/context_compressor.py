"""
ContextCompressor — 自动上下文压缩

当对话历史 token 数达到模型 context window 的 50% 阈值时，
自动对中间消息进行 summarization，保留头部（系统提示）和尾部（最近消息）。

设计参数：
  - threshold_percent = 0.50（50% 满就压缩）
  - protect_first_n = 3（保护前 3 条消息）
  - protect_last_n = 20（保护后 20 条消息）
  - 使用 LLM summarization 而非简单截断
"""

import logging
from typing import List, Tuple, Optional, Any
from app.core.base import Message

logger = logging.getLogger(__name__)


class ContextCompressor:
    """自动上下文压缩引擎"""

    DEFAULT_THRESHOLD_PERCENT = 0.50   # 50% context 满触发压缩
    DEFAULT_PROTECT_FIRST = 3          # 前 N 条消息不压缩
    DEFAULT_PROTECT_LAST = 20          # 后 N 条消息不压缩
    MIN_COMPRESS_CHARS = 30000          # 不足 30000 字符不压缩（约 7500 tokens）；50% threshold=64000 tokens 时，30K 字符 ≈ 7500 tokens，两者匹配

    def __init__(
        self,
        context_length: int = 128000,
        threshold_percent: float = DEFAULT_THRESHOLD_PERCENT,
        protect_first_n: int = DEFAULT_PROTECT_FIRST,
        protect_last_n: int = DEFAULT_PROTECT_LAST,
    ):
        self.context_length = context_length
        self.threshold_percent = threshold_percent
        self.protect_first_n = protect_first_n
        self.protect_last_n = protect_last_n
        self.threshold_tokens = int(context_length * threshold_percent)
        # 压缩统计
        self._compress_count = 0
        self._last_savings_pct = 0.0

    def estimate_messages_tokens(self, messages: List[Message]) -> int:
        """估算消息列表的 token 数（粗略估计：每字符 ≈ 0.25 token）"""
        total_chars = sum(len(m.content or "") for m in messages)
        return int(total_chars * 0.25)

    def should_compress(self, messages: List[Message]) -> bool:
        """判断是否需要压缩。

        触发条件：字符数估算 tokens >= threshold_tokens（context_length * threshold_percent）
        这意味着：当已使用的 token 容量达到 threshold 时，才触发压缩。
        """
        if len(messages) <= self.protect_first_n + self.protect_last_n + 1:
            return False
        total_chars = sum(len(m.content or "") for m in messages)
        if total_chars < self.MIN_COMPRESS_CHARS:
            return False
        estimated_tokens = int(total_chars * 0.25)
        # >= threshold 时触发（精确到 threshold_tokens 时也触发，不会漏掉临界情况）
        should = estimated_tokens >= self.threshold_tokens
        if should:
            logger.warning(f"[COMPRESS] should_compress=True | messages={len(messages)}, chars={total_chars}, estimated_tokens={estimated_tokens}, threshold={self.threshold_tokens}")
        return should

    async def compress(
        self,
        messages: List[Message],
        llm,
    ) -> Tuple[List[Message], str]:
        """
        压缩中间消息，保留头部保护区和尾部消息。

        Returns:
            (压缩后的消息列表, 摘要文本)
        """
        self._compress_count += 1

        # 分离：保护前缀、保护后缀、可压缩中间部分
        protected_first = list(messages[: self.protect_first_n])
        protected_last = list(messages[-self.protect_last_n :])
        middle = messages[self.protect_first_n : -self.protect_last_n]

        logger.warning(f"[COMPRESS] start #%d | total=%d, first=%d, middle=%d, last=%d",
                       self._compress_count, len(messages), len(protected_first), len(middle), len(protected_last))

        if not middle:
            return messages, ""

        original_chars = sum(len(m.content or "") for m in middle)
        logger.warning(f"[COMPRESS] middle chars=%d, protected_first[0]=%s, protected_last[0]=%s",
                       original_chars,
                       protected_first[0].role if protected_first else "EMPTY",
                       protected_last[0].role if protected_last else "EMPTY")

        original_chars = sum(len(m.content or "") for m in middle)

        # 构建 summarization prompt
        middle_texts = []
        for i, m in enumerate(middle):
            role = m.role.upper() if m.role else "UNKNOWN"
            content = (m.content or "").strip()
            if content:
                middle_texts.append(f"[{role} {i + 1}]\n{content}")
        combined = "\n\n---\n\n".join(middle_texts)

        summary_prompt = (
            "请简洁地总结以下对话的核心内容，保留关键信息、决策和结论。\n"
            "摘要应能让后续对话连贯进行，不要丢失重要细节。\n\n"
            f"{combined}"
        )

        try:
            summary_response = await llm.chat(
                messages=[Message(role="user", content=summary_prompt)],
                tools=None,
            )
            summary_text = (summary_response.content or "").strip()
        except Exception as exc:
            logger.warning("上下文 summarization 失败，降级为截断: %s", exc)
            summary_text = f"[已压缩 {len(middle)} 条消息，原文约 {original_chars} 字符]"

        self._last_savings_pct = (
            (original_chars - len(summary_text)) / original_chars * 100
            if original_chars > 0 else 0
        )

        # 构建压缩后的消息列表
        summary_msg = Message(
            role="system",
            content=f"[上下文已压缩 — 摘要]\n{summary_text}",
        )

        # 确保 protected_last 的首条消息不是 tool（tool 必须跟在 assistant 的 tool_calls 后）
        protected_first_adjusted = list(protected_first)
        protected_last_adjusted = list(protected_last)
        if protected_last_adjusted and protected_last_adjusted[0].role == "tool":
            # 如果 protected_last 以 tool 开头，说明压缩前最后的 assistant 消息
            #（包含 tool_calls）被截断了。把被截断的 assistant 也加入保护范围。
            if middle:
                last_of_middle = middle[-1]
                if last_of_middle.role == "assistant":
                    protected_last_adjusted.insert(0, last_of_middle)

        compressed = protected_first_adjusted + [summary_msg] + protected_last_adjusted

        logger.info(
            "Context compression #%d: %d messages → 1 summary (saved %d chars, %.0f%%)",
            self._compress_count,
            len(middle),
            original_chars - len(summary_text),
            self._last_savings_pct,
        )
        logger.warning(f"[COMPRESS] done #%d | result_messages=%d, first[0]=%s, last[0]=%s",
                       self._compress_count, len(compressed),
                       compressed[0].role if compressed else "EMPTY",
                       compressed[-1].role if compressed else "EMPTY")

        return compressed, summary_text

    @property
    def stats(self) -> dict:
        return {
            "compress_count": self._compress_count,
            "last_savings_pct": round(self._last_savings_pct, 1),
            "threshold_tokens": self.threshold_tokens,
            "context_length": self.context_length,
            "threshold_percent": self.threshold_percent,
        }
