"""
定时调度领域模块 - Cron System

提供定时任务管理能力：
- Job CRUD: create, list, pause, resume, remove, update
- 手动触发: trigger/run
- 调度器: tick() 执行引擎

参考 hermes-agent cron 系统设计:
- JSON 文件存储 (~/.tongyong/cron/jobs.json)
- 支持多种调度格式: duration, interval, cron, ISO timestamp
- 漏跑恢复机制
- 文件锁防止并发
"""

from app.domains.cron.executor import CronExecutor
from app.domains.cron import jobs
from app.domains.cron import scheduler

__all__ = [
    "CronExecutor",
    "jobs",
    "scheduler",
]