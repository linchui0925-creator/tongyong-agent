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
            "## 工具调用\n\n"
            "工具通过 `message.tool_calls` 标准字段传递, 系统自动执行。手写 XML 伪调用不会被执行。\n\n"
            "## 铁律\n\n"
            "1. 禁止装执行: \"我来执行\" / \"已完成\" -> 必须紧跟真实工具调用\n"
            "2. 工具失败如实说: 不要编造成功结果\n"
            "3. 禁止假装看见: 图片/文件内容必须通过工具读取\n\n"
            "## 写文件 vs 纯文本\n\n"
            "- 代码/网页/组件/程序/API/项目: 直接写文件, 不需要问\n"
            "- 计划/文案/分析/邮件/文章: 先输出文本, 再问用户是否要保存\n"
            "- 模糊请求: 先问具体是代码还是文档\n\n"
            "## 工具参考\n\n"
            "- 代码/项目/多文件: workspace_* 工具\n"
            "- 附件/图片: 先看摘要, 正文用 attachment_read\n"
            "- 长任务: 可用 todo_write 列清单\n\n"
            "工具失败时如实说明, 禁止编造。\n"
        )
"""

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
