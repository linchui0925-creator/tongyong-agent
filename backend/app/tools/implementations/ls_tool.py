"""
ls_tool - 目录列表工具

列出目录内容，支持递归、深度限制、文件类型过滤、排序、详细信息。
比 subprocess ls 更结构化，结果可直接被 LLM 解析。
"""

import asyncio
import logging
import os
import stat
from pathlib import Path
from typing import Optional, List

from app.tools.registry import registry

logger = logging.getLogger(__name__)

_MAX_ITEMS = 500


def _resolve_path(path: str) -> Optional[Path]:
    if not path:
        return Path.cwd()
    try:
        return Path(path).expanduser().resolve()
    except Exception:
        return None


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}K"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}M"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f}G"


def _get_perms(mode: int) -> str:
    is_dir = stat.S_ISDIR(mode)
    perms = "d" if is_dir else "-"
    # Permission bits: S_IRUSR, S_IWUSR, S_IXUSR, etc.
    perm_map = [
        (stat.S_IRUSR, "r"), (stat.S_IWUSR, "w"), (stat.S_IXUSR, "x"),
        (stat.S_IRGRP, "r"), (stat.S_IWGRP, "w"), (stat.S_IXGRP, "x"),
        (stat.S_IROTH, "r"), (stat.S_IWOTH, "w"), (stat.S_IXOTH, "x"),
    ]
    for bit, char in perm_map:
        perms += char if mode & bit else "-"
    return perms


async def ls_tool(
    path: str = ".",
    recursive: bool = False,
    depth: int = 1,
    show_hidden: bool = False,
    file_type: Optional[str] = None,
    sort_by: str = "name",
    max_items: int = 100,
    task_id: str = "default",
) -> str:
    """
    列出目录内容

    Args:
        path: 目录路径（默认当前目录）
        recursive: 是否递归列出子目录
        depth: 递归深度（recursive=True 时生效）
        show_hidden: 是否显示隐藏文件（以 . 开头）
        file_type: 按类型过滤：'dirs' 只显示目录，'files' 只显示文件
        sort_by: 排序方式：name / size / modified / type
        max_items: 最大显示项目数
        task_id: 任务标识（内部使用）
    """
    resolved = _resolve_path(path)
    if not resolved:
        return f"路径无效: {path}"

    if not resolved.exists():
        return f"路径不存在: {resolved}"

    if resolved.is_file():
        # 如果是文件，返回文件信息
        s = resolved.stat()
        return (
            f"文件: {resolved}\n"
            f"大小: {_format_size(s.st_size)}\n"
            f"权限: {_get_perms(s.st_mode)}\n"
            f"修改: {__import__('datetime').datetime.fromtimestamp(s.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"类型: {resolved.suffix or '(无扩展名)'}"
        )

    items: List[tuple] = []

    def scan_dir(dir_path: Path, current_depth: int):
        try:
            entries = list(dir_path.iterdir())
        except PermissionError:
            return
        except OSError:
            return

        for entry in entries:
            if not show_hidden and entry.name.startswith("."):
                continue
            if entry.name in {".DS_Store", "Thumbs.db"}:
                continue

            if file_type == "dirs" and not entry.is_dir():
                continue
            if file_type == "files" and not entry.is_file():
                continue

            try:
                s = entry.stat()
                items.append((
                    entry,
                    s.st_size if entry.is_file() else 0,
                    s.st_mtime,
                    stat.S_ISDIR(s.st_mode),
                ))
            except OSError:
                continue

            # 递归
            if recursive and entry.is_dir() and (depth <= 0 or current_depth < depth):
                scan_dir(entry, current_depth + 1)

    scan_dir(resolved, 0)

    # 排序
    if sort_by == "size":
        items.sort(key=lambda x: (-x[3], -x[1]))  # dirs first, then by size
    elif sort_by == "modified":
        items.sort(key=lambda x: (-x[3], -x[2]))
    elif sort_by == "type":
        items.sort(key=lambda x: (not x[3], x[0].suffix, x[0].name))
    else:  # name
        items.sort(key=lambda x: (not x[3], x[0].name.lower()))

    if not items:
        return f"{resolved} 是空目录" + ("" if show_hidden else "（使用 show_hidden=true 查看隐藏文件）")

    # 截断
    if len(items) > max_items:
        items = items[:max_items]
        truncated = True
    else:
        truncated = False

    # 格式化输出
    lines = [f"目录: {resolved} | 项目数: {len(items)}"]
    if recursive:
        lines.append(f"递归深度: {depth}")
    if file_type:
        lines.append(f"类型过滤: {file_type}")
    lines.append("")

    # 计算列宽
    max_name_len = min(max(len(str(e[0])) for e in items), 60)
    max_size_len = max(len(_format_size(e[1])) for e in items) if any(e[1] > 0 for e in items) else 4

    lines.append(f"{'权限':<10} {'大小':<{max_size_len}} {'修改时间':<19} {'名称'}")
    lines.append("-" * (10 + max_size_len + 19 + max_name_len + 5))

    for entry, size, mtime, is_dir in items:
        perms = _get_perms(entry.stat().st_mode) if not is_dir else "d" + "rwxr-xr-x"
        size_str = _format_size(size) if not is_dir else "-"
        mtime_str = __import__("datetime").datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        name = entry.name + "/" if is_dir else entry.name
        lines.append(f"{perms:<10} {size_str:<{max_size_len}} {mtime_str:<19} {name}")

    if truncated:
        lines.append(f"\n...（共 {len(items)} 项，已截断至 {max_items}）")

    # 统计摘要
    total_dirs = sum(1 for e in items if e[3])
    total_files = len(items) - total_dirs
    lines.append(f"\n摘要: {total_dirs} 目录, {total_files} 文件")

    return "\n".join(lines)


LS_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "目录路径（默认当前目录）",
            "default": ".",
        },
        "recursive": {
            "type": "boolean",
            "description": "是否递归列出子目录内容",
            "default": False,
        },
        "depth": {
            "type": "integer",
            "description": "递归深度（recursive=True 时生效，0=无限）",
            "default": 1,
        },
        "show_hidden": {
            "type": "boolean",
            "description": "是否显示隐藏文件（以 . 开头）",
            "default": False,
        },
        "file_type": {
            "type": "string",
            "description": "按类型过滤：'dirs' 只显示目录，'files' 只显示文件",
        },
        "sort_by": {
            "type": "string",
            "description": "排序方式（枚举: name, size, modified, type）",
            "default": "name",
            "enum": ["name", "size", "modified", "type"],
        },
        "max_items": {
            "type": "integer",
            "description": "最大显示项目数",
            "default": 100,
        },
        "task_id": {
            "type": "string",
            "description": "任务标识（内部使用）",
            "default": "default",
        },
    },
    "required": [],
}


registry.register(
    name="ls",
    toolset="terminal",
    description="列出目录内容。支持递归、深度限制、文件类型过滤、排序、详细信息（权限/大小/时间）。比 subprocess ls 更结构化，结果可直接被 LLM 解析。",
    schema=LS_SCHEMA,
    handler=ls_tool,
    is_async=True,
    emoji="📁",
    parallel_mode="safe",
)
