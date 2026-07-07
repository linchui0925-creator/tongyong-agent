"""
ApprovalManager - 审批管理器

管理工具执行的审批工作流
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
import logging
import sqlite3
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    """审批请求"""
    id: str
    tool_id: str
    session_id: str
    user_id: str
    parameters: Dict[str, Any]
    risk_assessment: Optional[Dict] = None
    status: str = 'pending'
    approval_mode: str = 'manual'
    expires_at: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class ApprovalResult:
    """审批结果"""
    approved: bool
    status: str
    approval_id: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "status": self.status,
            "approval_id": self.approval_id,
            "reason": self.reason,
        }


class ApprovalManager:
    """审批管理器"""
    
    def __init__(self, db_path: str = "./data/tongyong.db"):
        """
        初始化审批管理器
        
        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        self.default_approval_timeout = 300
        self._ensure_tables()
        
        logger.info("ApprovalManager 初始化完成")

    def _ensure_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tool_approvals (
                id TEXT PRIMARY KEY,
                tool_id TEXT NOT NULL,
                session_id TEXT,
                user_id TEXT,
                parameters TEXT,
                risk_assessment TEXT,
                status TEXT DEFAULT 'pending',
                approval_mode TEXT DEFAULT 'manual',
                expires_at TEXT,
                approved_by TEXT,
                approved_at TEXT,
                rejection_reason TEXT,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_approvals_status ON tool_approvals(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_approvals_session ON tool_approvals(session_id)")
        conn.commit()
        conn.close()
    
    async def create_request(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        session_id: str,
        user_id: str,
        risk_level: str = 'medium'
    ) -> ApprovalRequest:
        """
        创建审批请求
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            session_id: 会话 ID
            user_id: 用户 ID
            risk_level: 风险级别
            
        Returns:
            ApprovalRequest: 审批请求
        """
        request_id = str(uuid4())
        now = datetime.now()
        expires_at = now + timedelta(seconds=self.default_approval_timeout)
        
        request = ApprovalRequest(
            id=request_id,
            tool_id=self._get_tool_id(tool_name),
            session_id=session_id,
            user_id=user_id,
            parameters=parameters,
            risk_assessment={'risk_level': risk_level},
            status='pending',
            approval_mode='manual',
            expires_at=expires_at.isoformat(),
            created_at=now.isoformat()
        )
        
        await self._save_request(request)
        
        logger.info(f"创建审批请求: {request_id}, 工具: {tool_name}")
        
        return request
    
    async def approve(
        self,
        approval_id: str,
        approved_by: str,
        comment: Optional[str] = None
    ) -> ApprovalResult:
        """
        批准审批请求
        
        Args:
            approval_id: 审批 ID
            approved_by: 审批人
            
        Returns:
            ApprovalResult: 审批结果
        """
        try:
            request = await self._get_request(approval_id)
            
            if not request:
                return ApprovalResult(
                    approved=False,
                    status='not_found',
                    reason='审批请求不存在'
                )
            
            if request.status != 'pending':
                return ApprovalResult(
                    approved=False,
                    status=request.status,
                    reason=f'审批请求状态为 {request.status}'
                )
            
            if request.expires_at:
                expires = datetime.fromisoformat(request.expires_at)
                if datetime.now() > expires:
                    await self._update_status(approval_id, 'expired')
                    return ApprovalResult(
                        approved=False,
                        status='expired',
                        reason='审批请求已过期'
                    )
            
            await self._update_status(approval_id, 'approved', approved_by)
            
            logger.info(f"审批已批准: {approval_id}, 审批人: {approved_by}")
            
            return ApprovalResult(
                approved=True,
                status='approved',
                approval_id=approval_id
            )
            
        except Exception as e:
            logger.error(f"批准审批失败: {e}")
            return ApprovalResult(
                approved=False,
                status='error',
                reason=str(e)
            )
    
    async def reject(
        self,
        approval_id: str,
        rejected_by: str,
        reason: str
    ) -> ApprovalResult:
        """
        拒绝审批请求
        
        Args:
            approval_id: 审批 ID
            rejected_by: 拒绝人
            reason: 拒绝原因
            
        Returns:
            ApprovalResult: 审批结果
        """
        try:
            request = await self._get_request(approval_id)
            
            if not request:
                return ApprovalResult(
                    approved=False,
                    status='not_found',
                    reason='审批请求不存在'
                )
            
            if request.status != 'pending':
                return ApprovalResult(
                    approved=False,
                    status=request.status,
                    reason=f'审批请求状态为 {request.status}'
                )
            
            await self._update_status(approval_id, 'rejected', rejected_by, reason)
            
            logger.info(f"审批已拒绝: {approval_id}, 原因: {reason}")
            
            return ApprovalResult(
                approved=False,
                status='rejected',
                approval_id=approval_id,
                reason=reason
            )
            
        except Exception as e:
            logger.error(f"拒绝审批失败: {e}")
            return ApprovalResult(
                approved=False,
                status='error',
                reason=str(e)
            )
    
    async def auto_approve(self, approval_id: str) -> ApprovalResult:
        """
        自动批准（用于低风险操作）
        
        Args:
            approval_id: 审批 ID
            
        Returns:
            ApprovalResult: 审批结果
        """
        try:
            await self._update_status(approval_id, 'approved', 'system')
            
            logger.info(f"审批已自动批准: {approval_id}")
            
            return ApprovalResult(
                approved=True,
                status='auto_approved',
                approval_id=approval_id
            )
            
        except Exception as e:
            logger.error(f"自动批准失败: {e}")
            return ApprovalResult(
                approved=False,
                status='error',
                reason=str(e)
            )
    
    async def get_pending_requests(
        self,
        session_id: Optional[str] = None,
        limit: int = 50
    ) -> List[ApprovalRequest]:
        """
        获取待处理的审批请求
        
        Args:
            session_id: 会话 ID
            limit: 返回数量
            
        Returns:
            List[ApprovalRequest]: 待处理的审批请求列表
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if session_id:
                cursor.execute("""
                    SELECT id, tool_id, session_id, user_id, parameters, risk_assessment,
                           status, approval_mode, expires_at, approved_by, approved_at,
                           rejection_reason, created_at
                    FROM tool_approvals
                    WHERE status = 'pending' AND session_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (session_id, limit))
            else:
                cursor.execute("""
                    SELECT id, tool_id, session_id, user_id, parameters, risk_assessment,
                           status, approval_mode, expires_at, approved_by, approved_at,
                           rejection_reason, created_at
                    FROM tool_approvals
                    WHERE status = 'pending'
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            requests = []
            for row in rows:
                requests.append(ApprovalRequest(
                    id=row[0],
                    tool_id=row[1],
                    session_id=row[2],
                    user_id=row[3],
                    parameters=json.loads(row[4]) if row[4] else {},
                    risk_assessment=json.loads(row[5]) if row[5] else None,
                    status=row[6],
                    approval_mode=row[7],
                    expires_at=row[8],
                    approved_by=row[9],
                    approved_at=row[10],
                    rejection_reason=row[11],
                    created_at=row[12]
                ))
            
            return requests
            
        except Exception as e:
            logger.error(f"获取待处理审批失败: {e}")
            return []
    
    async def _save_request(self, request: ApprovalRequest):
        """保存审批请求到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO tool_approvals
                (id, tool_id, session_id, user_id, parameters, risk_assessment,
                 status, approval_mode, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request.id,
                request.tool_id,
                request.session_id,
                request.user_id,
                json.dumps(request.parameters),
                json.dumps(request.risk_assessment) if request.risk_assessment else None,
                request.status,
                request.approval_mode,
                request.expires_at,
                request.created_at
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"保存审批请求失败: {e}")
            raise
    
    async def _get_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        """获取审批请求"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, tool_id, session_id, user_id, parameters, risk_assessment,
                       status, approval_mode, expires_at, approved_by, approved_at,
                       rejection_reason, created_at
                FROM tool_approvals
                WHERE id = ?
            """, (approval_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return ApprovalRequest(
                    id=row[0],
                    tool_id=row[1],
                    session_id=row[2],
                    user_id=row[3],
                    parameters=json.loads(row[4]) if row[4] else {},
                    risk_assessment=json.loads(row[5]) if row[5] else None,
                    status=row[6],
                    approval_mode=row[7],
                    expires_at=row[8],
                    approved_by=row[9],
                    approved_at=row[10],
                    rejection_reason=row[11],
                    created_at=row[12]
                )
            
            return None
            
        except Exception as e:
            logger.error(f"获取审批请求失败: {e}")
            return None

    async def get_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        return await self._get_request(approval_id)

    async def update_risk_assessment(self, approval_id: str, risk_assessment: Dict[str, Any]) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tool_approvals SET risk_assessment = ? WHERE id = ?",
            (json.dumps(risk_assessment), approval_id),
        )
        conn.commit()
        conn.close()
    
    async def _update_status(
        self,
        approval_id: str,
        status: str,
        updated_by: Optional[str] = None,
        reason: Optional[str] = None
    ):
        """更新审批状态"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            
            if status == 'approved':
                cursor.execute("""
                    UPDATE tool_approvals
                    SET status = ?, approved_by = ?, approved_at = ?
                    WHERE id = ?
                """, (status, updated_by, now, approval_id))
            elif status == 'rejected':
                cursor.execute("""
                    UPDATE tool_approvals
                    SET status = ?, approved_by = ?, approved_at = ?, rejection_reason = ?
                    WHERE id = ?
                """, (status, updated_by, now, reason, approval_id))
            elif status == 'expired':
                cursor.execute("""
                    UPDATE tool_approvals
                    SET status = ?
                    WHERE id = ?
                """, (status, approval_id))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"更新审批状态失败: {e}")
            raise
    
    def _get_tool_id(self, tool_name: str) -> str:
        """获取工具 ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM tool_registry WHERE name = ?", (tool_name,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return row[0]
            
            return tool_name
            
        except Exception as e:
            logger.warning(f"获取工具ID失败: {e}")
            return tool_name
