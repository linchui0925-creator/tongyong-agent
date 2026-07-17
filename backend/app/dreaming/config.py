"""
Dreaming 配置类 - 管理梦境系统的配置
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import sqlite3
import json
import logging
from app.paths import data_path

logger = logging.getLogger(__name__)


@dataclass
class DreamingConfig:
    """梦境系统配置类"""
    
    # 基础开关
    enabled: bool = False
    frequency: str = "0 3 * * *"  # Cron 表达式，每天凌晨3点
    
    # 回溯窗口
    lookback_days: int = 7
    
    # 评分权重
    relevance_weight: float = 0.30
    frequency_weight: float = 0.24
    query_diversity_weight: float = 0.15
    recency_weight: float = 0.15
    consolidation_weight: float = 0.10
    conceptual_richness_weight: float = 0.06
    
    # 晋升阈值
    min_score: float = 0.8
    min_recall_count: int = 3
    min_unique_queries: int = 3
    
    # 阶段强化加成
    light_signal_weight: float = 0.1
    rem_signal_weight: float = 0.2
    
    # Jaccard 去重阈值
    jaccard_threshold: float = 0.9
    
    # 数据库路径
    db_path: str = data_path("tongyong.db")
    
    # 缓存的配置
    _config_cache: Dict[str, str] = field(default_factory=dict, repr=False)
    
    def __post_init__(self):
        """初始化后加载配置"""
        self.load_from_db()
    
    def load_from_db(self):
        """从数据库加载配置"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT config_key, config_value FROM dreaming_config")
            rows = cursor.fetchall()
            conn.close()
            
            self._config_cache = {row[0]: row[1] for row in rows}
            
            # 应用配置
            if 'dreaming_enabled' in self._config_cache:
                self.enabled = self._config_cache['dreaming_enabled'] == 'true'
            if 'dreaming_frequency' in self._config_cache:
                self.frequency = self._config_cache['dreaming_frequency']
            if 'lookback_days' in self._config_cache:
                self.lookback_days = int(self._config_cache['lookback_days'])
            if 'min_score' in self._config_cache:
                self.min_score = float(self._config_cache['min_score'])
            if 'min_recall_count' in self._config_cache:
                self.min_recall_count = int(self._config_cache['min_recall_count'])
            if 'min_unique_queries' in self._config_cache:
                self.min_unique_queries = int(self._config_cache['min_unique_queries'])
            
            # 加载权重
            if 'relevance_weight' in self._config_cache:
                self.relevance_weight = float(self._config_cache['relevance_weight'])
            if 'frequency_weight' in self._config_cache:
                self.frequency_weight = float(self._config_cache['frequency_weight'])
            if 'query_diversity_weight' in self._config_cache:
                self.query_diversity_weight = float(self._config_cache['query_diversity_weight'])
            if 'recency_weight' in self._config_cache:
                self.recency_weight = float(self._config_cache['recency_weight'])
            if 'consolidation_weight' in self._config_cache:
                self.consolidation_weight = float(self._config_cache['consolidation_weight'])
            if 'conceptual_richness_weight' in self._config_cache:
                self.conceptual_richness_weight = float(self._config_cache['conceptual_richness_weight'])
            
            logger.info("Dreaming配置从数据库加载成功")
            
        except Exception as e:
            logger.warning(f"从数据库加载配置失败，使用默认值: {e}")
    
    def save_to_db(self):
        """保存配置到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            config_map = {
                'dreaming_enabled': str(self.enabled).lower(),
                'dreaming_frequency': self.frequency,
                'lookback_days': str(self.lookback_days),
                'min_score': str(self.min_score),
                'min_recall_count': str(self.min_recall_count),
                'min_unique_queries': str(self.min_unique_queries),
                'relevance_weight': str(self.relevance_weight),
                'frequency_weight': str(self.frequency_weight),
                'query_diversity_weight': str(self.query_diversity_weight),
                'recency_weight': str(self.recency_weight),
                'consolidation_weight': str(self.consolidation_weight),
                'conceptual_richness_weight': str(self.conceptual_richness_weight),
            }
            
            from datetime import datetime
            now = datetime.now().isoformat()
            
            for key, value in config_map.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO dreaming_config (id, config_key, config_value, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (f"cfg_{key}", key, value, now))
            
            conn.commit()
            conn.close()
            
            self._config_cache = config_map
            logger.info("Dreaming配置保存到数据库成功")
            
        except Exception as e:
            logger.error(f"保存配置到数据库失败: {e}")
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        if hasattr(self, key):
            return getattr(self, key)
        return self._config_cache.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            self._config_cache[key] = str(value)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'enabled': self.enabled,
            'frequency': self.frequency,
            'lookback_days': self.lookback_days,
            'min_score': self.min_score,
            'min_recall_count': self.min_recall_count,
            'min_unique_queries': self.min_unique_queries,
            'weights': {
                'relevance': self.relevance_weight,
                'frequency': self.frequency_weight,
                'query_diversity': self.query_diversity_weight,
                'recency': self.recency_weight,
                'consolidation': self.consolidation_weight,
                'conceptual_richness': self.conceptual_richness_weight,
            },
            'thresholds': {
                'min_score': self.min_score,
                'min_recall_count': self.min_recall_count,
                'min_unique_queries': self.min_unique_queries,
            },
        }
    
    def validate(self) -> bool:
        """验证配置合法性"""
        errors = []
        
        # 权重验证
        total_weight = (
            self.relevance_weight +
            self.frequency_weight +
            self.query_diversity_weight +
            self.recency_weight +
            self.consolidation_weight +
            self.conceptual_richness_weight
        )
        
        if abs(total_weight - 1.0) > 0.01:
            errors.append(f"权重总和必须为1.0，当前为{total_weight}")
        
        # 阈值验证
        if not 0 <= self.min_score <= 1:
            errors.append(f"min_score必须在0-1之间，当前为{self.min_score}")
        
        if self.min_recall_count < 0:
            errors.append(f"min_recall_count必须非负，当前为{self.min_recall_count}")
        
        if self.min_unique_queries < 0:
            errors.append(f"min_unique_queries必须非负，当前为{self.min_unique_queries}")
        
        if errors:
            for error in errors:
                logger.error(f"配置验证失败: {error}")
            return False
        
        return True
