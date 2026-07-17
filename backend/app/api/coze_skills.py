"""扣子技能市场API"""
from fastapi import APIRouter, HTTPException, Query, Body
from app.services.coze_skills import (
    search_skills, get_skill_detail, install_skill, translate_skill,
    SKILLS_DIR, save_coze_config, get_coze_config, load_community_skills
)
from typing import Optional
from pathlib import Path
from pydantic import BaseModel

router = APIRouter(prefix="/api/skills/coze", tags=["coze-skills"])

class CozeConfigReq(BaseModel):
    coze_cookie: str = ""
    enable_community: bool = False

def _find_skill(name: str) -> Optional[Path]:
    if not SKILLS_DIR.exists(): return None
    for d in SKILLS_DIR.iterdir():
        if not d.is_dir(): continue
        p = d / name / "SKILL.md"
        if p.exists(): return p
    return None

@router.get("/config")
async def cfg_get(): return await get_coze_config()

@router.post("/config")
async def cfg_set(req: CozeConfigReq): return await save_coze_config(req.coze_cookie, req.enable_community)

@router.post("/community/load")
async def load_community(force: bool = Query(False)):
    """手动触发加载社区技能"""
    skills = await load_community_skills(force)
    return {"success": True, "count": len(skills), "message": f"已加载{len(skills)}个社区技能"}

@router.get("/search")
async def search(
    keyword: Optional[str] = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=50),
    category: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("hot"),
    source_filter: Optional[str] = Query("all"),
    load_community: bool = Query(False)
):
    try:
        return await search_skills(keyword, page, page_size, category, sort_by, source_filter, load_community)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")

@router.get("/categories")
async def cats():
    from app.services.coze_skills_builtin import FULL_SKILLS
    cfg = await get_coze_config()
    c = sorted({s["category"] for s in FULL_SKILLS})
    if cfg.get("enable_community"): c.append("社区技能")
    if cfg.get("official_available"): c.append("官方市场")
    return {"success": True, "categories": ["全部"] + c}

@router.get("/{skill_id}")
async def detail(skill_id: str):
    res = await get_skill_detail(skill_id)
    if not res["success"]: raise HTTPException(status_code=404, detail=res["message"])
    return res

@router.post("/{skill_id}/translate")
async def translate(skill_id: str, target_lang: str = Query("英文")):
    res = await translate_skill(skill_id, target_lang)
    if not res["success"]: raise HTTPException(status_code=400, detail=res["message"])
    return res

@router.post("/{skill_id}/install")
async def install(skill_id: str, translate_to_lang: Optional[str] = Query(None)):
    res = await install_skill(skill_id, translate_to_lang)
    if not res["success"]: raise HTTPException(status_code=400, detail=res["message"])
    return res

@router.get("/installed/{skill_dir}/body")
async def get_body(skill_dir: str):
    if ".." in skill_dir or "/" in skill_dir or "\\" in skill_dir:
        raise HTTPException(status_code=400, detail="非法路径")
    p = _find_skill(skill_dir)
    if not p: raise HTTPException(status_code=404, detail="未安装")
    try:
        import yaml
        content = p.read_text(encoding="utf-8")
        meta = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts)>=3:
                try: meta = yaml.safe_load(parts[1]) or {}
                except: pass
        return {"success": True, "name": meta.get("name", skill_dir), "body": content, "metadata": meta}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")
