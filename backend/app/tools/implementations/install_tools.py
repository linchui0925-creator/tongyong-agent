"""
install_tools - dependency installation helpers.

Provides a structured installation tool so the agent can install common project
and browser dependencies without hand-crafting shell commands.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from app.tools.registry import registry
from app.tools.implementations.terminal import _approval_allows_execution, _validate_command
from app.paths import data_path

_MAX_OUTPUT_CHARS = 120_000
_DEFAULT_TIMEOUT = 900


INSTALL_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["python", "node", "playwright", "git-mcp"],
            "description": "安装类型。python=node=playwright=git-mcp 等预设安装流程。",
        },
        "workdir": {
            "type": "string",
            "description": "安装命令执行目录；默认当前目录或工作区根目录。",
        },
        "session_id": {
            "type": "string",
            "description": "会话 ID，用于工作区定位与审批归属。",
        },
        "task_id": {
            "type": "string",
            "description": "任务 ID；优先于 session_id。",
        },
        "packages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要安装的包名或额外参数。",
        },
        "requirements_file": {
            "type": "string",
            "description": "Python 依赖文件路径（如 requirements.txt / pyproject.toml）。",
        },
        "package_manager": {
            "type": "string",
            "enum": ["pip", "uv", "npm", "pnpm", "yarn"],
            "description": "显式指定包管理器；默认根据 kind 推断。",
        },
        "approval_id": {
            "type": "string",
            "description": "高风险命令审批通过后的 ID。",
        },
        "timeout": {
            "type": "integer",
            "description": f"超时秒数，默认 {_DEFAULT_TIMEOUT}s。",
            "default": _DEFAULT_TIMEOUT,
        },
    },
    "required": ["kind"],
}


def _workspace_root() -> str:
    return os.getenv("TONGYONG_WORKSPACE_ROOT", data_path("workspaces"))


def _safe_task_id(session_id: Optional[str] = None, task_id: Optional[str] = None) -> str:
    raw = task_id or session_id or "default"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(raw))[:80] or "default"


def _get_workdir(workdir: Optional[str], session_id: Optional[str], task_id: Optional[str]) -> str:
    if workdir:
        return workdir
    # workspace 优先
    base = Path(_workspace_root()) / _safe_task_id(session_id, task_id)
    if base.exists():
        return str(base)
    return os.getcwd()


def _build_command(kind: str, package_manager: Optional[str], packages: list[str], requirements_file: str) -> str:
    kind = kind.lower().strip()
    pm = (package_manager or "").lower().strip()

    if kind == "playwright":
        return "python -m playwright install chromium"

    if kind == "git-mcp":
        return "uv tool install mcp-server-git || pip install mcp-server-git"

    if kind == "python":
        if requirements_file:
            if pm == "uv":
                return f"uv pip install -r {shlex.quote(requirements_file)}"
            if pm == "pip":
                return f"pip install -r {shlex.quote(requirements_file)}"
            # 默认优先 uv, 没有就 pip
            return f"uv pip install -r {shlex.quote(requirements_file)} || pip install -r {shlex.quote(requirements_file)}"
        if packages:
            quoted = " ".join(shlex.quote(p) for p in packages)
            if pm == "uv":
                return f"uv pip install {quoted}"
            if pm == "pip":
                return f"pip install {quoted}"
            return f"uv pip install {quoted} || pip install {quoted}"
        return "pip install -U pip"

    if kind == "node":
        if packages:
            quoted = " ".join(shlex.quote(p) for p in packages)
            if pm == "pnpm":
                return f"pnpm add {quoted}"
            if pm == "yarn":
                return f"yarn add {quoted}"
            return f"npm install {quoted}"
        if pm == "pnpm":
            return "pnpm install"
        if pm == "yarn":
            return "yarn install"
        return "npm install"

    raise ValueError(f"不支持的安装类型: {kind}")


async def install_tool(
    kind: str,
    workdir: str = "",
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    packages: Optional[list[str]] = None,
    requirements_file: str = "",
    package_manager: str = "",
    approval_id: Optional[str] = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> str:
    packages = packages or []
    command = _build_command(kind, package_manager, packages, requirements_file)
    err = _validate_command(command)
    if err:
        return f"⛔ {err}"

    wd = _get_workdir(workdir, session_id, task_id)
    approved, approval_message = await _approval_allows_execution(approval_id, command, session_id or task_id or "default")
    if not approved:
        return approval_message

    try:
        proc = await subprocess.create_subprocess_shell(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=wd,
            limit=1024 * 1024,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=max(1, int(timeout)))
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return json.dumps({
                "success": False,
                "message": f"⏱ 安装超时（>{timeout}s）",
                "command": command,
                "workdir": wd,
            }, ensure_ascii=False)

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        output = stdout + (("\n[stderr]\n" + stderr) if stderr else "")
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n...（输出过长，已截断）"
        return json.dumps({
            "success": proc.returncode == 0,
            "message": "✅ 安装完成" if proc.returncode == 0 else "❌ 安装失败",
            "command": command,
            "workdir": wd,
            "returncode": proc.returncode,
            "stdout": output,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "success": False,
            "message": f"❌ 安装执行失败: {exc}",
            "command": command,
            "workdir": wd,
        }, ensure_ascii=False)


def _register_tools():
    registry.register(
        name="install_dependencies",
        toolset="install",
        description=(
            "结构化安装工具。用于安装 Python / Node / Playwright / Git MCP 相关依赖。"
            "优先在工作区或项目目录内执行，不要手拼命令。"
        ),
        schema=INSTALL_SCHEMA,
        handler=install_tool,
        is_async=True,
        emoji="📦",
        parallel_mode="never",
    )


_register_tools()
