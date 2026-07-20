"""
trace API - W5-7 Runtime trace 查询路由

只读查询, 供前端/运维查看每条 chat 请求的 span 时间线。
- GET /api/trace/session/{session_id}  列出会话的 trace
- GET /api/trace/{trace_id}            单条 trace 的 span 时间线
所有查询失败降级为空结果, 绝不影响主流程。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.runtime import trace as rt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trace", tags=["trace"])


@router.get("/session/{session_id}")
async def list_session_traces(session_id: str, limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    store = rt.get_store()
    if store is None:
        return {"session_id": session_id, "enabled": False, "traces": []}
    try:
        traces = store.list_traces(session_id=session_id, limit=limit)
    except Exception as e:  # 查询失败降级
        logger.debug(f"list_session_traces failed: {e}")
        traces = []
    return {"session_id": session_id, "enabled": rt.is_enabled(), "traces": traces}


@router.get("/{trace_id}")
async def get_trace_timeline(trace_id: str) -> Dict[str, Any]:
    store = rt.get_store()
    if store is None:
        raise HTTPException(status_code=404, detail="runtime trace 未启用")
    try:
        trace = store.get_trace(trace_id)
    except Exception as e:
        logger.debug(f"get_trace failed: {e}")
        trace = None
    if not trace:
        raise HTTPException(status_code=404, detail="trace 不存在")
    try:
        spans = store.get_spans(trace_id)
    except Exception as e:
        logger.debug(f"get_spans failed: {e}")
        spans = []
    return {"trace": trace, "spans": spans}


@router.get("")
async def list_traces(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    store = rt.get_store()
    if store is None:
        return {"enabled": False, "traces": []}
    try:
        traces = store.list_traces(limit=limit)
    except Exception as e:
        logger.debug(f"list_traces failed: {e}")
        traces = []
    return {"enabled": rt.is_enabled(), "traces": traces}
