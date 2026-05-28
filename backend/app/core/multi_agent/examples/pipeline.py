"""
Leader 驱动流水线场景示例
用户下发任务 → Leader 分析 → 分配给 Coder → Tester → Reviewer → Leader 审批 → 下一子任务或完成
不满意则退回上游重新做。
"""

import asyncio
import logging

from app.core.multi_agent.team import Team
from app.core.multi_agent.role import TeamRole
from app.core.multi_agent.action import DistributeTaskAction
from app.core.multi_agent.tool_permission import ToolPermission

logger = logging.getLogger(__name__)


async def run_leader_pipeline_example(
    idea: str = "写一个 Python 猜数字游戏，带单元测试",
    n_round: int = 20,
):
    """
    Leader 驱动流水线示例

    角色配置:
    - Leader: 分析任务、分配、审批（watch: UserRequirement, Reject）
    - Coder: 写代码（watch: DistributeTask）
    - Tester: 写测试（watch: WriteCode）
    - Reviewer: 审查测试（watch: WriteTest）

    流程:
    1. Leader 接收任务，分析并分配给 Coder
    2. Coder 完成 → 提交给 Leader → Leader 审批 → 分配给 Tester
    3. Tester 完成 → 提交给 Leader → Leader 审批 → 分配给 Reviewer
    4. Reviewer 完成 → 提交给 Leader → Leader 审批 → 下一子任务或完成
    5. 不满意则退回上游重做
    """
    # 创建团队（leader_pipeline 模式）
    team = Team(name="Leader 开发团队", mode="leader_pipeline")

    # 雇佣 Leader
    leader = TeamRole.create(
        name="Leader",
        profile=(
            "任务指挥官。负责分析用户需求，判断简单/复杂任务，"
            "将简单任务直接分配给 Coder，将复杂任务拆分为多个子任务逐个处理。"
            "对下游的工作结果进行审批，不满意则退回重做。"
        ),
        watch_actions=["UserRequirement", "Reject"],
        action_types=["analyze_task", "distribute_task", "approve"],
        llm_provider="openai",
    )
    team.hire(leader)

    # 雇佣 Coder
    coder = TeamRole.create(
        name="Coder",
        profile="资深 Python 工程师，擅长写高质量、可维护的代码。",
        watch_actions=["DistributeTask"],
        action_types=["write_code"],
        llm_provider="openai",
    )
    team.hire(coder)

    # 雇佣 Tester
    tester = TeamRole.create(
        name="Tester",
        profile="测试工程师，专注于编写全面的 pytest 测试用例。",
        watch_actions=["WriteCode"],
        action_types=["write_test"],
        llm_provider="openai",
    )
    team.hire(tester)

    # 雇佣 Reviewer
    reviewer = TeamRole.create(
        name="Reviewer",
        profile="代码审查专家，擅长发现潜在 bug 和代码异味。",
        watch_actions=["WriteTest"],
        action_types=["write_review"],
        llm_provider="openai",
    )
    team.hire(reviewer)

    logger.info(f"启动 Leader 流水线: {idea}")

    # 运行
    messages = await team.run(idea=idea, n_round=n_round, send_to="Leader")

    # 输出结果
    print("\n" + "=" * 60)
    print("Leader 流水线结果")
    print("=" * 60)
    for msg in messages:
        if msg.role in ("assistant", "agent"):
            print(f"\n[{msg.sent_from} → {msg.send_to or '广播'}] ({msg.cause_by}):")
            print(f"{msg.content[:300]}\n---")

    return messages


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run_leader_pipeline_example())
    print(f"\n共生成 {len(result)} 条消息")