"""
TeamRole - Multi-Agent 角色抽象
角色 = 名称 + 描述 + 动作列表 + 监听规则 + 工具权限
"""

from pydantic import BaseModel, Field, PrivateAttr
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type
import logging

from app.core.multi_agent.message import TeamMessage, new_message
from app.core.multi_agent.action import TeamAction, get_action_class, create_action
from app.core.multi_agent.tool_permission import ToolPermission

if TYPE_CHECKING:
    from app.core.multi_agent.environment import Environment

logger = logging.getLogger(__name__)


# ── RoleContext 运行时上下文 ─────────────────────────────────

class RoleContext(BaseModel):
    """Role 运行时上下文（每个 action 执行周期新建）"""
    todo: Optional[TeamAction] = None          # 当前待执行的动作
    news: List[TeamMessage] = Field(default_factory=list)    # 观察到的消息
    memory: List[TeamMessage] = Field(default_factory=list)  # 角色记忆
    round: int = 0                              # 当前轮次


# ── TeamRole 角色 ──────────────────────────────────────────

class TeamRole(BaseModel):
    """角色 = 名称 + 描述 + 动作 + 监听规则 + 工具权限"""
    
    name: str = "Role"
    profile: str = ""                            # 角色描述（用作 system prompt）
    watch_actions: List[str] = Field(default_factory=list)   # 监听的动作名称列表
    actions: List[TeamAction] = Field(default_factory=list) # 已实例化的动作列表
    action_types: List[str] = Field(default_factory=list)   # 动作类型标识（用于重建 actions）
    action_configs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  # 动作参数配置 {type: {field: value}}
    
    # 工具权限
    tool_permission: ToolPermission = Field(default_factory=ToolPermission)
    
    # LLM 配置
    llm_provider: str = "deepseek"
    llm_model: str = ""

    # 连接图（上下游关系）
    upstream_roles: List[str] = Field(default_factory=list)   # 上游 Agent 名称列表
    downstream_roles: List[str] = Field(default_factory=list) # 下游 Agent 名称列表

    # 辩论场景专用
    opponent_name: str = ""
    stance: str = ""                            # 辩论立场（如"赞成禁止" / "反对禁止"，空=由 LLM 自行判断）
    
    # 运行时（不持久化）
    _rc: Optional[RoleContext] = PrivateAttr(default=None)
    _memory: List[TeamMessage] = PrivateAttr(default_factory=list)  # noqa: N816
    _env: Optional["Environment"] = PrivateAttr(default=None)  # noqa: N816
    
    # ── 动作管理 ─────────────────────────────────────────
    
    def set_actions(self, action_types: List[str]):
        """根据动作类型列表设置动作实例"""
        self.action_types = action_types
        self.actions = []
        for at in action_types:
            cls = get_action_class(at)
            if cls:
                kwargs = self.action_configs.get(at, {})
                self.actions.append(cls(**kwargs))
            else:
                logger.warning(f"[ROLE] 未知动作类型: {at}")
    
    def add_action(self, action: TeamAction):
        self.actions.append(action)
    
    def get_action(self, name: str) -> Optional[TeamAction]:
        for a in self.actions:
            if a.name == name:
                return a
        return None
    
    def get_default_action(self) -> Optional[TeamAction]:
        """返回第一个动作（默认执行）"""
        return self.actions[0] if self.actions else None
    
    # ── 监听管理 ─────────────────────────────────────────
    
    def watch(self, action_types: List[Type["TeamAction"]]):
        """设置监听的动作类型（传入类列表）"""
        self.watch_actions = [a.name for a in action_types]
    
    # ── 记忆管理 ─────────────────────────────────────────
    
    @property
    def memory(self) -> List[TeamMessage]:
        return self._memory
    
    def add_memory(self, msg: TeamMessage):
        self._memory.append(msg)
    
    def get_memories(self) -> List[TeamMessage]:
        return self._memory
    
    # ── 观察 ─────────────────────────────────────────
    
    def set_environment(self, env: "Environment"):
        self._env = env
    
    async def observe(self) -> List[TeamMessage]:
        """
        从环境获取监听范围内的新消息。
        委托给 Environment.get_messages_for_role() 以保持路由逻辑一致。
        """
        if not self._env:
            return []
        return self._env.get_messages_for_role(self)
    
    # ── 核心循环 ─────────────────────────────────────────
    
    async def _think(self) -> bool:
        """
        思考阶段：决定下一步动作。
        单 action 角色（Worker）执行默认动作；多 action 角色（Leader）基于
        最新定向消息的 cause_by 映射到对应动作。
        """
        if not self._rc:
            return False

        news = self._rc.news

        # 多 action 角色（Leader）：基于最新消息 cause_by 映射动作
        if len(self.actions) > 1:
            action = self._select_action_by_context()
            if action:
                self._rc.todo = action
                return True
            return False

        # 单 action 角色（Worker）：有新消息就执行默认动作
        if not news:
            return False

        default_action = self.get_default_action()
        if default_action:
            self._rc.todo = default_action
            return True
        return False

    # 可配置的 cause_by → action 映射（子类可覆盖）
    ACTION_MAP: Dict[str, str] = {
        "UserRequirement": "AnalyzeTask",
        "AnalyzeTask": "DistributeTask",
        "WriteCode": "Approve",
        "WriteTest": "Approve",
        "WriteReview": "Approve",
        "Reject": "Approve",
    }

    def _select_action_by_context(self) -> Optional[TeamAction]:
        """
        基于最新定向消息的 cause_by 映射到下一个动作。

        映射规则由 self.ACTION_MAP 控制，子类可覆盖以实现自定义路由。
        """
        if not self._rc or not self._rc.news:
            return None

        latest = self._rc.news[-1]
        cause = latest.cause_by

        # 尝试解析 TaskPayload，检测退回状态
        from app.core.multi_agent.message import TaskPayload
        task = TaskPayload.from_message(latest)
        if task and task.status == "rejected":
            # Worker 收到退回 → 重新执行自己的动作
            return self.get_default_action()

        # cause_by → action.name 映射
        action_type = self.ACTION_MAP.get(cause)
        if action_type:
            action = self.get_action(action_type)
            if action:
                return action

        return self.get_default_action()

    def _get_next_worker(self, current_worker: str) -> str:
        """
        根据下游角色列表返回当前 Worker 之后的下一个 Worker 名称。
        如果当前 Worker 是最后一个且没有更多子任务，返回 ""（流水线自然结束）。

        防御性设计：当 downstream_roles 为空时，使用内置默认流水线顺序。
        """
        workers = self.downstream_roles if self.downstream_roles else ["Coder", "Tester", "Reviewer"]
        if current_worker in workers:
            idx = workers.index(current_worker)
            if idx + 1 < len(workers):
                return workers[idx + 1]
            # 当前 Worker 是最后一个：检查是否有更多子任务
            team = self._get_team_ref()
            if team and hasattr(team, "_task_queue") and team._task_queue:
                return workers[0]  # 开始下一子任务
            return ""
        return workers[0] if workers else ""

    def _get_team_ref(self):
        """从 _env 反向获取 Team 引用"""
        if self._env is None:
            return None
        team = getattr(self._env, "_team", None)
        if team is None:
            logger.warning(f"[ROLE] {self.name} 的 _env 缺少 _team 引用")
        return team
    
    async def _act(self) -> Optional[TeamMessage]:
        """
        执行阶段：运行动作并生成消息。
        消息默认广播（send_to=""），辩论模式下改为定向对手。
        """
        if not self._rc or not self._rc.todo:
            return None

        todo = self._rc.todo
        logger.info(f"[ROLE] {self.name} 执行动作: {todo.name}")

        has_error = False
        try:
            result = await todo.run(self, self._rc)
        except Exception as e:
            logger.error(f"[ROLE] {self.name} 动作执行失败: {e}")
            result = f"执行失败: {e}"
            has_error = True

        # 构造消息（send_to: 优先取动作指定的目标，否则广播）
        send_to = todo.send_to or ""
        msg = new_message(
            content=result,
            role="assistant",
            sent_from=self.name,
            send_to=send_to,
            cause_by=todo.name,
        )

        # 标记错误消息
        if has_error:
            msg.metadata["error"] = True

        # 存入记忆
        self.add_memory(msg)

        return msg

    # ── 辩论角色（覆盖 observe + act）────────────────────────────────

    def make_debate_role(self, opponent_name: str) -> "TeamRole":
        """
        将当前角色转换为辩论角色（原地修改）：
        - observe 覆盖：只接受对手发来的定向消息（send_to == self.name）
        - _act 覆盖：构建对话历史，并定向发给对手
        """
        import types

        # 保存 self 引用供闭包使用
        self_ref = self

        # 辩论 observe：只接收发给自己的消息 + 广播初始消息
        async def debate_observe(self: "TeamRole") -> List[TeamMessage]:
            news: List[TeamMessage] = []
            for msg in self_ref._env.messages:
                # 广播消息（初始 idea）: 只要 cause_by 在 watch 里就接受
                if msg.send_to == "":
                    if not self_ref.watch_actions or msg.cause_by in self_ref.watch_actions:
                        news.append(msg)
                # 定向发给自己的消息（对手发言）: 接受
                elif msg.send_to == self_ref.name:
                    news.append(msg)
                # 发给其他人: 忽略
            return news

        # 辩论 act：基于 memory 构建上下文，定向发给对手
        async def debate_act(self: "TeamRole") -> Optional[TeamMessage]:
            if not self_ref._rc or not self_ref._rc.todo:
                return None

            todo = self_ref._rc.todo
            result = await todo.run(self_ref, self_ref._rc)
            msg = new_message(
                content=result,
                role="assistant",
                sent_from=self_ref.name,
                send_to=opponent_name,
                cause_by=todo.name,
            )
            self_ref.add_memory(msg)
            return msg

        # 用 object.__setattr__ 绕过 Pydantic v2 字段验证
        object.__setattr__(self, "observe", types.MethodType(debate_observe, self))
        object.__setattr__(self, "_act", types.MethodType(debate_act, self))
        self.opponent_name = opponent_name
        return self
    
    async def run(self, round_num: int) -> Optional[TeamMessage]:
        """
        Role 主运行循环：观察 → 思考 → 行动

        所有角色（包括多 action 角色如 Leader）仅在收到新消息时才行动。
        流水线推进依赖定向消息传递：Leader 处理完动作后将结果定向发给
        下游 Worker，Worker 完成后再定向发回 Leader，形成生产者-消费者链。
        """
        self._rc = RoleContext(round=round_num)
        self._rc.memory = list(self._memory)

        # 1. 观察：从环境获取新消息
        self._rc.news = await self.observe()

        # 2. 无消息：跳过
        if not self._rc.news:
            logger.debug(f"[ROLE] {self.name} 无新消息，跳过")
            self._mark_read()
            return None

        # 3. 思考：选择动作
        if not await self._think():
            self._mark_read()
            return None

        # 4. 行动：执行并返回消息
        msg = await self._act()
        self._mark_read()
        return msg

    def _mark_read(self):
        """标记该角色本轮所有消息为已读"""
        if self._env:
            self._env.mark_read(self.name)
    
    # ── 工具 Schemas 过滤 ─────────────────────────────────
    
    def get_filtered_schemas(self) -> List[dict]:
        """返回该角色可用工具的 schema（根据工具权限过滤）"""
        from app.tools.manager import get_tool_manager
        tool_mgr = get_tool_manager()
        all_schemas = tool_mgr.get_schemas()
        return self.tool_permission.filter_schemas(all_schemas)

    def build_system_prompt(self) -> str:
        """
        构建系统提示词：在 profile 基础上自动注入上下游 Agent 身份信息。
        让每个 Agent 在运行时知道自己的上下游合作伙伴。
        """
        base = self.profile
        context_parts = []
        if self.upstream_roles:
            context_parts.append(f"你的上游合作伙伴（接收任务来源）：{', '.join(self.upstream_roles)}")
        if self.downstream_roles:
            context_parts.append(f"你的下游合作伙伴（交付对象）：{', '.join(self.downstream_roles)}")
        if context_parts:
            return base + "\n\n" + "\n".join(context_parts)
        return base
    
    def add_watch_action(self, action: str):
        """动态添加监听的动作类型"""
        if action not in self.watch_actions:
            self.watch_actions.append(action)

    # ── 快捷构造 ─────────────────────────────────────────

    @classmethod
    def create(
        cls, name: str, profile: str,
        watch_actions: List[str], action_types: List[str],
        tool_permission: Optional[ToolPermission] = None,
        llm_provider: str = "deepseek",
        **kwargs
    ) -> "TeamRole":
        """角色工厂方法"""
        role = cls(
            name=name,
            profile=profile,
            watch_actions=watch_actions,
            action_types=action_types,
            tool_permission=tool_permission or ToolPermission(),
            llm_provider=llm_provider,
            **kwargs
        )
        role.set_actions(action_types)
        return role


# ── 预设角色模板 ─────────────────────────────────────────

ROLE_TEMPLATES: Dict[str, dict] = {
    "leader": {
        "name": "Leader",
        "profile": (
            "任务指挥官。职责："
            "1) 分析用户需求的复杂程度，判断简单/复杂"
            "2) 简单任务直接分配给 Coder 执行"
            "3) 复杂任务拆分为多个子任务列表，逐个分配"
            "4) 对每个环节的交付物进行验收"
            "5) 验收通过后传递到下一环节（Coder→Reviewer→Tester→下一子任务）"
            "6) 不合格则退回，必须指明具体需要修改的内容"
            "7) 所有子任务完成后的最终验收"
            "具备项目规划、任务分解和质量把控能力。"
        ),
        "watch_actions": ["UserRequirement", "Reject"],
        "action_types": ["analyze_task", "distribute_task", "approve"],
    },
    "coder": {
        "name": "Coder",
        "profile": (
            "资深 Python 工程师。职责："
            "1) 根据 Leader 分配的任务编写高质量、可维护的代码"
            "2) 遵循 PEP8 规范，注重错误处理和边界条件"
            "3) 代码必须可直接运行"
            "4) 收到退回时，根据 Leader 指明的修改要求精确修改代码"
            "编写完成后提交给 Leader 审批。"
        ),
        "watch_actions": ["DistributeTask"],
        "action_types": ["write_code"],
    },
    "reviewer": {
        "name": "Reviewer",
        "profile": (
            "代码审查专家。职责："
            "1) 审查 Coder 编写的代码逻辑、正确性和代码质量"
            "2) 检查潜在 bug、代码异味、性能问题和安全漏洞"
            "3) 给出评分(1-10)和具体改进建议"
            "4) 收到退回时，给出更深入的分析和更具体的建议"
            "审查完成后提交给 Leader 审批。"
        ),
        "watch_actions": ["WriteCode"],
        "action_types": ["write_review"],
    },
    "tester": {
        "name": "Tester",
        "profile": (
            "测试工程师。职责："
            "1) 针对已通过审查的代码编写全面的 pytest 测试用例"
            "2) 覆盖正常流程、边界条件和异常场景"
            "3) 追求高测试覆盖率"
            "4) 收到退回时，根据 Leader 指明的修改要求改进测试用例"
            "编写完成后提交给 Leader 审批。"
        ),
        "watch_actions": ["WriteReview"],
        "action_types": ["write_test"],
    },
    "debator": {
        "name": "Debator",
        "profile": "辩论选手，观点鲜明，语言犀利，擅长逻辑反驳。",
        "watch_actions": ["UserRequirement", "SpeakAloud"],
        "action_types": ["speak_aloud"],
    },
}

def create_role_from_template(
    template_name: str, name: str = "", opponent_name: str = "", **kwargs
) -> TeamRole:
    """从模板创建角色"""
    tpl = ROLE_TEMPLATES.get(template_name)
    if not tpl:
        raise ValueError(f"未知角色模板: {template_name}")

    role_kwargs = dict(tpl, **kwargs)
    if name:
        role_kwargs["name"] = name
    if opponent_name:
        role_kwargs["opponent_name"] = opponent_name

    return TeamRole.create(**role_kwargs)


def get_default_connections(template_name: str):
    """
    返回经典流水线模板的默认上下游连接配置。
    用于向后兼容：当使用模板自动配置四角色时，自动建立标准的 Leader→Coder→Tester→Reviewer 链。
    """
    CONNECTION_MAP = {
        "leader": {
            "upstream": ["user"],
            "downstream": ["Coder", "Reviewer", "Tester"],
        },
        "coder": {
            "upstream": ["Leader"],
            "downstream": ["Leader"],
        },
        "reviewer": {
            "upstream": ["Leader"],
            "downstream": ["Leader"],
        },
        "tester": {
            "upstream": ["Leader"],
            "downstream": ["Leader"],
        },
    }
    default = CONNECTION_MAP.get(template_name, {"upstream": [], "downstream": []})
    return (list(default["upstream"]), list(default["downstream"]))