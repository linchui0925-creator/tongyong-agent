"""
PermissionManager - 权限管理器

管理角色与工具的权限关系
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
import json
import logging
import sqlite3
from uuid import uuid4

logger = logging.getLogger(__name__)


class UserRole(str, Enum):
    """用户角色"""
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


@dataclass
class RolePermission:
    """角色权限"""
    
    id: str
    tool_id: str
    role: UserRole
    granted: bool = True
    conditions: Optional[Dict] = None
    granted_by: Optional[str] = None
    granted_at: Optional[str] = None
    expires_at: Optional[str] = None
    
    def __post_init__(self):
        """初始化后设置默认值"""
        if self.granted_at is None:
            self.granted_at = datetime.now().isoformat()
        if isinstance(self.role, str):
            self.role = UserRole(self.role)
    
    def is_valid(self) -> bool:
        """检查权限是否有效"""
        if not self.granted:
            return False
        
        if self.expires_at:
            expires = datetime.fromisoformat(self.expires_at)
            if datetime.now() > expires:
                return False
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'tool_id': self.tool_id,
            'role': self.role.value if isinstance(self.role, UserRole) else self.role,
            'granted': self.granted,
            'conditions': self.conditions,
            'granted_by': self.granted_by,
            'granted_at': self.granted_at,
            'expires_at': self.expires_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RolePermission':
        """从字典创建"""
        conditions = data.get('conditions')
        if isinstance(conditions, str):
            try:
                conditions = json.loads(conditions)
            except:
                conditions = None
        
        return cls(
            id=data['id'],
            tool_id=data['tool_id'],
            role=UserRole(data['role']),
            granted=bool(data.get('granted', True)),
            conditions=conditions,
            granted_by=data.get('granted_by'),
            granted_at=data.get('granted_at'),
            expires_at=data.get('expires_at'),
        )


@dataclass
class PermissionResult:
    """权限检查结果"""
    
    allowed: bool
    denial_reason: Optional[str] = None
    risk_level: Optional[str] = None
    requires_approval: bool = False
    permission_level: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'allowed': self.allowed,
            'denial_reason': self.denial_reason,
            'risk_level': self.risk_level,
            'requires_approval': self.requires_approval,
            'permission_level': self.permission_level,
        }


@dataclass
class SessionPermission:
    """会话临时权限"""
    
    id: str
    tool_id: str
    session_id: str
    granted: bool
    granted_by: Optional[str] = None
    granted_at: Optional[str] = None
    expires_at: Optional[str] = None
    
    def __post_init__(self):
        """初始化后设置默认值"""
        if self.granted_at is None:
            self.granted_at = datetime.now().isoformat()
    
    def is_valid(self) -> bool:
        """检查权限是否有效"""
        if not self.granted:
            return False
        
        if self.expires_at:
            expires = datetime.fromisoformat(self.expires_at)
            if datetime.now() > expires:
                return False
        
        return True


class PermissionManager:
    """权限管理器"""
    
    def __init__(self, db_path: str = "./data/tongyong.db"):
        """
        初始化权限管理器
        
        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        
        # 角色权限层级（数字越大权限越高）
        self.role_hierarchy = {
            UserRole.GUEST: 0,
            UserRole.USER: 1,
            UserRole.ADMIN: 2,
            UserRole.OWNER: 3,
        }
        
        logger.info("PermissionManager 初始化完成")
    
    async def check_role_permission(
        self,
        tool_id: str,
        role: str
    ) -> RolePermission:
        """
        检查角色对工具的权限
        
        Args:
            tool_id: 工具 ID
            role: 用户角色
            
        Returns:
            RolePermission: 角色权限对象
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, tool_id, role, granted, conditions, granted_by, granted_at, expires_at
                FROM tool_permissions
                WHERE tool_id = ? AND role = ?
            """, (tool_id, role))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return RolePermission(
                    id=row[0],
                    tool_id=row[1],
                    role=UserRole(row[2]),
                    granted=bool(row[3]),
                    conditions=json.loads(row[4]) if row[4] else None,
                    granted_by=row[5],
                    granted_at=row[6],
                    expires_at=row[7],
                )
            
            # 默认拒绝
            return RolePermission(
                id=str(uuid4()),
                tool_id=tool_id,
                role=UserRole(role),
                granted=False,
            )
            
        except Exception as e:
            logger.error(f"检查角色权限失败: {e}")
            return RolePermission(
                id=str(uuid4()),
                tool_id=tool_id,
                role=UserRole(role),
                granted=False,
            )
    
    async def check_session_permission(
        self,
        tool_id: str,
        session_id: str
    ) -> Optional[SessionPermission]:
        """
        检查会话临时权限
        
        Args:
            tool_id: 工具 ID
            session_id: 会话 ID
            
        Returns:
            Optional[SessionPermission]: 会话权限对象
        """
        # TODO: 实现会话权限检查
        return None
    
    async def grant_permission(
        self,
        tool_id: str,
        role: str,
        granted: bool = True,
        granted_by: Optional[str] = None,
        conditions: Optional[Dict] = None,
        expires_at: Optional[str] = None
    ) -> RolePermission:
        """
        授予或撤销权限
        
        Args:
            tool_id: 工具 ID
            role: 用户角色
            granted: 是否授予
            granted_by: 授权人
            conditions: 额外条件
            expires_at: 过期时间
            
        Returns:
            RolePermission: 权限对象
        """
        try:
            perm_id = str(uuid4())
            now = datetime.now().isoformat()
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO tool_permissions
                (id, tool_id, role, granted, conditions, granted_by, granted_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                perm_id,
                tool_id,
                role,
                1 if granted else 0,
                json.dumps(conditions) if conditions else None,
                granted_by,
                now,
                expires_at,
            ))
            
            conn.commit()
            conn.close()
            
            return RolePermission(
                id=perm_id,
                tool_id=tool_id,
                role=UserRole(role),
                granted=granted,
                conditions=conditions,
                granted_by=granted_by,
                granted_at=now,
                expires_at=expires_at,
            )
            
        except Exception as e:
            logger.error(f"授予权限失败: {e}")
            raise
    
    async def grant_session_permission(
        self,
        tool_id: str,
        session_id: str,
        granted: bool = True,
        granted_by: Optional[str] = None,
        expires_at: Optional[str] = None
    ) -> SessionPermission:
        """
        授予会话临时权限
        
        Args:
            tool_id: 工具 ID
            session_id: 会话 ID
            granted: 是否授予
            granted_by: 授权人
            expires_at: 过期时间
            
        Returns:
            SessionPermission: 会话权限对象
        """
        # TODO: 实现会话权限授予
        pass
    
    async def revoke_session_permission(
        self,
        tool_id: str,
        session_id: str
    ) -> bool:
        """
        撤销会话临时权限
        
        Args:
            tool_id: 工具 ID
            session_id: 会话 ID
            
        Returns:
            bool: 是否成功
        """
        # TODO: 实现会话权限撤销
        return False
    
    def get_role_level(self, role: str) -> int:
        """
        获取角色层级
        
        Args:
            role: 角色名称
            
        Returns:
            int: 角色层级
        """
        return self.role_hierarchy.get(UserRole(role), 0)
    
    def is_higher_role(self, role1: str, role2: str) -> bool:
        """
        判断角色1是否高于角色2
        
        Args:
            role1: 角色1
            role2: 角色2
            
        Returns:
            bool: 是否更高
        """
        return self.get_role_level(role1) > self.get_role_level(role2)
    
    async def get_permissions_by_role(self, role: str) -> List[Dict]:
        """
        获取角色的所有权限
        
        Args:
            role: 角色名称
            
        Returns:
            List[Dict]: 权限列表
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT tp.id, tp.tool_id, tr.name, tp.granted, tp.conditions, tp.expires_at
                FROM tool_permissions tp
                JOIN tool_registry tr ON tp.tool_id = tr.id
                WHERE tp.role = ?
            """, (role,))
            
            rows = cursor.fetchall()
            conn.close()
            
            permissions = []
            for row in rows:
                permissions.append({
                    'permission_id': row[0],
                    'tool_id': row[1],
                    'tool_name': row[2],
                    'granted': bool(row[3]),
                    'conditions': json.loads(row[4]) if row[4] else None,
                    'expires_at': row[5],
                })
            
            return permissions
            
        except Exception as e:
            logger.error(f"获取角色权限失败: {e}")
            return []
    
    async def get_tool_permissions(self, tool_id: str) -> Dict[str, bool]:
        """
        获取工具的所有角色权限
        
        Args:
            tool_id: 工具 ID
            
        Returns:
            Dict[str, bool]: 角色到权限的映射
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT role, granted
                FROM tool_permissions
                WHERE tool_id = ?
            """, (tool_id,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return {row[0]: bool(row[1]) for row in rows}
            
        except Exception as e:
            logger.error(f"获取工具权限失败: {e}")
            return {}
