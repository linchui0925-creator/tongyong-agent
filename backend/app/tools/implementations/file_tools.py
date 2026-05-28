"""
file_tools - 文件操作工具

提供文件读取、写入、编辑和搜索能力。
每个工具通过 registry.register() 自注册。
"""

import asyncio
import logging
import os
import re
import stat
import threading
from pathlib import Path
from typing import Optional

from app.tools.registry import registry

logger = logging.getLogger(__name__)

# ── 安全配置 ────────────────────────────────────────────

_MAX_READ_CHARS = 200_000
_BLOCKED_DEVICE_PATHS = frozenset({
    "/dev/zero", "/dev/random", "/dev/urandom", "/dev/full",
    "/dev/stdin", "/dev/tty", "/dev/console",
    "/dev/stdout", "/dev/stderr",
    "/dev/fd/0", "/dev/fd/1", "/dev/fd/2",
})

_SENSITIVE_PATH_PREFIXES = (
    "/etc/", "/boot/", "/usr/lib/systemd/",
    "/private/etc/", "/private/var/",
)
_SENSITIVE_EXACT_PATHS = frozenset({
    "/var/run/docker.sock", "/run/docker.sock",
})

# ── 读去重与循环检测 ───────────────────────────────────

_read_tracker_lock = threading.Lock()
_read_tracker: dict = {}
"""结构:
{
  task_id: {
    "last_key": tuple | None,       # 最近一次读请求的标识
    "consecutive": int,             # 连续相同请求的次数
    "read_timestamps": {path: mtime},  # 文件读取时的时间戳
  }
}
"""

_LARGE_FILE_HINT_BYTES = 512_000

# ── Binary / Image detection ──────────────────────────────

_BINARY_EXTENSIONS = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.exe', '.dll', '.so', '.dylib', '.o', '.a', '.lib', '.bin',
    '.mp3', '.mp4', '.avi', '.mov', '.mkv', '.wav', '.flac', '.ogg',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.pyc', '.pyo', '.class', '.wasm',
    '.db', '.sqlite', '.sqlite3',
})

_IMAGE_EXTENSIONS = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico',
})


def _is_binary_file(path_str: str, content_sample: str | None = None) -> bool:
    """Check if file is likely binary via extension (fast) + content analysis (fallback)."""
    ext = os.path.splitext(path_str)[1].lower()
    if ext in _BINARY_EXTENSIONS:
        return True
    if content_sample:
        non_printable = sum(1 for c in content_sample[:1000] if ord(c) < 32 and c not in '\n\r\t')
        return non_printable / min(len(content_sample), 1000) > 0.30
    return False


def _is_image_file(path_str: str) -> bool:
    return os.path.splitext(path_str)[1].lower() in _IMAGE_EXTENSIONS


def _suggest_similar_files(path: Path) -> list[str]:
    """Suggest similar files when the requested file is not found.

    Uses scored matching: same basename → prefix/substring → extension overlap.
    Returns up to 5 suggestions.
    """
    dir_path = path.parent
    filename = path.name
    if not dir_path.exists() or not dir_path.is_dir():
        return []

    basename_no_ext = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1].lower()
    lower_name = filename.lower()

    scored: list[tuple[int, str]] = []
    try:
        for f in dir_path.iterdir():
            if not f.is_file():
                continue
            lf = f.name.lower()
            score = 0

            if lf == lower_name:
                score = 100
            elif os.path.splitext(f.name)[0].lower() == basename_no_ext.lower():
                score = 90
            elif lf.startswith(lower_name) or lower_name.startswith(lf):
                score = 70
            elif lower_name in lf:
                score = 60
            elif lf in lower_name and len(lf) > 2:
                score = 40
            elif ext and os.path.splitext(f.name)[1].lower() == ext:
                common = set(lower_name) & set(lf)
                if len(common) >= max(len(lower_name), len(lf)) * 0.4:
                    score = 30

            if score > 0:
                scored.append((score, str(f)))
    except PermissionError:
        return []

    scored.sort(key=lambda x: -x[0])
    return [fp for _, fp in scored[:5]]


def _reset_read_tracker(task_id: str = "default"):
    """重置指定 task 的读去重状态（上下文压缩后调用）"""
    with _read_tracker_lock:
        data = _read_tracker.get(task_id)
        if data:
            # 保留 read_timestamps（避免写入时满屏假阳性）, 只清空循环计数
            data["last_key"] = None
            data["consecutive"] = 0


def _get_tracker_data(task_id: str = "default") -> dict:
    with _read_tracker_lock:
        if task_id not in _read_tracker:
            _read_tracker[task_id] = {"last_key": None, "consecutive": 0, "read_timestamps": {}}
        return _read_tracker[task_id]


def _update_read_timestamp(resolved_path: str, task_id: str = "default"):
    """记录文件的 mtime（读或写之后调用）"""
    try:
        mtime = os.path.getmtime(resolved_path)
    except OSError:
        return
    data = _get_tracker_data(task_id)
    data["read_timestamps"][resolved_path] = mtime


def _check_staleness(resolved_path: str, task_id: str = "default") -> Optional[str]:
    """如果文件自上次读取后被修改，返回警告信息"""
    try:
        current_mtime = os.path.getmtime(resolved_path)
    except OSError:
        return None
    data = _get_tracker_data(task_id)
    read_mtime = data["read_timestamps"].get(resolved_path)
    if read_mtime is not None and current_mtime != read_mtime:
        return (
            f"Warning: {resolved_path} was modified since you last read it "
            "(external edit or concurrent agent). The content you read may be "
            "stale. Consider re-reading to verify before writing."
        )
    return None


# ── 工具函数 ───────────────────────────────────────────


def _resolve_path(path: str) -> Optional[Path]:
    """解析并验证路径安全性"""
    raw = Path(path).expanduser()
    if raw.is_absolute():
        p = raw.resolve()
    else:
        cwd = Path.cwd().resolve()
        if cwd.name == "backend":
            repo_root = cwd.parent
        else:
            repo_root = cwd

        path_str = str(raw).replace("\\", "/")
        if path_str.startswith("backend/") and cwd.name == "backend":
            raw = Path(path_str[len("backend/"):])
            p = (cwd / raw).resolve()
        else:
            p = (repo_root / raw).resolve()
    if str(p) in _BLOCKED_DEVICE_PATHS:
        return None
    return p


def _is_sensitive_write(path: Path) -> bool:
    """检查是否为敏感系统路径"""
    resolved = str(path.resolve())
    if resolved in _SENSITIVE_EXACT_PATHS:
        return True
    for prefix in _SENSITIVE_PATH_PREFIXES:
        if resolved.startswith(prefix):
            return True
    return False


def _check_file_readable(path: Path) -> Optional[str]:
    """检查文件是否可读，返回错误信息或 None"""
    if not path.exists():
        return f"文件不存在: {path}"
    if not path.is_file():
        return f"不是文件: {path}"
    try:
        mode = path.stat().st_mode
        if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
            return f"设备文件不允许读取: {path}"
    except OSError:
        pass
    try:
        if path.stat().st_size > 50 * 1024 * 1024:
            return f"文件过大 (>50MB)，请使用 terminal 工具通过命令行读取: {path}"
    except OSError:
        pass
    return None


def _check_env() -> bool:
    """文件工具总是可用"""
    return True


# ═══════════════════════════════════════════════════════════
# read_file
# ═══════════════════════════════════════════════════════════

READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "文件路径（绝对路径或相对路径）",
        },
        "offset": {
            "type": "integer",
            "description": "起始行号（从 1 开始，默认 1）",
            "default": 1,
        },
        "limit": {
            "type": "integer",
            "description": "最多读取行数（默认 200，-1 表示全部）",
            "default": 200,
        },
        "task_id": {
            "type": "string",
            "description": "任务标识（内部使用，默认 default）",
            "default": "default",
        },
    },
    "required": ["path"],
}


async def read_file_tool(path: str, offset: int = 1, limit: int = 200, task_id: str = "default") -> str:
    resolved = _resolve_path(path)
    if not resolved:
        return f"路径无效或被禁止: {path}"

    resolved_str = str(resolved)

    # ── File existence + binary detection before dedup ──
    if not resolved.exists():
        suggestions = _suggest_similar_files(resolved)
        if suggestions:
            return (
                f"文件不存在: {resolved}\n"
                f"您要找的是不是:\n" + "\n".join(f"  - {s}" for s in suggestions)
            )
        return f"文件不存在: {resolved}"

    if not resolved.is_file():
        return f"不是文件: {resolved}"
    try:
        mode = resolved.stat().st_mode
        if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
            return f"设备文件不允许读取: {resolved}"
    except OSError:
        pass

    # Binary / image check (before any read attempt)
    if _is_image_file(resolved_str):
        return (
            f"🖼️ 图片文件检测到: {resolved}\n"
            f"请使用 terminal 工具查看此文件，或使用其他适当工具处理。"
        )
    try:
        file_size = resolved.stat().st_size
        if file_size > 50 * 1024 * 1024:
            return f"文件过大 (>50MB)，请使用 terminal 工具通过命令行读取: {resolved}"
    except OSError:
        pass

    # Sample-based binary detection
    sample_bytes = b""
    try:
        with open(resolved_str, "rb") as f:
            sample_bytes = f.read(1000)
    except OSError:
        pass
    if sample_bytes and _is_binary_file(resolved_str, sample_bytes.decode("utf-8", errors="replace")):
        return f"二进制文件，无法以文本方式显示: {resolved}"

    # ── 连续重读检测 ────────────────────────────────
    read_key = ("read", resolved_str, offset, limit)
    data = _get_tracker_data(task_id)
    was_dedup_hit = False

    with _read_tracker_lock:
        if data["last_key"] == read_key:
            data["consecutive"] += 1
        else:
            data["last_key"] = read_key
            data["consecutive"] = 1
        count = data["consecutive"]

        # 去重：文件未变更则跳过重读
        cached_mtime = data["read_timestamps"].get(resolved_str)
        if cached_mtime is not None:
            try:
                current_mtime = os.path.getmtime(resolved_str)
                if current_mtime == cached_mtime and count > 1:
                    was_dedup_hit = True
            except OSError:
                pass

    if count >= 2 and was_dedup_hit:
        return (
            f"BLOCKED: You have read this exact file region {count} times in a row. "
            "The content has NOT changed. You already have this information. "
            "STOP re-reading and proceed with your task."
        )

    if was_dedup_hit:
        return (
            f"[dedup] File unchanged since last read ({resolved_str}). "
            "The content from the earlier read_file result is still current — "
            "refer to that instead of re-reading."
        )

    try:
        encoding = _detect_encoding(resolved)
        text = resolved.read_text(encoding=encoding, errors="replace")
    except UnicodeDecodeError:
        return f"文件编码无法识别，请使用 terminal 工具通过命令行查看: {path}"
    except PermissionError:
        return f"权限不足: {path}"
    except Exception as e:
        return f"读取失败: {e}"

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    if offset < 1:
        offset = 1
    if limit == -1:
        limit = total_lines

    start = offset - 1
    end = min(start + limit, total_lines)
    selected = lines[start:end]

    content = "".join(selected)
    if len(content) > _MAX_READ_CHARS:
        content = content[:_MAX_READ_CHARS] + f"\n...（内容过长，已截断至 {_MAX_READ_CHARS} 字符）"

    # 记录读取时间戳用于去重和过期检测
    _update_read_timestamp(resolved_str, task_id)

    # 大文件提示
    try:
        file_size = resolved.stat().st_size
    except OSError:
        file_size = 0
    hint = ""
    if file_size > _LARGE_FILE_HINT_BYTES and limit > 200:
        hint = (
            f"\n💡 This file is large ({file_size:,} bytes). "
            "Consider reading only the section you need with offset and limit."
        )

    # 显示行号
    line_width = len(str(end))
    numbered = []
    for i, line in enumerate(selected, start=offset):
        numbered.append(f"{i:>{line_width}}|{line}")

    result = "".join(numbered)
    info = f"📄 {resolved}（{total_lines} 行，显示 {start + 1}-{end}）"
    if total_lines > end:
        info += f"\n💡 还有 {total_lines - end} 行未显示，用 offset={end + 1} limit={limit} 继续读取"
    if hint:
        info += hint
    # 连续重读 3 次警告
    if count >= 3 and count < 4:
        info += (
            f"\n⚠️  You have read this file region {count} times consecutively. "
            "Use the information you already have."
        )
    return info + "\n" + result


def _detect_encoding(path: Path) -> str:
    """尝试检测文件编码"""
    try:
        import chardet
    except Exception:
        return "utf-8"
    try:
        raw = path.read_bytes()[:8192]
        result = chardet.detect(raw)
        return result.get("encoding", "utf-8") or "utf-8"
    except Exception:
        return "utf-8"


# ═══════════════════════════════════════════════════════════
# write_file
# ═══════════════════════════════════════════════════════════

WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "文件路径（绝对路径或相对路径）",
        },
        "content": {
            "type": "string",
            "description": "文件内容",
        },
        "task_id": {
            "type": "string",
            "description": "任务标识（内部使用）",
            "default": "default",
        },
    },
    "required": ["path", "content"],
}


async def write_file_tool(path: str, content: str, task_id: str = "default") -> str:
    resolved = _resolve_path(path)
    if not resolved:
        return f"路径无效或被禁止: {path}"

    if _is_sensitive_write(resolved):
        return f"拒绝写入敏感系统路径: {resolved}"

    # 过期检测：文件在最后一次读取后被外部修改
    stale_warning = _check_staleness(str(resolved), task_id)

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        # 刷新时间戳，避免连续写入触发假阳性
        _update_read_timestamp(str(resolved), task_id)
        msg = f"✅ 已写入 {resolved}（{len(content)} 字符）"
        if stale_warning:
            msg += f"\n⚠️  {stale_warning}"
        return msg
    except PermissionError:
        return f"权限不足: {path}"
    except IsADirectoryError:
        return f"路径是目录: {path}"
    except Exception as e:
        return f"写入失败: {e}"


# ═══════════════════════════════════════════════════════════
# patch — 精确替换
# ═══════════════════════════════════════════════════════════

PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "文件路径",
        },
        "old_string": {
            "type": "string",
            "description": "要被替换的原文（必须精确匹配）",
        },
        "new_string": {
            "type": "string",
            "description": "替换后的内容",
        },
        "insert_at": {
            "type": "string",
            "description": "插入模式：'start' 文件开头插入，'end' 文件末尾插入。设置此值时不需 old_string",
            "enum": ["start", "end"],
        },
        "replace_all": {
            "type": "boolean",
            "description": "替换所有匹配项而非仅第一个（默认 false）",
            "default": False,
        },
        "task_id": {
            "type": "string",
            "description": "任务标识（内部使用）",
            "default": "default",
        },
    },
    "oneOf": [
        {"required": ["path", "old_string", "new_string"]},
        {"required": ["path", "new_string", "insert_at"]},
    ],
}


async def patch_tool(path: str, old_string: str = "", new_string: str = "", insert_at: str = "", replace_all: bool = False, task_id: str = "default") -> str:
    resolved = _resolve_path(path)
    if not resolved:
        return f"路径无效或被禁止: {path}"

    if _is_sensitive_write(resolved):
        return f"拒绝修改系统路径: {resolved}"

    if not resolved.exists():
        return f"文件不存在: {path}"

    # 过期检测
    stale_warning = _check_staleness(str(resolved), task_id)

    try:
        original = resolved.read_text(encoding="utf-8")
    except Exception as e:
        return f"读取失败: {e}"

    # 插入模式
    if insert_at:
        if insert_at == "start":
            new_content = new_string + original
        elif insert_at == "end":
            new_content = original + ("\n" if not original.endswith("\n") else "") + new_string
        else:
            return f"不支持的插入位置: {insert_at}"
    else:
        if not old_string:
            return "old_string 不能为空"
        if old_string not in original:
            return f"未在文件中找到匹配的原文（精确匹配）:\n```\n{old_string[:200]}\n```\n💡 使用 read_file 确认当前内容后再重试"
        if replace_all:
            new_content = original.replace(old_string, new_string)
        else:
            new_content = original.replace(old_string, new_string, 1)

    try:
        resolved.write_text(new_content, encoding="utf-8")
        # 刷新时间戳
        _update_read_timestamp(str(resolved), task_id)
        diff_size = len(new_content) - len(original)
        diff_sign = "+" if diff_size >= 0 else ""
        msg = f"✅ 已更新 {resolved}（{diff_sign}{diff_size} 字符）"
        if stale_warning:
            msg += f"\n⚠️  {stale_warning}"
        return msg
    except Exception as e:
        return f"写入失败: {e}"


# ═══════════════════════════════════════════════════════════
# search_files — 搜索文件内容或路径
# ═══════════════════════════════════════════════════════════

SEARCH_FILES_SCHEMA = {
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
        "type": {
            "type": "string",
            "description": "搜索类型：'content' 搜索文件内容，'filename' 搜索文件名",
            "enum": ["content", "filename"],
            "default": "content",
        },
        "glob": {
            "type": "string",
            "description": "文件通配符过滤，如 '*.py'、'*.tsx'、'*.{py,js}'（默认所有文件）",
            "default": "*",
        },
        "max_results": {
            "type": "integer",
            "description": "最大结果数（默认 20）",
            "default": 20,
        },
    },
    "required": ["pattern"],
}


async def search_files_tool(pattern: str, path: str = ".", type: str = "content", glob: str = "*", max_results: int = 20) -> str:  # noqa: A002
    root = Path(path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return f"目录不存在: {path}"

    results = []
    max_results = min(max_results, 100)

    try:
        for p in root.rglob(glob):
            if not p.is_file():
                continue
            if any(part.startswith(".") for part in p.relative_to(root).parts if part != p.name):
                continue

            if type == "filename":
                if re.search(pattern, p.name, re.IGNORECASE):
                    rel = p.relative_to(root)
                    results.append(str(rel))
                    if len(results) >= max_results:
                        break
            else:
                if p.stat().st_size > 1024 * 1024:
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                    for lineno, line in enumerate(text.splitlines(), 1):
                        if re.search(pattern, line, re.IGNORECASE):
                            rel = p.relative_to(root)
                            line_stripped = line.strip()[:150]
                            results.append(f"{rel}:{lineno}  {line_stripped}")
                            if len(results) >= max_results:
                                break
                        if len(results) >= max_results:
                            break
                except (OSError, UnicodeDecodeError):
                    continue
    except Exception as e:
        return f"搜索失败: {e}"

    if not results:
        return f"在 {root} 中未找到匹配 '{pattern}' 的结果"

    header = f"🔎 在 {root} 中搜索 '{pattern}'（{len(results)} 条结果）\n"
    return header + "\n".join(results[:max_results])


# ═══════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════

registry.register(
    name="read_file",
    toolset="file",
    description="读取文件内容。支持指定起始行和行数范围，自动检测编码，安全过滤设备文件。大文件建议用 offset+limit 分段读取。内置去重：相同文件重复读取时会提示使用已有结果。",
    schema=READ_FILE_SCHEMA,
    handler=read_file_tool,
    check_fn=_check_env,
    emoji="📖",
    max_result_size_chars=_MAX_READ_CHARS,
    parallel_mode="safe",
)

registry.register(
    name="write_file",
    toolset="file",
    description="创建新文件或覆盖已有文件。自动创建父目录。拒绝写入敏感系统路径。如文件在读取后被外部修改会给出警告。",
    schema=WRITE_FILE_SCHEMA,
    handler=write_file_tool,
    check_fn=_check_env,
    emoji="✍️",
    parallel_mode="path_scoped",
)

registry.register(
    name="patch",
    toolset="file",
    description="精确替换文件中的文本（replace 模式），或在文件开头/末尾插入内容。比 write_file 更安全，只修改指定部分。支持 replace_all 替换所有匹配项。",
    schema=PATCH_SCHEMA,
    handler=patch_tool,
    check_fn=_check_env,
    emoji="🔧",
    parallel_mode="path_scoped",
)

registry.register(
    name="search_files",
    toolset="file",
    description="搜索文件内容或文件名。支持正则表达式和 glob 通配符过滤。自动跳过 .git/node_modules 等目录。",
    schema=SEARCH_FILES_SCHEMA,
    handler=search_files_tool,
    check_fn=_check_env,
    emoji="🔎",
    parallel_mode="safe",
)
