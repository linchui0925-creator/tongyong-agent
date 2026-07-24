"""
ToolHarness API - 工具管理端点

基于 registry 单例，展示当前注册的所有工具及其 schema。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging

from app.core.base import Message
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


def _should_ask_for_clarification(message: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    text = (message or "").strip()
    if not text:
        return {
            "should_ask": True,
            "reason": "用户输入为空",
            "questions": ["你希望我先处理什么任务？"],
        }

    questions: List[str] = []
    lowered = text.lower()

    if len(text) < 8:
        questions.append("你希望我具体帮你完成什么？")

    vague_markers = ["优化一下", "帮我弄", "处理一下", "看看这个", "改一下", "做一下", "整理一下", "分析一下"]
    if any(marker in text for marker in vague_markers):
        questions.append("你希望我优化/处理的具体对象是什么？")

    if any(marker in text for marker in ["前端", "后端", "接口", "页面", "组件", "数据库", "脚本", "文档"]) is False:
        questions.append("这次任务主要作用于哪个范围或模块？")

    if any(marker in text for marker in ["代码", "配置", "页面", "接口", "文档", "数据", "图表"]) and not any(
        marker in text for marker in ["路径", "文件", "仓库", "项目", "接口地址"]
    ):
        questions.append("如果需要修改现有内容，请给我相关文件、路径或链接。")

    if any(marker in lowered for marker in ["方案", "架构", "设计", "选型", "实现方式"]) :
        questions.append("如果有多个方案，你更偏向哪一种，还是让我推荐一个？")

    if any(marker in text for marker in ["完成", "交付", "验收", "输出"]):
        questions.append("你希望我按什么标准判断这次任务完成？")

    unique_questions = []
    for q in questions:
        if q not in unique_questions:
            unique_questions.append(q)

    should_ask = len(unique_questions) > 0 and len(text) < 80
    if not should_ask and len(unique_questions) >= 2:
        should_ask = True

    return {
        "should_ask": should_ask,
        "reason": "存在关键上下文缺口" if should_ask else "信息看起来足够",
        "questions": unique_questions[:3],
        "session_id": session_id,
    }


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


@router.post("/ask")
async def ask_clarification(message: Dict[str, Any]) -> Dict[str, Any]:
    """轻量追问判断入口"""
    raw_message = str(message.get("message") or "")
    session_id = message.get("session_id")
    decision = _should_ask_for_clarification(raw_message, session_id=session_id)
    return decision


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
