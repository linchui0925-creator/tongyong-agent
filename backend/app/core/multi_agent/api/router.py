"""
Multi-Agent Team API - FastAPI 路由
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from typing import List
import json
import logging

from app.core.multi_agent.api.schemas import (
    CreateSessionRequest, SessionResponse,
    CreateRoleRequest, RoleResponse, ToolPermissionInput,
    RunTeamRequest, RunTeamResponse, MessageItem,
    SendMessageRequest, ToolsResponse, ToolsetInfo, ToolInfo, RoleTemplatesResponse,
    AgentTemplateRequest, AgentTemplateResponse, ImportAgentRequest,
    ConnectionCreateRequest, ConnectionResponse,
)
from app.core.multi_agent.api import service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/team", tags=["multi_agent"])


# ── Session ─────────────────────────────────────────

@router.post("/sessions", response_model=SessionResponse)
async def create_session(req: CreateSessionRequest):
    """创建新的团队会话"""
    session = service.create_session(req.name, req.config)
    return SessionResponse(**session)


@router.get("/sessions", response_model=List[SessionResponse])
async def list_sessions():
    """列出所有团队会话"""
    sessions = service.list_sessions()
    return [SessionResponse(**s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取会话详情"""
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return SessionResponse(**session)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    await service.delete_session(session_id)
    return {"ok": True}


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str):
    """主动终止正在运行的团队流水线"""
    ok = service.stop_team(session_id)
    return {"ok": ok}


# ── Role ─────────────────────────────────────────

@router.post("/sessions/{session_id}/roles", response_model=RoleResponse)
async def add_role(session_id: str, req: CreateRoleRequest):
    """向会话添加 Agent"""
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    try:
        params = req.model_dump()
        result = service.add_role(session_id, params)
        return RoleResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{session_id}/roles", response_model=List[RoleResponse])
async def list_roles(session_id: str):
    """列出会话中的所有 Agent"""
    roles = service.get_roles(session_id)
    return [RoleResponse(**r) for r in roles]


@router.delete("/sessions/{session_id}/roles/{role_name}")
async def delete_role(session_id: str, role_name: str):
    """移除 Agent"""
    service.delete_role(session_id, role_name)
    return {"ok": True}


@router.put("/sessions/{session_id}/roles/{role_name}", response_model=RoleResponse)
async def update_role(session_id: str, role_name: str, req: CreateRoleRequest):
    """更新 Agent 配置（身份信息 + 连接图）"""
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        params = req.model_dump()
        result = service.update_role(session_id, role_name, params)
        return RoleResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Connections ─────────────────────────────────────────

@router.post("/sessions/{session_id}/connections", response_model=ConnectionResponse)
async def create_connection(session_id: str, req: ConnectionCreateRequest):
    """创建 Agent 连接边（上游→下游）"""
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        result = service.add_connection(session_id, req.from_role, req.to_role, req.match_cause)
        return ConnectionResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{session_id}/connections", response_model=List[ConnectionResponse])
async def list_connections(session_id: str):
    """列出会话中的所有连接边"""
    conns = service.list_connections(session_id)
    return [ConnectionResponse(**c) for c in conns]


@router.delete("/sessions/{session_id}/connections")
async def delete_connection(session_id: str, from_role: str, to_role: str):
    """删除连接边"""
    service.delete_connection(session_id, from_role, to_role)
    return {"ok": True}


# ── Run ─────────────────────────────────────────

@router.post("/sessions/{session_id}/run", response_model=RunTeamResponse)
async def run_team(session_id: str, req: RunTeamRequest):
    """运行团队协作"""
    result = await service.run_team(
        session_id=session_id,
        idea=req.idea,
        n_round=req.n_round,
        send_to=req.send_to,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    messages = [
        MessageItem(
            id=m["id"],
            role=m["role"],
            content=m["content"],
            created_at=m["created_at"],
            sequence=m.get("sequence"),
            cause_by=m.get("cause_by", ""),
            sent_from=m.get("sent_from", ""),
            send_to=m.get("send_to", ""),
        )
        for m in result.get("messages", [])
    ]

    return RunTeamResponse(
        session_id=session_id,
        status=result["status"],
        rounds=result["rounds"],
        messages=messages,
    )


@router.get("/sessions/{session_id}/run/stream")
async def run_team_stream(
    session_id: str,
    idea: str,
    n_round: int = 5,
    send_to: str = "",
):
    """流式运行团队协作，SSE 实时推送每条消息"""
    async def generate():
        try:
            async for event in service.run_team_stream(
                session_id=session_id,
                idea=idea,
                n_round=n_round,
                send_to=send_to,
            ):
                yield {
                    "event": event["type"],
                    "data": json.dumps(event, ensure_ascii=False),
                }
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"type": "error", "message": str(e)})}

    return EventSourceResponse(generate())


# ── Messages ─────────────────────────────────────────

@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    """获取消息历史"""
    msgs = service.get_messages(session_id)
    return {"messages": [m.model_dump() for m in msgs]}


@router.post("/sessions/{session_id}/messages/send")
async def send_message(session_id: str, req: SendMessageRequest):
    """发送消息（用户输入）"""
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    result = await service.send_message(session_id, req.content, req.send_to)
    return result


# ── Tools & Templates ─────────────────────────────────────────

@router.get("/tools", response_model=ToolsResponse)
async def get_all_tools():
    """获取所有可用工具（用于权限配置）"""
    result = service.get_all_tools()
    return ToolsResponse(
        toolsets=[ToolsetInfo(**ts) for ts in result["toolsets"]],
        tools=[ToolInfo(**t) for t in result["tools"]],
    )


@router.get("/roles/templates", response_model=RoleTemplatesResponse)
async def get_role_templates():
    """获取角色模板列表"""
    result = service.get_role_templates()
    return RoleTemplatesResponse(**result)


# ── Agent Marketplace ─────────────────────────────────────────

@router.post("/marketplace", response_model=AgentTemplateResponse)
async def create_marketplace_agent(req: AgentTemplateRequest):
    """创建市场 Agent"""
    try:
        result = service.create_agent_template(req.model_dump())
        return AgentTemplateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/marketplace", response_model=List[AgentTemplateResponse])
async def list_marketplace_agents():
    """列出所有市场 Agent"""
    agents = service.list_agent_templates()
    return [AgentTemplateResponse(**a) for a in agents]


@router.get("/marketplace/categories", response_model=List[str])
async def list_marketplace_categories():
    """列出所有市场分类"""
    return service.list_marketplace_categories()


@router.get("/marketplace/skills/list")
async def list_marketplace_skills():
    """列出所有可用技能"""
    return {"skills": service.list_marketplace_skills()}


@router.get("/marketplace/{agent_id}", response_model=AgentTemplateResponse)
async def get_marketplace_agent(agent_id: str):
    """获取市场 Agent 详情"""
    agent = service.get_agent_template(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return AgentTemplateResponse(**agent)


@router.put("/marketplace/{agent_id}", response_model=AgentTemplateResponse)
async def update_marketplace_agent(agent_id: str, req: AgentTemplateRequest):
    """更新市场 Agent"""
    try:
        result = service.update_agent_template(agent_id, req.model_dump())
        return AgentTemplateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/marketplace/{agent_id}")
async def delete_marketplace_agent(agent_id: str):
    """删除市场 Agent"""
    try:
        service.delete_agent_template(agent_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/marketplace/{agent_id}/import")
async def import_marketplace_agent(agent_id: str, req: ImportAgentRequest):
    """从市场导入 Agent 到会话"""
    try:
        result = service.import_agent_to_session(
            session_id=req.session_id,
            template_id=agent_id,
            name_override=req.name_override,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))