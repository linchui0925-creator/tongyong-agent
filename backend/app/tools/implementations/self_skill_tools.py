"""
self_skill_tools - Harness for TongYong to draft and install local skills.

Only installs user/local skills as external + quarantined. No examples are
seeded here; the model must provide task-specific content.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

import yaml

from app.config import settings
from app.hermes.skill_file import SkillFileManager
from app.tools.registry import registry


MAX_SKILL_BODY_CHARS = 80_000


SELF_SKILL_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "skill 名称。"},
        "description": {"type": "string", "description": "一句话描述。"},
        "body": {"type": "string", "description": "SKILL.md 正文，不含 frontmatter。"},
        "category": {"type": "string", "description": "分类，默认 general。", "default": "general"},
        "auto_load": {"type": "boolean", "description": "是否请求自动加载；安装时仍默认隔离。", "default": False},
    },
    "required": ["name", "description", "body"],
}


SELF_SKILL_VALIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_md": {"type": "string", "description": "完整 SKILL.md 内容。"},
    },
    "required": ["skill_md"],
}


SELF_SKILL_INSTALL_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_md": {"type": "string", "description": "完整 SKILL.md 内容。"},
        "category": {"type": "string", "description": "安装分类，默认读取 frontmatter 或 general。", "default": "general"},
        "overwrite": {"type": "boolean", "description": "是否覆盖同名 skill，默认 false。", "default": False},
    },
    "required": ["skill_md"],
}


def self_skill_draft(
    name: str,
    description: str,
    body: str,
    category: str = "general",
    auto_load: bool = False,
) -> str:
    meta = {
        "name": _clean_name(name),
        "description": description.strip(),
        "version": "1.0.0",
        "skill_type": "external",
        "quarantined": True,
        "auto_load": bool(auto_load),
        "category": _clean_category(category),
    }
    skill_md = _build_skill_md(meta, body)
    report = _validate_skill_md(skill_md)
    return json.dumps({"ok": report["ok"], "skill_md": skill_md, "validation": report}, ensure_ascii=False, indent=2)


def self_skill_validate(skill_md: str) -> str:
    return json.dumps(_validate_skill_md(skill_md), ensure_ascii=False, indent=2)


def self_skill_install(skill_md: str, category: str = "general", overwrite: bool = False) -> str:
    report = _validate_skill_md(skill_md)
    if not report["ok"]:
        return json.dumps({"ok": False, "validation": report}, ensure_ascii=False, indent=2)

    meta, _body = _parse_skill_md(skill_md)
    name = _clean_name(str(meta.get("name") or _derive_name_from_body(_body) or "unnamed"))
    category = _clean_category(str(meta.get("category") or category or "general"))

    root = Path(settings.hermes_skills_dir)
    target_dir = root / category / _safe_dir_name(name)
    skill_path = target_dir / "SKILL.md"
    if skill_path.exists() and not overwrite:
        return json.dumps({"ok": False, "error": f"skill 已存在: {name}", "path": str(skill_path)}, ensure_ascii=False, indent=2)

    meta["name"] = name
    meta["description"] = str(meta.get("description") or _derive_description_from_body(_body) or name)
    meta["skill_type"] = "external"
    meta["quarantined"] = True
    meta["auto_load"] = bool(meta.get("auto_load", False))
    skill_md = _build_skill_md(meta, _body)

    manager = SkillFileManager(base_dir=str(root.parent))
    threat = manager._security_scan(skill_md)  # noqa: SLF001 - reuse existing project scanner
    if threat:
        return json.dumps({"ok": False, "error": f"安全扫描失败: {threat}"}, ensure_ascii=False, indent=2)

    target_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = skill_path.with_suffix(".tmp")
    tmp_path.write_text(skill_md, encoding="utf-8")
    os.replace(tmp_path, skill_path)

    try:
        from app.core.skills_index import refresh as refresh_skills_index
        refresh_skills_index()
    except Exception:
        pass

    return json.dumps({
        "ok": True,
        "name": name,
        "category": category,
        "path": str(skill_path),
        "skill_type": "external",
        "quarantined": True,
        "message": "skill 已安装到隔离区；需用户审核后才能解除隔离或提升为 system。",
    }, ensure_ascii=False, indent=2)


def _validate_skill_md(skill_md: str) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    if len(skill_md) > MAX_SKILL_BODY_CHARS:
        errors.append(f"skill 内容过长，超过 {MAX_SKILL_BODY_CHARS} 字符")
    meta, body = _parse_skill_md(skill_md)
    if not body.strip():
        errors.append("正文不能为空")
    if not meta.get("name") and not _derive_name_from_body(body):
        warnings.append("未提供 name，将尝试从正文标题推断")
    if not meta.get("description"):
        warnings.append("未提供 description，将使用正文首段或标题推断")
    if "## Steps" not in body:
        warnings.append("建议包含 ## Steps")
    if re.search(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", skill_md, re.I):
        errors.append("包含疑似提示注入内容")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metadata": meta,
        "body_chars": len(body),
    }


def _parse_skill_md(skill_md: str) -> tuple[dict, str]:
    text = skill_md.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]) or {}, parts[2].strip()
            except yaml.YAMLError:
                return {}, parts[2].strip()
    return {}, text


def _derive_name_from_body(body: str) -> Optional[str]:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            candidate = re.sub(r"^#+\s*", "", stripped).strip()
            candidate = re.sub(r"[^a-zA-Z0-9\s\-\u4e00-\u9fff]", "", candidate)[:80]
            if candidate:
                return candidate
    return None


def _derive_description_from_body(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped != "---":
            return stripped[:200]
    return ""


def _build_skill_md(meta: dict, body: str) -> str:
    return "---\n" + yaml.dump(meta, allow_unicode=True, default_flow_style=False) + "---\n\n" + body.strip() + "\n"


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", "-", str(name).strip())[:80] or "unnamed"


def _clean_category(category: str) -> str:
    raw = str(category or "general").strip().lower()
    safe = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
    return safe[:40] or "general"


def _safe_dir_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-一-鿿]", "-", name.lower()).strip("-") or "unnamed"


def _register_tools():
    registry.register(
        name="self_skill_draft",
        toolset="skill",
        description="生成一个本地 skill 草案；只返回 SKILL.md 文本，不安装。",
        schema=SELF_SKILL_DRAFT_SCHEMA,
        handler=self_skill_draft,
        is_async=False,
        emoji="🧩",
        parallel_mode="safe",
    )
    registry.register(
        name="self_skill_validate",
        toolset="skill",
        description="校验完整 SKILL.md 是否满足本地安装 harness 的基本要求。",
        schema=SELF_SKILL_VALIDATE_SCHEMA,
        handler=self_skill_validate,
        is_async=False,
        emoji="🧩",
        parallel_mode="safe",
    )
    registry.register(
        name="self_skill_install",
        toolset="skill",
        description="安装本地 skill。始终以 external + quarantined 写入，需用户审核后才可解除隔离或提升 system。",
        schema=SELF_SKILL_INSTALL_SCHEMA,
        handler=self_skill_install,
        is_async=False,
        emoji="🧩",
        parallel_mode="path_scoped",
    )


_register_tools()
