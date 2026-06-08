"""
Multi-Agent Team API - 业务逻辑服务
"""

from typing import Dict, List, Optional, Any
import logging
import threading

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
_teams_lock = threading.Lock()


def get_store() -> TeamSessionStore:
    global _store
    if _store is None:
        _store = TeamSessionStore()
    return _store


def get_active_team(session_id: str) -> Optional[Team]:
    with _teams_lock:
        return _active_teams.get(session_id)


def set_active_team(session_id: str, team: Team):
    with _teams_lock:
        _active_teams[session_id] = team


def remove_active_team(session_id: str):
    with _teams_lock:
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
    remove_active_team(session_id)
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
        if params.get("debate_side"):
            tpl["debate_side"] = params["debate_side"]
        if params.get("debate_position"):
            tpl["debate_position"] = params["debate_position"]
        if params.get("llm_provider"):
            tpl["llm_provider"] = params["llm_provider"]
        if params.get("llm_model"):
            tpl["llm_model"] = params["llm_model"]
        if "use_agent" in params:
            tpl["use_agent"] = params["use_agent"]
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
            debate_side=params.get("debate_side", ""),
            debate_position=params.get("debate_position", ""),
            upstream_roles=params.get("upstream_roles", []),
            downstream_roles=params.get("downstream_roles", []),
            use_agent=params.get("use_agent", False),
        )

    get_store().add_role(session_id, role)
    logger.info(f"[SERVICE] 添加角色: {role.name} → 会话 {session_id} (use_agent={role.use_agent})")
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
        "debate_side": role.debate_side,
        "debate_position": role.debate_position,
        "use_agent": role.use_agent,
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
            "debate_side": r.debate_side,
            "debate_position": r.debate_position,
            "upstream_roles": r.upstream_roles,
            "downstream_roles": r.downstream_roles,
            "use_agent": r.use_agent,
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
        "debate_side": role.debate_side,
        "debate_position": role.debate_position,
        "upstream_roles": role.upstream_roles,
        "downstream_roles": role.downstream_roles,
        "use_agent": role.use_agent,
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
    db_path = get_store().db_path
    team = Team(name=session["name"], mode=mode, timeout=timeout, session_id=session_id, db_path=db_path)

    # 图路由模式：无角色时自动配置四角色（含默认连接图）
    if mode == "pipeline" and not roles:
        from app.services.llm_manager import LLMManager
        current_provider = LLMManager().get_current_provider()
        logger.info(f"[SERVICE] 流水线模式，自动配置 Leader/Coder/Tester/Reviewer (llm={current_provider})")
        for tpl_name in ("leader", "coder", "tester", "reviewer"):
            role = create_role_from_template(tpl_name, llm_provider=current_provider)
            # 填充默认上下游连接
            up, down = get_default_connections(tpl_name)
            role.upstream_roles = up
            role.downstream_roles = down
            logger.info(f"[SERVICE]   创建角色 {role.name}: upstream={role.upstream_roles}, downstream={role.downstream_roles}")
            team.hire(role)
    else:
        logger.info(f"[SERVICE] 使用会话已有角色 (count={len(roles)}, mode={mode})")

        # 辩论模式：自动建立对手关系并持久化
        if mode == "debate":
            _setup_debate_opponents(roles)
            # 持久化 opponent_name 到数据库
            store = get_store()
            for role in roles:
                if role.opponent_name:
                    try:
                        store.update_role(session_id, role.name, {"opponent_name": role.opponent_name})
                    except Exception as e:
                        logger.warning(f"[SERVICE] 持久化对手失败: {role.name} -> {e}")

        for role in roles:
            logger.info(f"[SERVICE]   角色 {role.name}: upstream={role.upstream_roles}, downstream={role.downstream_roles}, actions={role.action_types}, debate_side={role.debate_side}, opponent={role.opponent_name}")
            # 如果角色有对手名（辩论场景），应用辩论覆盖
            if role.opponent_name:
                role.make_debate_role(opponent_name=role.opponent_name)
                # 辩论角色还需要监听 SpeakAloud/DebateSpeech（对手发言）
                role.add_watch_action("SpeakAloud")
                role.add_watch_action("DebateSpeech")
            team.hire(role)
    return team


def _setup_debate_opponents(roles: List[TeamRole]):
    """
    辩论模式：根据 debate_side 自动设置对手关系。
    规则：
    1. 正方一辩 ↔ 反方一辩
    2. 正方二辩 ↔ 反方二辩
    3. 正方三辩 ↔ 反方三辩
    4. 正方四辩 ↔ 反方四辩
    5. 如果没有对应的辩位对手，则找同辩位的对方辩手
    6. 裁判没有对手
    """
    positive_roles = [r for r in roles if r.debate_side == "positive"]
    negative_roles = [r for r in roles if r.debate_side == "negative"]

    # 按辩位排序
    position_order = {"first": 0, "second": 1, "third": 2, "fourth": 3, "judge": 4, "": 5}
    positive_roles.sort(key=lambda r: position_order.get(r.debate_position, 5))
    negative_roles.sort(key=lambda r: position_order.get(r.debate_position, 5))

    # 配对同辩位的正反方
    for pos_role in positive_roles:
        if pos_role.debate_position == "judge":
            continue  # 裁判没有对手
        # 找同辩位的反方
        neg_candidates = [r for r in negative_roles if r.debate_position == pos_role.debate_position]
        if neg_candidates:
            pos_role.opponent_name = neg_candidates[0].name
        else:
            # 没有同辩位，找对方还没有对手的角色
            unpaired_neg = [r for r in negative_roles if not r.opponent_name and r.debate_position != "judge"]
            if unpaired_neg:
                pos_role.opponent_name = unpaired_neg[0].name

    for neg_role in negative_roles:
        if neg_role.debate_position == "judge":
            continue
        if not neg_role.opponent_name:
            # 找正方还没有对手的角色
            unpaired_pos = [r for r in positive_roles if not r.opponent_name and r.debate_position != "judge"]
            if unpaired_pos:
                neg_role.opponent_name = unpaired_pos[0].name

    logger.info(f"[SERVICE] 辩论对手设置: {[(r.name, r.opponent_name) for r in roles if r.debate_side != 'judge']}")


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

    set_active_team(session_id, team)
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
        remove_active_team(session_id)


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
    set_active_team(session_id, team)

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
        remove_active_team(session_id)

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


# ══════════════════════════════════════════════════════════
# v2 — Scheduler / TaskQueue / Workspace 服务
# ══════════════════════════════════════════════════════════

# 全局 Scheduler 缓存（session_id → Scheduler）
_schedulers: Dict[str, Any] = {}
_schedulers_lock = threading.Lock()


def get_scheduler(session_id: str) -> Optional[Any]:
    with _schedulers_lock:
        return _schedulers.get(session_id)


def _get_session_db_path(session_id: str) -> str:
    """获取数据库路径（与 TeamSessionStore 共用）"""
    store = get_store()
    return store.db_path


def init_session_v2(session_id: str, max_concurrent: int = 4, claim_ttl_seconds: int = 300) -> None:
    """
    初始化 v2 会话：
    1. TaskQueue.init() 建表（幂等）
    2. 创建 Scheduler 实例并缓存
    """
    from app.core.multi_agent.task_queue import TaskQueue

    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()  # 幂等建表

    from app.core.multi_agent.scheduler import Scheduler
    sch = Scheduler(
        session_id=session_id,
        db_path=db_path,
        max_concurrent=max_concurrent,
        claim_ttl_seconds=claim_ttl_seconds,
    )
    with _schedulers_lock:
        _schedulers[session_id] = sch
    logger.info(f"[SERVICE] v2 init: session={session_id}, Scheduler(max={max_concurrent})")


def create_task(
    session_id: str,
    description: str,
    task_type: str = "",
    priority: int = 0,
    created_by: str = "",
) -> Dict[str, Any]:
    """创建任务并入队"""
    from app.core.multi_agent.task_queue import TaskQueue

    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()
    rec = queue.enqueue(
        session_id=session_id,
        description=description,
        task_type=task_type,
        created_by=created_by,
        priority=priority,
    )
    # 发布事件（同步写入 DB）
    from app.core.multi_agent.event_bus import EventBus
    EventBus.get_instance().publish_sync(
        event_type="task.pending",
        payload={"task_id": rec.id, "description": description, "created_by": created_by},
        source=created_by or "system",
        task_id=rec.id,
        session_id=session_id,
    )
    return _task_record_to_detail(rec, queue, session_id)


def list_tasks(session_id: str, state: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出任务（可按 state 过滤）"""
    from app.core.multi_agent.task_queue import TaskQueue

    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()
    records = queue.list_by_session(session_id, states=[state] if state else None)
    return [_task_record_to_status(r) for r in records]


def get_task_detail(session_id: str, task_id: str) -> Optional[Dict[str, Any]]:
    """获取任务详情（含依赖边）"""
    from app.core.multi_agent.task_queue import TaskQueue

    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()
    rec = queue.get(task_id)
    if not rec:
        return None
    links_result = queue.get_children(task_id)
    from app.core.multi_agent.api.schemas import TaskLinkResponse
    links = []
    for child_rec in links_result:
        links.append(TaskLinkResponse(
            id="",
            parent_id=task_id,
            child_id=child_rec.id,
            link_type="subtask",
        ))
    return _task_record_to_detail(rec, queue, session_id, links=links)


def claim_task(session_id: str, task_id: str, agent_name: str, ttl_seconds: int = 300):
    """Agent 认领任务"""
    from app.core.multi_agent.task_queue import TaskQueue

    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()
    rec = queue.get(task_id)
    if not rec:
        return False, None
    ok = queue.claim(task_id, agent_name, ttl_seconds=ttl_seconds)
    rec2 = queue.get(task_id)
    return ok, rec2


def complete_task(session_id: str, task_id: str, agent_name: str, result_summary: str = "") -> tuple:
    """标记任务完成"""
    from app.core.multi_agent.task_queue import TaskQueue

    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()
    rec = queue.get(task_id)
    if not rec:
        return False, None
    ok = queue.complete(task_id, agent_name, result_summary=result_summary)
    rec2 = queue.get(task_id)
    return ok, rec2


def reject_task(session_id: str, task_id: str, agent_name: str, reason: str = "") -> tuple:
    """拒绝任务"""
    from app.core.multi_agent.task_queue import TaskQueue

    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()
    rec = queue.get(task_id)
    if not rec:
        return False, None
    ok = queue.reject(task_id, agent_name, reason=reason)
    rec2 = queue.get(task_id)
    return ok, rec2


def link_tasks(session_id: str, parent_id: str, child_id: str, link_type: str = "blocks") -> Dict[str, Any]:
    """建立父子依赖边"""
    from app.core.multi_agent.task_queue import TaskQueue

    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()
    rec = queue.get(parent_id)
    if not rec:
        raise ValueError(f"Parent task not found: {parent_id}")
    result = queue.link(parent_id, child_id, link_type=link_type)
    return {"parent_id": parent_id, "child_id": child_id, "link_type": link_type, "created": result}


async def decompose_task(session_id: str, task_id: str) -> Dict[str, Any]:
    """分解任务（调用 LLM 将父任务拆为子任务）"""
    from app.core.multi_agent.task_queue import TaskQueue
    db_path = _get_session_db_path(session_id)
    queue = TaskQueue(db_path)
    queue.init()
    rec = queue.get(task_id)
    if not rec:
        raise ValueError(f"Task not found: {task_id}")

    # 获取 Scheduler 进行 LLM 分解
    sch = get_scheduler(session_id)
    if not sch:
        raise ValueError(f"Scheduler not initialized for session {session_id}")

    # 获取 LLM 实例用于任务分解
    from app.services.llm_manager import LLMManager
    from app.llm.factory import get_llm
    llm_mgr = LLMManager()
    provider = llm_mgr.get_current_provider()
    api_key = llm_mgr.get_api_key(provider)
    llm = get_llm(provider, api_key) if api_key else None
    children = await sch._decompose_requirement(rec.description, llm)

    child_ids = []
    for child_desc in children:
        child_rec = queue.enqueue(
            session_id=session_id,
            description=child_desc,
            task_type="subtask",
            created_by="scheduler",
            input_summary=rec.description,
        )
        queue.link(task_id, child_rec.id, link_type="blocks")
        child_ids.append(child_rec.id)

    return {
        "parent_task_id": task_id,
        "child_task_ids": child_ids,
        "count": len(child_ids),
    }


def get_workspace_content(session_id: str, task_id: str, sub: str = "files") -> Dict[str, Any]:
    """读取 workspace 文件或目录列表"""
    from app.core.multi_agent.workspace import get_workspace

    ws = get_workspace(task_id)
    if not ws.exists():
        raise FileNotFoundError(f"Workspace not found for task: {task_id}")

    base = ws.base / sub
    if sub == "files" or sub == "worktree":
        # 返回文件树
        files = {}
        for p in ws.base.rglob("*"):
            if p.is_file():
                rel = p.relative_to(ws.base)
                try:
                    content = p.read_text(errors="replace")
                    files[str(rel)] = {"size": p.stat().st_size, "content": content[:500]}
                except Exception:
                    files[str(rel)] = {"size": p.stat().st_size, "content": "<binary>"}
        return {"task_id": task_id, "workspace_path": str(ws.base), "files": files}
    else:
        # 读取单个文件
        if not base.exists():
            raise FileNotFoundError(f"File not found: {sub}")
        content = base.read_text(errors="replace")
        return {
            "task_id": task_id,
            "file_path": str(base),
            "content": content,
            "size": len(content),
        }


def get_scheduler_status(session_id: str) -> Optional[Dict[str, Any]]:
    """获取 Scheduler 状态"""
    sch = get_scheduler(session_id)
    if not sch:
        return None
    return sch.stats()


def stop_scheduler(session_id: str) -> bool:
    """停止 Scheduler"""
    sch = get_scheduler(session_id)
    if not sch:
        return False
    sch.stop()  # 同步方法，仅设置 _running = False
    with _schedulers_lock:
        _schedulers.pop(session_id, None)
    return True


# ── helpers ─────────────────────────────────────────

def _task_record_to_status(rec) -> Dict[str, Any]:
    return {
        "id": rec.id,
        "state": rec.state,
        "task_type": rec.task_type,
        "description": rec.description,
        "assigned_to": rec.assigned_to,
        "created_by": rec.created_by,
        "priority": rec.priority,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
        "started_at": rec.started_at or "",
        "completed_at": rec.completed_at or "",
        "result_summary": rec.result_summary or "",
    }


def _task_record_to_detail(rec, queue, session_id, links=None) -> Dict[str, Any]:
    from app.core.multi_agent.api.schemas import TaskLinkResponse
    all_links = links or []
    return {
        "id": rec.id,
        "session_id": session_id,
        "state": rec.state,
        "task_type": rec.task_type,
        "description": rec.description,
        "assigned_to": rec.assigned_to,
        "created_by": rec.created_by,
        "workspace_path": rec.workspace_path or "",
        "input_summary": rec.input_summary or "",
        "result_summary": rec.result_summary or "",
        "priority": rec.priority,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
        "started_at": rec.started_at or "",
        "completed_at": rec.completed_at or "",
        "links": [TaskLinkResponse(id=l.id, parent_id=l.parent_id, child_id=l.child_id, link_type=l.link_type) for l in all_links],
    }
