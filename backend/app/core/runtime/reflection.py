"""Runtime Reflection (W5-8) — 统一反思 / 结果校验组件

参考架构里的 "反思模块 Reflection": 校验工具结果、判断任务是否完成、失败重试、
修正行动方案。项目里原本散在 `delivery_gate` (证据门禁) + `agent.py`
(_validate_execution_claim / must_use_tool retry) 里, 这里收敛成一个可复用的
`Reflector`, 给出统一的 `ReflectionVerdict`。

判定维度:
  1. 执行声明校验: 声称"已执行"却无工具证据 → 需修正 (revise)
  2. 交付证据校验: 高风险任务缺写文件/build 证据 → 需继续/重试 (retry)
  3. 工具错误: 最近工具结果是错误 → 需重试 (retry)
  4. 空回复: 无内容且无工具 → 需重试 (retry)
  否则 → 完成 (complete)

复用 `delivery_gate` 的原子函数, 不重复实现规则; 只做编排 + trace 埋点。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.delivery_gate import (
    _classify_error_type,
    _is_error_result,
    _missing_tool_evidence,
    _required_tool_evidence,
    _validate_execution_claim,
)

logger = logging.getLogger(__name__)


class Decision(str, Enum):
    COMPLETE = "complete"   # 任务达成, 可收尾
    RETRY = "retry"         # 重试 (继续调用工具 / 补证据)
    REVISE = "revise"       # 修正回复 (声明与证据不符)


@dataclass
class ReflectionVerdict:
    decision: Decision
    reasons: List[str] = field(default_factory=list)
    correction: Optional[str] = None
    missing_evidence: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.decision == Decision.COMPLETE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": self.reasons,
            "correction": self.correction,
            "missing_evidence": self.missing_evidence,
        }


@dataclass
class Reflector:
    """统一反思器。无状态, 可进程级复用。"""

    def reflect(
        self,
        user_message: str,
        response_text: str,
        tools_used: Optional[List[str]] = None,
        commands_executed: Optional[List[str]] = None,
        last_tool_result: Optional[str] = None,
    ) -> ReflectionVerdict:
        tools_used = tools_used or []
        commands_executed = commands_executed or []

        _rt = _get_trace_mod()
        span_cm = _rt.start_span("reflection.reflect") if _rt else None
        span = span_cm.__enter__() if span_cm else None

        reasons: List[str] = []
        try:
            # 1. 最近工具结果是错误 → 重试
            if last_tool_result is not None and _is_error_result(last_tool_result):
                verdict = ReflectionVerdict(
                    decision=Decision.RETRY,
                    reasons=[f"最近工具结果为错误 ({_classify_error_type(last_tool_result)})"],
                )
                return self._finish(span, span_cm, verdict)

            # 2. 执行声明与工具证据不符 → 修正
            is_valid, correction = _validate_execution_claim(
                response_text, tools_used, commands_executed
            )
            if not is_valid:
                verdict = ReflectionVerdict(
                    decision=Decision.REVISE,
                    reasons=["回复声称已执行但本轮无工具证据"],
                    correction=correction,
                )
                return self._finish(span, span_cm, verdict)

            # 3. 高风险任务缺交付证据 → 重试
            requirements = _required_tool_evidence(user_message)
            missing = _missing_tool_evidence(requirements, tools_used, commands_executed)
            if missing and (response_text or "").strip():
                verdict = ReflectionVerdict(
                    decision=Decision.RETRY,
                    reasons=["任务缺少真实交付证据"],
                    missing_evidence=missing,
                )
                return self._finish(span, span_cm, verdict)

            # 4. 空回复且无工具 → 重试
            if not (response_text or "").strip() and not tools_used and not commands_executed:
                verdict = ReflectionVerdict(
                    decision=Decision.RETRY,
                    reasons=["本轮既无可见回复也无工具调用"],
                )
                return self._finish(span, span_cm, verdict)

            # 否则完成
            return self._finish(span, span_cm, ReflectionVerdict(decision=Decision.COMPLETE))
        except Exception as e:  # 反思绝不能打断主流程 → 保守判完成
            logger.debug(f"reflection failed, defaulting complete: {e}")
            return self._finish(span, span_cm, ReflectionVerdict(
                decision=Decision.COMPLETE, reasons=[f"reflection error: {type(e).__name__}"]
            ))

    def _finish(self, span, span_cm, verdict: ReflectionVerdict) -> ReflectionVerdict:
        if span is not None:
            span.attributes["decision"] = verdict.decision.value
            span.attributes["reasons"] = verdict.reasons
            if verdict.missing_evidence:
                span.attributes["missing_evidence"] = verdict.missing_evidence
        if span_cm is not None:
            span_cm.__exit__(None, None, None)
        return verdict


_DEFAULT_REFLECTOR: Optional[Reflector] = None


def get_reflector() -> Reflector:
    global _DEFAULT_REFLECTOR
    if _DEFAULT_REFLECTOR is None:
        _DEFAULT_REFLECTOR = Reflector()
    return _DEFAULT_REFLECTOR


def _get_trace_mod():
    try:
        from app.core.runtime import trace as _rt
        return _rt
    except Exception:
        return None
