"""
Skills API - 技能管理（Hermes 平文件 + 用户上传）

支持：
- 列表/查看/删除技能（已有）
- 用户上传 skill（zip、md、txt、json）
- 上传后自动解析并创建 skill
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel

from app.api.skill_upload_parser import (
    ALLOWED_EXTENSIONS,
    _parse_uploaded_file,
    _extract_steps_from_text,
    _extract_triggers,
    _extract_keywords,
    _derive_name_from_content,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])

_skill_manager = None
_skill_categories = ["general", "code", "devops", "data", "web", "mobile", "other"]


def _safe_float(raw, default=1.0):
    """安全解析版本号，处理引号包裹和多小数点的情况"""
    if not raw:
        return default
    s = re.sub(r"['\"]", "", str(raw)).strip()
    # 提取第一个有效数字
    m = re.search(r'\d+\.?\d*', s)
    if m:
        try:
            return float(m.group())
        except (ValueError, TypeError):
            pass
    return default


def init(skill_manager):
    global _skill_manager
    _skill_manager = skill_manager


# ── 已有接口 ──────────────────────────────────

@router.get("")
async def list_skills():
    """获取技能列表

    返回字段：
    - id / name / category / version / usage_count / success_rate
    - content（body 摘要 200 字符）
    - size_bytes（SKILL.md 文件大小）
    - source_repo（市场来源，如 "anthropics/skills"；本地手工创建则为空）
    - skill_type（"system" | "external"）
    - auto_load（bool）
    - quarantined（bool）
    - installed_at（ISO 时间戳）
    """
    if not _skill_manager:
        return {"skills": [], "total": 0}

    skills = _skill_manager.list_skills()
    result = []
    from pathlib import Path
    for s in skills:
        detail = _skill_manager.view_skill(s["name"])
        meta = (detail or {}).get("metadata") or {}
        # 文件大小：通过 list_skills 的 category + name 拼路径（SkillFileManager 没暴露 path）
        size_bytes = 0
        if detail:
            # 通过 _find_skill_path 私有方法查文件位置（避免我们这边重复实现）
            try:
                skill_path = _skill_manager._find_skill_path(s["name"])  # type: ignore[attr-defined]
                if skill_path:
                    f = Path(skill_path) / "SKILL.md"
                    if f.is_file():
                        size_bytes = f.stat().st_size
            except (AttributeError, OSError):
                pass
        installed_at = meta.get("installed_at") or ""

        result.append({
            "id": s["name"],
            "name": s["name"],
            # W5-3: display_name 优先 frontmatter name, 缺省回退目录名
            "display_name": (meta.get("name") or s["name"]) if isinstance(meta, dict) else s["name"],
            "content": (detail or {}).get("body", "")[:200] if detail else s.get("description", ""),
            "category": s.get("category", "general"),
            "usage_count": 0,
            "success_rate": 100.0,
            "version": _safe_float(s.get("version")),
            "trigger_conditions": [],
            "execution_steps": [],
            # 新增字段
            "size_bytes": size_bytes,
            "source_repo": meta.get("source", "") or "",
            "skill_type": meta.get("skill_type", "external"),
            "auto_load": bool(meta.get("auto_load", False)),
            "quarantined": bool(meta.get("quarantined", False)),
            "installed_at": installed_at,
        })
    return {"skills": result, "total": len(result)}


@router.get("/categories")
async def list_categories():
    """获取可用的 skill 分类"""
    return {"categories": _skill_categories}


# ── 改 skill 类型（system / external） + auto_load + quarantined ─────

class SkillTypePatch(BaseModel):
    skill_type: Optional[str] = None  # "system" | "external"
    auto_load: Optional[bool] = None
    quarantined: Optional[bool] = None


class BatchTypePatch(BaseModel):
    """批量 PATCH 请求体（注意：路由必须在 /{name}/type 之前声明）"""
    names: List[str]  # skill 名称列表
    skill_type: Optional[str] = None
    auto_load: Optional[bool] = None
    quarantined: Optional[bool] = None


# ── Phase 4+: token 估算（不调 LLM，本地粗估） ───────

class TokenPreviewRequest(BaseModel):
    """token 估算请求体"""
    names: List[str]  # 要估算的 skill 名称列表
    hypothetical: Optional[bool] = False  # True: 假设全部提升为 system 的预估


class TokenPreviewItem(BaseModel):
    name: str
    size_bytes: int
    estimated_tokens: int
    would_inject: bool  # 当前是否会被注入到 system prompt


class TokenPreviewResponse(BaseModel):
    items: List[TokenPreviewItem]
    total_tokens: int
    system_prompt_would_inject: int
    method: str  # "heuristic_cjk_aware"


def _estimate_tokens(text: str) -> int:
    """粗估 token 数：CJK 字符 1.5 char/token，ASCII 4 char/token

    实际 LLM tokenizer 差异较大（tiktoken/Claude/GPT 各不同），本估算作为 UI 提示用
    """
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
    ascii_chars = len(text) - cjk
    # 反向算 tokens：ASCII 4 char/token，CJK 1.5 char/token
    return max(1, int(round(ascii_chars / 4 + cjk / 1.5)))


@router.post("/preview-tokens", response_model=TokenPreviewResponse)
async def preview_tokens(req: TokenPreviewRequest):
    """估算若干 skill 的 token 占用

    - hypothetical=False: 按当前 skill_type 判断哪些会被注入到 system prompt
    - hypothetical=True:  假设列表中所有 skill 都被提升为 system，估算总注入
    """
    if not _skill_manager:
        return TokenPreviewResponse(
            items=[], total_tokens=0, system_prompt_would_inject=0, method="heuristic_cjk_aware"
        )
    items: List[TokenPreviewItem] = []
    total_tokens = 0
    inject_tokens = 0
    for name in req.names:
        detail = _skill_manager.view_skill(name)
        if not detail:
            continue
        # 完整内容 = frontmatter (转 yaml) + body
        body = detail.get("body", "")
        meta = detail.get("metadata", {}) or {}
        meta_yaml = "\n".join(f"{k}: {v}" for k, v in meta.items()) if meta else ""
        full_text = (("---\n" + meta_yaml + "\n---\n") if meta_yaml else "") + body

        tokens = _estimate_tokens(full_text)

        # 文件大小
        from pathlib import Path
        size = 0
        try:
            sf = _skill_manager._find_skill_path(name)  # noqa: SLF001
            if sf and sf.exists():
                size = sf.stat().st_size
        except Exception:
            pass

        # 假设 system 提升
        if req.hypothetical:
            would_inject = True
        else:
            would_inject = (meta.get("skill_type") == "system" and not meta.get("quarantined", True))

        items.append(TokenPreviewItem(
            name=name, size_bytes=size, estimated_tokens=tokens, would_inject=would_inject
        ))
        total_tokens += tokens
        if would_inject:
            inject_tokens += tokens

    return TokenPreviewResponse(
        items=items, total_tokens=total_tokens,
        system_prompt_would_inject=inject_tokens, method="heuristic_cjk_aware",
    )


@router.patch("/batch/type")
async def batch_patch_skill_type(batch: BatchTypePatch):
    """批量修改多个 skill 的元数据

    用途：
    - 批量解除隔离：{"names": ["pdf", "xlsx", "pptx"], "quarantined": false}
    - 批量提升为 system：{"names": [...], "skill_type": "system", "auto_load": true}
    - 批量降级：{"names": [...], "skill_type": "external"}
    """
    if not _skill_manager:
        raise HTTPException(status_code=503, detail="Skill manager not initialized")

    if not batch.names:
        raise HTTPException(status_code=400, detail="names 不能为空")
    if batch.skill_type is not None and batch.skill_type not in ("system", "external"):
        raise HTTPException(status_code=400, detail="skill_type 必须是 system 或 external")
    if len(batch.names) > 50:
        raise HTTPException(status_code=400, detail="单次最多 50 个 skill")

    results = []
    for name in batch.names:
        try:
            patch = SkillTypePatch(
                skill_type=batch.skill_type,
                auto_load=batch.auto_load,
                quarantined=batch.quarantined,
            )
            skill = _skill_manager.view_skill(name)
            if not skill:
                results.append({"name": name, "ok": False, "error": "not_found"})
                continue
            meta = dict(skill.get("metadata") or {})
            changed = []

            if patch.skill_type is not None and meta.get("skill_type") != patch.skill_type:
                ok, _ = _skill_manager.patch_skill(
                    name, f"skill_type: {meta.get('skill_type', 'external')}", f"skill_type: {patch.skill_type}"
                )
                if not ok:
                    _skill_manager.patch_skill(name, "---", f"---\nskill_type: {patch.skill_type}")
                changed.append("skill_type")

            if patch.auto_load is not None and meta.get("auto_load") != patch.auto_load:
                ok, _ = _skill_manager.patch_skill(
                    name, f"auto_load: {str(meta.get('auto_load', False)).lower()}",
                    f"auto_load: {str(patch.auto_load).lower()}"
                )
                if not ok:
                    _skill_manager.patch_skill(name, "---", f"---\nauto_load: {str(patch.auto_load).lower()}")
                changed.append("auto_load")

            if patch.quarantined is not None and meta.get("quarantined") != patch.quarantined:
                ok, _ = _skill_manager.patch_skill(
                    name, f"quarantined: {str(meta.get('quarantined', False)).lower()}",
                    f"quarantined: {str(patch.quarantined).lower()}"
                )
                if not ok:
                    _skill_manager.patch_skill(name, "---", f"---\nquarantined: {str(patch.quarantined).lower()}")
                changed.append("quarantined")

            results.append({"name": name, "ok": True, "changed": changed})
        except Exception as e:
            results.append({"name": name, "ok": False, "error": str(e)})

    try:
        from app.core.skills_index import refresh as refresh_skills_index
        refresh_skills_index()
    except Exception as e:
        logger.warning(f"刷新 skill 索引失败: {e}")

    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "ok": ok_count == len(results),
        "total": len(results),
        "succeeded": ok_count,
        "failed": len(results) - ok_count,
        "results": results,
    }


@router.patch("/{name}/type")
async def patch_skill_type(name: str, patch: SkillTypePatch):
    """修改 skill 的元数据：skill_type / auto_load / quarantined

    - 改 frontmatter 三个字段
    - 触发 skills_index 缓存刷新
    """
    if not _skill_manager:
        raise HTTPException(status_code=503, detail="Skill manager not initialized")

    if patch.skill_type is not None and patch.skill_type not in ("system", "external"):
        raise HTTPException(status_code=400, detail="skill_type 必须是 system 或 external")

    # 用 patch_skill 改 frontmatter 行（SkillFileManager 已有能力）
    skill = _skill_manager.view_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    meta = dict(skill.get("metadata") or {})

    changed = []
    if patch.skill_type is not None and meta.get("skill_type") != patch.skill_type:
        ok, msg = _skill_manager.patch_skill(
            name, f"skill_type: {meta.get('skill_type', 'external')}", f"skill_type: {patch.skill_type}"
        )
        if not ok:
            # 第一次 patch 失败可能因为缺字段，直接走原始文件修改
            ok2, msg2 = _skill_manager.patch_skill(
                name, "---", f"---\nskill_type: {patch.skill_type}"
            )
            if not ok2:
                raise HTTPException(status_code=500, detail=f"改 skill_type 失败: {msg} / {msg2}")
        changed.append("skill_type")

    if patch.auto_load is not None and meta.get("auto_load") != patch.auto_load:
        ok, msg = _skill_manager.patch_skill(
            name, f"auto_load: {str(meta.get('auto_load', False)).lower()}",
            f"auto_load: {str(patch.auto_load).lower()}"
        )
        if not ok:
            ok2, msg2 = _skill_manager.patch_skill(
                name, "---", f"---\nauto_load: {str(patch.auto_load).lower()}"
            )
            if not ok2:
                raise HTTPException(status_code=500, detail=f"改 auto_load 失败: {msg} / {msg2}")
        changed.append("auto_load")

    if patch.quarantined is not None and meta.get("quarantined") != patch.quarantined:
        ok, msg = _skill_manager.patch_skill(
            name, f"quarantined: {str(meta.get('quarantined', False)).lower()}",
            f"quarantined: {str(patch.quarantined).lower()}"
        )
        if not ok:
            ok2, msg2 = _skill_manager.patch_skill(
                name, "---", f"---\nquarantined: {str(patch.quarantined).lower()}"
            )
            if not ok2:
                raise HTTPException(status_code=500, detail=f"改 quarantined 失败: {msg} / {msg2}")
        changed.append("quarantined")

    # 触发 skills_index 缓存刷新
    try:
        from app.core.skills_index import refresh as refresh_skills_index
        refresh_skills_index()
    except Exception as e:
        logger.warning(f"刷新 skill 索引失败: {e}")

    return {"ok": True, "name": name, "changed": changed}


@router.get("/{name}")
async def get_skill(name: str):
    """获取技能详情"""
    if not _skill_manager:
        raise HTTPException(status_code=503, detail="Skill manager not initialized")
    skill = _skill_manager.view_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return skill


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str):
    """删除技能"""
    if not _skill_manager:
        raise HTTPException(status_code=503, detail="Skill manager not initialized")
    ok, msg = _skill_manager.delete_skill(skill_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


# ── 上传接口 ──────────────────────────────────



class UploadResult(BaseModel):
    success: bool
    skill_name: Optional[str] = None
    message: str
    parsed_triggers: List[str] = []
    parsed_steps: List[str] = []
    warnings: List[str] = []


@router.post("/upload", response_model=UploadResult)
async def upload_skill(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form("general"),
    name: Optional[str] = Form(None),
):
    """上传 skill 文件（支持 zip、md、txt、json 等）

    - .zip: 解压后读取所有文本文件，提取 trigger + steps
    - .md/.txt: 直接解析内容
    - .json/.yaml: 尝试读取 name/description/triggers/steps 字段
    """
    if not _skill_manager:
        raise HTTPException(status_code=503, detail="Skill manager not initialized")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}。支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # 读取文件内容
    content_bytes = await file.read()

    # 解析内容
    parsed = _parse_uploaded_file(content_bytes, ext, name)

    if not parsed["body_text"]:
        raise HTTPException(status_code=400, detail="无法从文件中提取有效内容")

    # 确定 skill 名称
    skill_name = parsed["name"] or name or _derive_name_from_content(parsed["body_text"])
    if not skill_name:
        raise HTTPException(status_code=400, detail="无法确定 skill 名称，请上传有意义的文件或提供 name 参数")

    # 分类安全检查
    if category not in _skill_categories:
        category = "general"

    # 创建 skill
    ok, msg = _skill_manager.create_skill(
        name=skill_name,
        description=parsed.get("description", f"用户上传的 skill: {skill_name}"),
        steps=parsed.get("steps", _extract_steps_from_text(parsed["body_text"])),
        pitfalls=parsed.get("pitfalls"),
        category=category,
        platforms=parsed.get("platforms"),
    )

    if not ok:
        return UploadResult(success=False, message=msg, warnings=parsed.get("warnings", []))

    # 如果有引用文件（从 zip 解压），添加引用
    if parsed.get("references"):
        for fname, fcontent in parsed["references"].items():
            _skill_manager.add_reference(skill_name, fname, fcontent)

    # 上传成功后立即刷新 skill 索引缓存，确保 agent 下一轮可见
    try:
        from app.core.skills_index import refresh as refresh_skills_index
        refresh_skills_index()
    except Exception as e:
        logger.warning(f"刷新 skill 索引失败: {e}")

    logger.info(f"Skill 上传成功: {skill_name} (category={category})")
    return UploadResult(
        success=True,
        skill_name=skill_name,
        message=f"Skill '{skill_name}' 创建成功",
        parsed_triggers=parsed.get("triggers", []),
        parsed_steps=parsed.get("steps", []),
        warnings=parsed.get("warnings", []),
    )


# ── 触发匹配 ──────────────────────────────────

class TriggerMatchRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class TriggerMatchResponse(BaseModel):
    matched: bool
    skill_name: Optional[str] = None
    skill_detail: Optional[Dict] = None
    match_reason: Optional[str] = None


@router.post("/trigger", response_model=TriggerMatchResponse)
async def trigger_skill(req: TriggerMatchRequest):
    """根据用户消息自动匹配最合适的 skill

    匹配策略：
    1. 精确匹配：消息包含 skill 名称
    2. 关键词匹配：消息包含 trigger 关键词
    3. 描述匹配：消息意图与 skill description 相关
    """
    if not _skill_manager:
        return TriggerMatchResponse(matched=False, match_reason="Skill manager 未初始化")

    all_skills = _skill_manager.list_skills()
    if not all_skills:
        return TriggerMatchResponse(matched=False, match_reason="暂无可用 skill")

    msg_lower = req.message.lower()
    best_match = None
    best_score = 0
    best_reason = ""

    for s in all_skills:
        name = s["name"].lower()
        desc = s.get("description", "").lower()
        category = s.get("category", "general")

        score = 0
        reason = ""

        # 精确名称匹配
        if name in msg_lower:
            score = 100
            reason = f"消息包含 skill 名称 '{s['name']}'"
        # trigger 关键词匹配（从 description 推断）
        else:
            keywords = _extract_keywords(desc)
            matched_kw = [kw for kw in keywords if kw in msg_lower]
            score = len(matched_kw) * 20
            if matched_kw:
                reason = f"匹配关键词: {', '.join(matched_kw)}"

        if score > best_score:
            best_score = score
            best_match = s
            best_reason = reason

    if best_match and best_score >= 20:
        detail = _skill_manager.view_skill(best_match["name"])
        return TriggerMatchResponse(
            matched=True,
            skill_name=best_match["name"],
            skill_detail=detail,
            match_reason=best_reason,
        )

    return TriggerMatchResponse(matched=False, match_reason="没有找到匹配的 skill")
