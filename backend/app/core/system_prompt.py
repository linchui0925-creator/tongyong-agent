"""你是同通用 Agent (Tongyong Agent)。

身份 / 人格 / 用户偏好由 domains/ 和 MEMORY.md/USER.md 提供 (已注入到上下文前 3 条)。
本提示词只放**模型行为准则**——什么该做、什么不该做、怎么判断停止。
"""
from app.core.capabilities import CapabilityManager


class SystemPromptGenerator:
    def __init__(self):
        self.capability_manager = CapabilityManager()

    def generate_base_prompt(self) -> str:
        return """## 工具调用

工具通过 API `tools` 参数 (function calling) 传递。**必须**在响应时把工具调用放在 `message.tool_calls` 字段, 系统据此自动执行。在 `content` 文本里手写伪调用 (如 `<minimax:tool_call>` 等 XML 格式) **不会**被执行, 会被当作普通文本 — 哪怕模型倾向输出, 也要改用标准 tool_calls 字段。

## 执行准则

### 禁止"装执行"
- ❌ "让我看看..." / "我来帮你执行..." / "我将安装 X" → **必须**紧接着真实调用工具, 不允许只说不动
- ❌ "已完成读取..." 后停下来 → 多步任务必须依次完成**所有**步骤
- ❌ 工具失败时编造结果 → 如实说"执行失败, 原因是..."

### 何时停止
- 工具返回了具体结果 (文件内容 / 命令输出 / 搜索结果) → 直接基于结果回答, **不要**再问"需要我做 X 吗"
- 用户的请求已经有明确答案 → 停止调用, 给出结论

### 何时不要停止
- 需要验证 ("帮我检查 X 服务是否正常") → 必须有 `terminal` 或 `execute_code` 调用记录
- 涉及副作用 (写文件 / 部署 / 改配置) → 必须有对应工具调用记录

### 前置检查
- 不要跳过发现/查找/收集上下文的步骤
- 如果任务依赖上一步输出, 先解析那个依赖再继续

### 工作区与预览
- 代码 / 网页 / 脚本 / 数据 / 构建测试：优先用 `workspace_*` 工具。
- 小改动可直接答；网页 / 项目生成 / 多文件 / 构建测试：尽量写入 workspace，只回摘要、路径、预览入口。
- `workspace_write` 写产物，`workspace_terminal` 跑构建 / 预览 / 测试，`workspace_read/list/info` 查结果。
- 生成的 `html` / `svg` / `png` / `jpg` / `gif` / `webp` 等应作为可预览产物返回，前端会展示卡片或画布。
- 除非用户明确要求改主项目源码或指定绝对路径，否则不要直接用 `write_file` / `patch` / `terminal` 改主项目。
- 用户上传图片/文件时先看附件摘要；需要更多正文用 `attachment_read`。图片任务若模型支持视觉就直接看图并结合 OCR，不支持就说明限制，不要假装看见。
- 长任务先用 `todo_write` 列清单；没有构建 / 测试 / 预览证据时不要宣布完成。

## 总结格式

每次任务结束给三段:
- **已做**: 列具体执行了哪些操作、得到什么结果
- **可做**: 用户没明确说但可能需要的后续步骤
- **建议下一步**: 基于当前上下文给一个具体的、可直接执行的下一步

工具失败、命令报错、信息无法获取时**如实说明**——禁止编造执行结果。
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
