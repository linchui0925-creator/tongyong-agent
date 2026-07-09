"""
扣子技能市场API接口
"""
from fastapi import APIRouter, HTTPException, Query
from app.services.coze_skills import search_skills, get_skill_detail, install_skill
from typing import Optional

router = APIRouter(prefix="/api/skills/coze", tags=["coze-skills"])


@router.get("/search")
async def search(
    keyword: Optional[str] = Query("", description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, description="每页数量")
):
    """搜索扣子公开技能"""
    try:
        return await search_skills(keyword, page, page_size)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.get("/{skill_id}")
async def detail(skill_id: str):
    """获取技能详情"""
    res = await get_skill_detail(skill_id)
    if not res["success"]:
        raise HTTPException(status_code=404, detail=res["message"])
    return res


@router.post("/{skill_id}/install")
async def install(skill_id: str):
    """安装技能到本地"""
    res = await install_skill(skill_id)
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return res
