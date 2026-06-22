"""
glob_tool - 文件路径模式匹配工具

按 glob 模式（**/*.py, src/**/*.ts 等）查找文件，列出匹配的相对路径。
与 ls 的区别: ls 列目录内容, glob 按模式跨目录匹配。

底层走 pathlib.Path.glob, 原生支持:
  *  *         单层通配
  *  **        跨任意层目录
  *  ?         单字符
  *  [abc]     字符集

为安全默认:
- 不递归进 .git / .venv / node_modules / __pycache__ 等高成本目录
- 结果限制 max_results (默认 500), 避免一次返回过多
- 默认不显示 . 开头的隐藏文件
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from app.tools.registry import registry

logger = logging.getLogger(__name__)

_MAX_RESULTS = 500

# 递归时主动跳过的目录 (节省时间, 避免误返回构建产物)
_PRUNE_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".next", ".vite", "target",  # Rust / Node 构建
})


def _resolve_path(path: str) -> Optional[Path]:
    if not path:
        return Path.cwd()
    try:
        return Path(path).expanduser().resolve()
    except Exception:
        return None


async def glob_tool(
    pattern: str,
    path: str = ".",
    include_hidden: bool = False,
    max_results: int = _MAX_RESULTS,
) -> str:
    """按 glob 模式匹配文件

    Args:
        pattern: glob 模式, e.g. "**/*.py", "src/*.ts", "tests/test_*.py"
        path: 搜索根目录, 默认当前目录
        include_hidden: 是否包含 . 开头的文件 (默认 False)
        max_results: 最大返回数, 超过则截断并提示 (默认 500)
    """
    if not pattern or not pattern.strip():
        return "[error] pattern 不能为空"

    resolved = _resolve_path(path)
    if resolved is None or not resolved.exists():
        return f"[error] 路径不存在: {path}"
    if not resolved.is_dir():
        return f"[error] 不是目录: {path}"

    # 异步跑 (pathlib.glob 在大目录上会阻塞)
    def _do_glob() -> List[Path]:
        out: List[Path] = []
        # pathlib.Path.glob 的 pattern 不能跨过 path, 用 rglob 等价于 **/* 模式
        # 但用户传 'src/*.py' 这种我们应当用 path.glob('src/*.py')
        try:
            for p in resolved.glob(pattern):
                # 过滤隐藏
                if not include_hidden and any(part.startswith(".") for part in p.relative_to(resolved).parts):
                    continue
                # 过滤 _PRUNE_DIRS
                if any(part in _PRUNE_DIRS for part in p.relative_to(resolved).parts):
                    continue
                # 只要文件
                if not p.is_file():
                    continue
                out.append(p)
        except (ValueError, OSError) as e:
            logger.debug(f"glob 错误: {e}")
            return []
        return out

    matches = await asyncio.to_thread(_do_glob)

    if not matches:
        return f"[glob: {pattern}]\n（无匹配文件）"

    # 按字典序排序
    matches.sort()

    truncated = False
    if len(matches) > max_results:
        matches = matches[:max_results]
        truncated = True

    # 输出相对路径 (相对 path, 方便 LLM 引用)
    lines = [f"[glob: {pattern}]"]
    for m in matches:
        try:
            rel = m.relative_to(resolved)
        except ValueError:
            rel = m
        lines.append(str(rel))

    if truncated:
        lines.append(f"\n...（匹配 > {max_results}, 已截断, 加 max_results 参数可看更多）")

    return "\n".join(lines)


# ── 注册 ────────────────────────────────────────────────

registry.register(
    name="glob",
    toolset="terminal",
    description=(
        "按 glob 模式匹配文件, 跨目录递归。\n"
        "支持 ** (任意层) / * (单层) / ? (单字符) / [abc] (字符集)。\n"
        "示例: '**/*.py' 找所有 Python 文件, 'src/**/*.ts' 找 src 下所有 TS, "
        "'tests/test_*.py' 找测试文件。\n"
        "默认跳过 .git/.venv/node_modules/__pycache__ 和隐藏文件, "
        "结果限制 500 条, 用 max_results 参数可调。"
    ),
    schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "glob 模式, e.g. '**/*.py', 'src/components/*.tsx'",
            },
            "path": {
                "type": "string",
                "description": "搜索根目录, 默认当前目录",
            },
            "include_hidden": {
                "type": "boolean",
                "description": "是否包含 . 开头的文件, 默认 false",
                "default": False,
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回数, 默认 500",
                "default": _MAX_RESULTS,
            },
        },
        "required": ["pattern"],
    },
    handler=glob_tool,
    is_async=True,
    emoji="🔍",
    parallel_mode="safe",
)
