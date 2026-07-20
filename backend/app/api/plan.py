"""Plan API - W5-8 显式规划器路由

POST /api/plan/build  {goal, provider?, model?} → Plan JSON
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from app.core.runtime.planner import build_plan_from_llm, build_plan_heuristic
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plan", tags=["plan"])


@router.post("/build")
async def build_plan(
    goal: str = Body(..., embed=True),
    provider: Optional[str] = Body(None),
    model: Optional[str] = Body(None),
):
    if not goal or not goal.strip():
        raise HTTPException(400, "goal 不能为空")
    goal = goal.strip()

    if not getattr(settings, "runtime_planner_enabled", False):
        plan = build_plan_heuristic(goal)
    else:
        try:
            from app.llm.factory import get_llm as _factory_get_llm
            llm = _factory_get_llm(provider=provider, model=model)
        except Exception as e:
            logger.debug(f"plan build llm 获取失败, 用 heuristic 兜底: {e}")
            plan = build_plan_heuristic(goal)
        else:
            plan = await build_plan_from_llm(goal, llm)

    # 持久化到 trace store, 供后续 stream 按 plan_id 加载
    try:
        from app.core.runtime import trace as _rt
        _store = _rt.get_store()
        if _store is not None:
            _store.save_plan(plan.plan_id, plan.goal,
                             [s.to_dict() for s in plan.steps])
    except Exception as _pe:
        logger.debug(f"plan persist skipped: {_pe}")

    return plan.to_dict()
