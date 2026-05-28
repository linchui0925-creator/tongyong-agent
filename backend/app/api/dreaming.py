"""
Dreaming API - 梦境系统管理端点
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dreaming", tags=["dreaming"])


class DreamingTriggerRequest(BaseModel):
    """触发梦境请求"""
    force: bool = False


class DreamingConfigUpdate(BaseModel):
    """更新配置请求"""
    enabled: Optional[bool] = None
    frequency: Optional[str] = None
    lookback_days: Optional[int] = None
    min_score: Optional[float] = None
    min_recall_count: Optional[int] = None
    min_unique_queries: Optional[int] = None


@router.get("/status")
async def get_dreaming_status() -> Dict[str, Any]:
    """
    获取梦境系统状态
    
    Returns:
        Dict: 梦境系统状态信息
    """
    try:
        from app.dreaming import DreamingEngine
        
        engine = DreamingEngine(
            memory_storage=None,
            llm=None
        )
        
        status = await engine.get_status()
        
        return status
        
    except Exception as e:
        logger.error(f"获取梦境状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trigger")
async def trigger_dreaming(request: DreamingTriggerRequest) -> Dict[str, Any]:
    """
    手动触发梦境扫描
    
    Args:
        request: 触发请求
        
    Returns:
        Dict: 扫描结果
    """
    try:
        from app.dreaming import DreamingEngine
        
        engine = DreamingEngine(
            memory_storage=None,
            llm=None
        )
        
        if not engine.config.enabled and not request.force:
            return {
                "status": "skipped",
                "message": "梦境系统未启用，请先启用或使用 force=true 强制执行"
            }
        
        result = await engine.run_full_sweep()
        
        return result
        
    except Exception as e:
        logger.error(f"触发梦境失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_dreaming_config() -> Dict[str, Any]:
    """
    获取梦境系统配置
    
    Returns:
        Dict: 当前配置
    """
    try:
        from app.dreaming import DreamingConfig
        
        config = DreamingConfig()
        
        return config.to_dict()
        
    except Exception as e:
        logger.error(f"获取配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
async def update_dreaming_config(request: DreamingConfigUpdate) -> Dict[str, Any]:
    """
    更新梦境系统配置
    
    Args:
        request: 配置更新请求
        
    Returns:
        Dict: 更新后的配置
    """
    try:
        from app.dreaming import DreamingConfig
        
        config = DreamingConfig()
        
        if request.enabled is not None:
            config.enabled = request.enabled
        
        if request.frequency is not None:
            config.frequency = request.frequency
        
        if request.lookback_days is not None:
            config.lookback_days = request.lookback_days
        
        if request.min_score is not None:
            config.min_score = request.min_score
        
        if request.min_recall_count is not None:
            config.min_recall_count = request.min_recall_count
        
        if request.min_unique_queries is not None:
            config.min_unique_queries = request.min_unique_queries
        
        config.save_to_db()
        
        return {
            "status": "success",
            "message": "配置已更新",
            "config": config.to_dict()
        }
        
    except Exception as e:
        logger.error(f"更新配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candidates")
async def get_dreaming_candidates(
    status: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    获取梦境候选列表
    
    Args:
        status: 过滤状态
        limit: 返回数量
        
    Returns:
        Dict: 候选列表
    """
    try:
        from app.dreaming.signals import DreamCandidate, CandidateStatus
        
        try:
            from app.dreaming.engine import DreamingEngine
            engine = DreamingEngine(memory_storage=None, llm=None)
            candidates = await engine._get_pending_candidates()
            
            if status:
                candidates = [c for c in candidates if c.status.value == status]
            
            return {
                "total": len(candidates),
                "candidates": [c.to_dict() for c in candidates[:limit]]
            }
        except:
            return {
                "total": 0,
                "candidates": []
            }
        
    except Exception as e:
        logger.error(f"获取候选失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backfill/preview")
async def preview_backfill(
    path: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=30)
) -> Dict[str, Any]:
    """
    预览 REM 回填候选

    Args:
        path: 指定日记文件路径（可选）
        days: 回溯天数（默认7天）

    Returns:
        Dict: 候选列表
    """
    try:
        from app.dreaming.backfill import REMBackfill
        backfill = REMBackfill()
        candidates = backfill.preview_diary(path, days)
        return {
            "total": len(candidates),
            "candidates": candidates,
        }
    except Exception as e:
        logger.error(f"预览回填失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backfill/run")
async def run_backfill(
    path: Optional[str] = None,
    days: int = 7,
    to_short_term: bool = False
) -> Dict[str, Any]:
    """
    执行 REM 回填

    Args:
        path: 指定日记文件路径（可选）
        days: 回溯天数
        to_short_term: 是否暂存到短期存储（默认写入 DREAMS.md）

    Returns:
        Dict: 回填结果
    """
    try:
        from app.dreaming.backfill import REMBackfill
        backfill = REMBackfill()

        if to_short_term:
            count, output = backfill.stage_short_term(path, days)
            return {
                "status": "completed",
                "entries": count,
                "output": output,
                "target": "short_term",
            }
        else:
            count, msg = backfill.backfill_to_dreams(path, days)
            return {
                "status": "completed" if count > 0 else "skipped",
                "entries": count,
                "message": msg,
                "target": "dreams_md",
            }
    except Exception as e:
        logger.error(f"执行回填失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backfill/rollback")
async def rollback_backfill(
    target: str = "dreams",
    filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    回滚 REM 回填

    Args:
        target: "dreams" 或 "short_term"
        filename: 指定文件名（仅 short_term）

    Returns:
        Dict: 回滚结果
    """
    try:
        from app.dreaming.backfill import REMBackfill
        backfill = REMBackfill()

        if target == "dreams":
            count = backfill.rollback_dreams()
        else:
            count = backfill.rollback_short_term(filename)

        return {
            "status": "completed",
            "removed": count,
        }
    except Exception as e:
        logger.error(f"回滚回填失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diary")
async def list_diary(days: int = Query(7, ge=1, le=30)) -> Dict[str, Any]:
    """
    获取近期日记列表

    Args:
        days: 回溯天数

    Returns:
        Dict: 日记文件列表
    """
    try:
        from app.dreaming.backfill import REMBackfill
        backfill = REMBackfill()
        stats = backfill.get_stats()
        return stats
    except Exception as e:
        logger.error(f"获取日记列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
