"""
ToolHarness API - 工具管理端点

基于 registry 单例，展示当前注册的所有工具及其 schema。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging

from app.tools.registry import registry, discover_builtin_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolExecutionRequest(BaseModel):
    """工具执行请求"""
    tool_name: str
    parameters: Dict[str, Any] = {}
    session_id: Optional[str] = None


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
