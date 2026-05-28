"""
会话上下文管理器模块
提供完整的会话上下文管理功能，包括历史检索、权重计算、上下文注入等
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from app.core.base import Message
from app.memory.storage import MemoryStorage
from app.memory.vector import VectorStore
import logging
import json
import hashlib

logger = logging.getLogger(__name__)


class ContextWeighter:
    """上下文权重计算器"""
    
    def __init__(self, llm=None):
        self.llm = llm
        self.half_life_days = 7  # 半衰期
        self.semantic_weight = 0.4
        self.keyword_weight = 0.3
        self.importance_weight = 0.3
        
    def calculate_time_decay(self, created_at: datetime) -> float:
        """计算时间衰减权重
        
        使用指数衰减：weight = 0.5^(days/half_life)
        """
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        days_since = (datetime.now() - created_at).days
        return 0.5 ** (days_since / max(self.half_life_days, 1))
    
    def calculate_keyword_overlap(self, text1: str, text2: str) -> float:
        """计算关键词重叠度
        
        基于TF-IDF的简化版本
        """
        # 提取关键词（简化版：分词后取重复词）
        words1 = set(self._tokenize(text1))
        words2 = set(self._tokenize(text2))
        
        # 停用词列表
        stop_words = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
        words1 = words1 - stop_words
        words2 = words2 - stop_words
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0
    
    def _tokenize(self, text: str) -> List[str]:
        """简单分词"""
        # 简化处理：按标点和空格分割
        import re
        tokens = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', text.lower())
        return tokens
    
    async def calculate_relevance(self, current_message: str, 
                                   historical_message: str,
                                   importance: int = 1) -> float:
        """计算相关度评分
        
        综合考虑：
        1. 语义相似度 (0-0.4)
        2. 关键词重叠度 (0-0.3)
        3. 重要性评分 (0-0.3)
        """
        # 关键词重叠度
        keyword_score = self.calculate_keyword_overlap(
            current_message, 
            historical_message
        )
        
        # 语义相似度（如果有LLM）
        semantic_score = 0.0
        if self.llm:
            try:
                embedding1 = await self.llm.get_embedding(current_message)
                embedding2 = await self.llm.get_embedding(historical_message)
                semantic_score = self._cosine_similarity(embedding1, embedding2)
            except Exception as e:
                logger.warning(f"语义相似度计算失败: {e}")
        
        # 重要性权重 (归一化到0-0.3)
        importance_score = min(importance / 10.0, 1.0) * 0.3
        
        # 综合评分
        return (semantic_score * self.semantic_weight + 
                keyword_score * self.keyword_weight + 
                importance_score)
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def calculate_final_weight(self, time_decay: float, relevance: float,
                               position: int, max_context: int) -> float:
        """计算最终权重
        
        综合考虑：
        1. 时间衰减 (0-0.2)
        2. 相关度 (0-0.5)
        3. 位置权重 (0-0.3)
        """
        # 位置权重：越近的消息权重越高
        position_weight = 1.0 - (position / max(max_context, 1)) * 0.5
        
        return time_decay * 0.2 + relevance * 0.5 + position_weight * 0.3


class ContextTracker:
    """上下文追踪器"""
    
    def __init__(self, memory_storage: MemoryStorage, 
                 vector_store: VectorStore = None,
                 llm = None):
        self.memory_storage = memory_storage
        self.vector_store = vector_store
        self.llm = llm
        self.weighter = ContextWeighter(llm)
        
    async def get_relevant_history(
        self,
        session_id: str,
        current_message: str,
        max_messages: int = 10,
        max_tokens: int = 2000
    ) -> List[Dict[str, Any]]:
        """获取相关的历史消息
        
        Args:
            session_id: 会话ID
            current_message: 当前消息
            max_messages: 最大消息数
            max_tokens: 最大token数
            
        Returns:
            List[Dict]: 相关历史消息列表（带权重）
        """
        try:
            # 获取会话的所有历史消息
            all_messages = await self.memory_storage.get_messages(session_id)
            
            if not all_messages:
                return []
            
            # 计算每条消息的权重
            weighted_messages = []
            
            for i, msg in enumerate(reversed(all_messages)):  # 从新到旧
                # 时间衰减
                time_decay = self.weighter.calculate_time_decay(msg.created_at)
                
                # 相关度
                relevance = await self._calculate_message_relevance(
                    current_message,
                    msg.content,
                    getattr(msg, 'importance', 1)
                )
                
                # 最终权重
                final_weight = self.weighter.calculate_final_weight(
                    time_decay,
                    relevance,
                    len(all_messages) - i,
                    len(all_messages)
                )
                
                # token估算
                tokens = self._estimate_tokens(msg.content)
                
                weighted_messages.append({
                    'message': msg,
                    'time_decay': time_decay,
                    'relevance': relevance,
                    'final_weight': final_weight,
                    'tokens': tokens
                })
            
            # 按权重排序
            weighted_messages.sort(key=lambda x: x['final_weight'], reverse=True)
            
            # 选择权重最高的，同时保留最近的
            selected = []
            recent_count = min(3, len(all_messages))  # 至少保留最近3条
            recent_messages = [item['message'] for item in weighted_messages[-recent_count:]]
            recent_message_ids = {msg.id for msg in recent_messages if msg.id is not None}
            recent_contents = {msg.content for msg in recent_messages}
            
            current_tokens = 0
            for wm in weighted_messages:
                msg = wm['message']
                # 跳过最近的（已保留）
                if (msg.id is not None and msg.id in recent_message_ids) or msg.content in recent_contents:
                    continue
                
                # 检查token限制
                if current_tokens + wm['tokens'] <= max_tokens and len(selected) < max_messages - recent_count:
                    selected.append(wm)
                    current_tokens += wm['tokens']
            
            # 合并并按时间排序
            final_messages = selected + [{'message': msg} for msg in recent_messages]
            final_messages.sort(key=lambda x: x['message'].created_at or "")
            
            logger.info(f"选择上下文消息: {len(final_messages)} 条")
            
            return final_messages
            
        except Exception as e:
            logger.error(f"获取相关历史失败: {e}", exc_info=True)
            return []
    
    async def _calculate_message_relevance(self, current_message: str, 
                                     historical_message: str,
                                     importance: int = 1) -> float:
        """计算消息相关度（内部方法，避免递归）"""
        return await self.weighter.calculate_relevance(
            current_message,
            historical_message,
            importance
        )
    
    def _estimate_tokens(self, text: str) -> int:
        """估算token数量（简化版：中文按2计算，英文按1计算）"""
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        english_words = len([w for w in text.split() if w.isalpha()])
        other_chars = len(text) - chinese_chars - sum(1 for c in text if c.isspace())
        
        # 中文2个token/字，英文单词1个token，其他1个token
        return chinese_chars * 2 + english_words * 1 + other_chars


class SessionContextManager:
    """会话上下文管理器"""
    
    def __init__(self, memory_storage: MemoryStorage,
                 vector_store: VectorStore = None,
                 llm = None):
        self.memory_storage = memory_storage
        self.vector_store = vector_store
        self.tracker = ContextTracker(memory_storage, vector_store, llm)
        self.weighter = ContextWeighter(llm)
        self.llm = llm
        
        # 缓存
        self.context_cache: Dict[str, Dict] = {}
        self.cache_ttl = 300  # 5分钟
        
    async def build_context(
        self,
        session_id: str,
        current_message: str,
        use_memory: bool = True,
        include_settings: bool = True
    ) -> Tuple[List[Message], Dict[str, Any]]:
        """构建完整上下文
        
        Args:
            session_id: 会话ID
            current_message: 当前消息
            use_memory: 是否使用长期记忆
            include_settings: 是否包含设定
            
        Returns:
            Tuple[List[Message], Dict]: (上下文消息列表, 元数据)
        """
        context_messages = []
        metadata = {
            'history_count': 0,
            'memory_count': 0,
            'token_count': 0,
            'cache_hit': False,
            'user_messages': 0,
            'assistant_messages': 0,
            'system_messages': 0
        }
        
        # 检查缓存
        cache_key = f"{session_id}:{hashlib.md5(current_message.encode()).hexdigest()}"
        if cache_key in self.context_cache:
            cached = self.context_cache[cache_key]
            if (datetime.now() - cached['timestamp']).total_seconds() < self.cache_ttl:
                logger.info("使用缓存的上下文")
                metadata['cache_hit'] = True
                return cached['messages'], metadata
        
        # 1. 添加设定（如果需要）
        if include_settings:
            settings = await self.memory_storage.get_all_settings(session_id)
            for setting in settings[:5]:  # 最多5个设定
                context_messages.append(Message(
                    role="system",
                    content=f"[设定] {setting['key']}: {setting['value']}"
                ))
                metadata['system_messages'] += 1
        
        # 2. 获取并注入相关历史消息 - 按时间顺序，保持对话连贯性
        relevant_history = await self._get_contextual_history(
            session_id,
            current_message,
            max_messages=50,
            max_tokens=6000
        )
        
        # 添加历史消息，按时间顺序
        for item in relevant_history:
            msg = item['message']
            context_messages.append(Message(
                role=msg.role,
                content=msg.content
            ))
            metadata['history_count'] += 1
            metadata['token_count'] += self._estimate_tokens(msg.content)
            
            # 统计用户和助手消息数量
            if msg.role == 'user':
                metadata['user_messages'] += 1
            elif msg.role == 'assistant':
                metadata['assistant_messages'] += 1
        
        # 3. 获取并注入相关长期记忆（如果需要）
        if use_memory and self.vector_store and self.llm:
            try:
                embedding = await self.llm.get_embedding(current_message)
                memories = await self.vector_store.search(
                    current_message,
                    embedding,
                    k=5,
                    session_id=session_id
                )
                
                for memory in memories:
                    context_messages.append(Message(
                        role="system",
                        content=f"[相关记忆] {memory.content}"
                    ))
                    metadata['memory_count'] += 1
                    metadata['system_messages'] += 1
                    
            except Exception as e:
                logger.warning(f"记忆检索失败: {e}")
        
        # 缓存结果
        self.context_cache[cache_key] = {
            'messages': context_messages,
            'timestamp': datetime.now()
        }
        
        logger.info(f"构建上下文完成: 用户消息{metadata['user_messages']}条, "
                   f"助手消息{metadata['assistant_messages']}条, "
                   f"记忆{metadata['memory_count']}条")
        
        return context_messages, metadata
    
    async def _get_contextual_history(
        self,
        session_id: str,
        current_message: str,
        max_messages: int = 50,
        max_tokens: int = 6000
    ) -> List[Dict[str, Any]]:
        """获取用于上下文的历史消息，保持原始时间顺序并限制长度。"""
        try:
            all_messages = await self.memory_storage.get_messages(session_id)
            logger.info(f"会话 {session_id} 总共有 {len(all_messages)} 条历史消息")

            if not all_messages:
                return []

            contextual_messages = []
            current_tokens = 0

            # 只保留最近的消息，并确保按原始顺序返回，避免错配 user/assistant
            for msg in all_messages[-max_messages:]:
                if msg.role not in {"user", "assistant"}:
                    continue
                tokens = self._estimate_tokens(msg.content)
                if current_tokens + tokens > max_tokens:
                    continue

                contextual_messages.append({
                    'message': msg,
                    'time_decay': 1.0,
                    'relevance': 0.5,
                    'final_weight': 1.0,
                    'tokens': tokens
                })
                current_tokens += tokens

            logger.info(f"上下文历史: {len(contextual_messages)} 条消息, token约{current_tokens}")
            return contextual_messages

        except Exception as e:
            logger.error(f"获取上下文历史失败: {e}", exc_info=True)
            return []

    async def _calculate_message_relevance(
        self,
        current_message: str,
        historical_message: str,
        importance: int = 1
    ) -> float:
        """复用ContextTracker的相关度计算实现。"""
        return await self.tracker._calculate_message_relevance(
            current_message,
            historical_message,
            importance
        )

    def _estimate_tokens(self, text: str) -> int:
        """复用ContextTracker的token估算实现。"""
        return self.tracker._estimate_tokens(text)
    
    async def validate_coherence(
        self,
        session_id: str,
        new_message: str
    ) -> Dict[str, Any]:
        """验证上下文连贯性
        
        Args:
            session_id: 会话ID
            new_message: 新消息
            
        Returns:
            Dict: 验证结果
        """
        try:
            # 获取最近的消息
            recent_messages = await self.memory_storage.get_messages(session_id)
            recent_messages = [m for m in recent_messages if m.role in {"user", "assistant"}]
            recent_messages = recent_messages[-5:]  # 最近5条
            
            if not recent_messages:
                return {
                    'is_coherent': True,
                    'coherence_score': 1.0,
                    'conflicts': [],
                    'suggestions': []
                }
            
            # 检查话题连续性（简化版）
            last_message = recent_messages[-1]
            
            # 话题关键词检查
            last_keywords = set(self.weighter._tokenize(last_message.content))
            new_keywords = set(self.weighter._tokenize(new_message))
            
            # 计算重叠度
            overlap = len(last_keywords & new_keywords) / max(len(last_keywords), 1)
            
            # 判断是否连贯
            is_coherent = overlap > 0.2 or len(recent_messages) < 3
            
            # 生成建议
            suggestions = []
            if not is_coherent:
                suggestions.append("检测到话题可能切换，建议开启新会话或明确说明")
            
            return {
                'is_coherent': is_coherent,
                'coherence_score': min(overlap * 2, 1.0),
                'conflicts': [],
                'suggestions': suggestions,
                'topic_overlap': overlap
            }
            
        except Exception as e:
            logger.error(f"上下文验证失败: {e}")
            return {
                'is_coherent': True,
                'coherence_score': 0.0,
                'conflicts': [str(e)],
                'suggestions': []
            }
    
    def clear_cache(self, session_id: Optional[str] = None):
        """清除缓存
        
        Args:
            session_id: 可选的会话ID，如果提供则只清除该会话的缓存
        """
        if session_id:
            # 清除特定会话的缓存
            self.context_cache = {
                k: v for k, v in self.context_cache.items()
                if not k.startswith(session_id)
            }
        else:
            self.context_cache.clear()
        
        logger.info(f"上下文缓存已清除")
