"""
技能数据模型 - 定义技能和相关数据结构
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


class SkillStatus(str, Enum):
    """技能状态"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


@dataclass
class Skill:
    """技能数据结构"""
    
    id: str
    name: str
    content: str
    category: str = "general"
    trigger_conditions: List[str] = field(default_factory=list)
    execution_steps: List[str] = field(default_factory=list)
    expected_outcome: str = ""
    usage_count: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    version: int = 1
    status: SkillStatus = SkillStatus.ACTIVE
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def __post_init__(self):
        """初始化后设置默认值"""
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if isinstance(self.status, str):
            self.status = SkillStatus(self.status)
    
    def update_success_rate(self, success: bool):
        """更新成功率"""
        self.success_count += 1 if success else 0
        self.usage_count += 1
        if self.usage_count > 0:
            self.success_rate = self.success_count / self.usage_count
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'content': self.content,
            'category': self.category,
            'trigger_conditions': self.trigger_conditions,
            'execution_steps': self.execution_steps,
            'expected_outcome': self.expected_outcome,
            'usage_count': self.usage_count,
            'success_count': self.success_count,
            'success_rate': self.success_rate,
            'version': self.version,
            'status': self.status.value if isinstance(self.status, SkillStatus) else self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Skill':
        """从字典创建"""
        import json
        
        trigger_conditions = data.get('trigger_conditions', [])
        if isinstance(trigger_conditions, str):
            try:
                trigger_conditions = json.loads(trigger_conditions)
            except:
                trigger_conditions = []
        
        execution_steps = data.get('execution_steps', [])
        if isinstance(execution_steps, str):
            try:
                execution_steps = json.loads(execution_steps)
            except:
                execution_steps = []
        
        return cls(
            id=data['id'],
            name=data['name'],
            content=data['content'],
            category=data.get('category', 'general'),
            trigger_conditions=trigger_conditions,
            execution_steps=execution_steps,
            expected_outcome=data.get('expected_outcome', ''),
            usage_count=data.get('usage_count', 0),
            success_count=data.get('success_count', 0),
            success_rate=data.get('success_rate', 0.0),
            version=data.get('version', 1),
            status=SkillStatus(data.get('status', 'active')),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
        )


@dataclass
class SkillDraft:
    """技能草稿 - 从执行轨迹提取的原始技能"""
    
    name: str
    content: str
    trigger_conditions: List[str] = field(default_factory=list)
    execution_steps: List[str] = field(default_factory=list)
    expected_outcome: str = ""
    confidence: float = 0.0
    source_trajectory: Optional[Dict] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'content': self.content,
            'trigger_conditions': self.trigger_conditions,
            'execution_steps': self.execution_steps,
            'expected_outcome': self.expected_outcome,
            'confidence': self.confidence,
            'source_trajectory': self.source_trajectory,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SkillDraft':
        """从字典创建"""
        return cls(
            name=data.get('name', ''),
            content=data.get('content', ''),
            trigger_conditions=data.get('trigger_conditions', []),
            execution_steps=data.get('execution_steps', []),
            expected_outcome=data.get('expected_outcome', ''),
            confidence=data.get('confidence', 0.0),
            source_trajectory=data.get('source_trajectory'),
        )


@dataclass
class SkillUsageLog:
    """技能使用记录"""
    
    id: str
    skill_id: str
    session_id: str
    trigger_context: str = ""
    execution_result: str = ""
    success: bool = False
    feedback: str = ""
    created_at: Optional[str] = None
    
    def __post_init__(self):
        """初始化后设置默认值"""
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'skill_id': self.skill_id,
            'session_id': self.session_id,
            'trigger_context': self.trigger_context,
            'execution_result': self.execution_result,
            'success': self.success,
            'feedback': self.feedback,
            'created_at': self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SkillUsageLog':
        """从字典创建"""
        return cls(
            id=data['id'],
            skill_id=data['skill_id'],
            session_id=data['session_id'],
            trigger_context=data.get('trigger_context', ''),
            execution_result=data.get('execution_result', ''),
            success=bool(data.get('success', False)),
            feedback=data.get('feedback', ''),
            created_at=data.get('created_at'),
        )


@dataclass
class TaskResult:
    """任务执行结果"""
    
    task_description: str
    outcome: str
    success: bool
    trajectory: List[Dict[str, Any]] = field(default_factory=list)
    execution_time: float = 0.0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'task_description': self.task_description,
            'outcome': self.outcome,
            'success': self.success,
            'trajectory': self.trajectory,
            'execution_time': self.execution_time,
            'error': self.error,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskResult':
        """从字典创建"""
        return cls(
            task_description=data.get('task_description', ''),
            outcome=data.get('outcome', ''),
            success=data.get('success', False),
            trajectory=data.get('trajectory', []),
            execution_time=data.get('execution_time', 0.0),
            error=data.get('error'),
        )
