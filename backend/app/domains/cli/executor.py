"""
CLIExecutor - CLI 命令执行器

将 LLM 的认知转化为实际的命令执行能力。
使用 asyncio.subprocess 执行命令，复用 terminal 工具的安全配置。
"""

import asyncio
import logging
import os
import re
from typing import Dict, Any, List, Optional

from app.domains.base import BaseDomainExecutor
from app.tools.security_config import _ALLOWED_COMMANDS, _FORBIDDEN_PATTERNS

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 100_000
_DEFAULT_TIMEOUT = 60


class CLIExecutor(BaseDomainExecutor):
    """CLI 命令执行器"""

    @property
    def name(self) -> str:
        return "cli"

    @property
    def description(self) -> str:
        return "执行 CLI 命令：运行测试、启动服务、安装依赖、文件操作、Git、Docker 等"

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    # ── 命令验证 ────────────────────────────────────────

    def _validate_command(self, command: str) -> Optional[str]:
        """验证命令安全性，返回错误信息或 None"""
        if len(command) > 2000:
            return "命令过长（最多 2000 字符）"

        cmd_base = command.split()[0] if command.split() else ""
        if cmd_base not in _ALLOWED_COMMANDS:
            return f"命令 '{cmd_base}' 不在允许列表中"

        for pattern in _FORBIDDEN_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return f"命令包含禁止的模式: {pattern}"

        if ".." in command and "/" in command:
            if re.search(r"\.\.[/\\]", command):
                return "路径遍历攻击检测"

        return None

    # ── 命令执行 ────────────────────────────────────────

    async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行 CLI 动作"""
        if action == "run":
            command = params.get("command", "")
            if not command:
                return {"success": False, "error": "命令不能为空", "stdout": "", "stderr": "", "returncode": -1}

            err = self._validate_command(command)
            if err:
                return {"success": False, "error": err, "stdout": "", "stderr": err, "returncode": -1}

            return await self._run_command(command)

        return {"success": False, "error": f"不支持的动作: {action}", "stdout": "", "stderr": "", "returncode": -1}

    async def _run_command(self, command: str) -> Dict[str, Any]:
        """执行命令并返回结果"""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir if os.path.isdir(self.working_dir) else None,
                limit=1024 * 1024,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=_DEFAULT_TIMEOUT
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "success": False,
                    "error": f"命令执行超时（{_DEFAULT_TIMEOUT}秒）",
                    "stdout": "",
                    "stderr": "命令执行超时",
                    "returncode": -1,
                    "timeout": True,
                }

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            if len(stdout) > _MAX_OUTPUT_CHARS:
                stdout = stdout[:_MAX_OUTPUT_CHARS] + "\n...（输出过长，已截断）"
            if len(stderr) > _MAX_OUTPUT_CHARS:
                stderr = stderr[:_MAX_OUTPUT_CHARS] + "\n...（输出过长，已截断）"

            return {
                "success": process.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "returncode": process.returncode,
            }

        except Exception as e:
            logger.error(f"命令执行失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }

    # ── 能力清单 ────────────────────────────────────────

    def get_capabilities(self) -> List[Dict[str, Any]]:
        return [
            {"action": "run", "description": "执行 CLI 命令", "params": {"command": "要执行的命令字符串"}},
        ]

    # ── 命令提取 ────────────────────────────────────────

    def extract_from_response(self, text: str) -> Optional[str]:
        """
        从 LLM 响应中提取命令

        只匹配 ```bash/shell/sh 代码块，不匹配行内 `code`，
        避免将 LLM 自然语言中的行内引用误认为命令。
        """
        patterns = [
            r'```(?:bash|shell|sh)\s*\n(.*?)```',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                cmd = match.group(1).strip()
                if cmd and not cmd.startswith(("#", "//", "<!--")):
                    return cmd
        return None

    # ── 结果格式化 ──────────────────────────────────────

    def format_result(self, result: Dict[str, Any]) -> str:
        """格式化执行结果为可读文本（不使用 ``` 避免嵌套混淆）"""
        if result.get("success"):
            stdout = result.get("stdout", "").strip()
            if stdout:
                return stdout
            return "命令执行成功（无输出）"
        else:
            error = result.get("error") or result.get("stderr", "未知错误")
            return f"命令执行失败：{error}"
