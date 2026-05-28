"""
DreamingEngine - 梦境引擎

梦境引擎负责协调三阶段睡眠过程的执行：Light → REM → Deep
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import Counter
import json
import logging
import sqlite3
from uuid import uuid4
import re
import os

from app.dreaming.config import DreamingConfig
from app.dreaming.signals import (
    PhaseSignal, PhaseType, DreamCandidate,
    CandidateStatus, SourceType, Insight
)
from app.dreaming.backfill import REMBackfill

logger = logging.getLogger(__name__)


class DreamingEngine:
    """梦境引擎 - 三阶段记忆整合协调器"""
    
    def __init__(
        self,
        memory_storage=None,
        vector_store=None,
        llm=None,
        config=None
    ):
        """初始化梦境引擎"""
        self.memory_storage = memory_storage
        self.vector_store = vector_store
        self.llm = llm
        self.config = config or DreamingConfig()
        self.phase_signals: Dict[str, PhaseSignal] = {}
        self.current_sweep_id: Optional[str] = None
        self.db_path = self.config.db_path
        self.backfill = REMBackfill(dreams_dir=os.path.join(
            os.path.dirname(self.db_path) or '.', 'dreams'
        ))

        logger.info("DreamingEngine 初始化完成")
    
    async def run_full_sweep(self) -> Dict[str, Any]:
        """执行完整的梦境扫描"""
        self.current_sweep_id = str(uuid4())
        logger.info(f"开始梦境扫描: sweep_id={self.current_sweep_id}")
        
        start_time = datetime.now()
        results = {
            'sweep_id': self.current_sweep_id,
            'light': {},
            'rem': {},
            'deep': {},
            'status': 'running',
            'start_time': start_time.isoformat(),
        }
        
        try:
            logger.info("=== 开始 Light Sleep 阶段 ===")
            light_result = await self._light_sleep()
            results['light'] = light_result
            
            logger.info("=== 开始 REM Sleep 阶段 ===")
            rem_result = await self._rem_sleep()
            results['rem'] = rem_result
            
            logger.info("=== 开始 Deep Sleep 阶段 ===")
            deep_result = await self._deep_sleep()
            results['deep'] = deep_result
            
            end_time = datetime.now()
            results['status'] = 'completed'
            results['end_time'] = end_time.isoformat()
            results['duration_seconds'] = (end_time - start_time).total_seconds()
            
            logger.info(f"梦境扫描完成")
            
            return results
            
        except Exception as e:
            logger.error(f"梦境扫描失败: {e}", exc_info=True)
            results['status'] = 'failed'
            results['error'] = str(e)
            raise
    
    async def _light_sleep(self) -> Dict[str, Any]:
        """Light Sleep 阶段：整理和暂存"""
        lookback_days = self.config.get('lookback_days', 7)
        cutoff_date = datetime.now() - timedelta(days=lookback_days)
        
        result = {
            'sessions_processed': 0,
            'messages_processed': 0,
            'candidates_created': 0,
            'duplicates_removed': 0,
            'status': 'completed'
        }
        
        try:
            if not self.memory_storage:
                logger.warning("memory_storage 未初始化")
                return result
            
            sessions = await self.memory_storage.get_sessions()
            result['sessions_processed'] = len(sessions)

            corpus_entries = []
            for session in sessions:
                try:
                    messages = await self.memory_storage.get_messages(session.id)
                    result['messages_processed'] += len(messages)

                    for msg in messages:
                        # 按日期过滤消息
                        msg_date = getattr(msg, 'created_at', None)
                        if msg_date:
                            try:
                                if isinstance(msg_date, str):
                                    msg_dt = datetime.fromisoformat(msg_date.replace('Z', '+00:00'))
                                else:
                                    msg_dt = msg_date
                                if msg_dt.replace(tzinfo=None) < cutoff_date:
                                    continue
                            except (ValueError, TypeError):
                                pass

                        if self._is_significant_content(msg.content):
                            corpus_entries.append({
                                'session_id': session.id,
                                'content': msg.content,
                                'role': msg.role,
                                'created_at': getattr(msg, 'created_at', None)
                            })
                except Exception as e:
                    logger.warning(f"处理会话失败: {session.id}, {e}")
            
            deduped_entries = self._jaccard_deduplicate(corpus_entries)
            result['duplicates_removed'] = len(corpus_entries) - len(deduped_entries)
            
            for entry in deduped_entries:
                candidate = await self._create_candidate(entry, SourceType.CONVERSATION)
                
                signal = PhaseSignal(
                    entry_id=candidate.id,
                    source_phase=PhaseType.LIGHT,
                    reinforcement_value=1.0,
                    reason='fresh_candidate',
                    sweep_id=self.current_sweep_id
                )
                self.phase_signals[f"light_{candidate.id}"] = signal
                result['candidates_created'] += 1
            
            # 写入当日日记
            diary_summary = (
                f"Light Sleep 处理了 {result['messages_processed']} 条消息，"
                f"创建 {result['candidates_created']} 个候选，"
                f"去重 {result['duplicates_removed']} 条"
            )
            try:
                self.backfill.write_diary_entry(diary_summary)
            except Exception as e:
                logger.warning(f"写入日记失败: {e}")

            await self._write_dream_log('light', result)

        except Exception as e:
            logger.error(f"Light Sleep 阶段执行失败: {e}", exc_info=True)
            result['status'] = 'failed'
            result['error'] = str(e)
        
        return result
    
    async def _rem_sleep(self) -> Dict[str, Any]:
        """REM Sleep 阶段：主题发现和模式识别"""
        result = {
            'candidates_analyzed': 0,
            'themes_discovered': 0,
            'insights_generated': 0,
            'reinforcement_signals': 0,
            'status': 'completed'
        }
        
        try:
            candidates = await self._get_pending_candidates()
            result['candidates_analyzed'] = len(candidates)
            
            tag_frequencies = Counter()
            for candidate in candidates:
                tag_frequencies.update(candidate.concept_tags)
            
            dominant_themes = tag_frequencies.most_common(5)
            result['themes_discovered'] = len(dominant_themes)
            
            for theme, count in dominant_themes:
                related_candidates = [
                    c for c in candidates 
                    if theme in c.concept_tags
                ]
                
                for candidate in related_candidates:
                    confidence = min(count / 10.0, 1.0)
                    
                    signal = PhaseSignal(
                        entry_id=candidate.id,
                        source_phase=PhaseType.REM,
                        reinforcement_value=confidence * 0.5,
                        reason=f'related_to_theme: {theme}',
                        sweep_id=self.current_sweep_id
                    )
                    self.phase_signals[f"rem_{candidate.id}"] = signal
                    result['reinforcement_signals'] += 1
            
            await self._write_dream_log('rem', result)
            
        except Exception as e:
            logger.error(f"REM Sleep 阶段执行失败: {e}", exc_info=True)
            result['status'] = 'failed'
            result['error'] = str(e)
        
        return result
    
    async def _deep_sleep(self) -> Dict[str, Any]:
        """Deep Sleep 阶段：评分和晋升"""
        result = {
            'candidates_scored': 0,
            'promoted': 0,
            'rejected': 0,
            'average_score': 0.0,
            'status': 'completed'
        }
        
        try:
            candidates = await self._get_pending_candidates()
            result['candidates_scored'] = len(candidates)
            
            total_scores = []
            
            for candidate in candidates:
                light_signal = self.phase_signals.get(f"light_{candidate.id}")
                rem_signal = self.phase_signals.get(f"rem_{candidate.id}")
                
                if light_signal:
                    candidate.phase_signal_light = light_signal.reinforcement_value
                if rem_signal:
                    candidate.phase_signal_rem = rem_signal.reinforcement_value
                
                await self._calculate_dimensions(candidate)
                
                final_score = candidate.calculate_final_score(
                    light_signal_weight=self.config.light_signal_weight,
                    rem_signal_weight=self.config.rem_signal_weight
                )
                total_scores.append(final_score)
                
                promoted = await self._evaluate_and_promote(candidate)
                
                if promoted:
                    result['promoted'] += 1
                else:
                    result['rejected'] += 1
            
            if total_scores:
                result['average_score'] = sum(total_scores) / len(total_scores)
            
            await self._write_dream_log('deep', result)
            await self._update_memory_file(promoted_count=result['promoted'])

            # REM Backfill: 将晋升候选也写入 DREAMS.md
            try:
                self.backfill.backfill_to_dreams(days=1)
            except Exception as e:
                logger.warning(f"REM 回填失败: {e}")
            
        except Exception as e:
            logger.error(f"Deep Sleep 阶段执行失败: {e}", exc_info=True)
            result['status'] = 'failed'
            result['error'] = str(e)
        
        return result
    
    def _is_significant_content(self, content: str) -> bool:
        """判断消息内容是否有价值"""
        if len(content) < 10:
            return False
        
        useless_patterns = [
            r'^[啊呀哈嗯哦呃]+$',
            r'^好的?$',
            r'^收到$',
            r'^ok+$',
            r'^👍+$',
        ]
        
        for pattern in useless_patterns:
            if re.match(pattern, content.strip()):
                return False
        
        return True
    
    def _jaccard_deduplicate(self, entries: List[Dict], threshold: float = 0.9) -> List[Dict]:
        """Jaccard 相似度去重 - 使用minhash优化"""
        if not entries:
            return []

        def tokenize(text: str) -> set:
            text = text.lower()
            # 中英文混合tokenize
            english_tokens = set(re.findall(r'[a-zA-Z]{2,}', text))
            chinese_tokens = set(re.findall(r'[一-鿿]+', text))
            return english_tokens | chinese_tokens

        def jaccard_similarity(set1: set, set2: set) -> float:
            if not set1 or not set2:
                return 0.0
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            return intersection / union if union > 0 else 0.0

        unique_entries = []
        seen_signatures = []

        for entry in entries:
            content = entry.get('content', '')
            signature = tokenize(content)

            # 使用any而非嵌套循环，稍微优化
            is_duplicate = any(
                jaccard_similarity(signature, seen_sig) >= threshold
                for seen_sig in seen_signatures
            )

            if not is_duplicate:
                unique_entries.append(entry)
                seen_signatures.append(signature)

        return unique_entries
    
    async def _create_candidate(self, entry: Dict, source_type: SourceType) -> DreamCandidate:
        """创建候选记忆"""
        candidate_id = str(uuid4())
        
        candidate = DreamCandidate(
            id=candidate_id,
            source_session_id=entry.get('session_id', ''),
            content=entry.get('content', ''),
            source_type=source_type,
            concept_tags=self._simple_keyword_extraction(entry.get('content', ''))
        )
        
        await self._save_candidate(candidate)
        
        return candidate
    
    def _simple_keyword_extraction(self, content: str) -> List[str]:
        """简单的关键词提取（支持中英文）"""
        stopwords = {
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '他', '她', '它', '们', '这个', '那个', '什么', '怎么', '如何', '为什么', '因为', '所以', '但是', '然而', '如果', '虽然', '还是', '或者', '而且', '并且', '可以', '可能', '应该', '需要', '开始', '进行', '完成', '已经', '正在', '之后', '之前', '时候', '地方', '事情', '问题', '方式', '方法', '感觉', '觉得', '知道', '相信', '希望', '愿意', '准备', '想要', '能够', '必须', '一定', '当然', '确实', '真是', '真是', '特别', '非常', '比较', '相当', '极', '甚', '更', '最', '太', '过', '真', '挺', '蛮', '怪', '好', '真', '可', '挺', '老', '甚', '极', '最', '太', '过', '更', '甚', '极', 'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'but', 'and', 'or', 'if', 'because', 'until', 'while', 'although', 'though', 'this', 'that', 'these', 'those', 'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves'
        }

        # 英文提取
        english_words = re.findall(r'[a-zA-Z]{3,}', content.lower())
        # 中文提取（按字符，不限于单词）
        chinese_chars = re.findall(r'[一-鿿]+', content)

        all_words = []
        for w in english_words:
            if w not in stopwords:
                all_words.append(w)

        for chars in chinese_chars:
            # 逐字符过滤并组成2-4字词
            filtered_chars = [c for c in chars if c not in stopwords]
            for i in range(len(filtered_chars)):
                for length in [2, 3, 4]:
                    if i + length <= len(filtered_chars):
                        word = ''.join(filtered_chars[i:i+length])
                        if word not in stopwords and len(word) >= 2:
                            all_words.append(word)

        word_freq = Counter(all_words)
        return [word for word, _ in word_freq.most_common(10)][:5]
    
    async def _save_candidate(self, candidate: DreamCandidate):
        """保存候选到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO dream_candidates
                (id, source_session_id, content, source_type, concept_tags, recall_count,
                 unique_query_count, query_diversity_score, relevance_score, recency_score,
                 consolidation_score, conceptual_richness_score, total_score, phase_signal_light,
                 phase_signal_rem, final_score, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                candidate.id,
                candidate.source_session_id,
                candidate.content,
                candidate.source_type.value if isinstance(candidate.source_type, SourceType) else candidate.source_type,
                json.dumps(candidate.concept_tags),
                candidate.recall_count,
                candidate.unique_query_count,
                candidate.query_diversity_score,
                candidate.relevance_score,
                candidate.recency_score,
                candidate.consolidation_score,
                candidate.conceptual_richness_score,
                candidate.total_score,
                candidate.phase_signal_light,
                candidate.phase_signal_rem,
                candidate.final_score,
                candidate.status.value if isinstance(candidate.status, CandidateStatus) else candidate.status,
                candidate.created_at,
                datetime.now().isoformat(),
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"保存候选失败: {e}")
    
    async def _write_dream_log(self, phase: str, data: Dict):
        """写入梦境日记 (同时写入 DREAMS.md)"""
        try:
            log_dir = os.path.join(os.path.dirname(self.db_path) or '.', 'dreams')
            os.makedirs(log_dir, exist_ok=True)

            # 原有的详细日志
            log_file = os.path.join(log_dir, 'dreams.md')
            timestamp = datetime.now().isoformat()
            content = f"\n## {phase.upper()} - {timestamp}\n\n"
            content += f"Sweep ID: {self.current_sweep_id}\n\n"
            content += f"```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```\n\n"

            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(content)

            # DREAMS.md - 人类友好格式
            dreams_file = os.path.join(log_dir, 'DREAMS.md')
            phase_icon = {"light": "🌙", "rem": "💭", "deep": "😴"}.get(phase, "🌙")

            dreams_entry = (
                f"\n---\n"
                f"### {phase_icon} {phase.upper()} - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            )

            if phase == "light":
                dreams_entry += (
                    f"- 处理会话: {data.get('sessions_processed', 0)}\n"
                    f"- 处理消息: {data.get('messages_processed', 0)}\n"
                    f"- 创建候选: {data.get('candidates_created', 0)}\n"
                )
            elif phase == "rem":
                dreams_entry += (
                    f"- 分析候选: {data.get('candidates_analyzed', 0)}\n"
                    f"- 发现主题: {data.get('themes_discovered', 0)}\n"
                    f"- 生成洞察: {data.get('insights_generated', 0)}\n"
                )
            elif phase == "deep":
                dreams_entry += (
                    f"- 评分候选: {data.get('candidates_scored', 0)}\n"
                    f"- 晋升: {data.get('promoted', 0)}\n"
                    f"- 拒绝: {data.get('rejected', 0)}\n"
                    f"- 平均分: {data.get('average_score', 0):.2f}\n"
                )

            with open(dreams_file, 'a', encoding='utf-8') as f:
                f.write(dreams_entry)

        except Exception as e:
            logger.warning(f"写入梦境日记失败: {e}")
    
    async def _get_pending_candidates(self) -> List[DreamCandidate]:
        """获取待处理的候选"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, source_session_id, content, source_type, concept_tags,
                       recall_count, unique_query_count, query_diversity_score,
                       relevance_score, recency_score, consolidation_score,
                       conceptual_richness_score, total_score, phase_signal_light,
                       phase_signal_rem, final_score, status, created_at, updated_at
                FROM dream_candidates
                WHERE status = 'pending'
            """)
            
            rows = cursor.fetchall()
            conn.close()
            
            candidates = []
            for row in rows:
                concept_tags = row[4]
                if isinstance(concept_tags, str):
                    try:
                        concept_tags = json.loads(concept_tags)
                    except:
                        concept_tags = []
                
                candidates.append(DreamCandidate(
                    id=row[0],
                    source_session_id=row[1],
                    content=row[2],
                    source_type=SourceType(row[3]),
                    concept_tags=concept_tags,
                    recall_count=row[5],
                    unique_query_count=row[6],
                    query_diversity_score=row[7],
                    relevance_score=row[8],
                    recency_score=row[9],
                    consolidation_score=row[10],
                    conceptual_richness_score=row[11],
                    total_score=row[12],
                    phase_signal_light=row[13],
                    phase_signal_rem=row[14],
                    final_score=row[15],
                    status=CandidateStatus(row[16]),
                    created_at=row[17],
                    updated_at=row[18],
                ))
            
            return candidates
            
        except Exception as e:
            logger.error(f"获取候选失败: {e}")
            return []
    
    async def _calculate_dimensions(self, candidate: DreamCandidate):
        """计算六维评分"""
        now = datetime.now()
        
        if candidate.created_at:
            try:
                created = datetime.fromisoformat(candidate.created_at)
                days_old = (now - created).days
                candidate.recency_score = max(0.0, 1.0 - (days_old / 30.0))
            except:
                candidate.recency_score = 0.5
        else:
            candidate.recency_score = 0.5
        
        if candidate.recall_count > 0:
            candidate.relevance_score = min(1.0, candidate.recall_count / 10.0)
        else:
            candidate.relevance_score = 0.3
        
        candidate.conceptual_richness_score = min(1.0, len(candidate.concept_tags) / 5.0)
        
        if candidate.unique_query_count > 0:
            candidate.query_diversity_score = min(1.0, candidate.unique_query_count / 5.0)
        else:
            candidate.query_diversity_score = 0.2
        
        candidate.consolidation_score = 0.3
    
    async def _evaluate_and_promote(self, candidate: DreamCandidate) -> bool:
        """评估并晋升候选"""
        try:
            meets_threshold = (
                candidate.final_score >= self.config.min_score and
                candidate.recall_count >= self.config.min_recall_count and
                candidate.unique_query_count >= self.config.min_unique_queries
            )
            
            # 新创建的候选具有默认值 0，需要给予初始机会
            # 对于 recall_count == 0 的新候选，使用 final_score 作为主要评判依据
            if candidate.recall_count == 0 and candidate.unique_query_count == 0:
                meets_threshold = candidate.final_score >= self.config.min_score

            candidate.status = CandidateStatus.PROMOTED if meets_threshold else CandidateStatus.REJECTED

            if meets_threshold:
                candidate.promoted_at = datetime.now().isoformat()
                logger.info(f"候选已晋升: {candidate.id}, 分数: {candidate.final_score:.2f}")
            else:
                logger.info(f"候选被拒绝: {candidate.id}, 分数: {candidate.final_score:.2f}")
            
            await self._save_candidate(candidate)
            
            return meets_threshold
            
        except Exception as e:
            logger.error(f"评估候选失败: {e}")
            return False
    
    async def _update_memory_file(self, promoted_count: int):
        """更新 MEMORY.md 文件 (写入实际晋升内容)"""
        try:
            memory_dir = os.path.join(os.path.dirname(self.db_path) or '.', 'hermes')
            os.makedirs(memory_dir, exist_ok=True)

            # 获取晋升的候选
            promoted = []
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT content FROM dream_candidates WHERE status = 'promoted' ORDER BY final_score DESC LIMIT 20"
                )
                promoted = [row[0] for row in cursor.fetchall()]
                conn.close()
            except Exception:
                pass

            memory_file = os.path.join(memory_dir, 'MEMORY.md')

            lines = [
                f"# 长期记忆",
                f"",
                f"最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                f"本次晋升: {promoted_count} 条",
                f"累计记忆: {len(promoted)} 条",
                f"",
            ]

            if promoted:
                lines.append("## 记忆内容\n")
                for i, content in enumerate(promoted, 1):
                    lines.append(f"- {content[:200]}")

            with open(memory_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')

        except Exception as e:
            logger.warning(f"更新MEMORY.md失败: {e}")
    
    async def get_status(self) -> Dict[str, Any]:
        """获取梦境系统状态"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM dream_candidates WHERE status = 'pending'")
            pending_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM dream_candidates WHERE status = 'promoted'")
            promoted_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM dream_candidates")
            total_count = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'enabled': self.config.enabled,
                'last_sweep': self.current_sweep_id,
                'pending_candidates': pending_count,
                'total_promoted': promoted_count,
                'total_candidates': total_count,
            }
            
        except Exception as e:
            logger.error(f"获取状态失败: {e}")
            return {
                'enabled': self.config.enabled,
                'last_sweep': None,
                'pending_candidates': 0,
                'total_promoted': 0,
                'total_candidates': 0,
            }
