"""
流水线 Worker / Leader Action（TaskPayload 版本）

Worker:
  WriteCodeAction   — 根据任务编写代码
  WriteTestAction   — 编写测试用例
  WriteReviewAction — 代码审查

Leader:
  AnalyzeTaskAction    — 分析任务，拆分子任务
  DistributeTaskAction — 将任务分配给下游 Agent
  ApprovalAction       — 审批（通过/退回）
  RejectAction         — 退回修改
"""

from pydantic import BaseModel, Field
from typing import TYPE_CHECKING, List, Optional
import json
import re
import logging

from app.core.multi_agent.actions.base import TeamAction, _call_llm

if TYPE_CHECKING:
    from app.core.multi_agent.role import TeamRole, RoleContext

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# Worker Actions
# ══════════════════════════════════════════════════════════

class WriteCodeAction(TeamAction):
    """写代码 Action（TaskPayload 版本）"""
    name: str = "WriteCode"
    description: str = "根据 Leader 分配的任务编写 Python 代码"

    instruction_template: str = """
## 任务
{description}

## 原始需求
{original_requirement}

## 退回反馈（如有）
{feedback}

请编写可运行的 Python 代码实现以上任务。
仅返回 ```python 代码块，不含其他文字。
"""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        from app.core.multi_agent.message import TaskPayload

        # 解析传入的 TaskPayload（来自 DistributeTask）
        payload = None
        for msg in reversed(context.news):
            p = TaskPayload.from_message(msg)
            if p:
                payload = p
                break

        description = ""
        original_req = ""
        feedback_text = ""
        if payload:
            description = payload.description or ""
            original_req = payload.original_requirement or ""
            if payload.feedback:
                fb = payload.feedback[-1]
                feedback_text = f"退回理由: {fb.reason}\n修改建议: {', '.join(fb.suggestions)}"
        else:
            # 兼容旧格式
            for msg in reversed(context.news):
                if msg.cause_by in ("DistributeTask", "UserRequirement") or msg.role == "user":
                    description = msg.content
                    break

        prompt = self.instruction_template.format(
            description=description or "写一个 hello world 函数",
            original_requirement=original_req or description or "",
            feedback=feedback_text or "无",
        )
        messages = [{"role": "user", "content": prompt}]
        result = await _call_llm(role, messages, tools=None)
        code = self._parse_code(result)

        # 构造返回的 TaskPayload（携带退回计数避免死循环）
        reply = TaskPayload(
            task_id=payload.task_id if payload else "",
            task_type="code",
            status="completed",
            description=description,
            original_requirement=original_req,
            result=code,
            rejection_count=payload.rejection_count if payload else 0,
        )
        # 定向发回给上游 Agent（Leader）
        self.send_to = role.upstream_roles[0] if role.upstream_roles else "Leader"
        return reply.to_content()


class WriteTestAction(TeamAction):
    """写测试 Action（TaskPayload 版本）"""
    name: str = "WriteTest"
    description: str = "根据代码编写 pytest 测试用例"

    k: int = 3

    context_template: str = """
## 被测代码
{context}

## 退回反馈（如有）
{feedback}

请为以上代码编写 {k} 个 pytest 测试用例。
覆盖正常流程、边界条件和异常场景。
仅返回 ```python 代码块，不含其他文字。
"""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        from app.core.multi_agent.message import TaskPayload

        # 解析传入的 TaskPayload（来自 Leader 的审批或分发）
        payload = None
        for msg in reversed(context.news):
            p = TaskPayload.from_message(msg)
            if p:
                payload = p
                break

        upstream_code = ""
        feedback_text = ""
        if payload:
            upstream_code = payload.context or payload.result or ""
            if payload.feedback:
                fb = payload.feedback[-1]
                feedback_text = f"退回理由: {fb.reason}\n修改建议: {', '.join(fb.suggestions)}"
        else:
            # 兼容旧格式
            for msg in reversed(context.news):
                if msg.cause_by == "WriteCode":
                    upstream_code = msg.content
                    break

        prompt = self.context_template.format(
            context=upstream_code or "# 未提供代码",
            feedback=feedback_text or "无",
            k=self.k,
        )
        messages = [{"role": "user", "content": prompt}]
        result = await _call_llm(role, messages, tools=None)
        tests = self._parse_code(result)

        # 构造返回的 TaskPayload
        reply = TaskPayload(
            task_id=payload.task_id if payload else "",
            task_type="test",
            status="completed",
            description=payload.description if payload else "",
            context=upstream_code,
            result=tests,
            rejection_count=payload.rejection_count if payload else 0,
        )
        self.send_to = role.upstream_roles[0] if role.upstream_roles else "Leader"
        return reply.to_content()


class WriteReviewAction(TeamAction):
    """审查代码 Action（TaskPayload 版本）"""
    name: str = "WriteReview"
    description: str = "审查 Coder 编写的代码并给出改进建议"

    review_template: str = """
## 待审查代码
{context}

## 审查清单
- 代码逻辑是否正确
- 是否有潜在 bug 或边界条件遗漏
- 代码质量和可读性
- 性能问题
- 安全漏洞

## 退回反馈（如有）
{feedback}

请审查以上代码，回复格式：
**评分**: 1-10
**核心问题**: ...
**改进建议**: ...
"""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        from app.core.multi_agent.message import TaskPayload

        payload = None
        for msg in reversed(context.news):
            p = TaskPayload.from_message(msg)
            if p:
                payload = p
                break

        code_to_review = ""
        feedback_text = ""
        if payload:
            code_to_review = payload.context or payload.result or ""
            if payload.feedback:
                fb = payload.feedback[-1]
                feedback_text = f"退回理由: {fb.reason}\n修改建议: {', '.join(fb.suggestions)}"
        else:
            for msg in reversed(context.news):
                if msg.cause_by == "WriteCode":
                    code_to_review = msg.content
                    break

        prompt = self.review_template.format(
            context=code_to_review or "# 未提供代码",
            feedback=feedback_text or "无",
        )
        messages = [{"role": "user", "content": prompt}]
        result = await _call_llm(role, messages, tools=None)

        reply = TaskPayload(
            task_id=payload.task_id if payload else "",
            task_type="review",
            status="completed",
            description=payload.description if payload else "",
            context=code_to_review,
            result=result,
            rejection_count=payload.rejection_count if payload else 0,
        )
        self.send_to = role.upstream_roles[0] if role.upstream_roles else "Leader"
        return reply.to_content()


# ══════════════════════════════════════════════════════════
# Leader Actions
# ══════════════════════════════════════════════════════════

class AnalyzeTaskAction(TeamAction):
    """
    Leader 分析任务并决定分发策略（TaskPayload 版本）。

    流程：
    1. 解析 UserRequirement 的 TaskPayload（或纯文本）
    2. LLM 分析任务，提取子任务列表
    3. 返回 TaskPayload（send_to=Leader 自身，供下一轮 DistributeTask 消费）
    """
    name: str = "AnalyzeTask"
    description: str = "分析用户任务，判断简单/复杂，决定分配策略"

    prompt_template: str = """
## 任务分析

用户需求：{task}

请分析并回复如下格式（必须严格按格式）：

**类型**: 简单 | 复杂
**分配**: 直接分配给 Coder | 拆分为子任务
**子任务列表**（仅复杂任务需要）：
1. [子任务1描述]
2. [子任务2描述]
...

**当前轮次任务**（本轮要分配的具体任务）：
[本轮需要执行的任务描述]
"""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        from app.core.multi_agent.message import TaskPayload

        # 提取用户原始需求
        task_content = ""
        for msg in reversed(context.news):
            if msg.cause_by == "UserRequirement" or msg.role == "user":
                task_content = msg.content
                break
            p = TaskPayload.from_message(msg)
            if p:
                task_content = p.description or p.original_requirement or msg.content
                break

        prompt = self.prompt_template.format(task=task_content or "无任务描述")
        messages = [{"role": "user", "content": prompt}]
        result = await _call_llm(role, messages, tools=None)

        # 解析子任务列表，填充 Team._task_queue
        subtasks = self._parse_subtasks(result)
        team = self._get_team(role)
        if team and subtasks:
            # 第一个子任务立即执行，其余入队
            team._task_queue.extend(subtasks[1:])
            logger.info(f"[LEADER] 分析完成，{len(subtasks)} 个子任务（队列剩余 {len(team._task_queue)} 个）")

        # 构造 TaskPayload，定向发给 Leader 自身
        payload = TaskPayload(
            task_type="analyze",
            status="completed",
            description=task_content,
            original_requirement=task_content,
            result=result,
            subtasks=subtasks,
            current_subtask=subtasks[0] if subtasks else task_content,
        )
        # 定向发给自身，供下一轮 DistributeTask 消费
        self.send_to = role.name
        return payload.to_content()

    def _parse_subtasks(self, text: str) -> List[str]:
        """从 LLM 输出中解析子任务列表"""
        lines = re.findall(r"(?:^\d+\.[ \t]+)(.+)", text, re.MULTILINE)
        if not lines:
            lines = re.findall(r"(?:^[ \t]+\d+\.[ \t]+)(.+)", text, re.MULTILINE)
        if not lines:
            for line in text.split("\n"):
                m = re.match(r"^\d+[.、)](.+)$", line.strip())
                if m:
                    lines.append(m.group(1).strip())
        return [l.strip() for l in lines if l.strip()]

    def _get_team(self, role: "TeamRole"):
        if role._env and hasattr(role._env, "_team"):
            return role._env._team
        return None


class DistributeTaskAction(TeamAction):
    """
    Leader 将任务分配给下游 Agent（TaskPayload 版本）。

    send_to 定向指定目标 Agent。任务来源优先级：
    1. TaskPayload 的 AnalyzeTask 结果中的当前子任务
    2. Team._task_queue
    3. 原始需求描述
    """
    name: str = "DistributeTask"
    description: str = "将任务定向分配给指定 Agent"

    target: str = ""          # 目标 Agent 名称
    task_instruction: str = "" # 任务描述

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        from app.core.multi_agent.message import TaskPayload, Feedback

        # ── 解析传入的 TaskPayload（来自 AnalyzeTask）──
        incoming_payload = None
        for msg in reversed(context.news):
            p = TaskPayload.from_message(msg)
            if p and p.task_type == "analyze":
                incoming_payload = p
                break

        # ── 自动推断目标 Agent ──
        target = self.target
        if not target:
            target = self._auto_detect_target(role)
            if not target:
                return "错误: 无法推断目标 Agent，检查流水线状态"
        self.send_to = target

        # ── 任务来源 ──
        description = self.task_instruction
        original_req = ""
        feedback_list: List[Feedback] = []

        if not description:
            # 从 incoming_payload 获取
            if incoming_payload:
                description = incoming_payload.current_subtask or incoming_payload.description
                original_req = incoming_payload.original_requirement or incoming_payload.description

        if not description:
            # 从 Team._task_queue
            team = self._get_team(role)
            if team and hasattr(team, "_task_queue") and team._task_queue:
                description = team._task_queue.pop(0)

        if not description:
            # 退回场景：从 news 中提取退回消息
            for msg in reversed(context.news):
                p = TaskPayload.from_message(msg)
                if p and p.status == "rejected":
                    description = p.description
                    original_req = p.original_requirement
                    feedback_list = p.feedback
                    break

        if not description:
            # 从原始 news 提取
            for msg in reversed(context.news):
                if msg.cause_by in ("AnalyzeTask", "UserRequirement") or msg.role == "user":
                    p = TaskPayload.from_message(msg)
                    if p:
                        description = p.description or msg.content
                    else:
                        description = msg.content
                    break

        logger.info(f"[LEADER] 分配任务 → {target}: {str(description)[:60]}...")

        # 根据目标确定 task_type（显式映射，不依赖位置）
        TASK_TYPE_MAP = {"Coder": "code", "Reviewer": "review", "Tester": "test"}
        task_type = TASK_TYPE_MAP.get(target, "code")

        payload = TaskPayload(
            task_id=incoming_payload.task_id if incoming_payload else "",
            task_type=task_type,
            status="pending",
            description=description or "",
            original_requirement=original_req or description or "",
            feedback=feedback_list,
        )
        return payload.to_content()

    def _auto_detect_target(self, role: "TeamRole") -> str:
        """根据下游角色列表和当前阶段推断下一个目标 Agent"""
        targets = role.downstream_roles if role.downstream_roles else ["Coder", "Tester", "Reviewer"]
        if not targets:
            return ""

        if not role._env:
            return targets[0]

        done_causes = [
            m.cause_by for m in role._env.get_all_messages()
            if m.cause_by and m.sent_from != "Team" and m.role not in ("system", "user")
        ]

        has_code = "WriteCode" in done_causes
        has_review = "WriteReview" in done_causes
        has_test = "WriteTest" in done_causes

        if not has_code:
            return targets[0] if len(targets) > 0 else "Coder"
        if has_code and not has_review:
            return targets[1] if len(targets) > 1 else targets[0]
        if has_review and not has_test:
            return targets[2] if len(targets) > 2 else targets[0]
        # 所有阶段完成，检查子任务队列
        team = self._get_team(role)
        if team and hasattr(team, "_task_queue") and team._task_queue:
            return targets[0]
        return targets[0]

    def _get_team(self, role: "TeamRole"):
        if role._env and hasattr(role._env, "_team"):
            return role._env._team
        return None


class ApprovalAction(TeamAction):
    """
    Leader 审批 Worker 的工作结果（TaskPayload 版本）。

    - 通过：status=completed，根据角色连接图路由到下一个 Worker
    - 退回：status=rejected，feedback 包含退回理由 + 修改建议，路由回原 Worker
    """
    name: str = "Approve"
    description: str = "审批上游提交的工作，通过则流转下一环节，退回则附修改建议"

    decision_template: str = """
## 审批任务

上游 Agent [{sender}] 提交的工作：

---
{content}
---

请审批以上工作。重点关注：
1. 任务核心功能是否完成
2. 是否有明显的错误或遗漏

格式：
**决定**: 通过 | 退回
**理由**: [一句话说明]
**修改要求**（仅退回时填写）: [具体、可执行的修改内容]

注意：如果核心功能已完成，请通过。不要因为风格偏好（如缺少注释、格式等）退回。
"""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        from app.core.multi_agent.message import TaskPayload, Feedback

        # 提取上游 TaskPayload
        payload = None
        sender = ""
        for msg in reversed(context.news):
            p = TaskPayload.from_message(msg)
            if p and p.status in ("completed", "rejected"):
                payload = p
                sender = msg.sent_from
                break

        if not payload:
            # 回退到环境扫描
            workers = role.downstream_roles if role.downstream_roles else ["Coder", "Tester", "Reviewer"]
            worker_set = set(workers)
            if role._env:
                for msg in reversed(role._env.get_all_messages()):
                    if msg.sent_from in worker_set:
                        p = TaskPayload.from_message(msg)
                        if p:
                            payload = p
                            sender = msg.sent_from
                            break

        if not payload:
            return "错误: 无法找到上游提交的工作内容"

        # 检测执行错误
        content_to_review = payload.result or payload.context or ""
        prompt = self.decision_template.format(content=content_to_review[:2000], sender=sender)
        messages = [{"role": "user", "content": prompt}]
        decision = await _call_llm(role, messages, tools=None)

        # 解析决定：优先 JSON，回退正则
        is_approved = self._parse_decision_json(decision)
        if is_approved is None:
            is_approved = bool(re.search(r"(?:决定|Decision)[^:：]*[：:]\s*通过|批准|approve|pass", decision, re.IGNORECASE))

        if is_approved:
            # ── 通过：路由到下一个 Worker ──
            next_worker = role._get_next_worker(sender) if hasattr(role, '_get_next_worker') else ""
            self.send_to = next_worker
            payload.status = "completed"
            # 传递上下文给下一环节（保留原始代码供后续使用）
            if payload.task_type in ("code", "review", "test"):
                pass  # context 已由各 Action 维护，不再覆盖
            payload.feedback = []
            return payload.to_content()
        else:
            # ── 退回：附反馈，路由回原 Worker ──
            payload.rejection_count = getattr(payload, 'rejection_count', 0) + 1

            # 防死循环：连续退回 2 次后自动通过
            if payload.rejection_count >= 2:
                logger.warning(f"[LEADER] {sender} 已退回 {payload.rejection_count} 次，自动通过")
                next_worker = role._get_next_worker(sender) if hasattr(role, '_get_next_worker') else ""
                self.send_to = next_worker
                payload.status = "completed"
                if payload.task_type == "code":
                    payload.context = payload.result
                elif payload.task_type == "test":
                    payload.context = payload.result
                payload.feedback = []
                return payload.to_content()

            feedback = self._parse_feedback(decision, role.name)
            self.send_to = sender
            payload.status = "rejected"
            payload.feedback.append(feedback)
            logger.info(f"[LEADER] 退回 → {sender} (第{payload.rejection_count}次): {feedback.reason}")
            return payload.to_content()

    def _parse_decision_json(self, decision_text: str) -> Optional[bool]:
        """尝试从 LLM 输出中解析 JSON 格式的审批决定，失败返回 None"""
        candidates = re.findall(r'\{[^}]*"decision"[^}]*\}', decision_text, re.IGNORECASE)
        for c in candidates:
            try:
                data = json.loads(c)
                val = str(data.get("decision", "")).lower()
                if val in ("approve", "通过", "批准", "pass", "yes", "true"):
                    return True
                if val in ("reject", "退回", "驳回", "no", "false"):
                    return False
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _parse_feedback(self, decision: str, from_agent: str) -> "Feedback":
        """从 LLM 决策文本中解析结构化退回反馈"""
        from app.core.multi_agent.message import Feedback

        # 尝试 JSON 解析（LLM 可能输出 {"reason": "...", "suggestions": [...]}）
        try:
            data = json.loads(decision)
            if isinstance(data, dict):
                reason = data.get("reason") or data.get("理由", decision[:200])
                suggestions = data.get("suggestions") or data.get("修改建议", [])
                if isinstance(suggestions, str):
                    suggestions = [suggestions]
                return Feedback(
                    reason=str(reason)[:500],
                    suggestions=[str(s) for s in suggestions if s],
                    from_agent=from_agent,
                )
        except (json.JSONDecodeError, TypeError):
            pass

        # 回退：正则解析
        reason_match = re.search(r"(?:理由|原因)[^:：]*[：:]\s*(.+?)(?:\n|$)", decision)
        suggest_match = re.search(r"(?:修改要求|修改建议|建议)[^:：]*[：:]\s*(.+?)(?:\n|$)", decision)

        return Feedback(
            reason=reason_match.group(1).strip() if reason_match else decision[:200],
            suggestions=[suggest_match.group(1).strip()] if suggest_match else [],
            from_agent=from_agent,
        )


class RejectAction(TeamAction):
    """
    退回修改 Action。

    Worker 收到 Leader 退回的 TaskPayload（status=rejected）后重新执行，
    基于 feedback 中的理由修改后重新提交。
    """
    name: str = "Reject"
    description: str = "收到退回后，根据反馈修改并重新提交"

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        from app.core.multi_agent.message import TaskPayload

        payload = None
        for msg in reversed(context.news):
            p = TaskPayload.from_message(msg)
            if p and p.status == "rejected":
                payload = p
                break

        # 将退回状态改为 working，让 Worker 的默认 action（WriteCode/WriteTest/WriteReview）
        # 读取 payload.feedback 并重新执行
        if payload:
            payload.status = "working"
            # 定向发回给自身，让默认 action 处理
            self.send_to = role.name
            return payload.to_content()

        # 兼容旧格式：扫描 "退回" 关键词
        reason = ""
        for msg in reversed(context.news):
            if msg.cause_by in ("Approve", "Reject") and "退回" in msg.content:
                reason = msg.content
                break

        if not reason:
            return "错误: 未收到退回消息"

        # 构建退回报价，让 LLM 重新执行
        prompt = f"## 任务被退回\n\n退回理由：{reason}\n\n请基于退回理由重新修改你的工作，并回复修改说明和结果。"
        messages = [{"role": "user", "content": prompt}]
        result = await _call_llm(role, messages, tools=None)

        upstream_targets = role.upstream_roles if role.upstream_roles else ["Leader"]
        self.send_to = upstream_targets[0]
        return result
