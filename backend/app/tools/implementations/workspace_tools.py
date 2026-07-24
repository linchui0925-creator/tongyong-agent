"""
workspace_tools - Single-agent isolated filesystem workspace.

Code/data tasks should use these tools by default so generated files, commands,
and intermediate artifacts do not write into the main project unless the user
explicitly asks to modify repository files.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from app.core.multi_agent.workspace import SUBDIRS, TaskWorkspace
from app.tools.registry import registry
from app.tools.runtime_context import get_tool_session_id, get_tool_turn_strategy
from app.paths import data_path


_MAX_READ_CHARS = 100_000
_MAX_OUTPUT_CHARS = 100_000
_DEFAULT_TIMEOUT = 120
_MAX_TIMEOUT = 900


def _workspace_root() -> str:
    return os.getenv("TONGYONG_WORKSPACE_ROOT", data_path("workspaces"))


def _safe_task_id(session_id: Optional[str] = None, task_id: Optional[str] = None) -> str:
    raw = task_id or session_id or get_tool_session_id()
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(raw))
    return safe[:80] or "default"


def _get_workspace(session_id: Optional[str] = None, task_id: Optional[str] = None) -> TaskWorkspace:
    return TaskWorkspace(_safe_task_id(session_id, task_id), root=_workspace_root(), created_by="single-agent").init()


def _validate_subdir(subdir: str) -> Optional[str]:
    if subdir not in SUBDIRS:
        return f"子目录必须是 {', '.join(SUBDIRS)} 之一"
    return None


def _validate_filename(filename: str) -> Optional[str]:
    if not filename or not str(filename).strip():
        return "filename 不能为空"
    p = Path(filename)
    if p.is_absolute() or ".." in p.parts:
        return "filename 必须是工作区内相对路径，不能是绝对路径或包含 .."
    return None


def _artifact_payload(path: str, kind: str, name: Optional[str] = None) -> dict:
    p = Path(path)
    encoded = quote(str(p), safe="")
    preview_url = f"/api/files/serve?path={encoded}" if kind == "image" else f"/api/files/preview?path={encoded}"
    return {
        "path": str(p),
        "name": name or p.name,
        "kind": kind,
        "preview_url": preview_url,
        "open_url": f"/api/files/serve?path={encoded}",
        "render_mode": "iframe" if kind == "web" else "image",
    }


WORKSPACE_INFO_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "可选会话 ID；默认使用当前请求会话。"},
        "task_id": {"type": "string", "description": "可选任务 ID；传入时覆盖 session_id。"},
    },
}


WORKSPACE_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "subdir": {
            "type": "string",
            "enum": list(SUBDIRS),
            "description": "工作区子目录。",
            "default": "output",
        },
        "pattern": {
            "type": "string",
            "description": "glob pattern，默认 **/*。",
            "default": "**/*",
        },
        "session_id": {"type": "string", "description": "可选会话 ID；默认使用当前请求会话。"},
        "task_id": {"type": "string", "description": "可选任务 ID；传入时覆盖 session_id。"},
    },
}


WORKSPACE_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "subdir": {"type": "string", "enum": list(SUBDIRS), "description": "工作区子目录。"},
        "filename": {"type": "string", "description": "工作区内相对文件名。"},
        "offset": {"type": "integer", "description": "起始行号，从 1 开始。", "default": 1},
        "limit": {"type": "integer", "description": "最多读取行数，-1 表示全部。", "default": 2000},
        "session_id": {"type": "string", "description": "可选会话 ID；默认使用当前请求会话。"},
        "task_id": {"type": "string", "description": "可选任务 ID；传入时覆盖 session_id。"},
    },
    "required": ["subdir", "filename"],
}


WORKSPACE_WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "subdir": {"type": "string", "enum": list(SUBDIRS), "description": "工作区子目录。"},
        "filename": {"type": "string", "description": "工作区内相对文件名。"},
        "content": {"type": "string", "description": "文件内容。"},
        "session_id": {"type": "string", "description": "可选会话 ID；默认使用当前请求会话。"},
        "task_id": {"type": "string", "description": "可选任务 ID；传入时覆盖 session_id。"},
    },
    "required": ["subdir", "filename", "content"],
}


WORKSPACE_TERMINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "要在工作区根目录执行的命令。"},
        "timeout": {"type": "integer", "description": f"超时秒数，默认 {_DEFAULT_TIMEOUT}s。", "default": _DEFAULT_TIMEOUT},
        "session_id": {"type": "string", "description": "可选会话 ID；默认使用当前请求会话。"},
        "task_id": {"type": "string", "description": "可选任务 ID；传入时覆盖 session_id。"},
        "approval_id": {"type": "string", "description": "高风险命令审批通过后的 ID。"},
        "sandbox_mode": {
            "type": "string",
            "enum": ["off", "macos"],
            "description": "可选沙盒模式。macOS 下可用 sandbox-exec 隔离工作区命令。",
            "default": "off",
        },
        "sandbox_preset": {
            "type": "string",
            "enum": ["read_only", "workspace_only", "network_off"],
            "description": "预设沙盒配置。与 sandbox_profile 二选一使用。",
        },
        "sandbox_profile": {
            "type": "string",
            "description": "可选自定义 sandbox-exec profile 文本。仅在 sandbox_mode=macos 时生效。",
        },
    },
    "required": ["command"],
}


async def workspace_info_tool(session_id: Optional[str] = None, task_id: Optional[str] = None) -> str:
    ws = _get_workspace(session_id, task_id)
    return json.dumps({
        "task_id": ws.task_id,
        "workspace_path": str(ws.base),
        "subdirs": list(SUBDIRS),
    }, ensure_ascii=False)


async def workspace_list_tool(
    subdir: str = "output",
    pattern: str = "**/*",
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> str:
    err = _validate_subdir(subdir)
    if err:
        return err
    ws = _get_workspace(session_id, task_id)
    root = ws.base / subdir
    files = []
    if root.exists():
        for p in sorted(root.glob(pattern or "**/*")):
            if p.is_file():
                files.append({"path": str(p.relative_to(ws.base)), "size": p.stat().st_size})
    return json.dumps({
        "task_id": ws.task_id,
        "workspace_path": str(ws.base),
        "count": len(files),
        "files": files[:500],
    }, ensure_ascii=False, indent=2)


async def workspace_read_tool(
    subdir: str,
    filename: str,
    offset: int = 1,
    limit: int = 2000,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> str:
    err = _validate_subdir(subdir) or _validate_filename(filename)
    if err:
        return err
    ws = _get_workspace(session_id, task_id)
    path = ws.path(subdir, filename)
    if not path.exists():
        return f"文件不存在: {subdir}/{filename}"
    if not path.is_file():
        return f"不是文件: {subdir}/{filename}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"读取失败: {exc}"

    lines = text.splitlines(keepends=True)
    if offset < 1:
        offset = 1
    if limit == -1:
        limit = len(lines)
    start = offset - 1
    end = min(start + limit, len(lines))
    content = "".join(lines[start:end])
    if len(content) > _MAX_READ_CHARS:
        content = content[:_MAX_READ_CHARS] + f"\n...（内容过长，已截断至 {_MAX_READ_CHARS} 字符）"
    return f"📄 workspace/{subdir}/{filename}（{len(lines)} 行，显示 {start + 1}-{end}）\n{content}"


def _artifact_payload(path: str, kind: str, name: Optional[str] = None) -> dict:
    encoded = quote(path, safe="")
    preview_url = f"/api/files/serve?path={encoded}" if kind == "image" else f"/api/files/preview?path={encoded}"
    return {
        "path": path,
        "name": name or Path(path).name,
        "kind": kind,
        "preview_url": preview_url,
        "open_url": f"/api/files/serve?path={encoded}",
        "render_mode": "iframe" if kind == "web" else "image",
    }


def workspace_write_tool(
    subdir: str,
    filename: str,
    content: str,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> str:
    err = _validate_subdir(subdir) or _validate_filename(filename)
    if err:
        return err
    ws = _get_workspace(session_id, task_id)
    path = ws.write(subdir, filename, content)
    suffix = Path(filename).suffix.lower()
    artifact_previews = []
    if suffix in {".html", ".htm"}:
        artifact_previews.append(_artifact_payload(str(path), "web", Path(filename).name))
    elif suffix in {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        artifact_previews.append(_artifact_payload(str(path), "image", Path(filename).name))
    return json.dumps({
        "message": f"✅ 已写入 workspace/{subdir}/{filename}（{len(content)} 字符）",
        "workspace_path": str(ws.base),
        "absolute_path": str(path),
        "path": str(path),
        "name": Path(filename).name,
        "kind": "web" if suffix in {".html", ".htm"} else "image" if suffix in {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"} else "file",
        "artifact_previews": artifact_previews,
    }, ensure_ascii=False)


async def workspace_terminal_tool(
    command: str,
    timeout: int = _DEFAULT_TIMEOUT,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    approval_id: Optional[str] = None,
    sandbox_mode: str = "off",
    sandbox_preset: str = "",
    sandbox_profile: str = "",
) -> str:
    from app.tools.implementations.terminal import _approval_allows_execution, _validate_command

    err = _validate_command(command)
    if err:
        return f"⛔ {err}"

    ws = _get_workspace(session_id, task_id)
    strategy = get_tool_turn_strategy() or {}
    if sandbox_mode == "off":
        sandbox_mode = str(strategy.get("sandbox_mode", "off") or "off")
    if not sandbox_preset:
        sandbox_preset = str(strategy.get("sandbox_preset", "") or "")
    approved, approval_message = await _approval_allows_execution(approval_id, command, session_id or ws.task_id)
    if not approved:
        return approval_message
    if sandbox_mode not in {"off", "macos"}:
        return f"⛔ 不支持的 sandbox_mode: {sandbox_mode}"
    if sandbox_preset and sandbox_preset not in {"read_only", "workspace_only", "network_off"}:
        return f"⛔ 不支持的 sandbox_preset: {sandbox_preset}"
    if sandbox_preset and sandbox_profile.strip():
        return "⛔ sandbox_preset 与 sandbox_profile 只能二选一"

    timeout = max(1, min(int(timeout or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))
    shell_cmd = command
    if sandbox_mode == "macos":
        profile = sandbox_profile.strip()
        if sandbox_preset == "read_only":
            profile = "(version 1)\n(deny default)\n(allow file-read*)\n(allow process*)"
        elif sandbox_preset == "workspace_only":
            profile = "(version 1)\n(deny default)\n(allow file-read*)\n(allow file-write* (subpath \".\"))\n(allow process*)"
        elif sandbox_preset == "network_off":
            profile = "(version 1)\n(deny default)\n(allow file-read*)\n(allow file-write* (subpath \".\"))\n(allow process*)\n(deny network*)"
        if not profile:
            profile = "(version 1)\n(deny default)\n(allow file-read*)\n(allow file-write* (subpath \".\"))\n(allow process*)\n(allow network*)"
        shell_cmd = f"sandbox-exec -p {shlex.quote(profile)} {command}"

    try:
        process = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws.base),
            limit=1024 * 1024,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return f"⏱ workspace 命令执行超时（>{timeout}s）"

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        output = stdout
        if stderr:
            output += ("\n" if output else "") + f"[stderr]\n{stderr}"
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n...（输出过长，已截断）"
        status = "✅" if process.returncode == 0 else "❌"
        artifact_previews = []
        for p in ws.base.rglob("*.html"):
            artifact_previews.append(_artifact_payload(str(p), "web", p.name))
            break
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg"):
            if artifact_previews:
                break
            for p in ws.base.rglob(ext):
                artifact_previews.append(_artifact_payload(str(p), "image", p.name))
                break
        sandbox_note = ""
        if sandbox_mode == "macos":
            sandbox_note = f" [沙盒环境中执行: macOS{f'/{sandbox_preset}' if sandbox_preset else ''}]"
        return json.dumps({
            "message": f"{status} workspace 命令完成（返回码 {process.returncode}，cwd={ws.base}）{sandbox_note}",
            "returncode": process.returncode,
            "workspace_path": str(ws.base),
            "stdout": output,
            "artifact_previews": artifact_previews,
        }, ensure_ascii=False)
    except Exception as exc:
        return f"❌ workspace 命令执行失败: {exc}"


def _register_tools():
    registry.register(
        name="workspace_info",
        toolset="workspace",
        description="查看当前会话隔离工作区路径和子目录。代码/数据任务应先用此工具确认工作区。",
        schema=WORKSPACE_INFO_SCHEMA,
        handler=workspace_info_tool,
        is_async=True,
        emoji="🧰",
        parallel_mode="safe",
    )
    registry.register(
        name="workspace_list",
        toolset="workspace",
        description="列出当前会话隔离工作区文件。默认只查看当前会话 workspace，不触碰主项目目录。",
        schema=WORKSPACE_LIST_SCHEMA,
        handler=workspace_list_tool,
        is_async=True,
        emoji="🧰",
        parallel_mode="safe",
    )
    registry.register(
        name="workspace_read",
        toolset="workspace",
        description="读取当前会话隔离工作区内文件。代码/数据任务默认使用 workspace_read 而不是 read_file。",
        schema=WORKSPACE_READ_SCHEMA,
        handler=workspace_read_tool,
        is_async=True,
        emoji="🧰",
        max_result_size_chars=_MAX_READ_CHARS,
        parallel_mode="safe",
    )
    registry.register(
        name="workspace_write",
        toolset="workspace",
        description="写入当前会话隔离工作区文件。代码/网页/数据产物默认写 workspace，避免污染主项目。",
        schema=WORKSPACE_WRITE_SCHEMA,
        handler=workspace_write_tool,
        is_async=True,
        emoji="🧰",
        parallel_mode="path_scoped",
    )
    registry.register(
        name="workspace_terminal",
        toolset="workspace",
        description="在当前会话隔离工作区根目录执行命令并等待输出完成；不会提前结束。代码任务默认用它运行 build/test。",
        schema=WORKSPACE_TERMINAL_SCHEMA,
        handler=workspace_terminal_tool,
        is_async=True,
        emoji="🧰",
        max_result_size_chars=_MAX_OUTPUT_CHARS,
        parallel_mode="never",
    )


_register_tools()
