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
            if bool(meta.get("quarantined", False)) or not bool(meta.get("enabled", True)):
                continue
            result[name] = {
                "path": str(skill_md),
                "category": category,
                "name": name,
                "display_name": meta.get("name", name),
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
    """获取 Skill 树中目录和文件的最近修改时间。"""
    skills_dir = _get_skills_dir()
    if not skills_dir.is_dir():
        return 0.0
    latest = 0.0
    for root, _, files in os.walk(skills_dir):
        paths = [Path(root), *(Path(root) / filename for filename in files)]
        for path in paths:
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
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

    meta = _read_frontmatter(skill_md)
    if bool(meta.get("quarantined", False)):
        return f"[error] Skill '{name}' 仍处于隔离状态，不能加载。"
    if not bool(meta.get("enabled", True)):
        return f"[error] Skill '{name}' 已停用，不能加载。"

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


# GitHub 上非仓库的保留路径段 — 这些不是 skill 仓库, 不能直接安装
_GITHUB_NON_REPO_SEGMENTS = {
    "topics", "search", "marketplace", "orgs", "sponsors", "collections",
    "trending", "about", "features", "settings", "notifications", "explore",
    "stars", "watching", "new", "login", "join",
}


def _normalize_github_source(raw: str):
    """把用户给的 source/URL 归一化。

    返回 (owner_repo, keyword):
      - owner_repo: 形如 'owner/repo' 的真实仓库 (可直接安装); 否则空串
      - keyword:    当输入是 topics/search 等非仓库页面时, 抽出的主题词 (用于搜索); 否则空串
    """
    if not raw:
        return "", ""
    text = raw.strip().strip("<>").strip()
    # 去掉协议与 github 域名前缀
    for pref in ("https://", "http://", "git@", "ssh://"):
        if text.startswith(pref):
            text = text[len(pref):]
    text = text.replace("github.com:", "github.com/")
    if text.startswith("www."):
        text = text[4:]
    if text.startswith("github.com/"):
        text = text[len("github.com/"):]
    # 去掉查询串 / 锚点 / .git 后缀 / 首尾斜杠
    text = text.split("?", 1)[0].split("#", 1)[0].strip().strip("/")
    if text.endswith(".git"):
        text = text[:-4]
    if not text:
        return "", ""
    parts = [p for p in text.split("/") if p]
    first = parts[0].lower()
    if first in _GITHUB_NON_REPO_SEGMENTS:
        # topics/<topic> / search?q=... → 取主题词做搜索关键字
        keyword = parts[1] if len(parts) > 1 else ""
        return "", keyword.replace("-", " ").strip()
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}", ""
    # 只有一个段 (光 owner, 或裸词) → 当搜索关键字
    return "", parts[0].replace("-", " ").strip()


def _match_install_candidate(name: str, candidates):
    """从实时搜索结果里挑最匹配的 skill (skill_id 精确 > name 精确 > 装机量最高)。"""
    lname = (name or "").strip().lower()
    for c in candidates:
        if str(c.get("skill_id", "")).lower() == lname:
            return c
    for c in candidates:
        if str(c.get("name", "")).lower() == lname:
            return c
    if candidates:
        return max(candidates, key=lambda c: int(c.get("installs") or 0))
    return None


async def skill_install(name: str, source: str = "") -> str:
    """下载并安装一个外部 skill 到本地 hermes skills 目录。

    - source 已知 (owner/repo) 时直接安装。
    - 只给 name 时先走实时搜索解析出 source, 解析不到就报错并给候选, 不空转。
    """
    from app.core import marketplace

    name = (name or "").strip()
    if not name:
        return "❌ 需要提供要安装的 skill 名称。"
    source = (source or "").strip()
    resolved_id = name

    # 归一化 source/name 里的 GitHub URL。若给的是 topics/search 等非仓库页面,
    # 抽出主题词转为搜索关键字 (自主纠偏, 不是死用原始 URL)。
    search_keyword = ""
    if source:
        norm_repo, kw = _normalize_github_source(source)
        if norm_repo:
            source = norm_repo
        else:
            search_keyword = kw
            source = ""
    if not source and (name.startswith(("http://", "https://", "github.com/")) or "/" in name):
        norm_repo, kw = _normalize_github_source(name)
        if norm_repo:
            source = norm_repo
        elif kw and not search_keyword:
            search_keyword = kw

    if not source:
        query = search_keyword or name
        candidates = []
        try:
            from app.core import skill_search
            candidates = await asyncio.to_thread(skill_search.search_skills, query, 10)
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill_install 实时搜索失败: %s", exc)
        cand = _match_install_candidate(name if not search_keyword else query, candidates)
        if cand:
            source = str(cand.get("source") or "")
            resolved_id = str(cand.get("skill_id") or name)
        else:
            try:
                local = await asyncio.to_thread(marketplace.list_marketplace_skills, None, query, None)
            except Exception:  # noqa: BLE001
                local = []
            if local:
                source = str(local[0].get("source_repo") or "")
                resolved_id = str(local[0].get("name") or name)
        if not source:
            hint = ""
            if candidates:
                names = "、".join(str(c.get("skill_id") or c.get("name")) for c in candidates[:5])
                hint = f" 相近的 skill: {names}。"
            topic_note = ""
            if search_keyword:
                topic_note = (
                    f" 你给的是 GitHub topics/搜索页(不是具体仓库)，已按主题词『{search_keyword}』检索。"
                )
            return (
                f"❌ 找不到可直接安装的 skill('{query}')，无法确定来源仓库。{topic_note}"
                f"{hint} 请给出具体 skill 仓库(格式 owner/repo)，或换个关键词。"
            )
    else:
        # 显式 owner/repo 但仓库里 skill 目录名未必等于 name, 让 marketplace 侧解析
        resolved_id = resolved_id or name

    try:
        result = await asyncio.to_thread(marketplace.install_skill, resolved_id, source)
    except Exception as exc:  # noqa: BLE001
        return f"❌ 安装 skill 失败: {exc}"

    if not result.get("ok"):
        return f"❌ 安装 skill 失败: {result.get('error', '未知错误')}（{resolved_id}@{source}）"

    total_files = result.get("total_files", 1)
    note = ""
    if result.get("quarantined"):
        note = " 该 skill 默认隔离(quarantined)，启用后才会进入可用列表。"
    return (
        f"✅ 已安装 skill '{resolved_id}'（来源 {source}，{total_files} 个文件）。{note}"
    )


# 启动时注册 (W4-21 P2-2: 显式 _register_tools, 便于测试 mock)


def _register_tools():
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

    registry.register(
        name="skill_install",
        toolset="skill",
        description=(
            "下载并安装一个外部 skill 到本地(经 GitHub API 拉取, 不需要 git/terminal)。\n"
            "用户要求“安装/下载某个 skill”时用它, 不要用 web_search/web_extract/terminal 去凑。\n"
            "source 可传 owner/repo 或完整 GitHub 仓库 URL; 不传则按 name 自动检索。\n"
            "若给的是 GitHub topics/搜索页(非具体仓库), 会自动按主题词检索真实仓库。\n"
            "解析不到来源会返回候选让你确认, 不要反复重试。"
        ),
        schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要安装的 skill 名称 / skillId",
                },
                "source": {
                    "type": "string",
                    "description": "可选来源仓库，格式 owner/repo；不传则自动解析。",
                },
            },
            "required": ["name"],
        },
        handler=skill_install,
        is_async=True,
        emoji="📥",
        parallel_mode="never",
    )






# 启动时注册 (W4-21 P2-2: 显式 _register_tools, 便于测试 mock)
_register_tools()
