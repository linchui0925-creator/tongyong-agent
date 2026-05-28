"""
梦境信号数据结构 - 定义阶段信号和风险评估
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


class PhaseType(str, Enum):
    """梦境阶段类型"""
    LIGHT = "light"
    REM = "rem"
    DEEP = "deep"


class CandidateStatus(str, Enum):
    """候选记忆状态"""
    PENDING = "pending"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SourceType(str, Enum):
    """记忆来源类型"""
    CONVERSATION = "conversation"
    REFLECTION = "reflection"
    SKILL = "skill"


@dataclass
class PhaseSignal:
    """阶段信号 - 存储 Light 和 REM 阶段的强化信号"""
    
    entry_id: str
    source_phase: PhaseType
    reinforcement_value: float
    reason: str
    sweep_id: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    
    def __post_init__(self):
        """初始化后设置默认值"""
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if isinstance(self.source_phase, str):
            self.source_phase = PhaseType(self.source_phase)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'entry_id': self.entry_id,
            'source_phase': self.source_phase.value if isinstance(self.source_phase, PhaseType) else self.source_phase,
            'reinforcement_value': self.reinforcement_value,
            'reason': self.reason,
            'sweep_id': self.sweep_id,
            'created_at': self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PhaseSignal':
        """从字典创建"""
        return cls(
            id=data.get('id'),
            entry_id=data['entry_id'],
            source_phase=PhaseType(data['source_phase']),
            reinforcement_value=data['reinforcement_value'],
            reason=data.get('reason', ''),
            sweep_id=data.get('sweep_id'),
            created_at=data.get('created_at'),
        )


@dataclass
class DreamCandidate:
    """梦境候选记忆"""
    
    id: str
    source_session_id: str
    content: str
    source_type: SourceType
    concept_tags: List[str] = field(default_factory=list)
    recall_count: int = 0
    unique_query_count: int = 0
    query_diversity_score: float = 0.0
    relevance_score: float = 0.0
    recency_score: float = 0.0
    consolidation_score: float = 0.0
    conceptual_richness_score: float = 0.0
    total_score: float = 0.0
    phase_signal_light: float = 0.0
    phase_signal_rem: float = 0.0
    final_score: float = 0.0
    status: CandidateStatus = CandidateStatus.PENDING
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    promoted_at: Optional[str] = None
    
    def __post_init__(self):
        """初始化后设置默认值"""
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if isinstance(self.source_type, str):
            self.source_type = SourceType(self.source_type)
        if isinstance(self.status, str):
            self.status = CandidateStatus(self.status)
    
    def calculate_final_score(
        self,
        light_signal_weight: float = 0.1,
        rem_signal_weight: float = 0.2
    ) -> float:
        """计算最终评分"""
        base_score = (
            self.relevance_score * 0.30 +
            float(self.recall_count) / 10 * 0.24 +  # 归一化
            self.query_diversity_score * 0.15 +
            self.recency_score * 0.15 +
            self.consolidation_score * 0.10 +
            self.conceptual_richness_score * 0.06
        )
        
        # 加上阶段强化信号
        self.final_score = (
            base_score +
            self.phase_signal_light * light_signal_weight +
            self.phase_signal_rem * rem_signal_weight
        )
        
        return self.final_score
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'source_session_id': self.source_session_id,
            'content': self.content,
            'source_type': self.source_type.value if isinstance(self.source_type, SourceType) else self.source_type,
            'concept_tags': self.concept_tags,
            'recall_count': self.recall_count,
            'unique_query_count': self.unique_query_count,
            'relevance_score': self.relevance_score,
            'recency_score': self.recency_score,
            'consolidation_score': self.consolidation_score,
            'conceptual_richness_score': self.conceptual_richness_score,
            'total_score': self.total_score,
            'final_score': self.final_score,
            'status': self.status.value if isinstance(self.status, CandidateStatus) else self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'promoted_at': self.promoted_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DreamCandidate':
        """从字典创建"""
        import json
        
        concept_tags = data.get('concept_tags', [])
        if isinstance(concept_tags, str):
            try:
                concept_tags = json.loads(concept_tags)
            except:
                concept_tags = []
        
        return cls(
            id=data['id'],
            source_session_id=data['source_session_id'],
            content=data['content'],
            source_type=SourceType(data['source_type']),
            concept_tags=concept_tags,
            recall_count=data.get('recall_count', 0),
            unique_query_count=data.get('unique_query_count', 0),
            query_diversity_score=data.get('query_diversity_score', 0.0),
            relevance_score=data.get('relevance_score', 0.0),
            recency_score=data.get('recency_score', 0.0),
            consolidation_score=data.get('consolidation_score', 0.0),
            conceptual_richness_score=data.get('conceptual_richness_score', 0.0),
            total_score=data.get('total_score', 0.0),
            phase_signal_light=data.get('phase_signal_light', 0.0),
            phase_signal_rem=data.get('phase_signal_rem', 0.0),
            final_score=data.get('final_score', 0.0),
            status=CandidateStatus(data.get('status', 'pending')),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            promoted_at=data.get('promoted_at'),
        )


@dataclass
class RiskAssessment:
    """风险评估结果"""
    
    risk_level: str  # low, medium, high, critical
    matched_patterns: List[Dict[str, str]] = field(default_factory=list)
    recommendation: str = ""
    approved: Optional[bool] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'risk_level': self.risk_level,
            'matched_patterns': self.matched_patterns,
            'recommendation': self.recommendation,
            'approved': self.approved,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RiskAssessment':
        """从字典创建"""
        return cls(
            risk_level=data.get('risk_level', 'low'),
            matched_patterns=data.get('matched_patterns', []),
            recommendation=data.get('recommendation', ''),
            approved=data.get('approved'),
        )


@dataclass
class Insight:
    """反思性洞察"""
    
    id: str
    theme: str
    content: str
    confidence: float
    related_entries: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    
    def __post_init__(self):
        """初始化后设置默认值"""
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'theme': self.theme,
            'content': self.content,
            'confidence': self.confidence,
            'related_entries': self.related_entries,
            'created_at': self.created_at,
        }
