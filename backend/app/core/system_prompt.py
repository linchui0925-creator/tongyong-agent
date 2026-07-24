"""你是同通用 Agent (Tongyong Agent)。

身份 / 人格 / 用户偏好由 domains/ 和 MEMORY.md/USER.md 提供 (已注入到上下文前 3 条)。
本提示词只放**模型行为准则**——什么该做、什么不该做、怎么判断停止。
"""
from app.core.capabilities import CapabilityManager


class SystemPromptGenerator:
    def __init__(self):
        self.capability_manager = CapabilityManager()

    def generate_base_prompt(self) -> str:
        return (
            "## 角色与模式\n\n"
            "你是维知，一个面向真实任务的智能体。\n"
            "当前轮次通常处于以下模式之一：\n"
            "- build / executor：真实执行任务，工具调用必须落地\n"
            "- plan / planner：先拆解、比较方案、明确步骤，再执行\n"
            "- ask / clarify：信息不足时先问最关键的问题\n\n"
            "## 核心原则\n\n"
            "1. 不要装执行；已完成/已修改/已找到必须有真实工具证据\n"
            "2. 工具失败如实说，不编造成功结果\n"
            "3. 图片、文件、网页内容必须通过工具读取，不要假装看见\n"
            "4. 卡住时先停下来说明卡点，避免空转或重复无效重试\n"
            "5. 默认简洁直接；能一句话说清就不要长篇展开\n"
            "6. 不确定时显式提问，不要默默补全\n\n"
            "## 先问还是先做\n\n"
            "- 目标、范围、验收标准不清时，优先 ask\n"
            "- 任务需要拆步骤、对比方案、先评估再执行时，优先 plan\n"
            "- 细节可以从上下文合理补全时，直接继续，不要打断用户\n\n"
            "## 写文件与输出\n\n"
            "- 代码/网页/组件/项目：优先用 workspace_* 工具完成真实改动\n"
            "- 文案/分析/总结：先给结果，再按需保存\n"
            "- 模糊请求：先确认是代码任务还是文本任务\n\n"
            "## 边界\n\n"
            "- 先收集，再推进，再回填；不要把临时探索直接当最终结论\n"
            "- 长结果要可回放，但不必把所有内容原样灌入上下文\n"
        )

    def generate_capability_prompt(self) -> str:
        from app.core.env_capabilities import generate_capability_prompt
        return generate_capability_prompt()

    def generate_full_prompt(self) -> str:
        from app.core.skills_index import get_skills_prompt, get_system_skills_content

        sections = [
            self.generate_base_prompt(),
            self.generate_capability_prompt(),
        ]
        system_skills = get_system_skills_content()
        if system_skills:
            sections.append(system_skills)
        sections.append(get_skills_prompt())
        return "\n\n".join(section for section in sections if section)

    def get_recommended_actions(self, message: str) -> str:
        capabilities = self.capability_manager.find_capability(message)
        if not capabilities:
            return ""
        actions = []
        for cap in capabilities[:2]:
            if cap.examples:
                actions.append(f"- **{cap.name}**: {cap.examples[0]}")
        if not actions:
            return ""
        return "我可以主动执行:\n" + "\n".join(actions)

    def should_execute(self, message: str) -> bool:
        execution_triggers = [
            "\u8fd0\u884c", "\u6267\u884c", "\u542f\u52a8", "\u6d4b\u8bd5", "\u6784\u5efa", "\u5b89\u88c5", "\u90e8\u7f72",
            "\u521b\u5efa", "\u5220\u9664", "\u4fee\u6539",
            "\u5206\u6790", "\u67e5\u770b", "\u67e5\u627e", "\u641c\u7d22",
            "\u8bb0\u4f4f", "\u5b66\u4e60"
        ]
        message_lower = message.lower()
        return any(trigger in message_lower for trigger in execution_triggers)

    def should_analyze(self, message: str) -> bool:
        analyze_triggers = [
            "\u5206\u6790", "\u67b6\u6784", "\u7ed3\u6784", "\u9879\u76ee", "\u6a21\u5757",
            "\u6709\u4ec0\u4e48", "\u5305\u542b", "\u4f9d\u8d56"
        ]
        message_lower = message.lower()
        return any(trigger in message_lower for trigger in analyze_triggers)

    def should_learn(self, message: str) -> bool:
        learn_triggers = ["\u8bb0\u4f4f", "\u5b66\u4e60", "\u4ee5\u540e", "\u504f\u597d", "\u4e60\u60ef"]
        message_lower = message.lower()
        return any(trigger in message_lower for trigger in learn_triggers)


prompt_generator = SystemPromptGenerator()


def get_system_prompt() -> str:
    return prompt_generator.generate_full_prompt()
