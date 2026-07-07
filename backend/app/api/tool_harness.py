"""
ToolHarness API - 工具管理端点

基于 registry 单例，展示当前注册的所有工具及其 schema。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging

from app.tools.registry import registry, discover_builtin_tools
from app.tools.approval import ApprovalManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolExecutionRequest(BaseModel):
    """工具执行请求"""
    tool_name: str
    parameters: Dict[str, Any] = {}
    session_id: Optional[str] = None


class ApprovalActionRequest(BaseModel):
    approval_id: str
    action: str
    reason: Optional[str] = None


def _ensure_tools_discovered():
    """确保工具已加载"""
    if not registry.get_all_tool_names():
        discover_builtin_tools()


@router.get("")
async def list_tools() -> Dict[str, Any]:
    """获取所有注册的工具列表"""
    _ensure_tools_discovered()
    names = registry.get_all_tool_names()
    schemas = registry.get_schemas()
    return {
        "total": len(names),
        "tools": names,
        "schemas": schemas,
    }


@router.post("/execute")
async def execute_tool(request: ToolExecutionRequest) -> Dict[str, Any]:
    """执行工具"""
    _ensure_tools_discovered()
    entry = registry.get_entry(request.tool_name)
    if not entry:
        raise HTTPException(status_code=404, detail=f"工具 '{request.tool_name}' 不存在")

    try:
        result = await registry.execute(request.tool_name, request.parameters)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"工具执行失败: {request.tool_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/pending")
async def list_pending_approvals(session_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    manager = ApprovalManager()
    approvals = await manager.get_pending_requests(session_id=session_id, limit=limit)
    return {
        "approvals": [
            {
                "id": a.id,
                "tool_id": a.tool_id,
                "session_id": a.session_id,
                "user_id": a.user_id,
                "parameters": a.parameters,
                "risk_assessment": a.risk_assessment or {},
                "status": a.status,
                "approval_mode": a.approval_mode,
                "expires_at": a.expires_at,
                "created_at": a.created_at,
            }
            for a in approvals
        ]
    }


@router.post("/approvals")
async def resolve_approval(request: ApprovalActionRequest) -> Dict[str, Any]:
    manager = ApprovalManager()
    action = request.action.lower().strip()
    if action == "approve":
        result = await manager.approve(request.approval_id, approved_by="user")
    elif action == "reject":
        result = await manager.reject(
            request.approval_id,
            rejected_by="user",
            reason=request.reason or "用户拒绝",
        )
    else:
        raise HTTPException(status_code=400, detail="action 必须是 approve 或 reject")

    return result.to_dict()


@router.get("/{tool_name}")
async def get_tool(tool_name: str) -> Dict[str, Any]:
    """获取指定工具详情"""
    _ensure_tools_discovered()
    entry = registry.get_entry(tool_name)
    if not entry:
        raise HTTPException(status_code=404, detail=f"工具 '{tool_name}' 不存在")
    return {
        "name": entry.name,
        "description": entry.description,
        "schema": entry.schema,
        "emoji": entry.emoji,
        "max_result_size_chars": entry.max_result_size_chars,
    }
