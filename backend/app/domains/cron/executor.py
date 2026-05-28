"""
CronExecutor - 定时调度执行器

提供定时任务的管理能力：
- Job CRUD (create, list, pause, resume, remove, update)
- 手动触发 (trigger/run)
- 调度器状态查看
"""

from typing import Any, Dict, List, Optional
import logging

from app.domains.base import BaseDomainExecutor

logger = logging.getLogger(__name__)


class CronExecutor(BaseDomainExecutor):
    """定时调度执行器"""

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return "定时调度系统：创建、管理定时任务"

    def __init__(self, scheduler=None):
        self.scheduler = scheduler
        # Lazy import to avoid circular dependency
        from app.domains.cron import jobs as cron_jobs
        self._jobs = cron_jobs

    async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action == "create":
            return await self._create(params)
        elif action == "list":
            return await self._list(params)
        elif action == "pause":
            return await self._pause(params)
        elif action == "resume":
            return await self._resume(params)
        elif action == "remove":
            return await self._remove(params)
        elif action == "update":
            return await self._update(params)
        elif action in ("run", "trigger", "run_now"):
            return await self._trigger(params)
        elif action == "status":
            return await self._status()
        elif action == "tick":
            return await self._tick()

        return {"success": False, "error": f"不支持的动作: {action}"}

    async def _create(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建新任务"""
        try:
            prompt = params.get("prompt", "")
            schedule = params.get("schedule")
            name = params.get("name")
            repeat = params.get("repeat")
            deliver = params.get("deliver")
            skill = params.get("skill")
            skills = params.get("skills")

            if not schedule:
                return {"success": False, "error": "schedule is required"}

            if not prompt and not skills:
                return {"success": False, "error": "prompt or skills is required"}

            job = self._jobs.create_job(
                prompt=prompt,
                schedule=schedule,
                name=name,
                repeat=repeat,
                deliver=deliver,
                skill=skill,
                skills=skills,
            )

            return {
                "success": True,
                "job": self._format_job(job),
                "message": f"Cron job '{job['name']}' created"
            }

        except Exception as e:
            logger.error("Failed to create cron job: %s", e)
            return {"success": False, "error": str(e)}

    async def _list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有任务"""
        try:
            include_disabled = params.get("include_disabled", False)
            jobs = self._jobs.list_jobs(include_disabled=include_disabled)
            return {
                "success": True,
                "count": len(jobs),
                "jobs": [self._format_job(j) for j in jobs]
            }
        except Exception as e:
            logger.error("Failed to list cron jobs: %s", e)
            return {"success": False, "error": str(e)}

    async def _pause(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """暂停任务"""
        try:
            job_id = params.get("job_id")
            reason = params.get("reason")

            if not job_id:
                return {"success": False, "error": "job_id is required"}

            job = self._jobs.pause_job(job_id, reason=reason)
            if not job:
                return {"success": False, "error": f"Job '{job_id}' not found"}

            return {"success": True, "job": self._format_job(job)}

        except Exception as e:
            logger.error("Failed to pause cron job: %s", e)
            return {"success": False, "error": str(e)}

    async def _resume(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """恢复任务"""
        try:
            job_id = params.get("job_id")

            if not job_id:
                return {"success": False, "error": "job_id is required"}

            job = self._jobs.resume_job(job_id)
            if not job:
                return {"success": False, "error": f"Job '{job_id}' not found"}

            return {"success": True, "job": self._format_job(job)}

        except Exception as e:
            logger.error("Failed to resume cron job: %s", e)
            return {"success": False, "error": str(e)}

    async def _remove(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """删除任务"""
        try:
            job_id = params.get("job_id")

            if not job_id:
                return {"success": False, "error": "job_id is required"}

            job = self._jobs.get_job(job_id)
            if not job:
                return {"success": False, "error": f"Job '{job_id}' not found"}

            removed = self._jobs.remove_job(job_id)
            if removed:
                return {"success": True, "message": f"Cron job '{job['name']}' removed"}
            return {"success": False, "error": "Failed to remove job"}

        except Exception as e:
            logger.error("Failed to remove cron job: %s", e)
            return {"success": False, "error": str(e)}

    async def _update(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """更新任务"""
        try:
            job_id = params.get("job_id")
            updates = params.get("updates", {})

            if not job_id:
                return {"success": False, "error": "job_id is required"}

            job = self._jobs.update_job(job_id, updates)
            if not job:
                return {"success": False, "error": f"Job '{job_id}' not found"}

            return {"success": True, "job": self._format_job(job)}

        except Exception as e:
            logger.error("Failed to update cron job: %s", e)
            return {"success": False, "error": str(e)}

    async def _trigger(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """手动触发任务"""
        try:
            job_id = params.get("job_id")

            if not job_id:
                return {"success": False, "error": "job_id is required"}

            job = self._jobs.trigger_job(job_id)
            if not job:
                return {"success": False, "error": f"Job '{job_id}' not found"}

            return {"success": True, "job": self._format_job(job)}

        except Exception as e:
            logger.error("Failed to trigger cron job: %s", e)
            return {"success": False, "error": str(e)}

    async def _status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        try:
            running = False
            if self.scheduler:
                running = True

            jobs = self._jobs.list_jobs(include_disabled=True)
            pending = [j for j in jobs if j.get("enabled", True) and j.get("state") == "scheduled"]
            paused = [j for j in jobs if not j.get("enabled", True)]

            return {
                "success": True,
                "running": running,
                "total_jobs": len(jobs),
                "pending_jobs": len(pending),
                "paused_jobs": len(paused),
            }
        except Exception as e:
            logger.error("Failed to get cron status: %s", e)
            return {"success": False, "error": str(e)}

    async def _tick(self) -> Dict[str, Any]:
        """手动触发一次调度检查"""
        try:
            from app.domains.cron.scheduler import tick
            executed = tick(verbose=True)
            return {"success": True, "executed": executed}
        except Exception as e:
            logger.error("Failed to run cron tick: %s", e)
            return {"success": False, "error": str(e)}

    def _format_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """格式化任务输出"""
        repeat = job.get("repeat", {})
        repeat_times = repeat.get("times")
        repeat_completed = repeat.get("completed", 0)

        if repeat_times is None:
            repeat_display = "forever"
        elif repeat_times == 1:
            repeat_display = "once"
        else:
            repeat_display = f"{repeat_completed}/{repeat_times}"

        return {
            "job_id": job["id"],
            "name": job["name"],
            "prompt": job.get("prompt", ""),
            "skill": job.get("skill"),
            "skills": job.get("skills", []),
            "schedule": job.get("schedule_display"),
            "repeat": repeat_display,
            "deliver": job.get("deliver", "local"),
            "next_run_at": job.get("next_run_at"),
            "last_run_at": job.get("last_run_at"),
            "last_status": job.get("last_status"),
            "last_error": job.get("last_error"),
            "enabled": job.get("enabled", True),
            "state": job.get("state", "scheduled"),
            "created_at": job.get("created_at"),
        }

    def get_capabilities(self) -> List[Dict[str, Any]]:
        return [
            {"action": "create", "description": "创建新的定时任务"},
            {"action": "list", "description": "查看所有定时任务"},
            {"action": "pause", "description": "暂停定时任务"},
            {"action": "resume", "description": "恢复已暂停的任务"},
            {"action": "remove", "description": "删除定时任务"},
            {"action": "update", "description": "更新任务配置"},
            {"action": "trigger", "description": "手动触发任务立即执行"},
            {"action": "status", "description": "查看调度器运行状态"},
            {"action": "tick", "description": "手动触发一次调度检查"},
        ]