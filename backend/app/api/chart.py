"""
Chart API 桩 - 占位路由，待业务侧接入图表生成能力。
"""
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def root():
    return {"message": "Chart API"}