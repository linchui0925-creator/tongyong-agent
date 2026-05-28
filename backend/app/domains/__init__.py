"""
domains - Agent 身份与能力认知模块

每个子目录包含:
- .md 文件: 定义 Agent 在某个领域的能力认知（认知层）
- .py 文件: 实现该领域的具体功能（执行层）

integrator.py 读取 .md 编译为提示词，domain executors 提供实际执行能力。
"""

from app.domains.integrator import DomainIntegrator, get_integrator
from app.domains.cli import CLIExecutor
from app.domains.tools import ToolsExecutor
from app.domains.memory import MemoryExecutor
from app.domains.cron import CronExecutor
from app.domains.identity import IdentityManager

__all__ = [
    "DomainIntegrator", "get_integrator",
    "CLIExecutor", "ToolsExecutor",
    "MemoryExecutor", "CronExecutor",
    "IdentityManager",
]
