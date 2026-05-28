"""
grep_tool - 文件内容搜索工具

在文件和目录中执行正则表达式搜索，支持上下文行、高亮、文件类型过滤。
比 search_files 更强大（支持正则），比 terminal grep 更易用（结构化参数）。
"""

import asyncio
import logging
import os
import re
import stat
from pathlib import Path
from typing import Optional, List

from app.tools.registry import registry

logger = logging.getLogger(__name__)

_MAX_RESULTS = 1000
_MAX_LINE_CONTEXT = 3


def _resolve_path(path: str, task_id: str = "default") -> Optional[Path]:
    """安全路径解析，限制在允许范围内"""
    if not path:
        return Path.cwd()
    try:
        resolved = Path(path).expanduser().resolve()
        # 禁止访问敏感路径
        forbidden = {"/etc/sudoers", "/etc/shadow", "/.ssh", "/.aws"}
        for forb in forbidden:
            if str(resolved).startswith(forb):
                return None
        return resolved
    except Exception:
        return None


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            f.read(8192)
        return False
    except Exception:
        return True


def _match_file(path: Path, pattern: str, glob: Optional[str], case_sensitive: bool) -> bool:
    """判断文件是否应该被搜索"""
    name = path.name
    if not case_sensitive:
        name = name.lower()
        pattern_lower = pattern.lower()
    else:
        pattern_lower = pattern

    if glob:
        if not re.match(glob.replace("*", ".*").replace("?", "."), name):
            return False
    return pattern_lower in name


async def grep_tool(
    pattern: str,
    path: str = ".",
    glob: Optional[str] = None,
    case_sensitive: bool = False,
    context_lines: int = 0,
    max_results: int = 100,
    file_type: Optional[str] = None,
    task_id: str = "default",
) -> str:
    """
    搜索文件内容或文件名

    Args:
        pattern: 搜索关键词或正则表达式
        path: 搜索起始目录（默认当前目录）
        glob: 文件名通配符过滤，如 '*.py'、'*.{py,js}'
        case_sensitive: 是否区分大小写
        context_lines: 每个匹配结果周围显示多少行上下文（0=不显示）
        max_results: 最大匹配数（达到后截断）
        file_type: 按文件类型过滤（py/js/ts/md/txt/log 等扩展名）
        task_id: 任务标识（内部使用）
    """
    resolved = _resolve_path(path, task_id)
    if not resolved:
        return f"路径无效或被禁止: {path}"

    if not resolved.exists():
        return f"路径不存在: {resolved}"

    # 编译正则
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"正则表达式错误: {e}"

    # 文件类型过滤器
    type_exts = None
    if file_type:
        type_exts = {f".{file_type.lower().lstrip('.')}"}
        # 常见类型快捷映射
        common_types = {
            "python": ".py", "py": ".py",
            "javascript": ".js", "js": ".js",
            "typescript": ".ts", "ts": ".ts",
            "markdown": ".md", "md": ".md",
            "text": ".txt", "txt": ".txt",
            "log": ".log",
            "json": ".json",
            "yaml": ".yaml", "yml": ".yml",
            "html": ".html", "htm": ".htm",
            "css": ".css",
            "shell": ".sh",
        }
        if file_type.lower() in common_types:
            type_exts = {common_types[file_type.lower()]}

    # 跳过目录
    skip_dirs = {".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode"}
    skip_patterns = {".DS_Store", "Thumbs.db"}

    matches: List[dict] = []
    total_lines = 0

    async def search_file(file_path: Path) -> List[dict]:
        """在单个文件中搜索"""
        results = []
        try:
            if _is_binary(file_path):
                return results
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except (OSError, PermissionError):
            return results

        file_matches = []
        for i, line in enumerate(lines):
            line_stripped = line.rstrip()
            if regex.search(line_stripped):
                # 构建上下文
                context_before = []
                if context_lines > 0:
                    start = max(0, i - context_lines)
                    context_before = [(j + 1, lines[j].rstrip()) for j in range(start, i)]

                match_start = regex.search(line_stripped).start()
                match_end = regex.search(line_stripped).end()
                highlighted = (
                    line_stripped[:match_start]
                    + "\033[91m" + line_stripped[match_start:match_end] + "\033[0m"
                    + line_stripped[match_end:]
                )

                entry = {
                    "file": str(file_path),
                    "line": i + 1,
                    "content": line_stripped,
                    "highlighted": highlighted,
                    "context_before": context_before,
                }
                file_matches.append(entry)

        return file_matches

    async def search_dir(dir_path: Path):
        """递归搜索目录"""
        try:
            entries = list(dir_path.iterdir())
        except PermissionError:
            return

        dirs_to_continue = []
        for entry in entries:
            if entry.name in skip_patterns:
                continue
            if entry.is_dir():
                if entry.name in skip_dirs:
                    continue
                dirs_to_continue.append(entry)
            elif entry.is_file():
                # 文件类型过滤
                if type_exts and entry.suffix.lower() not in type_exts:
                    continue
                # glob 过滤（用于文件名）
                if glob and not _match_file(entry, pattern, glob, case_sensitive):
                    continue

                file_matches = await search_file(entry)
                for fm in file_matches:
                    matches.append(fm)
                    if len(matches) >= max_results:
                        return

        # 继续搜索子目录
        for subdir in dirs_to_continue:
            if len(matches) >= max_results:
                break
            await search_dir(subdir)

    # 执行搜索
    if resolved.is_file():
        file_matches = await search_file(resolved)
        matches.extend(file_matches)
    else:
        await search_dir(resolved)

    # 格式化输出
    if not matches:
        return f"在 {resolved} 中未找到匹配 '{pattern}' 的内容"

    # 构建结果
    lines = [f"搜索: '{pattern}' | 路径: {resolved} | 匹配: {len(matches)} 个"]
    if glob:
        lines.append(f"文件名过滤: {glob}")
    if type_exts:
        lines.append(f"文件类型: {file_type}")
    lines.append("")

    # 按文件分组
    by_file: dict = {}
    for m in matches:
        f = m["file"]
        by_file.setdefault(f, []).append(m)

    for fpath, file_matches in sorted(by_file.items()):
        lines.append(f"\n{fpath}:")
        for m in file_matches:
            if context_lines > 0 and m.get("context_before"):
                for lc, lb in m["context_before"]:
                    lines.append(f"  {lc}: {lb}")
            lines.append(f"  {m['line']}: {m['content']}")

    if len(matches) >= max_results:
        lines.append(f"\n...（已达最大结果数 {max_results}）")

    total_lines = sum(len(file_matches) for file_matches in by_file.values())
    lines.append(f"\n共 {len(by_file)} 个文件，{total_lines} 个匹配")

    return "\n".join(lines)


GREP_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "搜索关键词或正则表达式",
        },
        "path": {
            "type": "string",
            "description": "搜索起始目录（默认当前目录）",
            "default": ".",
        },
        "glob": {
            "type": "string",
            "description": "文件名通配符过滤，如 '*.py'、'*.{py,js}'",
        },
        "case_sensitive": {
            "type": "boolean",
            "description": "是否区分大小写",
            "default": False,
        },
        "context_lines": {
            "type": "integer",
            "description": "每个匹配周围显示的上下文行数",
            "default": 0,
        },
        "max_results": {
            "type": "integer",
            "description": "最大匹配数",
            "default": 100,
        },
        "file_type": {
            "type": "string",
            "description": "按文件类型过滤（python/py, js, ts, md, txt, log, json, yaml 等）",
        },
        "task_id": {
            "type": "string",
            "description": "任务标识（内部使用）",
            "default": "default",
        },
    },
    "required": ["pattern"],
}


registry.register(
    name="grep",
    toolset="terminal",
    description="在文件中搜索匹配正则表达式的内容。比 search_files 更强大，支持正则。返回文件名、行号、匹配内容及上下文。",
    schema=GREP_SCHEMA,
    handler=grep_tool,
    is_async=True,
    emoji="🔎",
    parallel_mode="safe",
)
