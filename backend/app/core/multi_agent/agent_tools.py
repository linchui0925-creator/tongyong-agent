"""
Agent Tools — 角色 ReAct Agent 专用工具

提供 workspace 工具和 registry 工具过滤，供 TeamRole._run_as_agent() 使用。
"""

import asyncio
import logging
from typing import List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.multi_agent.workspace import TaskWorkspace
from app.tools.langchain_adapter import registry_to_langchain_tools

logger = logging.getLogger(__name__)


# ── Workspace 工具 Pydantic Schemas ─────────────────────────

class WorkspaceReadInput(BaseModel):
    subdir: str = Field(description="子目录: input, output, context, artifacts, logs")
    filename: str = Field(description="文件名")


class WorkspaceWriteInput(BaseModel):
    subdir: str = Field(description="子目录: input, output, context, artifacts, logs")
    filename: str = Field(description="文件名")
    content: str = Field(description="文件内容")


class WorkspaceListInput(BaseModel):
    subdir: str = Field(description="子目录: input, output, context, artifacts, logs")


class WorkspaceTerminalInput(BaseModel):
    command: str = Field(description="要执行的 shell 命令")
    timeout: int = Field(default=60, description="超时秒数")


# ── Workspace 工具构建 ──────────────────────────────────────

def build_workspace_tools(workspace: TaskWorkspace) -> List[StructuredTool]:
    """为指定 workspace 构建一组 LangChain StructuredTool"""

    async def _read(subdir: str, filename: str) -> str:
        try:
            content = workspace.read(subdir, filename)
            return content[:50000]  # 截断保护
        except FileNotFoundError:
            return f"文件不存在: {subdir}/{filename}"
        except Exception as e:
            return f"读取失败: {e}"

    async def _write(subdir: str, filename: str, content: str) -> str:
        try:
            path = workspace.write(subdir, filename, content)
            return f"已写入: {subdir}/{filename} ({len(content)} 字符)"
        except Exception as e:
            return f"写入失败: {e}"

    async def _list(subdir: str) -> str:
        try:
            files = workspace.list_files(subdir)
            if not files:
                return f"{subdir}/ 目录为空"
            return "\n".join(str(f.relative_to(workspace.base / subdir)) for f in files)
        except Exception as e:
            return f"列出失败: {e}"

    async def _terminal(command: str, timeout: int = 60) -> str:
        try:
            from app.tools.implementations.terminal import _validate_command
            ok, err = _validate_command(command)
            if not ok:
                return f"命令被拒绝: {err}"

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace.base),
                limit=1024 * 1024,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            out = stdout.decode("utf-8", errors="replace")[:100000]
            err_out = stderr.decode("utf-8", errors="replace")[:10000]
            result = out
            if err_out:
                result += f"\n[stderr]\n{err_out}"
            return result or "(无输出)"
        except asyncio.TimeoutError:
            return f"命令超时 ({timeout}s)"
        except Exception as e:
            return f"执行失败: {e}"

    return [
        StructuredTool(
            name="workspace_read",
            description="读取工作区文件。subdir: input/output/context/artifacts/logs",
            args_schema=WorkspaceReadInput,
            coroutine=_read,
            func=None,
        ),
        StructuredTool(
            name="workspace_write",
            description="写入工作区文件。subdir: input/output/context/artifacts/logs",
            args_schema=WorkspaceWriteInput,
            coroutine=_write,
            func=None,
        ),
        StructuredTool(
            name="workspace_list",
            description="列出工作区子目录中的文件",
            args_schema=WorkspaceListInput,
            coroutine=_list,
            func=None,
        ),
        StructuredTool(
            name="workspace_terminal",
            description="在工作区目录中执行 shell 命令（python, pytest, ls, cat 等）",
            args_schema=WorkspaceTerminalInput,
            coroutine=_terminal,
            func=None,
        ),
    ]


# ── Registry 工具过滤 ──────────────────────────────────────

def get_filtered_registry_tools(tool_permission) -> List[StructuredTool]:
    """按 ToolPermission 过滤 registry 工具，返回 LangChain StructuredTool 列表"""
    all_tools = registry_to_langchain_tools()
    filtered = []
    for tool in all_tools:
        if tool_permission.is_tool_allowed(tool.name):
            filtered.append(tool)
    return filtered
