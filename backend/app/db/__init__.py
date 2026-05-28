"""
数据库模块 - 包含数据库迁移脚本
"""

from app.db.migrations.m001_initial_schema import run_migration, rollback_migration

__all__ = ['run_migration', 'rollback_migration']
