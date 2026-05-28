"""
SkillManager - 技能管理器完整实现

支持五阶段闭环学习：Execute → Evaluate → Extract → Refine → Reuse
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import Counter
import json
import logging
import sqlite3
from uuid import uuid4
import re

from app.skills.models import Skill, SkillDraft, SkillUsageLog, TaskResult, SkillStatus

logger = logging.getLogger(__name__)


class SkillManager:
    """技能管理器 - 五阶段闭环学习协调器"""
    
    def __init__(
        self,
        memory_storage=None,
        llm=None,
        db_path: str = "./data/tongyong.db"
    ):
        """初始化技能管理器"""
        self.memory_storage = memory_storage
        self.llm = llm
        self.db_path = db_path
        
        self.refinement_threshold = 10
        self.min_pattern_length = 5
        
        logger.info("SkillManager 初始化完成")
    
    async def execute_evaluate_extract_refine(
        self,
        session_id: str,
        execution_result: TaskResult
    ) -> Optional[Skill]:
        """
        执行五阶段闭环学习
        
        1. Evaluate - 评估任务是否值得提取
        2. Extract - 从执行轨迹提取技能
        3. Refine - 优化或创建技能
        
        Args:
            session_id: 会话 ID
            execution_result: 任务执行结果
            
        Returns:
            Optional[Skill]: 创建或优化的技能
        """
        logger.info(f"开始五阶段学习: session={session_id}")
        
        try:
            is_non_trivial = await self._evaluate_significance(execution_result)
            if not is_non_trivial:
                logger.info("任务过于简单，跳过技能提取")
                return None
            
            skill_draft = await self._extract_skill(execution_result)
            if not skill_draft:
                logger.warning("技能提取失败")
                return None
            
            existing_skills = await self.search_skills(skill_draft.name)
            
            if existing_skills:
                optimized = await self._refine_skill(existing_skills[0], skill_draft)
                logger.info(f"技能已优化: {optimized.name}, 版本: {optimized.version}")
                return optimized
            else:
                new_skill = await self._create_skill(skill_draft)
                logger.info(f"新技能已创建: {new_skill.name}")
                return new_skill
                
        except Exception as e:
            logger.error(f"五阶段学习执行失败: {e}", exc_info=True)
            return None
    
    async def _evaluate_significance(self, execution_result: TaskResult) -> bool:
        """
        评估任务是否具有非平凡性
        
        判断标准：
        - 执行轨迹长度（至少2个步骤）
        - 成功与否
        - 任务复杂度
        
        Args:
            execution_result: 任务执行结果
            
        Returns:
            bool: 是否值得提取
        """
        if len(execution_result.trajectory) < 2:
            return False
        
        if not execution_result.success:
            return False
        
        unique_actions = set()
        for step in execution_result.trajectory:
            action = step.get('action', '')
            if action:
                unique_actions.add(action)
        
        if len(unique_actions) < 2:
            return False
        
        return True
    
    async def _extract_skill(self, execution_result: TaskResult) -> Optional[SkillDraft]:
        """
        从执行轨迹提取技能草稿
        
        Args:
            execution_result: 任务执行结果
            
        Returns:
            Optional[SkillDraft]: 提取的技能草稿
        """
        if not self.llm:
            logger.warning("LLM 未初始化，无法提取技能")
            return self._simple_extract_skill(execution_result)
        
        try:
            prompt = self._build_extraction_prompt(execution_result)
            
            _resp = await self.llm.chat([{"role": "user", "content": prompt}])
            response = _resp.content if hasattr(_resp, 'content') else str(_resp)

            skill_draft = self._parse_extraction_response(response)
            
            if skill_draft:
                skill_draft.source_trajectory = execution_result.to_dict()
            
            return skill_draft
            
        except Exception as e:
            logger.error(f"技能提取失败: {e}", exc_info=True)
            return self._simple_extract_skill(execution_result)
    
    def _simple_extract_skill(self, execution_result: TaskResult) -> Optional[SkillDraft]:
        """简单技能提取（无LLM时使用）"""
        try:
            actions = [step.get('action', step.get('details', '')) 
                      for step in execution_result.trajectory]
            
            steps = []
            for i, step in enumerate(execution_result.trajectory):
                action = step.get('action', '')
                details = step.get('details', '')
                if details:
                    steps.append(f"{i+1}. {action}: {details}")
                elif action:
                    steps.append(f"{i+1}. {action}")
            
            skill_name = self._generate_skill_name(execution_result.task_description, steps)
            
            return SkillDraft(
                name=skill_name,
                content=f"执行任务: {execution_result.task_description}",
                trigger_conditions=[execution_result.task_description[:100]],
                execution_steps=steps[:10],
                expected_outcome=execution_result.outcome[:200] if execution_result.outcome else "完成",
                confidence=0.6,
                source_trajectory=execution_result.to_dict()
            )
            
        except Exception as e:
            logger.error(f"简单技能提取失败: {e}")
            return None
    
    def _generate_skill_name(self, task: str, steps: List[str]) -> str:
        """生成技能名称（支持中文）"""
        # 提取中英文关键词
        keywords = []
        for word in task.split():
            word_clean = re.sub(r'[^\w一-鿿]', '', word)
            # 中文词（2 字及以上）或英文词（3 字符及以上）都保留
            if word_clean and (len(word_clean) >= 2):
                keywords.append(word_clean)

        if keywords:
            title = ' '.join(keywords[:4])
            if len(title) > 60:
                title = title[:60]
            return title

        if steps:
            first_step = steps[0][:50]
            return f"Skill: {first_step}"

        return f"CustomSkill_{datetime.now().strftime('%Y%m%d%H%M')}"
    
    def _build_extraction_prompt(self, execution_result: TaskResult) -> str:
        """构建技能提取提示"""
        trajectory_text = "\n".join([
            f"{i+1}. {step.get('action', '')}: {step.get('details', '')}"
            for i, step in enumerate(execution_result.trajectory)
        ])
        
        return f"""从以下执行轨迹中提取可复用的技能。

任务描述：{execution_result.task_description}

执行步骤：
{trajectory_text}

执行结果：{execution_result.outcome}

请提取以下信息（JSON 格式）：
{{
    "name": "技能名称（简洁明了）",
    "content": "技能描述（简要说明此技能的用途）",
    "trigger_conditions": ["触发条件1", "触发条件2"],
    "execution_steps": ["步骤1", "步骤2", "步骤3"],
    "expected_outcome": "预期结果",
    "confidence": 0.8
}}

仅返回 JSON，不要添加其他内容。"""
    
    def _parse_extraction_response(self, response: str) -> Optional[SkillDraft]:
        """解析 LLM 响应"""
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                
                return SkillDraft(
                    name=data.get('name', 'Unnamed Skill'),
                    content=data.get('content', ''),
                    trigger_conditions=data.get('trigger_conditions', []),
                    execution_steps=data.get('execution_steps', []),
                    expected_outcome=data.get('expected_outcome', ''),
                    confidence=data.get('confidence', 0.5),
                )
        except Exception as e:
            logger.warning(f"解析响应失败: {e}")
        
        return None
    
    async def _create_skill(self, skill_draft: SkillDraft) -> Skill:
        """创建新技能"""
        skill = Skill(
            id=str(uuid4()),
            name=skill_draft.name,
            content=skill_draft.content,
            trigger_conditions=skill_draft.trigger_conditions,
            execution_steps=skill_draft.execution_steps,
            expected_outcome=skill_draft.expected_outcome,
        )
        
        await self._save_skill(skill)
        
        return skill
    
    async def _refine_skill(
        self,
        existing_skill: Skill,
        new_draft: SkillDraft
    ) -> Skill:
        """优化现有技能"""
        existing_skill.version += 1
        existing_skill.updated_at = datetime.now().isoformat()
        
        all_conditions = set(existing_skill.trigger_conditions + new_draft.trigger_conditions)
        existing_skill.trigger_conditions = list(all_conditions)
        
        existing_steps = set(existing_skill.execution_steps)
        for step in new_draft.execution_steps:
            if step not in existing_steps:
                existing_skill.execution_steps.append(step)
        
        if new_draft.confidence > 0.7:
            existing_skill.content = new_draft.content
        
        await self._save_skill(existing_skill)
        
        return existing_skill
    
    async def search_skills(self, query: str, k: int = 5) -> List[Skill]:
        """
        搜索相关技能
        
        基于关键字匹配和触发条件相似度
        
        Args:
            query: 查询字符串
            k: 返回数量
            
        Returns:
            List[Skill]: 匹配的技能列表
        """
        try:
            query_lower = query.lower()
            query_words = set(re.findall(r'\w+', query_lower))
            
            all_skills = await self.get_all_skills()
            
            scored_skills = []
            for skill in all_skills:
                score = 0.0
                
                if query_lower in skill.name.lower():
                    score += 5.0
                
                if query_lower in skill.content.lower():
                    score += 2.0
                
                for condition in skill.trigger_conditions:
                    condition_lower = condition.lower()
                    if query_lower in condition_lower:
                        score += 3.0
                    
                    condition_words = set(re.findall(r'\w+', condition_lower))
                    overlap = query_words & condition_words
                    score += len(overlap) * 0.5
                
                for step in skill.execution_steps:
                    if query_lower in step.lower():
                        score += 1.0
                
                if score > 0:
                    scored_skills.append((skill, score))
            
            scored_skills.sort(key=lambda x: x[1], reverse=True)
            
            return [skill for skill, score in scored_skills[:k]]
            
        except Exception as e:
            logger.error(f"搜索技能失败: {e}")
            return []
    
    async def get_all_skills(self) -> List[Skill]:
        """获取所有技能"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, name, content, category, trigger_conditions, execution_steps,
                       expected_outcome, usage_count, success_count, success_rate,
                       version, status, created_at, updated_at
                FROM skills
                WHERE status = 'active'
                ORDER BY usage_count DESC, success_rate DESC
            """)
            
            rows = cursor.fetchall()
            conn.close()
            
            skills = []
            for row in rows:
                skills.append(Skill(
                    id=row[0],
                    name=row[1],
                    content=row[2],
                    category=row[3],
                    trigger_conditions=json.loads(row[4]) if row[4] else [],
                    execution_steps=json.loads(row[5]) if row[5] else [],
                    expected_outcome=row[6] or '',
                    usage_count=row[7],
                    success_count=row[8],
                    success_rate=row[9],
                    version=row[10],
                    status=SkillStatus(row[11]),
                    created_at=row[12],
                    updated_at=row[13],
                ))
            
            return skills
            
        except Exception as e:
            logger.error(f"获取所有技能失败: {e}")
            return []
    
    async def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取技能详情"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, name, content, category, trigger_conditions, execution_steps,
                       expected_outcome, usage_count, success_count, success_rate,
                       version, status, created_at, updated_at
                FROM skills
                WHERE id = ?
            """, (skill_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return Skill(
                    id=row[0],
                    name=row[1],
                    content=row[2],
                    category=row[3],
                    trigger_conditions=json.loads(row[4]) if row[4] else [],
                    execution_steps=json.loads(row[5]) if row[5] else [],
                    expected_outcome=row[6] or '',
                    usage_count=row[7],
                    success_count=row[8],
                    success_rate=row[9],
                    version=row[10],
                    status=SkillStatus(row[11]),
                    created_at=row[12],
                    updated_at=row[13],
                )
            
            return None
            
        except Exception as e:
            logger.error(f"获取技能失败: {e}")
            return None
    
    async def _save_skill(self, skill: Skill):
        """保存技能到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO skills 
                (id, name, content, category, trigger_conditions, execution_steps,
                 expected_outcome, usage_count, success_count, success_rate,
                 version, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                skill.id,
                skill.name,
                skill.content,
                skill.category,
                json.dumps(skill.trigger_conditions),
                json.dumps(skill.execution_steps),
                skill.expected_outcome,
                skill.usage_count,
                skill.success_count,
                skill.success_rate,
                skill.version,
                skill.status.value if isinstance(skill.status, SkillStatus) else skill.status,
                skill.created_at,
                skill.updated_at or datetime.now().isoformat(),
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"保存技能失败: {e}")
            raise
    
    async def log_skill_usage(
        self,
        skill_id: str,
        session_id: str,
        trigger_context: str = "",
        execution_result: str = "",
        success: bool = False,
        feedback: str = ""
    ) -> SkillUsageLog:
        """
        记录技能使用
        
        Args:
            skill_id: 技能 ID
            session_id: 会话 ID
            trigger_context: 触发上下文
            execution_result: 执行结果
            success: 是否成功
            feedback: 用户反馈
            
        Returns:
            SkillUsageLog: 使用记录
        """
        log = SkillUsageLog(
            id=str(uuid4()),
            skill_id=skill_id,
            session_id=session_id,
            trigger_context=trigger_context,
            execution_result=execution_result,
            success=success,
            feedback=feedback,
        )
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO skill_usage_log
                (id, skill_id, session_id, trigger_context, execution_result,
                 success, feedback, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log.id,
                log.skill_id,
                log.session_id,
                log.trigger_context,
                log.execution_result,
                1 if log.success else 0,
                log.feedback,
                log.created_at,
            ))
            
            conn.commit()
            conn.close()
            
            skill = await self.get_skill(skill_id)
            if skill:
                skill.update_success_rate(success)
                await self._save_skill(skill)
            
            if success and skill and skill.usage_count >= self.refinement_threshold:
                await self._trigger_refinement(skill_id)
            
        except Exception as e:
            logger.error(f"记录技能使用失败: {e}")
        
        return log
    
    async def _trigger_refinement(self, skill_id: str):
        """触发技能优化"""
        try:
            skill = await self.get_skill(skill_id)
            if not skill:
                return
            
            recent_logs = await self.get_recent_usage_logs(skill_id, limit=10)
            
            failures = [log for log in recent_logs if not log.success]
            
            if len(failures) > 3:
                logger.info(f"触发技能优化: {skill.name}, 失败次数: {len(failures)}")
                
                if self.llm:
                    refinement_suggestions = await self._generate_refinement_suggestions(
                        skill, failures
                    )
                    logger.info(f"优化建议: {refinement_suggestions}")
            
        except Exception as e:
            logger.error(f"触发技能优化失败: {e}")
    
    async def _generate_refinement_suggestions(
        self,
        skill: Skill,
        failures: List[SkillUsageLog]
    ) -> str:
        """生成优化建议"""
        if not self.llm:
            return "启用LLM以获取详细优化建议"
        
        try:
            failure_contexts = "\n".join([
                f"- {log.trigger_context}: {log.execution_result}"
                for log in failures[:5]
            ])
            
            prompt = f"""分析以下技能的使用失败案例，生成优化建议：

技能名称: {skill.name}
当前步骤: {json.dumps(skill.execution_steps, ensure_ascii=False)}

失败案例:
{failure_contexts}

请提供：
1. 失败原因分析
2. 步骤优化建议
3. 新的执行步骤建议

请简洁回复。"""
            
            _resp = await self.llm.chat([{"role": "user", "content": prompt}])
            response = _resp.content if hasattr(_resp, 'content') else str(_resp)

            return response[:500]
            
        except Exception as e:
            logger.error(f"生成优化建议失败: {e}")
            return "无法生成优化建议"
    
    async def get_recent_usage_logs(
        self,
        skill_id: str,
        limit: int = 10
    ) -> List[SkillUsageLog]:
        """获取技能近期使用记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, skill_id, session_id, trigger_context, execution_result,
                       success, feedback, created_at
                FROM skill_usage_log
                WHERE skill_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (skill_id, limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            logs = []
            for row in rows:
                logs.append(SkillUsageLog(
                    id=row[0],
                    skill_id=row[1],
                    session_id=row[2],
                    trigger_context=row[3],
                    execution_result=row[4],
                    success=bool(row[5]),
                    feedback=row[6],
                    created_at=row[7],
                ))
            
            return logs
            
        except Exception as e:
            logger.error(f"获取使用记录失败: {e}")
            return []
    
    async def delete_skill(self, skill_id: str) -> bool:
        """删除技能（标记为已废弃）"""
        try:
            skill = await self.get_skill(skill_id)
            if skill:
                skill.status = SkillStatus.DEPRECATED
                skill.updated_at = datetime.now().isoformat()
                await self._save_skill(skill)
                logger.info(f"技能已标记为废弃: {skill_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"删除技能失败: {e}")
            return False
    
    async def get_skill_statistics(self) -> Dict[str, Any]:
        """获取技能统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_skills,
                    SUM(usage_count) as total_usage,
                    SUM(success_count) as total_success,
                    AVG(success_rate) as avg_success_rate,
                    COUNT(CASE WHEN usage_count > 0 THEN 1 END) as used_skills
                FROM skills
                WHERE status = 'active'
            """)
            
            row = cursor.fetchone()
            conn.close()
            
            return {
                'total_skills': row[0] or 0,
                'total_usage': row[1] or 0,
                'total_success': row[2] or 0,
                'avg_success_rate': row[3] or 0.0,
                'used_skills': row[4] or 0,
            }
            
        except Exception as e:
            logger.error(f"获取技能统计失败: {e}")
            return {
                'total_skills': 0,
                'total_usage': 0,
                'total_success': 0,
                'avg_success_rate': 0.0,
                'used_skills': 0,
            }
