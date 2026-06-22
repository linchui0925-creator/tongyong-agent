"""
skill_tools - Skill 查看工具

提供 skill 读取和列表能力：
- skill_view(name): 按名称读取完整 SKILL.md 内容
- skill_list(): 列出所有可用 skill 的索引（name + description）

注册到 registry，供 Agent 按需调用。
"""

import asyncio
import logging
import os
import re
import yaml
from pathlib import Path
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from app.tools.registry import registry
from app.config import settings

logger = logging.getLogger(__name__)

# ── 路径配置 ────────────────────────────────────────────

_SKILLS_BASE_DIR = Path(settings.hermes_skills_dir)

# ── 缓存（避免每次请求都扫描文件系统）───────────────────────

_skill_index_cache: Dict[str, Tuple[float, str]] = {}  # name → (mtime, content)
_skill_index_mtime: Optional[float] = None


def _get_skills_dir() -> Path:
    """获取 skill 目录"""
    return _SKILLS_BASE_DIR


def _scan_skill_dirs() -> Dict[str, Dict]:
    """扫描所有 skill 目录，返回 {name: {path, category, frontmatter}}"""
    skills_dir = _get_skills_dir()
    if not skills_dir.is_dir():
        return {}

    result = {}
    for cat_dir in sorted(skills_dir.iterdir()):
        if not cat_dir.is_dir() or cat_dir.name.startswith("_"):
            continue
        category = cat_dir.name
        for skill_dir in sorted(cat_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            name = skill_dir.name
            meta = _read_frontmatter(skill_md)
            result[name] = {
                "path": str(skill_md),
                "category": category,
                "name": name,
                "description": meta.get("description", ""),
                "version": meta.get("version", "1.0"),
                "platforms": meta.get("platforms", []),
            }
    return result


def _read_frontmatter(path: Path) -> Dict:
    """读取 YAML frontmatter"""
    try:
        content = path.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                meta = yaml.safe_load(parts[1]) or {}
                return meta
    except Exception:
        pass
    return {}


def _get_index_mtime() -> float:
    """获取 skill 目录的最近修改时间"""
    skills_dir = _get_skills_dir()
    if not skills_dir.is_dir():
        return 0.0
    latest = 0.0
    for cat_dir in skills_dir.iterdir():
        if cat_dir.is_dir():
            m = cat_dir.stat().st_mtime
            if m > latest:
                latest = m
    return latest


# ── 工具实现 ────────────────────────────────────────────

def skill_view(name: str) -> str:
    """读取指定 skill 的完整 SKILL.md 内容

    当 Agent 决定使用某个 skill 时，调用此工具加载完整内容。
    """
    skills_dir = _get_skills_dir()
    if not skills_dir.is_dir():
        return f"[error] Skill 目录不存在: {skills_dir}"

    # 跨目录查找（name 可能带分类前缀）
    skill_md = None

    # 1. 先尝试直接路径
    for cat_dir in skills_dir.iterdir():
        if cat_dir.is_dir() and not cat_dir.name.startswith("_"):
            direct = cat_dir / name / "SKILL.md"
            if direct.is_file():
                skill_md = direct
                break

    # 2. 如果找不到，搜索同名 skill
    if skill_md is None:
        for cat_dir in skills_dir.iterdir():
            if cat_dir.is_dir() and not cat_dir.name.startswith("_"):
                for skill_dir in cat_dir.iterdir():
                    if skill_dir.is_dir() and skill_dir.name == name:
                        found = skill_dir / "SKILL.md"
                        if found.is_file():
                            skill_md = found
                            break
        if skill_md is None:
            # 模糊匹配
            name_lower = name.lower()
            for cat_dir in skills_dir.iterdir():
                if cat_dir.is_dir() and not cat_dir.name.startswith("_"):
                    for skill_dir in cat_dir.iterdir():
                        if (skill_dir.is_dir() and
                            (name_lower in skill_dir.name.lower() or
                             skill_dir.name.lower() in name_lower)):
                            found = skill_dir / "SKILL.md"
                            if found.is_file():
                                skill_md = found
                                break
                    if skill_md:
                        break

    if skill_md is None:
        available = _build_available_skills_index()
        return f"[error] Skill '{name}' 未找到。\n\n可用 skill 列表：\n{available}"

    try:
        content = skill_md.read_text(encoding="utf-8")
        # 去掉 frontmatter，只返回 body 部分用于上下文注入
        # W4-12 SKILL 修复: 删除 dead code `meta = _build_available_skills_index()`
        #   该变量在 if 分支里被赋错 (赋成 skill 列表而不是 frontmatter dict) 且从未被用
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                body = parts[2].strip()
                return f"[skill: {name}]\n{body}"
        return f"[skill: {name}]\n{content}"
    except Exception as e:
        return f"[error] 读取 skill '{name}' 失败: {e}"


def skill_list() -> str:
    """列出所有可用 skill（用于 Agent 了解有哪些 skill 可用）"""
    return _build_available_skills_index()


def _build_available_skills_index() -> str:
    """构建 <available_skills> 索引块，供注入 system prompt"""
    global _skill_index_cache, _skill_index_mtime

    current_mtime = _get_index_mtime()

    # 检测变化
    if _skill_index_mtime != current_mtime or not _skill_index_cache:
        _skill_index_mtime = current_mtime
        _skill_index_cache = _scan_skill_dirs()

    if not _skill_index_cache:
        return "[available_skills]\n（暂无 skill）"

    # 按分类组织
    by_category: Dict[str, List[Dict]] = {}
    for name, info in _skill_index_cache.items():
        cat = info["category"]
        by_category.setdefault(cat, []).append(info)

    lines = ["[available_skills]"]
    for cat in sorted(by_category.keys()):
        lines.append(f"\n  ### {cat}")
        for info in sorted(by_category[cat], key=lambda x: x["name"]):
            desc = info["description"] or "（无描述）"
            # 截断描述，保持索引简洁
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"  - {info['name']}: {desc}")

    return "\n".join(lines)


# ── 注册 ────────────────────────────────────────────────

registry.register(
    name="skill_view",
    toolset="skill",
    description=(
        "读取指定 skill 的完整内容。\n"
        "当 Agent 决定使用某个 skill 来完成任务时，调用此工具加载完整 SKILL.md。\n"
        "输入 skill 名称（可模糊匹配），返回完整文档内容（Steps、Pitfalls、References 等）。"
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "skill 名称（来自 skill_list 或 available_skills 索引）",
            },
        },
        "required": ["name"],
    },
    handler=skill_view,
    is_async=False,
    emoji="📋",
    parallel_mode="safe",
)

registry.register(
    name="skill_list",
    toolset="skill",
    description=(
        "列出所有可用 skill 的索引（名称 + 描述）。\n"
        "Agent 在不确定该用哪个 skill 时，先调用此工具查看可用列表。"
    ),
    schema={
        "type": "object",
        "properties": {},
    },
    handler=skill_list,
    is_async=False,
    emoji="📚",
    parallel_mode="safe",
)


# ── W4-15 load_skill 别名 ─────────────────────────────────
# 兼容用户熟悉的 Anthropic-style 命名, 行为与 skill_view 一致

def load_skill(name: str) -> str:
    """Load the full content of a skill by name (alias for skill_view).

    W4-15 2026-06-22: 注册第二个名字指向同一 handler, LLM 可以用 load_skill
    或 skill_view, 行为完全一致。走 wrapper 而不是 alias 抽象, 是因为:
      - registry 没引入 alias 系统, 改动面最小
      - description 里明说"alias for skill_view", 避免 LLM 误以为是新工具
    """
    return skill_view(name)


registry.register(
    name="load_skill",
    toolset="skill",
    description=(
        "Load the full content of a skill by name. (Alias for skill_view.)\n"
        "输入 skill 名称, 返回 SKILL.md 完整内容 (Steps/Pitfalls/References 等)。\n"
        "匹配规则与 skill_view 相同: 精确 → 同名 → 模糊匹配。"
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "skill 名称（来自 skill_list 或 available_skills 索引）",
            },
        },
        "required": ["name"],
    },
    handler=load_skill,
    is_async=False,
    emoji="📋",
    parallel_mode="safe",
)
