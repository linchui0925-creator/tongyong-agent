# Agent 能力增强方案

## 问题分析

### 当前 Agent 的局限性

通过分析代码，发现当前 Agent 存在以下核心问题：

#### 1. 缺乏项目架构理解能力

**现状**：
- Agent 只进行简单的对话处理
- 没有分析项目文件结构的能力
- 无法理解代码架构和模块关系
- 无法读取和分析项目代码
- 缺少项目相关的上下文注入机制

**具体表现**：
```
用户：帮我分析一下这个项目的架构
Agent：只能给出模糊的回答，无法深入分析
```

#### 2. 缺乏 CLI 命令执行能力

**现状**：
- Agent 只是接收消息 → 调用 LLM → 保存回复
- 没有工具执行机制
- 无法执行 shell 命令
- 无法操作文件
- 只能做对话，无法执行实际任务

**具体表现**：
```
用户：帮我创建一个新的组件
Agent：只能生成代码，无法实际创建文件
```

#### 3. 缺乏自动技能创建机制

**现状**：
- 我们已经实现了 SkillManager 骨架
- 但 Agent 没有集成技能学习能力
- 没有自动识别可复用模式的机制
- 每次都是从头开始

**具体表现**：
```
用户：我教你一个命令，以后执行这个任务就用这个命令
Agent：无法记录和复用这个"命令"
```

## 增强方案设计

### 方案一：工具系统集成（推荐）

#### 1.1 实现项目架构理解能力

**目标**：让 Agent 能够理解项目结构和代码架构

**实现方案**：

```python
class ProjectContextManager:
    """项目上下文管理器"""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.structure_cache = None
    
    async def analyze_structure(self) -> Dict[str, Any]:
        """分析项目结构"""
        structure = {
            'languages': [],        # 编程语言
            'frameworks': [],        # 框架
            'modules': [],           # 模块
            'dependencies': {},      # 依赖关系
            'architecture': {}       # 架构模式
        }
        
        # 1. 分析目录结构
        structure['modules'] = await self._analyze_directories()
        
        # 2. 分析配置文件
        structure['config'] = await self._analyze_configs()
        
        # 3. 分析依赖关系
        structure['dependencies'] = await self._analyze_dependencies()
        
        return structure
    
    async def get_file_content(self, file_path: str) -> str:
        """获取文件内容"""
        full_path = os.path.join(self.project_root, file_path)
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    async def search_code(self, pattern: str) -> List[Dict]:
        """搜索代码"""
        results = []
        for root, dirs, files in os.walk(self.project_root):
            for file in files:
                if file.endswith(('.py', '.js', '.ts', '.tsx')):
                    path = os.path.join(root, file)
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if pattern in content:
                            results.append({
                                'file': path,
                                'content': content
                            })
        return results
```

**在 Agent 中集成**：

```python
class EnhancedAgent:
    def __init__(self):
        self.project_context = ProjectContextManager(
            project_root="/Users/linc/Documents/tongyong-agent"
        )
    
    async def chat(self, message: str):
        # 1. 检测是否需要项目上下文
        if self._needs_project_context(message):
            project_info = await self.project_context.analyze_structure()
            context_prompt = self._build_project_context_prompt(project_info)
            messages.append(SystemMessage(content=context_prompt))
        
        # 2. 继续正常的对话流程
        response = await self.llm.chat(messages)
        return response
    
    def _needs_project_context(self, message: str) -> bool:
        """判断是否需要项目上下文"""
        keywords = [
            '架构', '结构', '分析', '代码', '模块',
            '项目', '组件', '创建', '修改'
        ]
        return any(kw in message for kw in keywords)
```

#### 1.2 实现 CLI 命令执行能力

**目标**：让 Agent 能够执行实际的 CLI 命令

**实现方案**：

```python
class CommandExecutor:
    """命令执行器"""
    
    def __init__(self, working_dir: str):
        self.working_dir = working_dir
        self.allowed_commands = [
            'ls', 'cat', 'grep', 'find', 'git',
            'npm', 'pip', 'python', 'node',
            'mkdir', 'touch', 'echo', 'cp', 'mv'
        ]
    
    async def execute(self, command: str) -> Dict[str, Any]:
        """安全执行命令"""
        # 1. 命令白名单检查
        cmd_parts = command.split()
        if cmd_parts[0] not in self.allowed_commands:
            return {
                'success': False,
                'error': f'命令 {cmd_parts[0]} 不在允许列表中'
            }
        
        # 2. 危险命令检查
        dangerous = ['rm -rf', 'sudo', 'mkfs', 'dd if=/dev/zero']
        if any(d in command for d in dangerous):
            return {
                'success': False,
                'error': '检测到危险命令，需要审批'
            }
        
        # 3. 执行命令
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir
        )
        stdout, stderr = await proc.communicate()
        
        return {
            'success': proc.returncode == 0,
            'stdout': stdout.decode(),
            'stderr': stderr.decode(),
            'returncode': proc.returncode
        }
```

**在 Agent 中集成**：

```python
class EnhancedAgent:
    def __init__(self):
        self.command_executor = CommandExecutor(
            working_dir="/Users/linc/Documents/tongyong-agent"
        )
    
    async def process_message(self, message: str) -> Dict[str, Any]:
        # 1. 检测是否需要执行命令
        if self._needs_command_execution(message):
            command = self._extract_command(message)
            result = await self.command_executor.execute(command)
            
            # 2. 生成自然语言响应
            response = self._generate_command_response(command, result)
            return {'reply': response, 'executed': True}
        
        # 3. 否则进行正常对话
        return await self.chat(message)
    
    def _needs_command_execution(self, message: str) -> bool:
        """判断是否需要执行命令"""
        action_keywords = [
            '创建', '删除', '修改', '执行', '运行',
            '帮我', '请', 'build', 'test', 'run'
        ]
        return any(kw in message for kw in action_keywords)
```

#### 1.3 实现自动技能创建机制

**目标**：让 Agent 能够从对话中自动学习可复用的技能

**实现方案**：

```python
class AutoSkillLearner:
    """自动技能学习器"""
    
    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager
        self.learning_threshold = 3  # 重复次数达到3次才学习
    
    async def analyze_conversation(self, messages: List[Dict]) -> Optional[Skill]:
        """分析对话，识别可复用的模式"""
        # 1. 检测重复模式
        patterns = self._detect_patterns(messages)
        
        if not patterns:
            return None
        
        # 2. 检查是否值得学习
        for pattern in patterns:
            if pattern['count'] >= self.learning_threshold:
                # 3. 创建技能
                skill = await self._create_skill(pattern)
                return skill
        
        return None
    
    async def _detect_patterns(self, messages: List[Dict]) -> List[Dict]:
        """检测重复模式"""
        patterns = []
        
        # 简单的模式检测逻辑
        # 检测相似的任务描述
        task_descriptions = [m['content'] for m in messages]
        
        for i, desc1 in enumerate(task_descriptions):
            count = sum(1 for desc2 in task_descriptions 
                      if self._is_similar(desc1, desc2))
            if count >= 2:
                patterns.append({
                    'description': desc1,
                    'count': count,
                    'type': 'repeated_task'
                })
        
        return patterns
    
    def _is_similar(self, text1: str, text2: str) -> bool:
        """判断两个文本是否相似"""
        # 简单的相似度检测
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return False
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) > 0.7
    
    async def _create_skill(self, pattern: Dict) -> Skill:
        """创建技能"""
        skill = Skill(
            name=self._generate_skill_name(pattern['description']),
            content=pattern['description'],
            trigger_conditions=[pattern['description']],
            execution_steps=['执行指定任务'],
            category='auto_learned'
        )
        
        await self.skill_manager.create(skill)
        
        return skill
```

**在 Agent 中集成**：

```python
class EnhancedAgent:
    def __init__(self):
        self.skill_learner = AutoSkillLearner()
    
    async def chat(self, message: str):
        # 1. 检索相关技能
        relevant_skills = await self.skill_manager.search(message)
        if relevant_skills:
            skills_context = self._build_skills_context(relevant_skills)
            messages.append(SystemMessage(content=skills_context))
        
        # 2. 正常对话
        response = await self.llm.chat(messages)
        
        # 3. 记录对话用于技能学习
        await self.skill_learner.record_conversation(message, response)
        
        # 4. 检查是否可以学习新技能
        if self.skill_learner.should_learn():
            new_skill = await self.skill_learner.analyze_conversation()
            if new_skill:
                logger.info(f"自动学习到新技能: {new_skill.name}")
        
        return response
```

### 方案二：增强上下文注入

#### 2.1 项目架构摘要

```python
SYSTEM_PROMPT = """你是一个专业的编程助手。

## 项目信息
项目名称：同通用 Agent
项目路径：/Users/linc/Documents/tongyong-agent

### 技术栈
- 后端：Python FastAPI + SQLite
- 前端：React + TypeScript + Vite
- LLM：通义千问 / OpenAI

### 项目结构
backend/
├── app/
│   ├── api/          # API 路由
│   ├── core/         # 核心模块（Agent引擎）
│   ├── memory/       # 记忆存储
│   ├── llm/          # LLM 接口
│   ├── tools/        # 工具系统（新增）
│   ├── skills/       # 技能系统（新增）
│   ├── dreaming/      # 梦境系统（新增）
│   └── scheduler/     # 调度系统（新增）
frontend/
├── src/
│   ├── components/   # React 组件
│   ├── pages/        # 页面
│   └── utils/        # 工具函数

### 可用命令
- npm run dev    # 启动前端开发服务器（端口5173）
- npm run build  # 构建前端
- python app/main.py  # 启动后端（端口8000）
- pytest tests/        # 运行测试

你具备以下能力：
1. 理解项目架构和代码
2. 执行 CLI 命令
3. 创建和修改文件
4. 分析和解决问题
5. 从对话中学习新技能
"""
```

#### 2.2 动态上下文注入

```python
async def build_dynamic_context(self, message: str) -> str:
    """构建动态上下文"""
    contexts = []
    
    # 1. 项目结构上下文（如果需要）
    if any(kw in message for kw in ['架构', '结构', '分析']):
        structure = await self.project_manager.analyze()
        contexts.append(f"## 当前项目结构\n{structure}")
    
    # 2. 近期修改上下文（如果有）
    recent_changes = await self.git_manager.get_recent_changes()
    if recent_changes:
        contexts.append(f"## 近期修改\n{recent_changes}")
    
    # 3. 技能上下文（如果相关）
    skills = await self.skill_manager.get_relevant_skills(message)
    if skills:
        contexts.append(f"## 相关技能\n{skills}")
    
    return "\n\n".join(contexts)
```

### 方案三：CLI 命令理解增强

#### 3.1 自然语言到命令的转换

```python
class CommandConverter:
    """自然语言到命令的转换"""
    
    COMMAND_PATTERNS = {
        '启动.*服务': {
            'backend': 'cd backend && python app/main.py',
            'frontend': 'cd frontend && npm run dev'
        },
        '运行.*测试': {
            'backend': 'cd backend && pytest tests/',
            'frontend': 'cd frontend && npm test'
        },
        '构建.*': 'npm run build',
        '安装.*依赖': 'npm install',
        '创建.*组件': 'touch {name}.tsx'
    }
    
    def convert(self, natural_language: str) -> Optional[str]:
        """将自然语言转换为命令"""
        for pattern, command in self.COMMAND_PATTERNS.items():
            if re.search(pattern, natural_language):
                # 提取参数
                match = re.search(pattern, natural_language)
                params = match.groups()
                
                if isinstance(command, dict):
                    return command.get(params[0] if params else 'backend', '')
                
                return command.format(*params)
        
        return None
```

#### 3.2 命令执行结果理解

```python
async def execute_and_explain(self, command: str) -> str:
    """执行命令并解释结果"""
    # 1. 执行命令
    result = await self.executor.execute(command)
    
    # 2. 生成解释
    if result['success']:
        return f"命令执行成功！\n\n输出：\n{result['stdout']}"
    else:
        return f"命令执行失败。\n\n错误：\n{result['stderr']}\n\n建议：检查命令是否正确"
```

## 实现优先级

### Phase 1：基础能力（1-2天）
1. ✅ 集成 ProjectContextManager
2. ✅ 增强 System Prompt
3. ✅ 基础 CLI 执行能力

### Phase 2：智能增强（2-3天）
1. ✅ CommandConverter 实现
2. ✅ 自动技能学习基础
3. ✅ 上下文动态注入

### Phase 3：体验优化（1-2天）
1. ✅ 命令结果自然语言解释
2. ✅ 技能推荐和展示
3. ✅ 用户反馈收集

## 测试用例

### 测试1：项目架构理解
```python
# 输入
message = "帮我分析一下这个项目的架构"

# 期望输出
# Agent 应该分析：
# - 后端技术栈（FastAPI + SQLite）
# - 前端技术栈（React + TypeScript）
# - 项目目录结构
# - 模块依赖关系
```

### 测试2：CLI 命令执行
```python
# 输入
message = "帮我运行一下后端测试"

# 期望输出
# 1. 识别为需要执行命令
# 2. 转换为：cd backend && pytest tests/
# 3. 执行并返回结果
# 4. 用自然语言解释结果
```

### 测试3：自动技能学习
```python
# 对话序列
messages = [
    "帮我创建一个用户组件",
    "再创建一个订单组件",
    "再创建一个产品组件"
]

# 期望行为
# 检测到重复模式（创建组件）
# 自动学习为技能"批量创建组件"
# 下次用户说"再创建几个组件"时自动应用该技能
```

## 预期效果

### Before
```
用户：帮我分析项目架构
Agent：这是一个基于FastAPI的项目...（模糊回答）

用户：创建个组件
Agent：好的，我来帮你创建...（无法实际创建）
```

### After
```
用户：帮我分析项目架构
Agent：
## 项目架构分析

**技术栈**：Python FastAPI + React + TypeScript

**目录结构**：
- backend/app/ - 后端应用代码
- frontend/src/ - 前端源代码

**模块依赖**：...

用户：创建个组件
Agent：正在为你创建组件...
$ cd frontend/src/components
$ touch NewComponent.tsx
✅ 组件创建成功！

需要我帮你添加组件内容吗？
```

## 风险评估

### 技术风险
- ❌ **命令执行安全**：需要严格的命令白名单和危险命令检测
- ⚠️ **误识别模式**：自动学习的技能可能不准确
- ⚠️ **上下文长度**：动态上下文可能超过 LLM 的 token 限制

### 缓解措施
1. **命令安全**：多层检查（白名单 + 黑名单 + 审批）
2. **技能验证**：创建技能需要用户确认
3. **上下文压缩**：优先注入关键信息，压缩次要信息

## 总结

通过以上增强方案，Agent 将具备：

1. ✅ **项目理解能力**：能够深入分析项目架构和代码
2. ✅ **命令执行能力**：能够执行实际的 CLI 命令
3. ✅ **技能学习能力**：能够从对话中自动学习可复用模式
4. ✅ **智能上下文**：能够动态注入相关的项目信息

这些能力将使 Agent 从一个简单的对话助手进化为一个真正能够**理解项目、执行任务、持续学习**的智能编程助手。
