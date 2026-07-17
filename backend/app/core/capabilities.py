"""
CapabilityManager - Agent能力清单管理器

让Agent知道自己有什么能力，以及如何使用这些能力
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import json

@dataclass
class Capability:
    """能力定义"""
    name: str
    description: str
    category: str  # conversation, execution, learning, analysis
    triggers: List[str]  # 触发关键词
    examples: List[str]  # 使用示例
    limitations: Optional[str] = None  # 限制说明
    requires_confirmation: bool = False  # 是否需要确认
    danger_level: str = "safe"  # safe, warning, danger
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'triggers': self.triggers,
            'examples': self.examples,
            'limitations': self.limitations,
            'requires_confirmation': self.requires_confirmation,
            'danger_level': self.danger_level
        }


class CapabilityManager:
    """Agent能力清单管理器"""
    
    def __init__(self):
        self.capabilities = self._load_default_capabilities()
    
    def _load_default_capabilities(self) -> List[Capability]:
        """加载默认能力清单"""
        return [
            # 对话能力
            Capability(
                name="自然语言对话",
                description="理解用户意图，进行自然的语言交流",
                category="conversation",
                triggers=["对话", "聊天", "回答", "解释"],
                examples=[
                    "用户问：什么是FastAPI",
                    "Agent答：FastAPI是一个现代快速的Web框架..."
                ],
                limitations=None,
                danger_level="safe"
            ),
            
            # CLI命令执行能力
            Capability(
                name="CLI命令执行",
                description="执行系统命令，如运行测试、启动服务、安装依赖等",
                category="execution",
                triggers=[
                    "运行", "执行", "启动", "停止", "构建", "测试",
                    "安装", "部署", "build", "run", "test", "install"
                ],
                examples=[
                    "用户：运行pytest测试",
                    "Agent：执行命令: pytest tests/ -v",
                    "用户：启动后端服务",
                    "Agent：执行命令: cd backend && python app/main.py"
                ],
                limitations="只能执行预定义的安全命令，如pytest、npm、git等",
                requires_confirmation=True,
                danger_level="warning"
            ),
            
            # 项目分析能力
            Capability(
                name="项目架构分析",
                description="分析项目结构、技术栈、模块关系",
                category="analysis",
                triggers=[
                    "分析", "架构", "结构", "模块", "依赖",
                    "查看项目", "有什么", "包含什么"
                ],
                examples=[
                    "用户：分析这个项目",
                    "Agent：项目包含 backend/app/ 模块，frontend/src/ 组件..."
                ],
                limitations="只能分析项目结构，无法修改代码",
                danger_level="safe"
            ),
            
            # 代码搜索能力
            Capability(
                name="代码搜索",
                description="搜索项目中的代码文件和内容",
                category="analysis",
                triggers=[
                    "搜索", "查找", "找找", "grep", "find"
                ],
                examples=[
                    "用户：查找所有测试文件",
                    "Agent：执行: find . -name '*test*.py'"
                ],
                limitations="只搜索代码文件",
                danger_level="safe"
            ),
            
            # 文件读取能力
            Capability(
                name="文件读取",
                description="读取项目文件内容",
                category="execution",
                triggers=[
                    "查看", "读文件", "cat", "打开"
                ],
                examples=[
                    "用户：看看app.py的内容",
                    "Agent：读取文件: backend/app/main.py"
                ],
                limitations="只能读取，不能写入",
                danger_level="safe"
            ),
            
            # 技能学习能力
            Capability(
                name="技能学习",
                description="学习用户教的技能，下次自动使用",
                category="learning",
                triggers=[
                    "记住", "学习", "以后", "下次", "模板"
                ],
                examples=[
                    "用户：记住我的命令风格",
                    "Agent：好的，已记住你的习惯",
                    "用户：每次测试前先检查环境",
                    "Agent：已学习，会在测试前自动检查环境"
                ],
                limitations="学习需要用户明确表达",
                danger_level="safe"
            ),
            
            # 技能应用能力
            Capability(
                name="技能应用",
                description="使用已学习的技能自动执行任务",
                category="learning",
                triggers=[
                    "使用技能", "执行技能", "用技能"
                ],
                examples=[
                    "用户：执行我的代码审查流程",
                    "Agent：找到技能'代码审查'，执行中..."
                ],
                limitations="技能需要先学习才能使用",
                danger_level="safe"
            ),
            
            # 记忆能力
            Capability(
                name="记忆管理",
                description="记住用户偏好、项目设定、关键决策",
                category="conversation",
                triggers=[
                    "记住", "别忘", "重要", "设定"
                ],
                examples=[
                    "用户：记住我更喜欢详细注释",
                    "Agent：已记住，会在代码中添加详细注释"
                ],
                limitations="记忆会持久化存储",
                danger_level="safe"
            ),
            
            # 帮助能力
            Capability(
                name="能力清单",
                description="告诉用户Agent有哪些能力",
                category="conversation",
                triggers=[
                    "你会什么", "有什么能力", "能做什么", "help", "能力"
                ],
                examples=[
                    "用户：你有什么能力？",
                    "Agent：我的能力包括：对话、命令执行、项目分析..."
                ],
                limitations=None,
                danger_level="safe"
            ),
            
            # 代码生成能力
            Capability(
                name="代码生成",
                description="生成代码、组件、API等",
                category="execution",
                triggers=[
                    "写代码", "创建", "生成", "创建"
                ],
                examples=[
                    "用户：创建一个React组件",
                    "Agent：生成组件代码..."
                ],
                limitations="网页/项目/多文件/构建测试任务优先写入 workspace；小改动可直接回答。",
                requires_confirmation=True,
                danger_level="warning"
            ),
            
            # 调试能力
            Capability(
                name="代码调试",
                description="分析错误、定位问题",
                category="analysis",
                triggers=[
                    "报错", "错误", "debug", "问题", "bug"
                ],
                examples=[
                    "用户：运行报错",
                    "Agent：分析错误信息..."
                ],
                limitations="只能分析，无法直接修复",
                danger_level="safe"
            ),
            
            # 优化建议
            Capability(
                name="代码优化建议",
                description="提供代码改进建议",
                category="analysis",
                triggers=[
                    "优化", "改进", "建议", "性能"
                ],
                examples=[
                    "用户：有什么优化建议吗",
                    "Agent：建议：1. 添加缓存 2. 优化数据库查询..."
                ],
                limitations="只提供建议，不自动修改",
                danger_level="safe"
            ),

            # 人格设定能力
            Capability(
                name="人格与用户画像",
                description="拥有可配置的Agent人格设定和用户画像，能根据设定调整行为方式",
                category="conversation",
                triggers=[
                    "人格", "性格", "你是谁", "你叫什么", "设定", "画像",
                    "偏好", "习惯", "风格", "语气", "记住我"
                ],
                examples=[
                    "用户：你有什么人格设定？",
                    "Agent：我的人格设定包括专业助手身份和简洁沟通风格...",
                    "用户：记住我喜欢详细解释",
                    "Agent：已更新用户画像，会在后续回答中提供详细解释"
                ],
                limitations="人格设定通过MEMORY.md管理，用户画像通过USER.md管理",
                danger_level="safe"
            ),

            # 梦境反思能力
            Capability(
                name="梦境反思与记忆归纳",
                description="通过后台反思引擎分析对话，自动提炼模式、偏好和见解并晋升为长期记忆",
                category="learning",
                triggers=[
                    "梦境", "反思", "忘记", "还记得", "学习",
                    "成长", "归纳", "提炼", "长期记忆"
                ],
                examples=[
                    "用户：你还记得我上次说的吗？",
                    "Agent：梦境系统已将关键信息纳入长期记忆...",
                    "用户：帮我归纳一下我们的讨论",
                    "Agent：通过梦境反思，我提炼出以下关键点..."
                ],
                limitations="梦境自动运行，也可手动触发",
                danger_level="safe"
            ),

            # 工具执行能力
            Capability(
                name="工具执行框架",
                description="可以执行CLI命令、文件操作、项目分析等多种工具，完成复杂任务",
                category="execution",
                triggers=[
                    "运行", "执行", "创建", "删除", "修改", "启动",
                    "安装", "构建", "测试", "分析", "查看", "工具"
                ],
                examples=[
                    "用户：运行测试",
                    "Agent：使用CLI工具执行: pytest tests/ -v",
                    "用户：帮我创建一个API路由",
                    "Agent：使用文件工具创建新的路由文件..."
                ],
                limitations="危险操作需用户确认",
                requires_confirmation=True,
                danger_level="warning"
            ),
        ]
    
    def get_all_capabilities(self) -> List[Capability]:
        """获取所有能力"""
        return self.capabilities
    
    def get_capabilities_by_category(self, category: str) -> List[Capability]:
        """按类别获取能力"""
        return [c for c in self.capabilities if c.category == category]
    
    def find_capability(self, query: str) -> List[Capability]:
        """根据查询找到相关能力"""
        query_lower = query.lower()
        matches = []
        
        for cap in self.capabilities:
            # 检查触发词
            if any(trigger in query_lower for trigger in cap.triggers):
                matches.append(cap)
                continue
            
            # 检查描述
            if any(word in cap.description.lower() for word in query_lower):
                matches.append(cap)
                continue
        
        return matches
    
    def generate_capability_list_prompt(self) -> str:
        """生成能力清单提示词"""
        sections = {
            'conversation': '💬 对话能力',
            'execution': '⚡ 执行能力',
            'analysis': '🔍 分析能力',
            'learning': '🧠 学习能力'
        }
        
        lines = ["## 我具备的能力\n"]
        
        for category, title in sections.items():
            caps = self.get_capabilities_by_category(category)
            if caps:
                lines.append(f"\n### {title}\n")
                for cap in caps:
                    lines.append(f"**{cap.name}**：{cap.description}")
                    if cap.examples:
                        lines.append(f"\n  示例：")
                        for ex in cap.examples[:2]:
                            lines.append(f"\n  - {ex}")
                    if cap.limitations:
                        lines.append(f"\n  ⚠️ 限制：{cap.limitations}")
        
        lines.append("\n---\n")
        lines.append("你可以随时问我：\"你有什么能力\"来查看完整清单")
        
        return '\n'.join(lines)
    
    def generate_usage_guide(self) -> str:
        """生成使用指南"""
        return """
## 如何与我交互

### 1. 基本对话
直接用自然语言提问，我理解你的意图并回答。

### 2. 执行命令
- 告诉我\"运行pytest\" → 自动执行测试
- 告诉我\"启动后端\" → 启动服务
- 告诉我\"构建项目\" → 执行构建

### 3. 项目分析
- 告诉我\"分析项目架构\" → 分析项目结构
- 告诉我\"搜索XXX\" → 搜索代码
- 告诉我\"查看app.py\" → 读取文件

### 4. 学习技能
- 告诉我\"记住我的习惯\" → 学习用户偏好
- 告诉\"以后做XX就用YY\" → 创建可复用模式

### 5. 主动使用能力
你可以这样说：
- \"运行后端测试\"
- \"分析这个模块\"
- \"创建新组件\"
- \"记住我的编码风格\"
- \"查找所有API路由\"
"""
    
    def get_capability_summary(self) -> str:
        """获取能力摘要"""
        categories = {}
        for cap in self.capabilities:
            if cap.category not in categories:
                categories[cap.category] = []
            categories[cap.category].append(cap.name)
        
        lines = ["## 我的能力概览\n"]
        for cat, names in categories.items():
            lines.append(f"**{cat}**：{', '.join(names)}")
        
        return '\n'.join(lines)
