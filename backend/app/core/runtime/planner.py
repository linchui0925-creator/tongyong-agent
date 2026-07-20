"""Runtime Planner (W5-8) — 显式多步 Action 规划器

参考架构里的 "规划模块 Planner": LLM 拆解复杂任务 → 生成多步骤 Action 列表,
执行过程中跟踪每步状态, 支持重规划。

与现有实现的关系:
  - `todo_tools` 是给**模型自己**维护 checklist 的工具; 这里的 Planner 是**runtime 侧**
    的一等公民数据结构 + 生命周期管理, 可被 agent 循环/reflection/trace 直接消费。
  - 不强绑 LLM: `build_plan_from_llm` 走注入的 llm; 无 llm 或解析失败时
    `build_plan_heuristic` 给一个单步兜底计划, 保证 runtime 永远有计划可跟踪。

落库: 复用 runtime trace — `plan.build` / `plan.step` span; Plan 本身内存态,
需要持久化时调用方自行落库 (MVP 不引入新表)。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    index: int
    action: str
    tool: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    result: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "tool": self.tool,
            "status": self.status.value,
            "result": self.result,
            "note": self.note,
        }


@dataclass
class Plan:
    plan_id: str
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    created_ts: float = field(default_factory=time.time)

    # ── 状态查询 ──
    @property
    def is_complete(self) -> bool:
        return all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps) if self.steps else False

    @property
    def has_failure(self) -> bool:
        return any(s.status == StepStatus.FAILED for s in self.steps)

    def current_step(self) -> Optional[PlanStep]:
        for s in self.steps:
            if s.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS):
                return s
        return None

    def progress(self) -> Dict[str, int]:
        done = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        return {"completed": done, "total": len(self.steps)}

    # ── 状态推进 ──
    def start_step(self, index: int) -> Optional[PlanStep]:
        step = self._get(index)
        if step:
            step.status = StepStatus.IN_PROGRESS
            _emit_step_span(self, step)
        return step

    def complete_step(self, index: int, result: Optional[str] = None) -> Optional[PlanStep]:
        step = self._get(index)
        if step:
            step.status = StepStatus.COMPLETED
            step.result = result
            _emit_step_span(self, step)
        return step

    def fail_step(self, index: int, note: Optional[str] = None) -> Optional[PlanStep]:
        step = self._get(index)
        if step:
            step.status = StepStatus.FAILED
            step.note = note
            _emit_step_span(self, step)
        return step

    def skip_step(self, index: int, note: Optional[str] = None) -> Optional[PlanStep]:
        step = self._get(index)
        if step:
            step.status = StepStatus.SKIPPED
            step.note = note
        return step

    def replan(self, new_steps: List[Dict[str, Any]]) -> None:
        """保留已完成步骤, 用新步骤替换未完成部分 (重规划)。"""
        kept = [s for s in self.steps if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)]
        start = len(kept)
        appended = _steps_from_dicts(new_steps, start_index=start + 1)
        self.steps = kept + appended

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "progress": self.progress(),
            "is_complete": self.is_complete,
            "has_failure": self.has_failure,
        }

    def _get(self, index: int) -> Optional[PlanStep]:
        for s in self.steps:
            if s.index == index:
                return s
        return None


# ── 构建 ──────────────────────────────────────────

_MAX_STEPS = 20


def _steps_from_dicts(items: List[Dict[str, Any]], start_index: int = 1) -> List[PlanStep]:
    steps: List[PlanStep] = []
    for i, item in enumerate(items[:_MAX_STEPS], start=start_index):
        if isinstance(item, str):
            action, tool = item, None
        else:
            action = str(item.get("action") or item.get("step") or "").strip()
            tool = item.get("tool")
        if not action:
            continue
        steps.append(PlanStep(index=i, action=action, tool=tool))
    return steps


def build_plan_heuristic(goal: str) -> Plan:
    """无 LLM 兜底: 单步计划, 保证 runtime 永远有可跟踪计划。"""
    plan = Plan(plan_id=uuid.uuid4().hex, goal=goal)
    plan.steps = [PlanStep(index=1, action=goal.strip() or "完成用户请求")]
    return plan


_PLAN_PROMPT = (
    "你是任务规划器。把下面的用户目标拆成有序、可执行的步骤 (最多 {max} 步)。"
    "每步是一个具体动作, 如果该步需要调用某个工具, 给出 tool 名。"
    '只输出 JSON: {{"steps": [{{"action": "...", "tool": "可选工具名或null"}}]}}。'
    "不要输出任何解释。\n\n用户目标:\n{goal}"
)


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    # 直接尝试
    try:
        return json.loads(text)
    except Exception:
        pass
    # 提取第一个 {...} 块
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


async def build_plan_from_llm(goal: str, llm: Any, max_steps: int = _MAX_STEPS) -> Plan:
    """用注入的 llm 生成结构化计划; 失败回退到 heuristic。

    llm 需实现 `async chat(messages=[...])` 返回带 `.content` 的对象 (跟项目 BaseLLM 一致)。
    """
    _rt = _get_trace_mod()
    span_cm = _rt.start_span("plan.build", {"goal": goal[:200]}) if _rt else None
    span = span_cm.__enter__() if span_cm else None
    try:
        if llm is None:
            plan = build_plan_heuristic(goal)
            _tag_span(span, plan, source="heuristic")
            return plan
        prompt = _PLAN_PROMPT.format(goal=goal, max=max_steps)
        try:
            from app.core.base import Message
            messages = [Message(role="user", content=prompt)]
        except Exception:
            messages = [{"role": "user", "content": prompt}]
        try:
            resp = await llm.chat(messages=messages, tools=None)
            content = getattr(resp, "content", None) or ""
        except Exception as e:
            logger.debug(f"planner llm failed: {e}")
            plan = build_plan_heuristic(goal)
            _tag_span(span, plan, source="heuristic_llm_error")
            return plan
        data = _extract_json(content)
        raw_steps = (data or {}).get("steps") if isinstance(data, dict) else None
        if not raw_steps:
            plan = build_plan_heuristic(goal)
            _tag_span(span, plan, source="heuristic_parse_fail")
            return plan
        plan = Plan(plan_id=uuid.uuid4().hex, goal=goal)
        plan.steps = _steps_from_dicts(raw_steps)
        if not plan.steps:
            plan = build_plan_heuristic(goal)
            _tag_span(span, plan, source="heuristic_empty")
            return plan
        _tag_span(span, plan, source="llm")
        return plan
    finally:
        if span_cm is not None:
            span_cm.__exit__(None, None, None)


def _tag_span(span, plan: Plan, source: str) -> None:
    if span is not None:
        span.attributes["source"] = source
        span.attributes["step_count"] = len(plan.steps)
        span.attributes["plan_id"] = plan.plan_id


def _emit_step_span(plan: Plan, step: PlanStep) -> None:
    _rt = _get_trace_mod()
    if _rt is None:
        return
    try:
        _rt.record_span(
            "plan.step",
            0.0,
            status="error" if step.status == StepStatus.FAILED else "ok",
            attributes={
                "plan_id": plan.plan_id,
                "index": step.index,
                "status": step.status.value,
                "tool": step.tool,
            },
        )
    except Exception:
        pass


def _get_trace_mod():
    try:
        from app.core.runtime import trace as _rt
        return _rt
    except Exception:
        return None
