"""
Skills API - 技能管理（Hermes 平文件 + 用户上传）

支持：
- 列表/查看/删除技能（已有）
- 用户上传 skill（zip、md、txt、json）
- 上传后自动解析并创建 skill
"""

import os
import re
import zipfile
import tempfile
import shutil
import logging
from pathlib import Path
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
import yaml

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
    """获取技能列表"""
    if not _skill_manager:
        return {"skills": [], "total": 0}

    skills = _skill_manager.list_skills()
    result = []
    for s in skills:
        detail = _skill_manager.view_skill(s["name"])
        result.append({
            "id": s["name"],
            "name": s["name"],
            "content": detail["body"][:200] if detail and detail.get("body") else s.get("description", ""),
            "category": s.get("category", "general"),
            "usage_count": 0,
            "success_rate": 100.0,
            "version": _safe_float(s.get("version")),
            "trigger_conditions": [],
            "execution_steps": [],
        })
    return {"skills": result, "total": len(result)}


@router.get("/categories")
async def list_categories():
    """获取可用的 skill 分类"""
    return {"categories": _skill_categories}


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

ALLOWED_EXTENSIONS = {
    ".zip", ".md", ".txt", ".json", ".yaml", ".yml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".sh", ".bash", ".zsh",
    ".html", ".css", ".sql",
}


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


# ── 解析函数 ──────────────────────────────────

def _parse_uploaded_file(content_bytes: bytes, ext: str, override_name: Optional[str] = None) -> Dict:
    """从上传内容中提取 skill 信息"""
    result = {
        "name": override_name,  # 用户显式提供的 name 优先
        "description": "",
        "steps": [],
        "pitfalls": None,
        "triggers": [],
        "platforms": [],
        "body_text": "",
        "references": {},
        "warnings": [],
    }

    if ext == ".zip":
        result.update(_parse_zip(content_bytes))
    elif ext in (".json",):
        result.update(_parse_json(content_bytes))
    elif ext in (".yaml", ".yml"):
        result.update(_parse_yaml(content_bytes))
    else:
        result.update(_parse_text(content_bytes.decode("utf-8", errors="replace")))
        # _parse_text 返回新 dict，update 会覆盖 name，所以保留用户提供的 override_name
        if override_name:
            result["name"] = override_name
    # 始终保留用户显式提供的 name
    if override_name:
        result["name"] = override_name

    # 自动提取 trigger
    if result["body_text"] and not result["triggers"]:
        result["triggers"] = _extract_triggers(result["body_text"])

    return result


def _parse_zip(content_bytes: bytes) -> Dict:
    result = {"warnings": []}
    refs = {}
    body_texts = []

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "upload.zip")
            with open(zip_path, "wb") as f:
                f.write(content_bytes)

            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    fname = os.path.basename(info.filename)
                    if fname.startswith(".") or fname.startswith("_"):
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in ALLOWED_EXTENSIONS:
                        continue

                    data = zf.read(info.filename).decode("utf-8", errors="replace")

                    # 优先读取 README/SKILL 等说明文件
                    base_lower = os.path.basename(info.filename).lower()
                    if base_lower in ("readme.md", "readme.txt", "skill.md", "skill.txt",
                                      "readme", "skill"):
                        body_texts.append(data)
                        # 用户显式提供的 name 优先，否则从文件名推断
                        if not result.get("name"):
                            result["name"] = _derive_name_from_content(data)

                    # 收集引用文件
                    if ext in (".md", ".txt", ".py", ".js", ".ts", ".sh", ".json", ".yaml"):
                        refs[fname] = data[:2000]  # 限制大小

        result["references"] = refs
        if body_texts:
            result["body_text"] = "\n\n".join(body_texts)
    except Exception as e:
        result["warnings"].append(f"ZIP 解压失败: {e}，将作为普通文本处理")
        result["body_text"] = content_bytes.decode("utf-8", errors="replace")

    # 从 body_text 提取 steps/description
    if result.get("body_text"):
        result.update(_parse_text(result["body_text"]))

    return result


def _parse_json(content_bytes: bytes) -> Dict:
    import json
    try:
        data = json.loads(content_bytes.decode("utf-8", errors="replace"))
        desc = data.get("description", "")
        body_text = data.get("content") or data.get("body") or desc or content_bytes.decode("utf-8", errors="replace")
        return {
            "name": data.get("name"),
            "description": desc,
            "steps": data.get("steps", data.get("execution_steps", [])),
            "pitfalls": data.get("pitfalls", data.get("warnings")),
            "triggers": data.get("triggers", data.get("trigger_conditions", [])),
            "platforms": data.get("platforms", []),
            "body_text": body_text,
        }
    except Exception as e:
        return {"warnings": [f"JSON 解析失败: {e}"], "body_text": content_bytes.decode("utf-8", errors="replace")}


def _parse_yaml(content_bytes: bytes) -> Dict:
    try:
        data = yaml.safe_load(content_bytes.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            desc = data.get("description", "")
            body_text = data.get("content") or data.get("body") or desc or content_bytes.decode("utf-8", errors="replace")
            return {
                "name": data.get("name"),
                "description": desc,
                "steps": data.get("steps", data.get("execution_steps", [])),
                "pitfalls": data.get("pitfalls", data.get("warnings")),
                "triggers": data.get("triggers", data.get("trigger_conditions", [])),
                "platforms": data.get("platforms", []),
                "body_text": body_text,
            }
        return {"body_text": content_bytes.decode("utf-8", errors="replace")}
    except Exception as e:
        return {"warnings": [f"YAML 解析失败: {e}"], "body_text": content_bytes.decode("utf-8", errors="replace")}


def _parse_text(text: str) -> Dict:
    result = {}
    result["body_text"] = text

    # 尝试从 frontmatter 提取
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                # name 以调用方传入的 override_name 为准，不覆盖
                if not result.get("name"):
                    result["name"] = meta.get("name")
                result["description"] = meta.get("description", "")
                result["triggers"] = meta.get("triggers", [])
                result["platforms"] = meta.get("platforms", [])
            except Exception:
                pass

    # 从 body 中提取 steps
    lines = text.split("\n")
    steps = []
    for line in lines:
        stripped = line.strip()
        # 匹配 1. 2. 或 - 或 numbered list
        m = re.match(r"^\d+[.)]\s+(.+)", stripped)
        if m:
            steps.append(m.group(1).strip())
        elif stripped.startswith("- ") and len(steps) > 0:
            steps.append(stripped[2:].strip())

    if steps:
        result["steps"] = steps

    # 尝试提取 description（取第一段非空文字）
    if not result.get("description"):
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and len(stripped) > 10:
                result["description"] = stripped[:200]
                break

    return result


def _extract_steps_from_text(text: str) -> List[str]:
    lines = text.split("\n")
    steps = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^\d+[.)]\s+(.+)", stripped)
        if m:
            steps.append(m.group(1).strip())
        elif re.match(r"^[-*]\s+(.+)", stripped) and len(steps) > 0:
            steps.append(re.sub(r"^[-*]\s+", "", stripped).strip())
    return steps[:20]  # 最多 20 步


def _extract_triggers(text: str) -> List[str]:
    """从文本中提取可能的 trigger 关键词"""
    triggers = set()
    # 匹配代码块外的关键词模式
    # 提取带引号的关键词或加粗文本
    patterns = [
        r'\*\*([^*]+)\*\*',
        r'`([^`]+)`',
        r'触发[:：]\s*([^\n]+)',
        r'触发条件[:：]\s*([^\n]+)',
        r'当.*时.*执行',
        r'(?:use|apply|run|execute)\s+([a-zA-Z\s]+)',
    ]
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            word = m.group(1 or 0).strip().lower()
            if word and 2 < len(word) < 50:
                triggers.add(word[:80])
    return sorted(list(triggers))[:10]


def _extract_keywords(text: str) -> List[str]:
    """从描述中提取关键词"""
    # 去除 markdown 符号
    clean = re.sub(r'[#*`>\[\]]', ' ', text.lower())
    words = re.findall(r'[a-zA-Z]{4,}', clean)
    # 统计词频，取 top 10
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq.keys(), key=lambda x: freq[x], reverse=True)[:10]


def _derive_name_from_content(text: str) -> Optional[str]:
    """从内容中推断 skill 名称"""
    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        # # SkillName 格式
        m = re.match(r"^#+\s*(.+)", stripped)
        if m:
            name = m.group(1).strip().split("\n")[0].strip()
            name = re.sub(r"[^a-zA-Z0-9\s\-]", "", name)[:60]
            if name:
                return name
        # "name: xxx" 格式
        m2 = re.match(r"^\s*name:\s*(.+)", stripped, re.IGNORECASE)
        if m2:
            name = m2.group(1).strip()[:60]
            if name:
                return name
    return None
