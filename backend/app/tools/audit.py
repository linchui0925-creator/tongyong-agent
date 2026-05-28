"""
AuditLogger - 审计日志记录器

记录所有工具调用和操作
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
import logging
import sqlite3
from uuid import uuid4

logger = logging.getLogger(__name__)


class AuditLog:
    """审计日志"""
    
    def __init__(
        self,
        id: str,
        tool_id: str,
        session_id: Optional[str],
        user_id: Optional[str],
        action: str,
        parameters: Optional[Dict] = None,
        result: Optional[str] = None,
        error_message: Optional[str] = None,
        risk_level: Optional[str] = None,
        approval_status: Optional[str] = None,
        approved_by: Optional[str] = None,
        approved_at: Optional[str] = None,
        execution_time_ms: Optional[int] = None,
        created_at: Optional[str] = None,
    ):
        self.id = id
        self.tool_id = tool_id
        self.session_id = session_id
        self.user_id = user_id
        self.action = action
        self.parameters = parameters
        self.result = result
        self.error_message = error_message
        self.risk_level = risk_level
        self.approval_status = approval_status
        self.approved_by = approved_by
        self.approved_at = approved_at
        self.execution_time_ms = execution_time_ms
        self.created_at = created_at or datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'tool_id': self.tool_id,
            'session_id': self.session_id,
            'user_id': self.user_id,
            'action': self.action,
            'parameters': self.parameters,
            'result': self.result,
            'error_message': self.error_message,
            'risk_level': self.risk_level,
            'approval_status': self.approval_status,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at,
            'execution_time_ms': self.execution_time_ms,
            'created_at': self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuditLog':
        """从字典创建"""
        return cls(
            id=data['id'],
            tool_id=data['tool_id'],
            session_id=data.get('session_id'),
            user_id=data.get('user_id'),
            action=data['action'],
            parameters=json.loads(data['parameters']) if isinstance(data.get('parameters'), str) else data.get('parameters'),
            result=data.get('result'),
            error_message=data.get('error_message'),
            risk_level=data.get('risk_level'),
            approval_status=data.get('approval_status'),
            approved_by=data.get('approved_by'),
            approved_at=data.get('approved_at'),
            execution_time_ms=data.get('execution_time_ms'),
            created_at=data.get('created_at'),
        )


class AuditLogger:
    """审计日志记录器"""
    
    def __init__(self, db_path: str = "./data/tongyong.db"):
        """
        初始化审计日志记录器
        
        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        logger.info("AuditLogger 初始化完成")
    
    async def log_execution(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        result: str = 'success',
        error_message: Optional[str] = None,
        risk_level: str = 'low',
        execution_time_ms: Optional[int] = None,
        approved_by: Optional[str] = None,
    ) -> AuditLog:
        """
        记录工具执行
        
        Args:
            tool_name: 工具名称
            parameters: 参数（敏感数据将被屏蔽）
            session_id: 会话 ID
            user_id: 用户 ID
            result: 执行结果
            error_message: 错误信息
            risk_level: 风险级别
            execution_time_ms: 执行时间（毫秒）
            approved_by: 审批人
            
        Returns:
            AuditLog: 审计日志对象
        """
        log = AuditLog(
            id=str(uuid4()),
            tool_id=self._get_tool_id(tool_name),
            session_id=session_id,
            user_id=user_id,
            action='execute',
            parameters=self._mask_sensitive_parameters(parameters),
            result=result,
            error_message=error_message,
            risk_level=risk_level,
            approval_status='approved' if approved_by else 'not_required',
            approved_by=approved_by,
            approved_at=datetime.now().isoformat() if approved_by else None,
            execution_time_ms=execution_time_ms,
        )
        
        await self._save_log(log)
        
        return log
    
    async def log_approval(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        session_id: str,
        user_id: str,
        status: str,
        approved_by: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        risk_level: str = 'medium',
    ) -> AuditLog:
        """
        记录审批操作
        
        Args:
            tool_name: 工具名称
            parameters: 参数
            session_id: 会话 ID
            user_id: 用户 ID
            status: 审批状态
            approved_by: 审批人
            rejection_reason: 拒绝原因
            risk_level: 风险级别
            
        Returns:
            AuditLog: 审计日志对象
        """
        log = AuditLog(
            id=str(uuid4()),
            tool_id=self._get_tool_id(tool_name),
            session_id=session_id,
            user_id=user_id,
            action='approve' if status == 'approved' else 'reject',
            parameters=self._mask_sensitive_parameters(parameters),
            result=status,
            risk_level=risk_level,
            approval_status=status,
            approved_by=approved_by,
            approved_at=datetime.now().isoformat() if approved_by else None,
            error_message=rejection_reason,
        )
        
        await self._save_log(log)
        
        return log
    
    async def get_logs(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        risk_level: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLog]:
        """
        查询审计日志
        
        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            tool_name: 工具名称
            risk_level: 风险级别
            start_date: 开始日期
            end_date: 结束日期
            limit: 返回数量
            offset: 偏移量
            
        Returns:
            List[AuditLog]: 审计日志列表
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            conditions = []
            params = []
            
            if session_id:
                conditions.append("session_id = ?")
                params.append(session_id)
            
            if user_id:
                conditions.append("user_id = ?")
                params.append(user_id)
            
            if tool_name:
                conditions.append("tool_id IN (SELECT id FROM tool_registry WHERE name = ?)")
                params.append(tool_name)
            
            if risk_level:
                conditions.append("risk_level = ?")
                params.append(risk_level)
            
            if start_date:
                conditions.append("created_at >= ?")
                params.append(start_date.isoformat())
            
            if end_date:
                conditions.append("created_at <= ?")
                params.append(end_date.isoformat())
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            cursor.execute(f"""
                SELECT id, tool_id, session_id, user_id, action, parameters, result,
                       error_message, risk_level, approval_status, approved_by, approved_at,
                       execution_time_ms, created_at
                FROM tool_audit_log
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, params + [limit, offset])
            
            rows = cursor.fetchall()
            conn.close()
            
            logs = []
            for row in rows:
                logs.append(AuditLog(
                    id=row[0],
                    tool_id=row[1],
                    session_id=row[2],
                    user_id=row[3],
                    action=row[4],
                    parameters=json.loads(row[5]) if row[5] else None,
                    result=row[6],
                    error_message=row[7],
                    risk_level=row[8],
                    approval_status=row[9],
                    approved_by=row[10],
                    approved_at=row[11],
                    execution_time_ms=row[12],
                    created_at=row[13],
                ))
            
            return logs
            
        except Exception as e:
            logger.error(f"查询审计日志失败: {e}")
            return []
    
    async def get_statistics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        获取审计统计
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            Dict: 统计数据
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            date_filter = ""
            params = []
            
            if start_date:
                date_filter += " AND created_at >= ?"
                params.append(start_date.isoformat())
            
            if end_date:
                date_filter += " AND created_at <= ?"
                params.append(end_date.isoformat())
            
            # 总执行次数
            cursor.execute(f"""
                SELECT COUNT(*) FROM tool_audit_log WHERE action = 'execute' {date_filter}
            """, params)
            total_executions = cursor.fetchone()[0]
            
            # 成功次数
            cursor.execute(f"""
                SELECT COUNT(*) FROM tool_audit_log WHERE action = 'execute' AND result = 'success' {date_filter}
            """, params)
            successful_executions = cursor.fetchone()[0]
            
            # 失败次数
            cursor.execute(f"""
                SELECT COUNT(*) FROM tool_audit_log WHERE action = 'execute' AND result = 'failed' {date_filter}
            """, params)
            failed_executions = cursor.fetchone()[0]
            
            # 风险级别分布
            cursor.execute(f"""
                SELECT risk_level, COUNT(*) 
                FROM tool_audit_log 
                WHERE action = 'execute' {date_filter}
                GROUP BY risk_level
            """, params)
            risk_distribution = {row[0]: row[1] for row in cursor.fetchall()}
            
            # 工具使用排名
            cursor.execute(f"""
                SELECT tr.name, COUNT(*) as count
                FROM tool_audit_log tal
                JOIN tool_registry tr ON tal.tool_id = tr.id
                WHERE tal.action = 'execute' {date_filter}
                GROUP BY tal.tool_id
                ORDER BY count DESC
                LIMIT 10
            """, params)
            tool_usage_ranking = [{'tool': row[0], 'count': row[1]} for row in cursor.fetchall()]
            
            conn.close()
            
            return {
                'total_executions': total_executions,
                'successful_executions': successful_executions,
                'failed_executions': failed_executions,
                'success_rate': successful_executions / total_executions if total_executions > 0 else 0,
                'risk_distribution': risk_distribution,
                'tool_usage_ranking': tool_usage_ranking,
            }
            
        except Exception as e:
            logger.error(f"获取审计统计失败: {e}")
            return {}
    
    async def _save_log(self, log: AuditLog):
        """保存日志到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO tool_audit_log
                (id, tool_id, session_id, user_id, action, parameters, result,
                 error_message, risk_level, approval_status, approved_by, approved_at,
                 execution_time_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log.id,
                log.tool_id,
                log.session_id,
                log.user_id,
                log.action,
                json.dumps(log.parameters) if log.parameters else None,
                log.result,
                log.error_message,
                log.risk_level,
                log.approval_status,
                log.approved_by,
                log.approved_at,
                log.execution_time_ms,
                log.created_at,
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"保存审计日志失败: {e}")
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
    
    def _mask_sensitive_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """屏蔽敏感参数"""
        sensitive_keys = ['password', 'token', 'api_key', 'secret', 'credential', 'key', 'auth']
        masked = {}
        
        for key, value in parameters.items():
            if any(s in key.lower() for s in sensitive_keys):
                masked[key] = '***MASKED***'
            else:
                if isinstance(value, dict):
                    masked[key] = self._mask_sensitive_parameters(value)
                else:
                    masked[key] = value
        
        return masked
