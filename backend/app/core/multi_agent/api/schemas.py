"""
Multi-Agent Team API - Pydantic 请求/响应模型
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


# ── Session ─────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    config: Dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    id: str
    name: str
    status: str
    config: Dict[str, Any] = {}
    created_at: str
    updated_at: str


# ── Role ─────────────────────────────────────────

class ToolPermissionInput(BaseModel):
    allowed_tools: List[str] = Field(default_factory=list)
    denied_tools: List[str] = Field(default_factory=list)
    max_tool_turns: int = 20


class CreateRoleRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    profile: str = Field(default="")
    watch_actions: List[str] = Field(default_factory=list)
    action_types: List[str] = Field(default_factory=list)
    action_configs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    tool_permission: ToolPermissionInput = Field(default_factory=ToolPermissionInput)
    llm_provider: str = Field(default="deepseek")
    llm_model: str = Field(default="")
    opponent_name: str = Field(default="")
    stance: str = Field(default="")  # 辩论立场（如"赞成禁止" / "反对禁止"）
    upstream_roles: List[str] = Field(default_factory=list)   # 上游 Agent 名称
    downstream_roles: List[str] = Field(default_factory=list) # 下游 Agent 名称
    template: Optional[str] = None  # 模板名称（替代以上字段快速创建）
    use_agent: bool = Field(default=False)  # Agent 模式（LangChain ReAct）


class RoleResponse(BaseModel):
    name: str
    profile: str
    watch_actions: List[str]
    action_types: List[str]
    action_configs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    tool_permission: ToolPermissionInput
    llm_provider: str
    llm_model: str
    opponent_name: str
    stance: str = ""
    upstream_roles: List[str] = Field(default_factory=list)
    downstream_roles: List[str] = Field(default_factory=list)
    use_agent: bool = False
    status: str  # hired / fired


# ── Connections ─────────────────────────────────────────

class ConnectionCreateRequest(BaseModel):
    from_role: str = Field(..., min_length=1)
    to_role: str = Field(..., min_length=1)
    match_cause: str = Field(default="")


class ConnectionResponse(BaseModel):
    id: str
    session_id: str
    from_role: str
    to_role: str
    match_cause: str = ""


# ── Run ─────────────────────────────────────────

class RunTeamRequest(BaseModel):
    idea: str = Field(..., min_length=1)
    n_round: int = Field(default=5, ge=1, le=50)
    send_to: str = Field(default="")  # 首发角色名称


class MessageItem(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    sequence: Optional[int] = None
    cause_by: str
    sent_from: str
    send_to: str


class RunTeamResponse(BaseModel):
    session_id: str
    status: str
    rounds: int
    messages: List[MessageItem]


# ── Send Message ─────────────────────────────────────────

class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    send_to: str = Field(default="")  # 空=广播


# ── Tools ─────────────────────────────────────────

class ToolInfo(BaseModel):
    name: str
    toolset: str
    description: str
    emoji: str


class ToolsetInfo(BaseModel):
    name: str
    tools: List[str]
    available: bool


class ToolsResponse(BaseModel):
    toolsets: List[ToolsetInfo]
    tools: List[ToolInfo]


# ── Role Templates ─────────────────────────────────────────

class RoleTemplateInfo(BaseModel):
    name: str
    profile: str
    watch_actions: List[str]
    action_types: List[str]


class RoleTemplatesResponse(BaseModel):
    templates: Dict[str, RoleTemplateInfo]


# ── Agent Marketplace ─────────────────────────────────────────

class AgentTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    profile: str = Field(default="")
    category: str = Field(default="")
    tags: List[str] = Field(default_factory=list)
    watch_actions: List[str] = Field(default_factory=list)
    action_types: List[str] = Field(default_factory=list)
    action_configs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    tool_permission: ToolPermissionInput = Field(default_factory=ToolPermissionInput)
    llm_provider: str = Field(default="deepseek")
    llm_model: str = Field(default="")
    opponent_name: str = Field(default="")
    stance: str = Field(default="")
    skills: List[str] = Field(default_factory=list)


class AgentTemplateResponse(BaseModel):
    id: str
    name: str
    profile: str
    category: str
    tags: List[str]
    watch_actions: List[str]
    action_types: List[str]
    action_configs: Dict[str, Dict[str, Any]]
    tool_permission: ToolPermissionInput
    llm_provider: str
    llm_model: str
    opponent_name: str
    stance: str
    skills: List[str]
    created_at: str
    updated_at: str


class ImportAgentRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    name_override: Optional[str] = None


# ── Tasks (v2 任务队列) ─────────────────────────────────────────

class TaskStatusResponse(BaseModel):
    """任务状态概览（列表用）"""
    id: str
    state: str
    task_type: str
    description: str
    assigned_to: str
    created_by: str
    priority: int
    created_at: str
    updated_at: str
    started_at: str
    completed_at: str
    result_summary: str


class TaskLinkResponse(BaseModel):
    """任务依赖边"""
    id: str
    parent_id: str
    child_id: str
    link_type: str


class TaskDetailResponse(BaseModel):
    """任务详情"""
    id: str
    session_id: str
    state: str
    task_type: str
    description: str
    assigned_to: str
    created_by: str
    workspace_path: str
    input_summary: str
    result_summary: str
    priority: int
    created_at: str
    updated_at: str
    started_at: str
    completed_at: str
    links: List[TaskLinkResponse] = Field(default_factory=list)


class WorkspaceFileResponse(BaseModel):
    """workspace 文件内容"""
    task_id: str
    file_path: str
    content: str
    size: int


# ── New: create session with v2 tables init ─────────────────────────────────

class CreateSessionV2Request(BaseModel):
    """创建 v2 会话（同时初始化任务队列表）"""
    name: str = Field(..., min_length=1, max_length=100)
    config: Dict[str, Any] = Field(default_factory=dict)
    mode: str = Field(default="pipeline")  # pipeline | debate
    max_concurrent: int = Field(default=4, ge=1, le=16)
    claim_ttl_seconds: int = Field(default=300, ge=30, le=3600)
