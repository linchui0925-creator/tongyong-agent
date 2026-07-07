"""
terminal - 命令行执行工具

在终端中执行 shell 命令。支持超时、后台执行、工作目录、PTY 模式。
自带安全校验：白名单命令基 + 禁止模式 + 路径穿越检测。
"""

import asyncio
import json
import logging
import os
import re
import shlex
from typing import Optional

from app.tools.registry import registry
from app.tools.security_config import _ALLOWED_COMMANDS, _FORBIDDEN_PATTERNS

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 100_000
_DEFAULT_TIMEOUT = 60
_MAX_FOREGROUND_TIMEOUT = 600

_APPROVAL_PATTERNS = [
    (re.compile(r"\brm\s+-(?:[a-zA-Z]*r[a-zA-Z]*f|[a-zA-Z]*f[a-zA-Z]*r)\b"), "recursive_force_delete", "critical"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git_reset_hard", "high"),
    (re.compile(r"\bgit\s+clean\s+-[^\n]*f"), "git_clean_force", "high"),
    (re.compile(r"\bchmod\s+-R\b"), "recursive_chmod", "high"),
    (re.compile(r"\bchown\s+-R\b"), "recursive_chown", "high"),
]


def _validate_command(command: str) -> Optional[str]:
    """验证命令安全性，返回错误信息或 None"""
    if len(command) > 2000:
        return "命令过长（最多 2000 字符）"

    cmd_base = command.split()[0] if command.split() else ""
    if cmd_base not in _ALLOWED_COMMANDS:
        return f"命令 '{cmd_base}' 不在允许列表中"

    for pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"命令包含禁止的模式: {pattern}"

    # 路径穿越
    if ".." in command and "/" in command:
        if re.search(r"\.\.[/\\]", command):
            return "路径遍历攻击检测"

    # 禁止通过任何方式调用 playwright（import、CLI 命令、Python 脚本）
    if re.search(r'\bplaywright\b', command, re.IGNORECASE):
        return "浏览器操作请使用 browser 工具，不要通过终端调用 playwright"

    return None


def _approval_risk(command: str) -> Optional[dict]:
    matched = []
    highest = None
    rank = {"medium": 1, "high": 2, "critical": 3}
    for pattern, description, level in _APPROVAL_PATTERNS:
        if pattern.search(command):
            matched.append({"description": description, "risk_level": level})
            if highest is None or rank[level] > rank[highest]:
                highest = level
    if not matched:
        return None
    return {"risk_level": highest or "high", "matched_patterns": matched}


async def _approval_allows_execution(
    approval_id: Optional[str],
    command: str,
    session_id: Optional[str],
) -> tuple[bool, str]:
    risk = _approval_risk(command)
    if not risk:
        return True, ""

    from app.tools.approval import ApprovalManager

    manager = ApprovalManager()
    if approval_id:
        request = await manager.get_request(approval_id)
        if not request:
            return False, json.dumps({
                "approval_required": True,
                "status": "not_found",
                "approval_id": approval_id,
                "reason": "审批记录不存在",
            }, ensure_ascii=False)
        approved_command = str((request.parameters or {}).get("command", ""))
        if approved_command != command:
            return False, json.dumps({
                "approval_required": True,
                "status": "command_mismatch",
                "approval_id": approval_id,
                "reason": "审批 ID 对应的命令与本次命令不一致，不能复用审批。",
                "approved_command": approved_command,
            }, ensure_ascii=False)
        if request.status == "approved":
            return True, ""
        return False, json.dumps({
            "approval_required": True,
            "status": request.status,
            "approval_id": approval_id,
            "reason": "高风险命令尚未批准",
        }, ensure_ascii=False)

    request = await manager.create_request(
        tool_name="terminal",
        parameters={"command": command},
        session_id=session_id or "default",
        user_id="agent",
        risk_level=risk["risk_level"],
    )
    await manager.update_risk_assessment(request.id, risk)
    return False, json.dumps({
        "approval_required": True,
        "status": "pending",
        "approval_id": request.id,
        "risk_assessment": risk,
        "message": "高风险命令已拦截，请在审批队列批准后携带 approval_id 重新调用 terminal。",
    }, ensure_ascii=False)


def _check_terminal() -> bool:
    """终端工具总是可用"""
    return True


TERMINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "要执行的 shell 命令",
        },
        "timeout": {
            "type": "integer",
            "description": f"超时秒数（默认 {_DEFAULT_TIMEOUT}s，前台最大 {_MAX_FOREGROUND_TIMEOUT}s）",
            "default": _DEFAULT_TIMEOUT,
        },
        "workdir": {
            "type": "string",
            "description": "工作目录（绝对路径，默认当前目录）",
        },
        "background": {
            "type": "boolean",
            "description": "后台执行（适用于长时间运行的任务，默认 false）",
            "default": False,
        },
        "session_id": {
            "type": "string",
            "description": "当前会话 ID，用于高风险命令审批队列归属。",
        },
        "approval_id": {
            "type": "string",
            "description": "审批通过后的 ID。高风险命令必须携带已批准的 approval_id 才会执行。",
        },
    },
    "required": ["command"],
}


async def terminal_tool(
    command: str,
    timeout: int = _DEFAULT_TIMEOUT,
    workdir: str = "",
    background: bool = False,
    session_id: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> str:
    # 安全校验
    err = _validate_command(command)
    if err:
        return f"⛔ {err}"

    approved, approval_message = await _approval_allows_execution(approval_id, command, session_id)
    if not approved:
        return approval_message

    cwd = workdir if workdir else None
    if cwd and not os.path.isdir(cwd):
        return f"工作目录不存在: {cwd}"

    timeout = min(timeout, _MAX_FOREGROUND_TIMEOUT if not background else 86400)

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            limit=1024 * 1024,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return f"⏱ 命令执行超时（>{timeout}s）"

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        output = ""
        if stdout:
            output += stdout
        if stderr:
            if output:
                output += "\n"
            output += f"[stderr]\n{stderr}"

        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n...（输出过长，已截断）"

        status = "✅" if process.returncode == 0 else "❌"
        return f"{status} 命令完成（返回码 {process.returncode}）\n{output}"

    except Exception as e:
        logger.error(f"命令执行失败: {e}", exc_info=True)
        return f"❌ 命令执行失败: {e}"




def _register_tools():
    registry.register(
        name="terminal",
        toolset="terminal",
        description="执行 shell 命令（编译、运行、安装、git、文件操作等）。支持超时、工作目录、后台执行。注意：不要用此工具实现浏览器操作（打开网页、截图等）——请使用专门的 browser 工具。",
        schema=TERMINAL_SCHEMA,
        handler=terminal_tool,
        check_fn=_check_terminal,
        is_async=True,
        emoji="💻",
        max_result_size_chars=_MAX_OUTPUT_CHARS,
        parallel_mode="never",
    )


# 启动时注册 (W4-21 P2-2: 显式 _register_tools, 便于测试 mock)
_register_tools()
