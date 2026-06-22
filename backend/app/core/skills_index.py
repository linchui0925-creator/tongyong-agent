"""
skills_index - Skill 索引动态生成

<available_skills> 索引块：
- 由代码动态扫描 skills/ 目录生成
- 每次请求时按需生成（mtime 检测变化）
- 注入 system prompt，让 Agent 知道有哪些 skill 可用
- Agent 按需调用 skill_view(name) 读取完整内容
"""

import logging
import os
import yaml
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_SKILLS_BASE_DIR = Path(settings.hermes_skills_dir)


def _scan_skills() -> dict:
    """扫描所有 SKILL.md，返回 {name: {category, description, version, platforms, skill_type, auto_load, quarantined}}"""
    base = _SKILLS_BASE_DIR
    if not base.is_dir():
        return {}

    result = {}
    for cat_dir in sorted(base.iterdir()):
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
            # 安全缺省：缺 skill_type 默认 "external"，避免 system 权限滥用
            skill_type = str(meta.get("skill_type", "external")).strip().lower()
            if skill_type not in ("system", "external"):
                skill_type = "external"
            auto_load = bool(meta.get("auto_load", False))
            # quarantined：缺失字段视为 False（向后兼容）
            quarantined = bool(meta.get("quarantined", False))
            result[name] = {
                "category": category,
                "description": meta.get("description", ""),
                "version": meta.get("version", "1.0"),
                "platforms": meta.get("platforms", []),
                "skill_type": skill_type,
                "auto_load": auto_load,
                "quarantined": quarantined,
            }
    return result


def _read_frontmatter(path: Path) -> dict:
    try:
        content = path.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return yaml.safe_load(parts[1]) or {}
    except Exception:
        pass
    return {}


def _get_dir_mtime() -> float:
    """获取 skill 目录的最近修改时间"""
    base = _SKILLS_BASE_DIR
    if not base.is_dir():
        return 0.0
    latest = 0.0
    for root, dirs, files in os.walk(base):
        try:
            m = Path(root).stat().st_mtime
            if m > latest:
                latest = m
        except OSError:
            pass
        for fname in files:
            try:
                m = (Path(root) / fname).stat().st_mtime
                if m > latest:
                    latest = m
            except OSError:
                pass
    return latest



def get_skills_index() -> dict:
    """获取 skill 索引（自动按 mtime 检测变化）

    W4-12 SKILL 修复 2026-06-21: 移除死代码 _cached_scan / @lru_cache, 用单一全局
    _last_mtime + _last_index 跟踪, 变化时直接重新扫描。
    """
    global _last_mtime, _last_index
    current_mtime = _get_dir_mtime()
    if current_mtime != _last_mtime:
        _last_mtime = current_mtime
        _last_index = _scan_skills()
    return _last_index


_last_mtime: float = 0.0
_last_index: dict = {}


def format_skills_prompt() -> str:
    """将 skill 索引格式化为 <available_skills> 块

    区分：
    - system skills：默认 system 提示词可见（标记 🔒）
    - external skills：用户已激活的（quarantined=false）
    - 隔离区：跳过
    """
    skills = get_skills_index()

    if not skills:
        return """## 可用 Skill 索引

<available_skills>
（当前没有已上传的 skill。你可以通过上传 md/json/zip 文件来创建 skill。）
</available_skills>

**如何使用 skill：**
- 调用 `skill_list()` 查看所有可用 skill 的完整索引
- 调用 `skill_view(name)` 读取某个 skill 的完整内容
- 匹配到相关 skill 时，必须先 skill_view 加载内容，再按文档执行
"""

    # 过滤掉隔离区；分类
    system_skills: list = []
    external_skills: list = []
    for name, info in skills.items():
        if info.get("quarantined"):
            continue
        if info.get("skill_type") == "system":
            system_skills.append((name, info))
        else:
            external_skills.append((name, info))

    # 按分类组织（仅 external 需要索引，system 由 get_system_skills_content 注入完整内容）
    by_category: dict = {}
    for name, info in external_skills:
        cat = info["category"]
        by_category.setdefault(cat, []).append((name, info))

    lines = ["## 可用 Skill 索引\n"]
    lines.append("<available_skills>")
    lines.append("")
    if system_skills:
        lines.append(f"**系统级 skill（{len(system_skills)} 个，已自动加载完整内容到上方）**\n")
        for name, info in sorted(system_skills, key=lambda x: x[0]):
            # W4-12 SKILL 修复: 80 字符硬截断加 ... 防止描述被切到无意义位置
            desc = info.get("description", "（无描述）")
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"- 🔒 `{name}`: {desc}")
        lines.append("")
    if external_skills:
        lines.append("**外部 skill（按需调用 `skill_view(name)` 加载完整内容）**\n")
        for cat in sorted(by_category.keys()):
            lines.append(f"### {cat}")
            for name, info in sorted(by_category[cat], key=lambda x: x[0]):
                desc = info.get("description") or "（无描述）"
                if len(desc) > 100:
                    desc = desc[:97] + "..."
                platforms = info.get("platforms", [])
                plat_str = f" [{', '.join(platforms)}]" if platforms else ""
                lines.append(f"- `{name}`{plat_str}: {desc}")
            lines.append("")
    else:
        lines.append("（当前没有已激活的外部 skill。）\n")
    lines.append("</available_skills>")
    lines.append("")
    lines.append("**工具：** `skill_list()` 列出索引 | `skill_view(name)` 读取详情")

    return "\n".join(lines)


# ── system skills 完整内容注入 ──────────────────────────

# 8KB 上限：超过则只截取"决策启发式"段（Heuristic / 启发式 / Decision）
_SYSTEM_CONTENT_MAX_BYTES = 8 * 1024
_HEURISTIC_SECTION_PATTERNS = ("Heuristic", "启发式", "Decision", "决策", "Pitfall")


def _extract_heuristic_sections(body: str) -> str:
    """从 SKILL.md body 中截取启发式段，避免 system prompt 爆"""
    if not body:
        return ""
    lines = body.splitlines()
    keep: list = []
    in_section = False
    section_level = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            if any(pat in title for pat in _HEURISTIC_SECTION_PATTERNS):
                in_section = True
                section_level = 2
                keep.append(line)
            elif in_section:
                # 退出启发式段
                break
            else:
                continue
        elif in_section:
            keep.append(line)
    return "\n".join(keep).strip() if keep else body[:_SYSTEM_CONTENT_MAX_BYTES]


def get_system_skills_content() -> str:
    """读取所有 skill_type=system 且 auto_load=true 的 skill 完整内容

    用途：在 agent 启动时一次性注入到 system prompt，避免按需调用。

    截断策略：
    - 总内容 > 8KB 时，每个 skill 只取"启发式"段
    - 启发式段为空时取 body 前 8KB/N 切分
    """
    skills = get_skills_index()
    system_skills = [
        (name, info) for name, info in skills.items()
        if info.get("skill_type") == "system"
        and info.get("auto_load")
        and not info.get("quarantined")
    ]
    if not system_skills:
        return ""

    # 直接读 SKILL.md，绕开 SkillFileManager 的 base_dir 假设
    blocks: list = []
    total_size = 0
    budget_per = _SYSTEM_CONTENT_MAX_BYTES // max(len(system_skills), 1)

    for name, info in sorted(system_skills, key=lambda x: x[0]):
        skill_md = _SKILLS_BASE_DIR / info["category"] / name / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            raw = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        # 复用本模块的 frontmatter 解析；body 用 content.split("---", 2)[2]
        meta = _read_frontmatter(skill_md)
        if raw.startswith("---") and raw.count("---") >= 2:
            body = raw.split("---", 2)[2].strip()
        else:
            body = raw.strip()

        # 总预算：先看是否需要启发式截断
        if total_size + len(body) > _SYSTEM_CONTENT_MAX_BYTES:
            content = _extract_heuristic_sections(body)[:budget_per]
        else:
            content = body

        blocks.append(
            f"### 🔒 {name}（system / auto_load）\n"
            f"version: {meta.get('version', '?')}\n\n"
            f"{content}"
        )
        total_size += len(content)

    if not blocks:
        return ""

    return (
        "## 系统级 Skills（已自动加载完整内容）\n\n"
        "以下是 system 级 skill 的完整内容，已注入到本次会话。"
        "匹配到相关任务时直接按文档执行，**无需再调用 skill_view**。\n\n"
        + "\n\n---\n\n".join(blocks)
    )


# 模块加载时预热
_detected: str | None = None
# W4-12 SKILL 修复: get_skills_prompt 需要追踪 mtime 才能感知新 skill 上传
_last_skills_prompt_mtime: float = 0.0


def get_skills_prompt() -> str:
    """获取 skill 索引提示词（延迟初始化 + mtime 缓存）

    W4-12 SKILL 修复: 旧实现 _detected 只在第一次 None 时生成, 之后再调用永远
    返回旧字符串, 上传新 skill 后 system prompt 看不到。修复后每次调用都检查
    mtime, 变化时刷新 _detected。
    """
    global _detected, _last_skills_prompt_mtime
    current_mtime = _get_dir_mtime()
    if _detected is None or current_mtime != _last_skills_prompt_mtime:
        _detected = format_skills_prompt()
        _last_skills_prompt_mtime = current_mtime
        if current_mtime == 0:
            logger.info("Skill 索引生成完成")
        else:
            logger.info("Skill 索引已刷新 (mtime 变化)")
    return _detected


def refresh():
    """强制重新生成（例如上传新 skill 后）"""
    global _detected, _last_mtime, _last_skills_prompt_mtime
    _last_mtime = 0.0
    _last_skills_prompt_mtime = 0.0
    _detected = None  # W4-12: 让 get_skills_prompt 重新走 mtime 路径
    return get_skills_prompt()
