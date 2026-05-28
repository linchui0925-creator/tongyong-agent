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
from functools import lru_cache

logger = logging.getLogger(__name__)

_SKILLS_BASE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"


def _scan_skills() -> dict:
    """扫描所有 SKILL.md，返回 {name: {category, description, version, platforms}}"""
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
            result[name] = {
                "category": category,
                "description": meta.get("description", ""),
                "version": meta.get("version", "1.0"),
                "platforms": meta.get("platforms", []),
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


@lru_cache(maxsize=1)
def _cached_scan() -> dict:
    """带缓存的扫描，mtime 变化时自动失效"""
    return _scan_skills()


def get_skills_index() -> dict:
    """获取 skill 索引（自动按 mtime 检测变化）"""
    current_mtime = _get_dir_mtime()
    cached = _cached_scan()
    # lru_cache 不支持 mtime 感知的失效，改用全局 mtime 跟踪
    global _last_mtime
    if current_mtime != _last_mtime:
        _last_mtime = current_mtime
        return _scan_skills()
    return cached


_last_mtime: float = 0.0


def format_skills_prompt() -> str:
    """将 skill 索引格式化为 <available_skills> 块"""
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

    # 按分类组织
    by_category: dict = {}
    for name, info in skills.items():
        cat = info["category"]
        by_category.setdefault(cat, []).append((name, info))

    lines = ["## 可用 Skill 索引\n"]
    lines.append("<available_skills>")
    lines.append("")
    lines.append("**你拥有以下 skill。当你需要完成某个任务时，先调用 `skill_list()` 查看索引，")
    lines.append("然后调用 `skill_view(name)` 加载完整内容，再按文档执行。**")
    lines.append("")

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

    lines.append("</available_skills>")
    lines.append("")
    lines.append("**工具：** `skill_list()` 列出索引 | `skill_view(name)` 读取详情")

    return "\n".join(lines)


# 模块加载时预热
_detected: str | None = None


def get_skills_prompt() -> str:
    """获取 skill 索引提示词（延迟初始化 + mtime 缓存）"""
    global _detected
    if _detected is None:
        _detected = format_skills_prompt()
        logger.info("Skill 索引生成完成")
    return _detected


def refresh():
    """强制重新生成（例如上传新 skill 后）"""
    global _detected, _last_mtime
    _last_mtime = 0.0
    _detected = format_skills_prompt()
    return _detected
