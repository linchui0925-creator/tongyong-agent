"""
安全配置 - 命令白名单和禁止模式

供 terminal 工具和 CLI executor 共同使用 (P2-4 W4-20 热加载).

加载顺序:
1. 内置 _DEFAULT_ALLOWED_COMMANDS (兜底, 永远生效)
2. data/terminal_whitelist.txt 追加 (一行一个命令, # 开头是注释, 空行跳过)
3. data/terminal_blacklist.txt 追加到 _FORBIDDEN_PATTERNS (一行一个 regex)

启动时自动加载. 如需热重载 (debug), 调 reload_security_config().
"""

import logging
import re
from pathlib import Path
from typing import List

from app.config import settings
from app.paths import data_path

logger = logging.getLogger(__name__)

# ── 内置默认 (P2-4 之前是 _ALLOWED_COMMANDS, 现拆成 _DEFAULT + 加载) ──

_DEFAULT_ALLOWED_COMMANDS = [
    # 文件查看
    "cat", "less", "more", "head", "tail", "wc", "diff",
    # 文件操作
    "cp", "mv", "rm", "touch", "mkdir", "chmod", "chown",
    # 文本处理
    "grep", "rg", "awk", "sed", "sort", "uniq",
    # 文件查找
    "find", "locate", "which", "type",
    # 目录与路径
    "ls", "pwd", "cd", "tree", "du", "df",
    # 进程管理
    "ps", "top", "htop", "kill", "killall",
    # 网络
    "curl", "wget", "ping", "nc", "ss", "netstat",
    # 压缩
    "tar", "gzip", "gunzip", "zip", "unzip", "bzip2", "xz",
    # SHELL 内置
    "echo", "printf", "source", "export",
    # Python 生态
    "python", "python3", "pip", "pip3", "pytest", "mypy", "ruff", "black", "flake8", "uv",
    # Node 生态
    "node", "npm", "npx", "yarn", "pnpm", "bun",
    # 版本控制
    "git", "svn",
    # 容器
    "docker", "docker-compose",
    # 数据库
    "sqlite3", "redis-cli", "psql", "mysql",
    # 构建工具
    "make", "cmake", "cargo", "rustc", "go", "gcc", "g++", "clang",
    # 系统信息
    "date", "cal", "whoami", "id", "uname", "hostname", "uptime", "dmesg",
    # macOS 特定
    "open", "brew", "sw_vers", "defaults", "plutil",
    # 环境
    "env", "printenv", "xargs", "time", "watch",
    # 编码与校验
    "base64", "shasum", "sha256sum", "md5sum",
    # 杂项
    "jq", "yq", "rsync", "screen", "tmux",
]

_DEFAULT_FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+/(?:\s|$)",
    r"sudo\s+",
    r"curl.*\|.*sh",
    r"wget.*\|.*sh",
    r">\s*/etc/",
    r"mkfs",
    r"dd\s+.*of=/dev/",
    r":\(\)\{\s*:\|:",
]

# ── 外部配置文件路径 (相对 settings.data_dir, 缺省 ./data) ──

_WHITELIST_FILE = Path(settings.database_url).parent / "terminal_whitelist.txt"
_BLACKLIST_FILE = Path(settings.database_url).parent / "terminal_blacklist.txt"
# 上面用了 database_url (./data/tongyong.db) 反推 data 目录. 兜底:
if not _WHITELIST_FILE.parent.exists():
    _WHITELIST_FILE = Path(data_path("terminal_whitelist.txt"))
    _BLACKLIST_FILE = Path(data_path("terminal_blacklist.txt"))


def _load_extra_list(path: Path) -> List[str]:
    """从文件加载额外列表 (一行一项, # 开头是注释)"""
    if not path.is_file():
        return []
    out: List[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            out.append(stripped)
    except Exception as e:
        logger.warning(f"[security_config] 读 {path} 失败: {e}, 跳过")
    return out


def _load_extra_patterns(path: Path) -> List[str]:
    """从文件加载额外 forbidden regex (一行一个)"""
    if not path.is_file():
        return []
    out: List[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # 简单校验: 必须能 compile
            try:
                re.compile(stripped)
            except re.error as e:
                logger.warning(f"[security_config] {path} 跳过非法 regex {stripped!r}: {e}")
                continue
            out.append(stripped)
    except Exception as e:
        logger.warning(f"[security_config] 读 {path} 失败: {e}, 跳过")
    return out


def _build_allowed() -> List[str]:
    """构建最终白名单 (内置 + 外部文件)"""
    extra = _load_extra_list(_WHITELIST_FILE)
    merged = list(_DEFAULT_ALLOWED_COMMANDS) + extra
    if extra:
        logger.info(f"[security_config] 从 {_WHITELIST_FILE} 追加 {len(extra)} 个白名单命令")
    return merged


def _build_forbidden() -> List[str]:
    """构建最终黑名单 regex (内置 + 外部文件)"""
    extra = _load_extra_patterns(_BLACKLIST_FILE)
    merged = list(_DEFAULT_FORBIDDEN_PATTERNS) + extra
    if extra:
        logger.info(f"[security_config] 从 {_BLACKLIST_FILE} 追加 {len(extra)} 个黑名单 pattern")
    return merged


# 启动时加载一次 (兼容旧模块属性 _ALLOWED_COMMANDS / _FORBIDDEN_PATTERNS)
_ALLOWED_COMMANDS: List[str] = _build_allowed()
_FORBIDDEN_PATTERNS: List[str] = _build_forbidden()


def reload_security_config() -> tuple[List[str], List[str]]:
    """热重载 (供 debug / admin 端点调用). 返回 (allowed, forbidden).

    注意: 必须 in-place 修改 (clear + extend), 不能 global 重绑,
    否则旧 import 引用 (terminal.py:16 / cli/executor.py:15) 看不到.
    """
    _ALLOWED_COMMANDS.clear()
    _ALLOWED_COMMANDS.extend(_build_allowed())
    _FORBIDDEN_PATTERNS.clear()
    _FORBIDDEN_PATTERNS.extend(_build_forbidden())
    return _ALLOWED_COMMANDS, _FORBIDDEN_PATTERNS
