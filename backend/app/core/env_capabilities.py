"""
env_capabilities - 运行时环境能力检测

双轨架构：
- 工具描述：通过 API `tools` 参数传递（来自 registry.get_schemas()，function calling 协议）
- 工具索引：本模块的 generate_capability_prompt() 按 toolset 分组生成人类可读清单
- Skills 索引：在 system prompt 文本里（见 skills_index.py）

P4 (2026-06-02) 起不再写盘 domains/tools/tools.md——LLM 推理时通过 function calling
协议直接拿到 schema，不再需要 14KB markdown 镜像。
"""

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

# ── 环境检测 ────────────────────────────────────────────────────────────────

def _check_package(package: str) -> str | None:
    try:
        import importlib.metadata
        return importlib.metadata.version(package)
    except Exception:
        return None


def _check_cli(name: str) -> str | None:
    path = shutil.which(name)
    if not path:
        return None
    try:
        result = subprocess.run(
            [name, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or result.stderr.strip() or path
    except Exception:
        return path


@lru_cache(maxsize=1)
def detect() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "packages": {},
        "cli_tools": {},
    }
    for pkg in ["playwright", "httpx", "chromadb"]:
        ver = _check_package(pkg)
        if ver:
            result["packages"][pkg] = ver
    for cmd in ["git", "node", "npm", "curl", "docker", "sqlite3"]:
        ver = _check_cli(cmd)
        if ver:
            result["cli_tools"][cmd] = ver
    return result


def _format_env_detection() -> str:
    """当前环境信息（Python 版本、已安装包、CLI 工具）"""
    env = detect()
    lines = ["## 当前环境\n"]
    lines.append(f"- Python {env['python']}")
    for pkg, ver in env.get("packages", {}).items():
        lines.append(f"- {pkg}=={ver}")
    for cmd, ver in env.get("cli_tools", {}).items():
        short = ver.split("\n")[0] if "\n" in ver else ver
        lines.append(f"- {cmd}: {short}")
    return "\n".join(lines)


# ── 工具索引（双轨：不在 system prompt 里放工具描述）──────────────

# 工具集标签
_TOOLSET_LABELS = {
    "file": "📁 文件",
    "terminal": "💻 终端",
    "browser": "🌐 浏览器",
    "web": "🔍 网络",
    "desktop": "🖥️ 桌面",
    "android": "📱 Android",
    "interactive": "❓ 交互",
    "skill": "🎯 Skill",
}


def generate_capability_prompt() -> str:
    """工具集索引（按 toolset 分组的人类可读清单）。

    工具描述通过 API `tools` 参数走 function calling 协议传给 LLM，
    本函数只生成"按 toolset 分组的工具名列表"——给 LLM 一个高层概览，
    让它知道"有哪些类别的工具可用"，不重复 tools schema 本身。

    注意：P4 (2026-06-02) 之前这里曾提示 agent 用 read_file('tools.md')
    读 14KB markdown 镜像，那是反模式——已删除。
    """
    lines = ["## 可用工具集\n"]
    lines.append(
        "**工具描述通过 API 的 `tools` 参数传递，Agent 推理时自动看到。**\n"
        "**（本节只列工具集分组和工具名索引；详细 schema 在 function calling 协议里。）**"
    )

    try:
        from app.tools.registry import registry, discover_builtin_tools
        discover_builtin_tools()
        toolsets = registry.get_available_toolsets()
        for ts in sorted(toolsets.keys()):
            info = toolsets[ts]
            label = _TOOLSET_LABELS.get(ts, f"🔧 {ts}")
            tools = sorted(info["tools"])
            available = "✅" if info["available"] else "⚠️ 需要配置"
            lines.append(f"\n### {label} {available}")
            lines.append(" " + " | ".join(f"`{t}`" for t in tools))
    except Exception as e:
        logger.warning(f"无法从 registry 读取工具集: {e}")

    return "\n".join(lines)


# ── 公开 API ────────────────────────────────────────────────────────────────

_detected: str | None = None


def get_env_prompt() -> str:
    global _detected
    if _detected is None:
        try:
            _detected = _format_env_detection()
        except Exception as e:
            logger.warning(f"环境能力检测失败: {e}")
            _detected = ""
    return _detected


def refresh():
    global _detected
    detect.cache_clear()
    _detected = None
    return get_env_prompt()
