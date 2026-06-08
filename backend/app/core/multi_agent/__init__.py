"""
Multi-Agent 子包（5/28 重构 v2）：state machine / event bus / workspace / task queue / scheduler / action system。
"""

# Multi-Agent Team Module

from app.core.multi_agent.message import TeamMessage, new_message
from app.core.multi_agent.actions import TeamAction, create_action, get_action_class, list_action_types
from app.core.multi_agent.to_message import from_tool_result, from_text, from_dict, from_message
from app.core.multi_agent.tool_permission import ToolPermission
from app.core.multi_agent.role import TeamRole, RoleContext, create_role_from_template, ROLE_TEMPLATES
from app.core.multi_agent.environment import Environment
from app.core.multi_agent.team import Team, run_team_async, run_team_sync
from app.core.multi_agent.session_store import TeamSessionStore

# v2 基础设施
from app.core.multi_agent.state_machine import TaskState, TaskEvent, StateMachine, TransitionError
from app.core.multi_agent.event_bus import EventBus, get_event_bus, publish_event, Event
from app.core.multi_agent.workspace import TaskWorkspace, WorkspaceManager, get_workspace, get_workspace_manager
from app.core.multi_agent.task_queue import TaskQueue, TaskRecord
from app.core.multi_agent.execution_context import TaskExecutionContext, ExecutionResult, ToolCall, ToolCallState, ToolCallManager
from app.core.multi_agent.scheduler import Scheduler, AgentTask
from app.core.multi_agent.environment import Environment, EventBusEnvironment  # Environment = 向后兼容别名
