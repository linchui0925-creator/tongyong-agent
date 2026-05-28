"""
Multi-Agent Team API - 业务逻辑服务
"""

from typing import Dict, List, Optional, Any
import logging
import asyncio

from app.core.multi_agent.session_store import TeamSessionStore
from app.core.multi_agent.team import Team
from app.core.multi_agent.role import TeamRole, ROLE_TEMPLATES
from app.core.multi_agent.tool_permission import ToolPermission
from app.core.multi_agent.message import TeamMessage, new_message

logger = logging.getLogger(__name__)

# 全局会话存储
_store: Optional[TeamSessionStore] = None
# 会话 ID → Team 实例（内存中运行中的 Team）
_active_teams: Dict[str, Team] = {}
_teams_lock = asyncio.Lock()


def get_store() -> TeamSessionStore:
    global _store
    if _store is None:
        _store = TeamSessionStore()
    return _store


def get_active_team(session_id: str) -> Optional[Team]:
    return _active_teams.get(session_id)


async def set_active_team(session_id: str, team: Team):
    async with _teams_lock:
        _active_teams[session_id] = team


async def remove_active_team(session_id: str):
    async with _teams_lock:
        _active_teams.pop(session_id, None)


# ── Session ─────────────────────────────────────────

def create_session(name: str, config: dict = None) -> Dict[str, Any]:
    session = get_store().create_session(name, config)
    logger.info(f"[SERVICE] 创建会话: {session['id']} ({name})")
    return session


def list_sessions() -> List[Dict[str, Any]]:
    return get_store().list_sessions()


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    return get_store().get_session(session_id)


async def delete_session(session_id: str):
    # 清除内存中的 Team
    await remove_active_team(session_id)
    get_store().delete_session(session_id)
    logger.info(f"[SERVICE] 删除会话: {session_id}")


def stop_team(session_id: str) -> bool:
    """主动终止正在运行的团队流水线"""
    team = get_active_team(session_id)
    if not team:
        return False
    team.stop()
    return True


# ── Role ─────────────────────────────────────────

def add_role(session_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    # 支持从模板创建
    template = params.get("template")
    if template and template in ROLE_TEMPLATES:
        tpl = dict(ROLE_TEMPLATES[template])
        # 合并用户覆盖的参数
        for k in ["name", "profile", "watch_actions", "action_types"]:
            if params.get(k):
                tpl[k] = params[k]
        if params.get("opponent_name"):
            tpl["opponent_name"] = params["opponent_name"]
        if params.get("stance"):
            tpl["stance"] = params["stance"]
        role = TeamRole.create(**tpl)
        # 模板创建时自动填充上下游连接
        from app.core.multi_agent.role import get_default_connections
        up, down = get_default_connections(template)
        # 使用模板默认连接，仅当用户显式提供非空值时才覆盖
        role.upstream_roles = params["upstream_roles"] if params.get("upstream_roles") else up
        role.downstream_roles = params["downstream_roles"] if params.get("downstream_roles") else down
    else:
        tool_perm = params.get("tool_permission", {})
        role = TeamRole.create(
            name=params["name"],
            profile=params.get("profile", ""),
            watch_actions=params.get("watch_actions", []),
            action_types=params.get("action_types", []),
            action_configs=params.get("action_configs", {}),
            tool_permission=ToolPermission(
                allowed_tools=tool_perm.get("allowed_tools", []),
                denied_tools=tool_perm.get("denied_tools", []),
                max_tool_turns=tool_perm.get("max_tool_turns", 20),
            ),
            llm_provider=params.get("llm_provider", "deepseek"),
            llm_model=params.get("llm_model", ""),
            opponent_name=params.get("opponent_name", ""),
            stance=params.get("stance", ""),
            upstream_roles=params.get("upstream_roles", []),
            downstream_roles=params.get("downstream_roles", []),
        )

    get_store().add_role(session_id, role)
    logger.info(f"[SERVICE] 添加角色: {role.name} → 会话 {session_id}")
    return {
        "name": role.name, "profile": role.profile,
        "watch_actions": role.watch_actions,
        "action_types": role.action_types,
        "action_configs": role.action_configs,
        "tool_permission": role.tool_permission.model_dump(),
        "llm_provider": role.llm_provider,
        "llm_model": role.llm_model,
        "opponent_name": role.opponent_name,
        "stance": role.stance,
        "status": "hired",
    }


def get_roles(session_id: str) -> List[Dict[str, Any]]:
    roles = get_store().get_roles(session_id)
    return [
        {
            "name": r.name, "profile": r.profile,
            "watch_actions": r.watch_actions,
            "action_types": r.action_types,
            "action_configs": r.action_configs,
            "tool_permission": r.tool_permission.model_dump(),
            "llm_provider": r.llm_provider,
            "llm_model": r.llm_model,
            "opponent_name": r.opponent_name,
            "stance": r.stance,
            "status": "hired",
        }
        for r in roles
    ]


def delete_role(session_id: str, role_name: str):
    get_store().delete_role(session_id, role_name)
    logger.info(f"[SERVICE] 删除角色: {role_name} ← 会话 {session_id}")


def update_role(session_id: str, role_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """更新 Agent 配置（身份信息 + 连接图）"""
    store = get_store()
    role = store.update_role(session_id, role_name, params)
    if not role:
        raise ValueError(f"Agent 不存在: {role_name}")

    logger.info(f"[SERVICE] 更新角色: {role_name}")
    return {
        "name": role.name, "profile": role.profile,
        "watch_actions": role.watch_actions,
        "action_types": role.action_types,
        "action_configs": role.action_configs,
        "tool_permission": role.tool_permission.model_dump(),
        "llm_provider": role.llm_provider,
        "llm_model": role.llm_model,
        "opponent_name": role.opponent_name,
        "stance": role.stance,
        "upstream_roles": role.upstream_roles,
        "downstream_roles": role.downstream_roles,
        "status": "hired",
    }


    # ── 构建 Team 实例 ─────────────────────────────────────────

def _build_team(session_id: str, session: Dict[str, Any], roles: List[TeamRole]) -> Team:
    """根据会话和角色列表构建 Team 实例，对手辩论角色做 special patch"""
    from app.core.multi_agent.role import create_role_from_template, get_default_connections

    config = session.get("config", {})
    mode = config.get("mode", "pipeline")
    # 向后兼容：旧的 leader_pipeline 模式统一为 pipeline
    if mode == "leader_pipeline":
        mode = "pipeline"
    timeout = config.get("timeout", 0)
    team = Team(name=session["name"], mode=mode, timeout=timeout)

    # 图路由模式：无角色时自动配置四角色（含默认连接图）
    if mode == "pipeline" and not roles:
        logger.info(f"[SERVICE] 流水线模式，自动配置 Leader/Coder/Tester/Reviewer")
        for tpl_name in ("leader", "coder", "tester", "reviewer"):
            role = create_role_from_template(tpl_name)
            # 填充默认上下游连接
            up, down = get_default_connections(tpl_name)
            role.upstream_roles = up
            role.downstream_roles = down
            logger.info(f"[SERVICE]   创建角色 {role.name}: upstream={role.upstream_roles}, downstream={role.downstream_roles}")
            team.hire(role)
    else:
        logger.info(f"[SERVICE] 使用会话已有角色 (count={len(roles)}, mode={mode})")
        for role in roles:
            logger.info(f"[SERVICE]   角色 {role.name}: upstream={role.upstream_roles}, downstream={role.downstream_roles}, actions={role.action_types}")
            # 如果角色有对手名（辩论场景），应用辩论覆盖
            if role.opponent_name:
                role.make_debate_role(opponent_name=role.opponent_name)
                # 辩论角色还需要监听 SpeakAloud（对手发言）
                role.add_watch_action("SpeakAloud")
            team.hire(role)
    return team


# ── Connections ─────────────────────────────────────────

def add_connection(session_id: str, from_role: str, to_role: str, match_cause: str = "") -> Dict[str, Any]:
    """添加连接边（上游→下游），同时同步更新两个角色的 upstream/downstream 字段"""
    store = get_store()
    # 验证两个角色都存在
    roles = store.get_roles(session_id)
    role_names = {r.name for r in roles}
    if from_role not in role_names:
        raise ValueError(f"源角色不存在: {from_role}")
    if to_role not in role_names:
        raise ValueError(f"目标角色不存在: {to_role}")

    # 持久化到 team_connections 表
    conn = store.add_connection(session_id, from_role, to_role, match_cause)

    # 同步更新 from_role 的 downstream_roles 和 to_role 的 upstream_roles
    store.update_role_connections(session_id, from_role, to_role)

    logger.info(f"[SERVICE] 添加连接: {from_role} → {to_role}")
    return conn


def list_connections(session_id: str) -> List[Dict[str, Any]]:
    return get_store().get_connections(session_id)


def delete_connection(session_id: str, from_role: str, to_role: str):
    store = get_store()
    store.delete_connection(session_id, from_role, to_role)
    # 同步更新两个角色的 upstream/downstream 字段
    store.update_role_connections(session_id, from_role, to_role)
    logger.info(f"[SERVICE] 删除连接: {from_role} → {to_role}")


# ── Run ─────────────────────────────────────────

async def run_team_stream(
    session_id: str, idea: str, n_round: int = 5, send_to: str = ""
):
    """流式运行团队协作流程（生成器）"""
    session = get_store().get_session(session_id)
    if not session:
        yield {"type": "error", "message": f"会话不存在: {session_id}"}
        return

    roles = get_store().get_roles(session_id)

    team = _build_team(session_id, session, roles)

    await set_active_team(session_id, team)
    get_store().update_session_status(session_id, "running")

    try:
        async for msg in team.run_stream(idea=idea, n_round=n_round, send_to=send_to):
            yield {
                "type": "message",
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at,
                "sequence": msg.sequence,
                "cause_by": msg.cause_by,
                "sent_from": msg.sent_from,
                "send_to": msg.send_to,
            }
            get_store().add_message(session_id, msg)

        get_store().update_session_status(session_id, "completed")
        yield {"type": "done", "rounds": team._round}

    except Exception as e:
        logger.exception("流式运行异常")
        get_store().update_session_status(session_id, "error")
        yield {"type": "error", "message": str(e)}
    finally:
        await remove_active_team(session_id)


# ── Run ─────────────────────────────────────────

async def run_team(
    session_id: str, idea: str, n_round: int = 5, send_to: str = ""
) -> Dict[str, Any]:
    """运行团队协作流程"""
    # 1. 获取会话和角色
    session = get_store().get_session(session_id)
    if not session:
        return {"error": f"会话不存在: {session_id}"}

    roles = get_store().get_roles(session_id)

    # 2. 构建 Team 实例（roles 为空时自动配置默认角色）
    team = _build_team(session_id, session, roles)

    # 3. 写入内存
    await set_active_team(session_id, team)

    # 4. 更新状态
    get_store().update_session_status(session_id, "running")

    try:
        # 5. 运行
        messages = await team.run(idea=idea, n_round=n_round, send_to=send_to)

        # 6. 持久化消息
        for msg in messages:
            get_store().add_message(session_id, msg)

        # 7. 更新状态
        get_store().update_session_status(session_id, "completed")
    finally:
        await remove_active_team(session_id)

    return {
        "session_id": session_id,
        "status": "completed",
        "rounds": team._round,
        "messages": [msg.model_dump() for msg in messages],
    }


# ── Messages ─────────────────────────────────────────

def get_messages(session_id: str) -> List[TeamMessage]:
    return get_store().get_messages(session_id)


async def send_message(session_id: str, content: str, send_to: str = "") -> Dict[str, Any]:
    """用户发送消息到团队"""
    msg = new_message(content=content, role="user", sent_from="user", send_to=send_to, cause_by="UserRequirement")
    msg.session_id = session_id
    
    # 存入 store
    get_store().add_message(session_id, msg)
    
    # 如果有活跃的 Team，也推送到环境
    team = get_active_team(session_id)
    if team:
        team._env.publish(msg)
    
    return msg.model_dump()


# ── Tools ─────────────────────────────────────────

def get_all_tools() -> Dict[str, Any]:
    """获取所有可用工具（用于权限配置 UI）"""
    from app.tools.registry import registry
    from app.tools.manager import get_tool_manager
    
    tool_mgr = get_tool_manager()
    all_tools = tool_mgr.list_tools()
    
    # 按 toolset 分组
    toolsets_map = registry.get_available_toolsets()
    toolsets = []
    all_tools_info = []
    
    for ts_name, ts_info in toolsets_map.items():
        toolsets.append({
            "name": ts_name,
            "tools": sorted(ts_info["tools"]),
            "available": ts_info["available"],
        })
        for tool_name in sorted(ts_info["tools"]):
            entry = registry.get_entry(tool_name)
            if entry:
                all_tools_info.append({
                    "name": tool_name,
                    "toolset": ts_name,
                    "description": entry.description,
                    "emoji": entry.emoji,
                })
    
    return {"toolsets": toolsets, "tools": all_tools_info}


def get_role_templates() -> Dict[str, Any]:
    """获取角色模板列表"""
    return {
        "templates": {
            name: {
                "name": tpl["name"],
                "profile": tpl["profile"],
                "watch_actions": tpl["watch_actions"],
                "action_types": tpl["action_types"],
            }
            for name, tpl in ROLE_TEMPLATES.items()
        }
    }


# ── Agent Marketplace ─────────────────────────────────────────

def create_agent_template(params: Dict[str, Any]) -> Dict[str, Any]:
    """创建市场 Agent"""
    store = get_store()
    # 检查名称唯一
    existing = store.get_template_by_name(params["name"])
    if existing:
        raise ValueError(f"Agent 名称已存在: {params['name']}")

    tool_perm = params.get("tool_permission", {})
    data = {
        "name": params["name"],
        "profile": params.get("profile", ""),
        "category": params.get("category", ""),
        "tags": params.get("tags", []),
        "watch_actions": params.get("watch_actions", []),
        "action_types": params.get("action_types", []),
        "action_configs": params.get("action_configs", {}),
        "tool_permission": {
            "allowed_tools": tool_perm.get("allowed_tools", []),
            "denied_tools": tool_perm.get("denied_tools", []),
            "max_tool_turns": tool_perm.get("max_tool_turns", 20),
        },
        "llm_provider": params.get("llm_provider", "deepseek"),
        "llm_model": params.get("llm_model", ""),
        "opponent_name": params.get("opponent_name", ""),
        "stance": params.get("stance", ""),
        "skills": params.get("skills", []),
    }
    result = store.create_template(data)
    logger.info(f"[MARKET] 创建 Agent: {result['name']} ({result['id']})")
    return result


def list_agent_templates() -> List[Dict[str, Any]]:
    """列出所有市场 Agent"""
    return get_store().list_templates()


def get_agent_template(template_id: str) -> Optional[Dict[str, Any]]:
    """获取市场 Agent 详情"""
    return get_store().get_template(template_id)


def update_agent_template(template_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """更新市场 Agent"""
    store = get_store()
    existing = store.get_template(template_id)
    if not existing:
        raise ValueError(f"Agent 不存在: {template_id}")
    # 如果重命名，检查名称冲突
    if "name" in params and params["name"] != existing["name"]:
        conflict = store.get_template_by_name(params["name"])
        if conflict:
            raise ValueError(f"Agent 名称已存在: {params['name']}")
    result = store.update_template(template_id, params)
    logger.info(f"[MARKET] 更新 Agent: {result['name']}")
    return result


def delete_agent_template(template_id: str):
    """删除市场 Agent"""
    store = get_store()
    existing = store.get_template(template_id)
    if not existing:
        raise ValueError(f"Agent 不存在: {template_id}")
    store.delete_template(template_id)
    logger.info(f"[MARKET] 删除 Agent: {existing['name']}")


def import_agent_to_session(session_id: str, template_id: str, name_override: str = None) -> Dict[str, Any]:
    """从市场导入 Agent 到会话"""
    store = get_store()
    session = store.get_session(session_id)
    if not session:
        raise ValueError(f"会话不存在: {session_id}")

    template = store.get_template(template_id)
    if not template:
        raise ValueError(f"市场 Agent 不存在: {template_id}")

    name = name_override or template["name"]
    tool_perm = template.get("tool_permission", {})
    role = TeamRole.create(
        name=name,
        profile=template.get("profile", ""),
        watch_actions=template.get("watch_actions", []),
        action_types=template.get("action_types", []),
        action_configs=template.get("action_configs", {}),
        tool_permission=ToolPermission(
            allowed_tools=tool_perm.get("allowed_tools", []),
            denied_tools=tool_perm.get("denied_tools", []),
            max_tool_turns=tool_perm.get("max_tool_turns", 20),
        ),
        llm_provider=template.get("llm_provider", "deepseek"),
        llm_model=template.get("llm_model", ""),
        opponent_name=template.get("opponent_name", ""),
        stance=template.get("stance", ""),
    )
    store.add_role(session_id, role)
    logger.info(f"[MARKET] 导入 Agent: {name} → 会话 {session_id}")
    return {
        "name": role.name, "profile": role.profile,
        "watch_actions": role.watch_actions,
        "action_types": role.action_types,
        "action_configs": role.action_configs,
        "tool_permission": role.tool_permission.model_dump(),
        "llm_provider": role.llm_provider,
        "llm_model": role.llm_model,
        "opponent_name": role.opponent_name,
        "stance": role.stance,
        "status": "hired",
    }


def list_marketplace_categories() -> List[str]:
    """列出所有市场分类"""
    return get_store().list_template_categories()


def list_marketplace_skills() -> List[Dict[str, Any]]:
    """列出所有可用技能（供市场表单选择）"""
    try:
        from app.hermes.skill_file import SkillFileManager
        mgr = SkillFileManager()
        skills = mgr.list_skills()
        return [
            {"name": s.get("name", ""), "description": s.get("description", ""), "category": s.get("category", "")}
            for s in skills
        ]
    except Exception as e:
        logger.warning(f"[MARKET] 获取技能列表失败: {e}")
        return []