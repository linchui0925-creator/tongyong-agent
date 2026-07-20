"""
调度系统 - 梦境和技能优化任务的定时调度
"""

from typing import Optional, Callable
from datetime import datetime
import asyncio
import logging
import threading
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.paths import data_path

logger = logging.getLogger(__name__)


class AgentScheduler:
    """Agent任务调度器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化调度器"""
        if not hasattr(self, '_initialized'):
            self.scheduler = AsyncIOScheduler()
            self._initialized = True
            self._running = False
            logger.info("AgentScheduler 初始化完成")
    
    def start(self):
        """启动调度器"""
        if not self._running:
            self.scheduler.start()
            self._running = True
            logger.info("调度器已启动")
    
    def stop(self):
        """停止调度器"""
        if self._running:
            self.scheduler.shutdown(wait=False)
            self._running = False
            logger.info("调度器已停止")
    
    def add_dreaming_job(
        self,
        dreaming_callback: Callable,
        hour: int = 3,
        minute: int = 0
    ):
        """
        添加梦境扫描任务
        
        Args:
            dreaming_callback: 梦境扫描回调函数
            hour: 执行小时（默认凌晨3点）
            minute: 执行分钟
        """
        trigger = CronTrigger(hour=hour, minute=minute)
        
        self.scheduler.add_job(
            dreaming_callback,
            trigger=trigger,
            id='dreaming_sweep',
            name='梦境扫描',
            replace_existing=True
        )
        
        logger.info(f"梦境扫描任务已添加: 每天 {hour:02d}:{minute:02d}")
    
    def add_skill_refinement_job(
        self,
        refinement_callback: Callable,
        hour: int = 2,
        minute: int = 0
    ):
        """
        添加技能优化任务
        
        Args:
            refinement_callback: 技能优化回调函数
            hour: 执行小时（默认凌晨2点）
            minute: 执行分钟
        """
        trigger = CronTrigger(hour=hour, minute=minute)
        
        self.scheduler.add_job(
            refinement_callback,
            trigger=trigger,
            id='skill_refinement',
            name='技能优化',
            replace_existing=True
        )
        
        logger.info(f"技能优化任务已添加: 每天 {hour:02d}:{minute:02d}")
    
    def add_cleanup_job(
        self,
        cleanup_callback: Callable,
        hour: int = 4,
        minute: int = 0
    ):
        """
        添加清理任务
        
        Args:
            cleanup_callback: 清理回调函数
            hour: 执行小时（默认凌晨4点）
            minute: 执行分钟
        """
        trigger = CronTrigger(hour=hour, minute=minute)
        
        self.scheduler.add_job(
            cleanup_callback,
            trigger=trigger,
            id='cleanup',
            name='系统清理',
            replace_existing=True
        )
        
        logger.info(f"清理任务已添加: 每天 {hour:02d}:{minute:02d}")
    
    def remove_job(self, job_id: str):
        """
        移除任务
        
        Args:
            job_id: 任务ID
        """
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"任务已移除: {job_id}")
        except Exception as e:
            logger.warning(f"移除任务失败: {job_id}, {e}")
    
    def get_jobs(self):
        """获取所有任务"""
        return self.scheduler.get_jobs()
    
    def is_running(self) -> bool:
        """检查调度器是否运行"""
        return self._running


_scheduler_instance = None


def get_scheduler() -> AgentScheduler:
    """获取调度器单例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = AgentScheduler()
    return _scheduler_instance


async def scheduled_skill_refinement():
    """定时执行的技能优化"""
    try:
        from app.skills import SkillManager
        
        manager = SkillManager(db_path=data_path("tongyong.db"))
        
        skills = await manager.get_all_skills()
        
        refined_count = 0
        for skill in skills:
            if skill.usage_count >= manager.refinement_threshold:
                recent_logs = await manager.get_recent_usage_logs(skill.id, limit=10)
                failures = [log for log in recent_logs if not log.success]
                
                if len(failures) > 3:
                    await manager._trigger_refinement(skill.id)
                    refined_count += 1
        
        logger.info(f"定时技能优化完成: 优化了 {refined_count} 个技能")
        
    except Exception as e:
        logger.error(f"定时技能优化失败: {e}", exc_info=True)


async def scheduled_cleanup():
    """定时执行的系统清理"""
    try:
        import sqlite3
        import os
        
        db_path = data_path("tongyong.db")
        
        if not os.path.exists(db_path):
            return
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM dream_candidates WHERE status = 'expired' AND created_at < datetime('now', '-30 days')")
        expired_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM skill_usage_log WHERE created_at < datetime('now', '-90 days')")
        logs_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM tool_audit_log WHERE created_at < datetime('now', '-180 days')")
        audit_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM tool_approvals WHERE status IN ('approved', 'rejected', 'expired') AND created_at < datetime('now', '-30 days')")
        approvals_deleted = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        logger.info(f"定时清理完成: 删除 {expired_deleted} 个过期候选, {logs_deleted} 条使用日志, {audit_deleted} 条审计日志, {approvals_deleted} 个审批记录")

        # W5-7: runtime trace 保留期清理 (独立 runtime_trace.db, 失败不影响主清理)
        try:
            import time as _time
            from app.config import settings as _settings
            from app.core.runtime import trace as _rt
            _store = _rt.get_store()
            if _store is not None:
                _days = getattr(_settings, "runtime_trace_retention_days", 14)
                _cutoff = _time.time() - _days * 86400
                _purged = _store.purge_older_than(_cutoff)
                logger.info(f"runtime trace 清理: 删除 {_purged} 条过期 trace (保留 {_days} 天)")
        except Exception as _rt_err:
            logger.debug(f"runtime trace 清理跳过: {_rt_err}")

    except Exception as e:
        logger.error(f"定时清理失败: {e}", exc_info=True)
