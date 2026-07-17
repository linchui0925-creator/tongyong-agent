"""
数据库迁移脚本 - 阶段一：基础设施表结构

该脚本创建支持 Dreaming、Skill 和 ToolHarness 功能的基础数据库表
"""

import sqlite3
import os
import logging
from datetime import datetime
from app.paths import data_path

logger = logging.getLogger(__name__)

MIGRATION_VERSION = "001"
MIGRATION_NAME = "initial_schema_phase1"


def get_connection(db_path: str) -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn: sqlite3.Connection):
    """创建所有基础表"""
    cursor = conn.cursor()
    
    # ==================== Dreaming 相关表 ====================
    
    # 候选记忆表 - 存储待评估的记忆候选
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dream_candidates (
            id TEXT PRIMARY KEY,
            source_session_id TEXT NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT NOT NULL,
            concept_tags TEXT,
            recall_count INTEGER DEFAULT 0,
            unique_query_count INTEGER DEFAULT 0,
            query_diversity_score FLOAT DEFAULT 0.0,
            relevance_score FLOAT DEFAULT 0.0,
            recency_score FLOAT DEFAULT 0.0,
            consolidation_score FLOAT DEFAULT 0.0,
            conceptual_richness_score FLOAT DEFAULT 0.0,
            total_score FLOAT DEFAULT 0.0,
            phase_signal_light FLOAT DEFAULT 0.0,
            phase_signal_rem FLOAT DEFAULT 0.0,
            final_score FLOAT DEFAULT 0.0,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            promoted_at TEXT,
            FOREIGN KEY (source_session_id) REFERENCES sessions(id)
        )
    """)
    
    # 阶段信号表 - 存储梦境各阶段的强化信号
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS phase_signals (
            id TEXT PRIMARY KEY,
            sweep_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            reinforcement_value FLOAT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    # 梦境配置表 - 存储 Dreaming 系统配置
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dreaming_config (
            id TEXT PRIMARY KEY,
            config_key TEXT NOT NULL UNIQUE,
            config_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    # ==================== Skill 相关表 ====================
    
    # 技能表 - 存储 Agent 生成的技能
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            trigger_conditions TEXT,
            execution_steps TEXT,
            expected_outcome TEXT,
            usage_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            success_rate FLOAT DEFAULT 0.0,
            version INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)
    
    # 技能使用记录表 - 记录技能的使用情况
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_usage_log (
            id TEXT PRIMARY KEY,
            skill_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            trigger_context TEXT,
            execution_result TEXT,
            success INTEGER DEFAULT 0,
            feedback TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (skill_id) REFERENCES skills(id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    
    # ==================== User Model 相关表 ====================
    
    # 用户模型表 - 存储用户偏好和建模数据
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_models (
            id TEXT PRIMARY KEY,
            user_identifier TEXT NOT NULL,
            model_type TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence FLOAT DEFAULT 1.0,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(user_identifier, model_type, key)
        )
    """)
    
    # ==================== ToolHarness 相关表 ====================
    
    # 工具注册表 - 存储可用工具的元数据
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool_registry (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            category TEXT,
            permission_level INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            requires_approval INTEGER DEFAULT 0,
            approval_patterns TEXT,
            config_schema TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)
    
    # 工具权限表 - 存储角色与工具的权限关系
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool_permissions (
            id TEXT PRIMARY KEY,
            tool_id TEXT NOT NULL,
            role TEXT NOT NULL,
            granted INTEGER DEFAULT 1,
            conditions TEXT,
            granted_by TEXT,
            granted_at TEXT,
            expires_at TEXT,
            FOREIGN KEY (tool_id) REFERENCES tool_registry(id),
            UNIQUE(tool_id, role)
        )
    """)
    
    # 工具调用日志表 - 记录所有工具调用
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool_audit_log (
            id TEXT PRIMARY KEY,
            tool_id TEXT NOT NULL,
            session_id TEXT,
            user_id TEXT,
            action TEXT NOT NULL,
            parameters TEXT,
            result TEXT,
            error_message TEXT,
            risk_level TEXT,
            approval_status TEXT,
            approved_by TEXT,
            approved_at TEXT,
            execution_time_ms INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tool_id) REFERENCES tool_registry(id)
        )
    """)
    
    # 工具审批表 - 管理待审批的操作
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool_approvals (
            id TEXT PRIMARY KEY,
            tool_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            parameters TEXT NOT NULL,
            risk_assessment TEXT,
            status TEXT DEFAULT 'pending',
            approval_mode TEXT DEFAULT 'manual',
            expires_at TEXT,
            approved_by TEXT,
            approved_at TEXT,
            rejection_reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tool_id) REFERENCES tool_registry(id)
        )
    """)
    
    # ==================== 创建索引 ====================
    
    # Dreaming 相关索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dream_candidates_status ON dream_candidates(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dream_candidates_session ON dream_candidates(source_session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase_signals_sweep ON phase_signals(sweep_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase_signals_entry ON phase_signals(entry_id)")
    
    # Skill 相关索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_usage_skill ON skill_usage_log(skill_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_usage_session ON skill_usage_log(session_id)")
    
    # User Model 索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_models_identifier ON user_models(user_identifier)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_models_type ON user_models(model_type)")
    
    # ToolHarness 相关索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_registry_name ON tool_registry(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_registry_category ON tool_registry(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_permissions_tool ON tool_permissions(tool_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_permissions_role ON tool_permissions(role)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_log_tool ON tool_audit_log(tool_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_log_session ON tool_audit_log(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_log_created ON tool_audit_log(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_approvals_status ON tool_approvals(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_approvals_session ON tool_approvals(session_id)")
    
    conn.commit()
    logger.info("所有基础表创建完成")


def insert_default_config(conn: sqlite3.Connection):
    """插入默认配置"""
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    # Dreaming 默认配置
    dreaming_defaults = [
        ("dreaming_enabled", "false"),
        ("dreaming_frequency", "0 3 * * *"),
        ("lookback_days", "7"),
        ("min_score", "0.8"),
        ("min_recall_count", "3"),
        ("min_unique_queries", "3"),
        ("relevance_weight", "0.30"),
        ("frequency_weight", "0.24"),
        ("query_diversity_weight", "0.15"),
        ("recency_weight", "0.15"),
        ("consolidation_weight", "0.10"),
        ("conceptual_richness_weight", "0.06"),
    ]
    
    for key, value in dreaming_defaults:
        cursor.execute("""
            INSERT OR IGNORE INTO dreaming_config (id, config_key, config_value, updated_at)
            VALUES (?, ?, ?, ?)
        """, (f"cfg_{key}", key, value, now))
    
    # Skill 默认配置
    cursor.execute("""
        INSERT OR IGNORE INTO dreaming_config (id, config_key, config_value, updated_at)
        VALUES (?, ?, ?, ?)
    """, ("cfg_skills_enabled", "skills_enabled", "false", now))
    
    cursor.execute("""
        INSERT OR IGNORE INTO dreaming_config (id, config_key, config_value, updated_at)
        VALUES (?, ?, ?, ?)
    """, ("cfg_skill_refinement_threshold", "skill_refinement_threshold", "10", now))
    
    # ToolHarness 默认配置
    tool_harness_defaults = [
        ("tool_harness_enabled", "false"),
        ("approval_mode", "manual"),
        ("cli_allowed_commands", "ls,cat,grep,find,git,npm,pip,python,python3,node,cargo,make"),
        ("cli_default_timeout", "30"),
        ("cli_max_output_lines", "1000"),
    ]
    
    for key, value in tool_harness_defaults:
        cursor.execute("""
            INSERT OR IGNORE INTO dreaming_config (id, config_key, config_value, updated_at)
            VALUES (?, ?, ?, ?)
        """, (f"cfg_{key}", key, value, now))
    
    conn.commit()
    logger.info("默认配置插入完成")


def insert_default_tools(conn: sqlite3.Connection):
    """插入默认工具注册"""
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    default_tools = [
        {
            "id": "tool_file_read",
            "name": "file_read",
            "description": "读取文件内容",
            "category": "file",
            "permission_level": 0,  # read
            "enabled": 1,
            "requires_approval": 0,
        },
        {
            "id": "tool_file_write",
            "name": "file_write",
            "description": "写入文件内容",
            "category": "file",
            "permission_level": 1,  # write
            "enabled": 1,
            "requires_approval": 0,
        },
        {
            "id": "tool_shell",
            "name": "shell",
            "description": "执行Shell命令",
            "category": "system",
            "permission_level": 2,  # execute
            "enabled": 1,
            "requires_approval": 1,  # 需要审批
        },
        {
            "id": "tool_web_search",
            "name": "web_search",
            "description": "网络搜索",
            "category": "network",
            "permission_level": 0,  # read
            "enabled": 1,
            "requires_approval": 0,
        },
        {
            "id": "tool_web_fetch",
            "name": "web_fetch",
            "description": "获取网页内容",
            "category": "network",
            "permission_level": 0,  # read
            "enabled": 1,
            "requires_approval": 0,
        },
        {
            "id": "tool_code_interpreter",
            "name": "code_interpreter",
            "description": "Python代码执行",
            "category": "system",
            "permission_level": 2,  # execute
            "enabled": 1,
            "requires_approval": 1,
        },
        {
            "id": "tool_database_query",
            "name": "database_query",
            "description": "数据库查询",
            "category": "database",
            "permission_level": 0,  # read
            "enabled": 1,
            "requires_approval": 0,
        },
    ]
    
    for tool in default_tools:
        cursor.execute("""
            INSERT OR IGNORE INTO tool_registry 
            (id, name, description, category, permission_level, enabled, requires_approval, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tool["id"],
            tool["name"],
            tool["description"],
            tool["category"],
            tool["permission_level"],
            tool["enabled"],
            tool["requires_approval"],
            now,
            now
        ))
    
    # 设置默认角色权限
    default_permissions = [
        # Owner 拥有所有工具权限
        ("perm_owner_file_read", "tool_file_read", "owner", 1),
        ("perm_owner_file_write", "tool_file_write", "owner", 1),
        ("perm_owner_shell", "tool_shell", "owner", 1),
        ("perm_owner_web_search", "tool_web_search", "owner", 1),
        ("perm_owner_web_fetch", "tool_web_fetch", "owner", 1),
        ("perm_owner_code_interpreter", "tool_code_interpreter", "owner", 1),
        ("perm_owner_database_query", "tool_database_query", "owner", 1),
        
        # Admin 拥有大部分工具权限（执行命令需要审批）
        ("perm_admin_file_read", "tool_file_read", "admin", 1),
        ("perm_admin_file_write", "tool_file_write", "admin", 1),
        ("perm_admin_shell", "tool_shell", "admin", 1),
        ("perm_admin_web_search", "tool_web_search", "admin", 1),
        ("perm_admin_web_fetch", "tool_web_fetch", "admin", 1),
        ("perm_admin_code_interpreter", "tool_code_interpreter", "admin", 1),
        ("perm_admin_database_query", "tool_database_query", "admin", 1),
        
        # User 拥有只读和部分写入权限
        ("perm_user_file_read", "tool_file_read", "user", 1),
        ("perm_user_file_write", "tool_file_write", "user", 1),
        ("perm_user_shell", "tool_shell", "user", 0),  # 无权限
        ("perm_user_web_search", "tool_web_search", "user", 1),
        ("perm_user_web_fetch", "tool_web_fetch", "user", 1),
        ("perm_user_code_interpreter", "tool_code_interpreter", "user", 0),  # 无权限
        ("perm_user_database_query", "tool_database_query", "user", 1),
        
        # Guest 只有只读权限
        ("perm_guest_file_read", "tool_file_read", "guest", 1),
        ("perm_guest_file_write", "tool_file_write", "guest", 0),  # 无权限
        ("perm_guest_shell", "tool_shell", "guest", 0),  # 无权限
        ("perm_guest_web_search", "tool_web_search", "guest", 1),
        ("perm_guest_web_fetch", "tool_web_fetch", "guest", 1),
        ("perm_guest_code_interpreter", "tool_code_interpreter", "guest", 0),  # 无权限
        ("perm_guest_database_query", "tool_database_query", "guest", 0),  # 无权限
    ]
    
    for perm in default_permissions:
        cursor.execute("""
            INSERT OR IGNORE INTO tool_permissions
            (id, tool_id, role, granted, granted_at)
            VALUES (?, ?, ?, ?, ?)
        """, (perm[0], perm[1], perm[2], perm[3], now))
    
    conn.commit()
    logger.info("默认工具注册完成")


def run_migration(db_path: str = data_path("tongyong.db")):
    """运行迁移"""
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "./data", exist_ok=True)
    
    conn = get_connection(db_path)
    
    try:
        logger.info(f"开始执行迁移: {MIGRATION_NAME}")
        create_tables(conn)
        insert_default_config(conn)
        insert_default_tools(conn)
        logger.info(f"迁移执行完成: {MIGRATION_NAME}")
        
        return True
    except Exception as e:
        logger.error(f"迁移执行失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def rollback_migration(db_path: str = data_path("tongyong.db")):
    """回滚迁移"""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    try:
        logger.info(f"开始回滚迁移: {MIGRATION_NAME}")
        
        # 删除所有新增的表（按照依赖顺序）
        cursor.execute("DROP TABLE IF EXISTS tool_approvals")
        cursor.execute("DROP TABLE IF EXISTS tool_audit_log")
        cursor.execute("DROP TABLE IF EXISTS tool_permissions")
        cursor.execute("DROP TABLE IF EXISTS tool_registry")
        cursor.execute("DROP TABLE IF EXISTS user_models")
        cursor.execute("DROP TABLE IF EXISTS skill_usage_log")
        cursor.execute("DROP TABLE IF EXISTS skills")
        cursor.execute("DROP TABLE IF EXISTS dreaming_config")
        cursor.execute("DROP TABLE IF EXISTS phase_signals")
        cursor.execute("DROP TABLE IF EXISTS dream_candidates")
        
        conn.commit()
        logger.info(f"回滚完成: {MIGRATION_NAME}")
        
        return True
    except Exception as e:
        logger.error(f"回滚失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    db_path = sys.argv[1] if len(sys.argv) > 1 else data_path("tongyong.db")
    
    if len(sys.argv) > 2 and sys.argv[2] == "rollback":
        rollback_migration(db_path)
    else:
        run_migration(db_path)
