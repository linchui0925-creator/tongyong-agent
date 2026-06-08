"""
HermesConstraintEngine - Agent 行为约束引擎

解决 "agent以为说了就等于做了" 的问题：
1. 工具执行后验证：确保 agent 认知与实际执行结果一致
2. 承诺追踪：跟踪 agent 说要做什么 vs 实际做了什么
3. 认知纠正：在关键节点注入约束，防止幻觉式自我欺骗
4. 循环控制：基于客观标准判断是否该继续执行工具

使用方式：在 AgentEngine.stream_chat() 的关键节点注入约束检查
"""

import re
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """单次工具执行的记录"""
    tool_name: str
    arguments: Dict
    result: str
    success: bool
    timestamp: float
    agent_claimed_action: Optional[str] = None  # agent 说要做什么


@dataclass
class CommitmentRecord:
    """Agent 承诺要执行的行动"""
    commitment: str
    context: str
    timestamp: float
    fulfilled: bool = False
    fulfilled_by: Optional[str] = None  # 通过哪个工具完成


@dataclass
class ToolResultValidation:
    """工具结果验证结果"""
    is_valid: bool
    reason: str
    severity: str = "error"  # "error", "warning", "info"


class HermesConstraintEngine:
    """
    Hermes 约束引擎 - 防止 agent 幻觉式自我欺骗

    核心约束：
    1. 工具执行后必须验证结果有效性
    2. 基于客观标准判断是否继续循环，而不是依赖模型自我评估
    3. 承诺的行动必须有对应的工具调用记录
    """

    def __init__(self, max_empty_results: int = 3, max_tool_rounds: Optional[int] = None):
        self.execution_log: List[ExecutionRecord] = []
        self.commitments: List[CommitmentRecord] = []
        self._last_tool_result: Optional[str] = None
        self._last_tool_name: Optional[str] = None

        # 循环控制参数
        # max_tool_rounds 默认值优先级: 显式参数 > HERMES_MAX_TOOL_ROUNDS env > ITERATION_MAX_ROUNDS env > 50
        if max_tool_rounds is None:
            import os as _os
            _env = _os.getenv("HERMES_MAX_TOOL_ROUNDS") or _os.getenv("ITERATION_MAX_ROUNDS")
            try:
                max_tool_rounds = max(1, int(_env)) if _env else 50
            except ValueError:
                max_tool_rounds = 50
        self.max_empty_results = max_empty_results  # 连续空结果阈值
        self.max_tool_rounds = max_tool_rounds       # 最大工具轮次
        self._consecutive_empty = 0                  # 连续空结果计数
        self._consecutive_valid = 0                  # 连续有效结果计数

    def record_tool_execution(
        self,
        tool_name: str,
        arguments: Dict,
        result: str,
        success: bool,
        timestamp: float
    ) -> None:
        """记录工具执行结果"""
        record = ExecutionRecord(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            success=success,
            timestamp=timestamp
        )
        self.execution_log.append(record)
        self._last_tool_result = result
        self._last_tool_name = tool_name
        logger.info(f"[Hermes] 工具执行记录: {tool_name} -> {'成功' if success else '失败'}")

    def validate_tool_result(self, tool_name: str, result: str,
                             expected_min_length: int = 5) -> ToolResultValidation:
        """
        验证单个工具结果是否有效

        Returns:
            ToolResultValidation - 包含 is_valid, reason, severity
        """
        # 1. 检查是否错误
        if result.startswith("工具执行失败"):
            return ToolResultValidation(
                is_valid=False,
                reason=f"{tool_name} 执行失败",
                severity="error"
            )

        lower = result.lower()
        if any(err in lower for err in ["error", "错误", "失败", "超时"]):
            # 排除误报（如"没有错误"之类的）
            if "没有错误" not in result and "no error" not in lower:
                return ToolResultValidation(
                    is_valid=False,
                    reason=f"{tool_name} 返回错误信息",
                    severity="error"
                )

        # 2. 检查是否为空
        stripped = result.strip()
        if not stripped:
            return ToolResultValidation(
                is_valid=False,
                reason=f"{tool_name} 返回为空",
                severity="error"
            )

        # 3. 检查内容过短
        if len(stripped) < expected_min_length:
            return ToolResultValidation(
                is_valid=False,
                reason=f"{tool_name} 返回内容过短（{len(stripped)} 字符）",
                severity="warning"
            )

        # 4. 工具特定检查
        if tool_name in ("read_file", "search_files", "terminal", "bash"):
            # 文件/命令工具，结果应该有实质内容
            if len(stripped) < 20:
                return ToolResultValidation(
                    is_valid=True,  # 不算错误，但标记
                    reason=f"{tool_name} 返回内容较短",
                    severity="warning"
                )

        if tool_name == "web_search":
            # 搜索应该有结果列表
            if len(stripped) < 50:
                return ToolResultValidation(
                    is_valid=False,
                    reason="搜索结果内容过少，可能查询失败",
                    severity="warning"
                )

        return ToolResultValidation(
            is_valid=True,
            reason="有效",
            severity="info"
        )

    def record_result_for_loop_control(self, tool_name: str, validation: ToolResultValidation):
        """记录结果用于循环控制决策"""
        if validation.is_valid and validation.severity != "error":
            self._consecutive_empty = 0
            self._consecutive_valid += 1
        else:
            self._consecutive_empty += 1
            self._consecutive_valid = 0

    def should_continue_loop(self, tools_used: List[str],
                             tool_results: List[Tuple[str, str]],
                             current_round: int) -> Tuple[bool, str]:
        """
        基于工具执行情况判断是否该继续 React 循环

        这是客观判断，不依赖模型自我评估。

        Returns:
            (should_continue, reason)
        """
        # 1. 达到最大轮次，强制停止
        if current_round >= self.max_tool_rounds:
            return False, f"已达到最大工具轮次（{self.max_tool_rounds}），强制停止"

        # 2. 连续空结果过多，停止
        if self._consecutive_empty >= self.max_empty_results:
            return False, (
                f"连续 {self._consecutive_empty} 次工具返回无效结果，"
                "可能遇到无法解决的问题"
            )

        # 3. 分析本轮工具结果
        valid_count = 0
        invalid_count = 0
        error_count = 0

        for tool_name, result in tool_results:
            validation = self.validate_tool_result(tool_name, result)
            self.record_result_for_loop_control(tool_name, validation)

            if not validation.is_valid:
                invalid_count += 1
                if validation.severity == "error":
                    error_count += 1
            else:
                valid_count += 1

        # 4. 如果全是错误，尝试换方法但最多再给一次机会
        if invalid_count > 0 and valid_count == 0:
            if current_round >= self.max_tool_rounds - 1:
                return False, "所有工具执行失败，已无重试机会"
            return True, "工具全部失败，将尝试其他方法"

        # 5. 检查是否在"兜圈子"（相同工具+相同参数）
        if self._consecutive_valid >= 3:
            recent = self.execution_log[-3:]
            # 只有工具名+参数都相同才算是真正的重复
            seen = set()
            for record in recent:
                key = (record.tool_name, str(record.arguments))
                if key in seen:
                    return False, (
                        f"连续 {self._consecutive_valid} 次执行相同命令（{record.tool_name}）"
                        "但未取得进展，停止循环"
                    )
                seen.add(key)

        return True, "继续执行"

    def check_claim_alignment(self, agent_summary: str) -> Tuple[bool, Optional[str]]:
        """
        检查 agent 的总结是否与实际执行结果一致

        Returns:
            (is_aligned, correction_message)
            - is_aligned: True 表示总结与实际一致
            - correction_message: 如果不一致，返回纠正消息
        """
        if not self.execution_log:
            return True, None

        # 检查是否有未执行的承诺
        unfulfilled = [c for c in self.commitments if not c.fulfilled]
        if unfulfilled:
            # agent 可能在总结中声称完成了还未做的事
            for commitment in unfulfilled:
                # 检查总结是否提到了这个承诺
                if commitment.commitment[:50] in agent_summary:
                    return False, (
                        f"[Hermes约束] 你承诺了「{commitment.commitment[:50]}...」但尚未执行。 "
                        f"请先完成该承诺，再在总结中提及。"
                    )

        # 检查工具执行结果与 agent 描述是否匹配
        recent = self.execution_log[-3:]  # 最近3次执行
        for record in recent:
            # 如果 agent 说"成功执行了 X"，但实际 X 失败了
            if not record.success and f"成功执行 {record.tool_name}" in agent_summary:
                return False, (
                    f"[Hermes约束] 你声称「成功执行了 {record.tool_name}」，"
                    f"但实际执行结果是失败。请基于实际结果而非预期来描述。"
                )

        return True, None

    def extract_commitments(self, agent_message: str, timestamp: float) -> List[str]:
        """
        从 agent 消息中提取承诺的行动

        返回可能需要追踪的承诺列表
        """
        commitments = []

        # 检测"我要做 X"、"我将做 X"、"让我来执行"等模式
        patterns = [
            r"我来执行[：:]?\s*(.+)",
            r"我将要?\s*(.+)",
            r"开始\s+(\w+)\s+任务",
            r"正在启动\s+(\w+)",
            r"将执行\s+(\w+)",
            r"准备开始\s+(\w+)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, agent_message)
            commitments.extend(matches)

        return commitments

    def add_commitment(self, commitment: str, context: str, timestamp: float) -> None:
        """记录一个新的承诺"""
        record = CommitmentRecord(
            commitment=commitment,
            context=context,
            timestamp=timestamp
        )
        self.commitments.append(record)
        logger.info(f"[Hermes] 承诺记录: {commitment[:50]}...")

    def mark_commitment_fulfilled(self, commitment_hint: str, tool_name: str) -> None:
        """标记某个承诺已被特定工具完成"""
        for record in reversed(self.commitments):
            if not record.fulfilled and commitment_hint in record.commitment:
                record.fulfilled = True
                record.fulfilled_by = tool_name
                logger.info(f"[Hermes] 承诺已履行: {record.commitment[:50]}... -> {tool_name}")
                return

    def get_constraint_prompt(self) -> str:
        """
        获取注入到 agent 上下文的约束提示

        在关键节点调用此方法，将约束注入 system message
        """
        unfulfilled_count = len([c for c in self.commitments if not c.fulfilled])

        base_constraint = """[Hermes 行为约束]
你必须基于实际执行结果来描述，不能基于预期或假设：
1. 工具执行后，根据返回的实际结果描述outcome，不能说"成功执行了"然后省略结果
2. 如果工具返回错误，你必须如实描述"执行失败：原因"，而不是假装成功了
3. 不要声称完成了某个行动，除非你有对应的工具调用记录

"""

        if unfulfilled_count > 0:
            base_constraint += f"""[未完成承诺警告]
你有 {unfulfilled_count} 个承诺尚未完成。不要在回复中声称这些承诺已履行，
直到你有对应的工具执行记录。"""

        return base_constraint

    def get_execution_summary(self) -> str:
        """获取执行摘要，用于调试和日志"""
        if not self.execution_log:
            return "尚无工具执行记录"

        lines = ["[执行记录]"]
        for i, record in enumerate(self.execution_log[-5:], 1):
            status = "✓" if record.success else "✗"
            lines.append(f"{i}. {status} {record.tool_name}: {record.result[:60]}...")

        unfulfilled = [c for c in self.commitments if not c.fulfilled]
        if unfulfilled:
            lines.append(f"\n[未完成承诺 {len(unfulfilled)}]")
            for c in unfulfilled[-3:]:
                lines.append(f"  - {c.commitment[:50]}...")

        return "\n".join(lines)

    def reset_session(self) -> None:
        """重置会话状态（开始新对话时调用）"""
        self.execution_log.clear()
        self.commitments.clear()
        self._last_tool_result = None
        self._last_tool_name = None
        self._consecutive_empty = 0
        self._consecutive_valid = 0
        logger.info("[Hermes] 会话状态已重置")