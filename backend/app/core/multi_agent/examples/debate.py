"""
Debate 场景示例：两人对抗式辩论
"""

import asyncio
import logging

from app.core.multi_agent.team import Team
from app.core.multi_agent.role import TeamRole
from app.core.multi_agent.action import SpeakAloudAction
from app.core.multi_agent.tool_permission import ToolPermission

logger = logging.getLogger(__name__)


async def run_debate_example(
    idea: str = "气候政策：美国是否应该大幅增加可再生能源投资",
    n_round: int = 5
):
    """
    辩论协作示例：Biden vs Trump
    
    流程:
    - 两个 Debator 交替发言
    - 每次发言都会听到对方上一轮的论点
    - 通过 send_to 实现定向发送（不被第三方收到）
    """
    biden = TeamRole.create(
        name="Biden",
        profile="Democrat",
        watch_actions=["UserRequirement", "SpeakAloud"],
        action_types=["speak_aloud"],
        opponent_name="Trump",
    )
    
    trump = TeamRole.create(
        name="Trump",
        profile="Republican",
        watch_actions=["UserRequirement", "SpeakAloud"],
        action_types=["speak_aloud"],
        opponent_name="Biden",
    )
    
    # 构建 Team
    team = Team(name="总统辩论赛")
    team.hire(biden)
    team.hire(trump)
    
    logger.info(f"启动辩论: {idea}")
    
    # 运行（由 Biden 先发言）
    messages = await team.run(idea=idea, n_round=n_round, send_to="Biden")
    
    # 输出结果
    print("\n" + "=" * 60)
    print("辩论结果")
    print("=" * 60)
    for msg in messages:
        if msg.role == "assistant" and msg.cause_by == "SpeakAloud":
            print(f"\n[{msg.sent_from}]:\n{msg.content}\n")
    
    return messages


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run_debate_example())
    print(f"\n共生成 {len(result)} 条消息")