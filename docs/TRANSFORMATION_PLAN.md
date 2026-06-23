

# 同通用 Agent 智能迭代改造方案

## 一、背景与目标

### 1.1 项目现状

当前同通用 Agent 项目是一个基于 FastAPI 后端与 React 前端的智能对话系统，其核心架构包含以下关键组件：

**后端核心模块**

- `AgentEngine`：主控引擎，负责对话处理、记忆管理和上下文构建
- `SessionContextManager`：会话上下文管理器，从数据库加载完整上下文
- `MemoryStorage`：SQLite 数据库存储层，管理会话、消息、记忆和设定
- `MemoryReviewer`：记忆审查器（可选组件），基于消息轮次阈值触发记忆提取
- `VectorStore`：向量存储层，支持语义检索

**现有工具系统**

当前项目的工具系统尚处于起步阶段，`tools` 目录基本为空。`AgentEngine` 主要通过 LLM 对话接口与用户交互，尚未建立结构化的工具调用机制。现有的数据库操作通过 `MemoryStorage` 封装，与 Agent 核心紧耦合，缺乏统一的工具注册和管理体系。

### 1.2 改造目标

本次改造旨在融合两大开源项目的核心特性，构建一个具备以下能力的新一代智能 Agent：

**核心能力目标**

- **睡眠式记忆巩固**：借鉴 OpenClaw Dreaming 的三阶段记忆整合机制，实现异步化、智能化的记忆管理
- **自我进化能力**：借鉴 Hermes Agent 的闭环学习机制，使 Agent 能够从经验中自动生成技能并持续优化
- **多维度评估体系**：建立六维评分机制，确保只有高质量内容才能晋升为长期记忆
- **跨会话知识传递**：打破会话隔离壁垒，实现跨会话的模式识别和知识复用
- **用户建模能力**：建立用户偏好模型，提供个性化服务体验
- **工具权限控制**：基于 Harness 思想构建安全的工具调用体系，实现细粒度的权限管理和危险操作审批

## 二、技术研究分析

### 2.1 OpenClaw Dreaming 机制深度解析

#### 2.1.1 设计理念

OpenClaw Dreaming 的设计灵感来源于人类睡眠过程中的记忆巩固机制。神经科学研究表明，人类睡眠包含浅睡期（Light Sleep）、快速眼动期（REM）和深睡期（Deep Sleep）三个阶段，每个阶段在记忆巩固中扮演不同角色。OpenClaw 将这一生理机制抽象为工程实现，通过三阶段协作流水线实现记忆的智能化管理。

传统 Agent 的记忆管理面临两个极端困境：过于激进会导致所有细节进入长期记忆，造成上下文臃肿和噪声积累；过于保守则会导致真正重要的模式丢失，使长期记忆形同虚设。Dreaming 机制通过分阶段评分和强化信号机制，在两个极端之间找到了平衡点。

#### 2.1.2 三阶段协作模型

**Light Sleep 阶段**承担整理和暂存的职责。该阶段的主要任务包括：读取近期每日记忆文件，摄入会话记录到语料库，使用 Jaccard 相似度（阈值 0.9）进行去重，暂存候选条目并记录强化信号。Light Sleep 阶段的输出仅写入梦境日记（Dream Diary），不会直接写入 MEMORY.md 文件。这一阶段的关键词是"排序和暂存"，为后续阶段提供候选池。

**REM Sleep 阶段**负责模式识别和主题发现。该阶段的核心任务是：读取回溯窗口内的短期召回条目，分析概念标签频率，提取主题模式，识别候选真理，生成反思性洞察。与 Light Sleep 类似，REM Sleep 的输出也不直接写入长期记忆，而是为 Deep Sleep 阶段提供强化信号。例如，当 Deep Sleep 对某个候选条目进行评分时，如果 REM 发现该条目与近期连续出现的主题高度相关，则会提供一个额外的加权加成。

**Deep Sleep 阶段**是整个机制的核心决策环节。该阶段对所有候选条目进行加权评分，应用阶段强化加成，过滤未通过阈值的候选，重新水化存活片段，最终将高质量内容追加到 MEMORY.md。Deep Sleep 是唯一有权写入长期记忆的阶段，这种权限分离确保了噪音数据永远不会污染长期记忆。

#### 2.1.3 六维加权评分机制

Deep Sleep 阶段采用六个加权基础信号对每个候选条目进行评分，各信号权重如下：

| 信号维度 | 权重 | 描述 |
|---------|------|------|
| 相关性（Relevance） | 0.30 | 平均检索质量，衡量信息被召回时的质量 |
| 频率（Frequency） | 0.24 | 条目积累的短期信号数量 |
| 查询多样性（Query Diversity） | 0.15 | 不同查询或日上下文中出现该条目的数量 |
| 时效性（Recency） | 0.15 | 时间衰减后的新鲜度分数 |
| 整合度（Consolidation） | 0.10 | 多日重复出现的强度 |
| 概念丰富度（Conceptual Richness） | 0.06 | 片段或路径中的概念标签密度 |

六个信号必须同时满足各自的阈值门才能晋升：最低分（minScore）需达到 0.8 以上，最小召回次数（minRecallCount）需达到 3 次以上，最小独立查询数（minUniqueQueries）需达到 3 个以上。任何一项不达标都会导致条目无法晋升。

#### 2.1.4 调度与输出机制

Dreaming 默认关闭，需要手动启用。调度时间默认设定为每天凌晨 3:00（UTC）自动执行一次完整的三阶段扫描，用户可通过 cron 表达式自定义运行频率。每次扫描在同一 sweep 内按固定顺序执行：Light → REM → Deep，三个阶段之间存在数据依赖关系。

输出文件分为机器状态和人类可读两类。机器状态文件存储在 `memory/.dreams/` 目录下，包括召回存储（recall-store）、阶段信号记录（phase-signals.json）、摄入检查点（ingestion-checkpoints）、锁文件（locks）和脱敏后会话语料库（session-corpus）。人类可读输出包括主梦境日记文件（DREAMS.md）、每日深度阶段详细报告（memory/dreaming/deep/YYYY-MM-DD.md）和长期记忆文件（MEMORY.md）。

### 2.2 Hermes Agent 自我进化机制深度解析

#### 2.2.1 设计理念

Hermes Agent 由 Nous Research 开发，核心差异化在于其内置的自学习闭环机制。与传统 Agent 框架将 LLM 视为执行引擎、记忆视为上下文注入的设计不同，Hermes 将 Agent 自身视为学习和进化的主体，使系统能够从经验中创建技能、在使用中自我改进、跨会话持续积累记忆。

Hermes 的设计哲学源于对现有 Agent 框架局限性的深刻洞察。传统框架面临三大困境：上下文窗口有限（模型有 token 上限）、会话隔离（每次对话都是独立实例）、无持久化层（离开对话记忆消失）。这导致用户每次都需要重复劳动，Agent 无法积累长期知识，跨会话的洞察丢失，体验割裂。

#### 2.2.2 五阶段闭环学习循环

Hermes 的自动技能生成遵循五阶段闭环流程：执行（Execute）→ 评估（Evaluate）→ 提取（Extract）→ 优化（Refine）→ 重用（Reuse）。

**执行阶段**中，Agent 接收到任务后，首先搜索技能库中是否存在相关模式。如果找到适用的技能，则将技能内容注入对话上下文，然后执行任务。与传统框架的关键区别在于，Hermes 在执行过程中会详细记录自身的行动轨迹，包括工具调用历史、成功失败状态和输出结果。

**评估阶段**在任务完成后触发。Agent 评估当前使用的方法是否具有非平凡性（Non-trivial），即该方法是否值得作为可复用的模式保存。Hermes 会对比使用技能和不使用技能的执行效果，评估技能的边际贡献。

**提取阶段**将成功的执行轨迹转化为结构化的技能文档。技能文档包含触发条件（When to use）、执行步骤（How to do）和预期结果（Expected outcome）三个核心部分。与手工编写的技能模板不同，Hermes 的技能是从实际执行经验中自动生成的。

**优化阶段**确保技能在持续使用中不断进化。当 Agent 在使用技能时遇到边界情况或发现更优方案，会自动更新技能内容。这种"边用边学"的机制使技能随着使用次数增加而不断进化，初期可能存在粗糙或不完善的地方，但会逐渐趋于成熟。

**重用阶段**实现跨会话的知识传递。通过全文搜索定位相关对话，用 LLM 生成摘要还原上下文，Agent 能够回答诸如"我上周二在处理什么项目"这类问题。

#### 2.2.3 四层记忆架构

Hermes 采用四层记忆架构，各层职责分明且互为补充：

**L1 层**为工作记忆，即会话上下文，在会话关闭时完全清除。该层是 Agent 进行实时推理的主战场，直接参与每次对话的上下文构建。

**L2 层**为持久事实记忆，存储环境信息和已学习的见解。L2 层的典型内容包括项目技术栈、团队约定、已解决的决定等。L2 采用小型策展文件（如 MEMORY.md）存储，文件格式简洁，易于人类直接阅读和编辑。

**L3 层**为跨会话检索层，通过 SQLite FTS5 全文搜索引擎实现。该层支持关键字检索，帮助 Agent 在大量历史会话中快速定位相关信息。

**L4 层**为技能层，将工作流程存储为 Markdown 文件。与开发人员在部署前编写的 LangChain 工具或 AutoGPT 插件不同，L4 技能是自生成的：从 Agent 实际运行的工作流中发展而来，开发人员无需编写任何代码。

#### 2.2.4 用户建模系统

Hermes 通过 Honcho 子系统实现用户建模。Honcho 负责收集和整理用户偏好、工作风格和交互习惯等信息，并将这些信息持久化存储。当用户与 Agent 交互时，Honcho 会将相关的用户模型信息注入上下文，使 Agent 能够提供个性化的服务体验。

用户模型与技能系统采用分离存储的设计。技能存储"怎么做"（程序性知识），用户模型存储用户偏好信息。这种分离确保了技能的可复用性不受用户个体差异的影响，同时用户偏好信息也不会污染技能库。

### 2.3 Hermes Agent 安全机制深度解析

#### 2.3.1 深度防御安全模型

Hermes Agent 采用五层深度防御安全模型，每层针对不同的威胁向量提供保护：

**第一层：用户授权** - 控制谁可以与 Agent 交互。通过平台级别的允许列表（allow-all flag）、DM 配对批准列表和平台特定的允许名单实现。`_is_user_authorized()` 方法按特定顺序检查这些配置。

**第二层：危险命令审批** - 对潜在破坏性操作要求人工确认。`tools/approval.py` 中的 `check_all_command_guards()` 函数实现约 230 行代码的审批逻辑，覆盖 30+ 种危险命令模式，包括递归删除、磁盘格式化、Fork 炸弹、SQL DROP 等。

**第三层：容器隔离** - Docker/Singularity/Modal 沙箱化执行。容器内运行时自动跳过危险命令审批提示，因为破坏性命令无法逃逸出容器。容器丢弃所有 Linux capabilities，仅选择性添加三个（DAC_OVERRIDE、CHOWN、FOWNER），并设置"no-new-privileges"标志阻止权限提升。

**第四层：MCP 凭证过滤** - 环境变量隔离。错误消息经过清理，剥离 GitHub PAT、OpenAI 风格密钥、Bearer 令牌和包含敏感信息的参数。

**第五层：跨会话隔离** - 不同会话之间的数据和状态隔离，防止信息泄露。

#### 2.3.2 危险命令检测机制

危险命令检测使用正则表达式模式匹配识别高风险操作。当命令匹配时，执行暂停直到用户批准。触发审批的模式包括：

| 模式类别 | 示例命令 | 风险描述 |
|---------|---------|---------|
| 递归删除 | `rm -rf`、`find -delete` | 可能永久丢失数据 |
| 磁盘操作 | `mkfs`、`dd if=/dev/zero` | 可能破坏文件系统 |
| 系统修改 | `sudo`、`chmod 777` | 可能提升权限或开放访问 |
| 网络操作 | `curl | sh`、`wget -O-` | 可能执行恶意代码 |
| 进程操作 | `kill -9`、`pkill` | 可能终止关键进程 |
| 危险函数 | `eval()`、`exec()`、`system()` | 可能执行任意代码 |

#### 2.3.3 审批模式配置

危险命令审批支持三种可配置模式：

**手动模式（默认）** - 检测到危险命令时暂停执行，等待用户明确批准。

**智能模式** - 使用 LLM 辅助评估命令风险，结合模式匹配和语义分析提供更准确的判断。

**关闭模式** - 仅在容器隔离环境中使用，跳过所有审批检查。

#### 2.3.4 权限层级设计

Hermes 支持基于角色的访问控制（RBAC），定义四层权限结构：

**Owner（所有者）** - 拥有系统的完全控制权，可以管理所有配置和访问权限。

**Admin（管理员）** - 拥有大部分管理功能，可以执行非破坏性操作和技能管理。

**User（用户）** - 标准用户权限，可以与 Agent 对话，使用基础工具。

**Guest（访客）** - 最低权限，仅允许只读操作和基础对话。

## 三、可行性评估

### 3.1 技术可行性分析

#### 3.1.1 架构兼容性评估

当前项目的后端架构基于 FastAPI 和 SQLite，与 OpenClaw 和 Hermes 的技术选型高度兼容。FastAPI 的异步特性天然支持 Dreaming 机制的后台任务调度需求，SQLite 的 FTS5 扩展可以满足跨会话检索需求。

项目现有的 `AgentEngine` 类提供了良好的扩展基础。通过新增组件并保持与现有接口的向后兼容，可以在不破坏原有业务逻辑的前提下实现功能增强。现有的 `SessionContextManager` 可以与新的记忆整合系统无缝对接，作为检索层的上游接口。

前端基于 React 和 TypeScript，与 OpenClaw 的 Gateway 架构类似，可以复用现有的 UI 组件实现梦境状态展示和技能管理等交互界面。

#### 3.1.2 核心模块适配分析

**记忆存储层适配**：当前 `MemoryStorage` 采用 SQLite 作为存储引擎，支持添加表结构以适应新的数据模型。Dreaming 机制所需的召回计数、多样性追踪等数据可以通过新增字段或关联表实现，与现有记忆表保持兼容。

**上下文管理适配**：现有的 `SessionContextManager` 可以在构建上下文时集成新的检索策略。REM Sleep 阶段的主题发现结果可以作为上下文增强信号注入，提高检索的相关性。

**向量检索适配**：项目已集成向量存储功能，可直接复用作为语义检索引擎。Dreaming 机制可利用向量检索结果计算相关性信号，实现评分机制。

### 3.2 功能融合可行性

#### 3.2.1 互补性分析

OpenClaw Dreaming 和 Hermes 自我进化在功能层面存在良好的互补关系。Dreaming 擅长处理记忆的整理和筛选，确保长期记忆的高质量；Hermes 擅长处理技能的生成和优化，实现知识的程序化复用。两者的结合可以实现"记忆→知识→技能"的完整转化链条。

具体而言，Dreaming 的 Light Sleep 阶段可以识别对话中的程序性知识片段，提交给 Hermes 的提取阶段；Hermes 生成的技能在多次使用后，其效果数据可以作为 Dreaming 的强化信号，影响记忆晋升决策。

#### 3.2.2 冲突点识别

两者在记忆晋升触发机制上存在潜在冲突。Dreaming 依赖多维度评分机制决定记忆晋升，Hermes 依赖执行评估决定技能创建。如果同时启用两种机制，可能导致重复处理相同内容。

解决方案：将 Dreaming 和 Hermes 的触发条件差异化设置。Dreaming 作为周期性批处理任务，主要处理未被明确技能化的模式识别；Hermes 作为事件驱动任务，仅在任务完成后触发评估。

### 3.3 资源需求评估

#### 3.3.1 计算资源

Dreaming 机制的主要计算负载集中在 Deep Sleep 阶段的多维评分计算和向量化操作。建议采用后台异步执行模式，避免影响用户请求的响应延迟。调度周期建议设定为每日一次，在系统负载较低时段执行。

Hermes 的计算负载主要集中在技能提取和优化阶段，同样建议采用异步执行模式。由于技能提取涉及 LLM 调用，需要配置相应的 API 配额。

#### 3.3.2 存储资源

新增数据主要包括：梦境阶段状态和信号记录、候选记忆池、梦境日记、技能库和用户模型文件。预估存储增量在 50MB 以内，主要取决于会话数量和技能库规模。

建议采用与现有数据隔离存储的策略，在 `data/dreams/` 目录下管理梦境相关数据，在 `data/skills/` 目录下管理技能和用户模型。

## 四、融合架构设计

### 4.1 总体架构

融合系统的总体架构采用分层设计，自下而上依次为：数据持久层、检索引擎层、记忆整合层、技能管理层、工具管理层和 Agent 核心层。各层之间通过定义良好的接口通信，保持松耦合和高内聚。

```
┌─────────────────────────────────────────────────────┐
│                   Agent 核心层                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 对话处理器  │  │ 任务执行器  │  │ 上下文构建器 │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
├─────────────────────────────────────────────────────┤
│                  工具管理层 (Harness)                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 工具注册表  │  │ 权限控制器  │  │ 审批管理器  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
├─────────────────────────────────────────────────────┤
│                  技能管理层                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 技能生成器  │  │ 技能优化器  │  │ 技能检索器  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
├─────────────────────────────────────────────────────┤
│                  记忆整合层                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ Light Sleep │  │ REM Sleep  │  │ Deep Sleep  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
├─────────────────────────────────────────────────────┤
│                  检索引擎层                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 向量检索   │  │ 全文检索   │  │ 混合检索   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
├─────────────────────────────────────────────────────┤
│                  数据持久层                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ SQLite DB   │  │ 文件存储   │  │ 向量索引   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 4.2 核心组件设计

#### 4.2.1 DreamingEngine（梦境引擎）

梦境引擎是记忆整合层的核心组件，负责协调三阶段睡眠过程的执行。引擎接受调度器触发，按照 Light → REM → Deep 的顺序执行记忆整合流程。

**关键接口设计**

```python
class DreamingEngine:
    def __init__(self, memory_storage: MemoryStorage, vector_store: VectorStore, llm: BaseLLM):
        self.memory_storage = memory_storage
        self.vector_store = vector_store
        self.llm = llm
        self.config = DreamingConfig()
        self.phase_signals: Dict[str, PhaseSignal] = {}
    
    async def run_full_sweep(self):
        """执行完整的梦境扫描"""
        await self._light_sleep()
        await self._rem_sleep()
        await self._deep_sleep()
    
    async def _light_sleep(self):
        """Light Sleep：整理和暂存"""
        pass
    
    async def _rem_sleep(self):
        """REM Sleep：主题发现"""
        pass
    
    async def _deep_sleep(self):
        """Deep Sleep：评分和晋升"""
        pass
```

**阶段信号传递机制**

Light Sleep 和 REM Sleep 的输出通过阶段信号（PhaseSignal）传递给 Deep Sleep。阶段信号包含对各候选条目的强化加成值，Deep Sleep 在计算最终评分时将这些加成纳入考虑。

```python
@dataclass
class PhaseSignal:
    entry_id: str
    source_phase: str  # "light" or "rem"
    reinforcement_value: float
    reason: str
```

#### 4.2.2 SkillManager（技能管理器）

技能管理器是技能管理层的主体，负责技能的生成、优化和检索。技能管理器与 Agent 核心交互，在任务执行完成后触发技能提取流程。

**技能数据结构**

```python
@dataclass
class Skill:
    id: str
    name: str
    content: str
    category: str
    trigger_conditions: List[str]
    execution_steps: List[str]
    expected_outcome: str
    usage_count: int = 0
    success_rate: float = 0.0
    created_at: datetime
    updated_at: datetime
    version: int = 1
```

**技能生成流程**

技能生成由 Agent 自身触发，利用 LLM 的推理能力从执行轨迹中提取结构化知识。生成过程包括轨迹分析、模式识别、文档生成和验证确认四个步骤。

#### 4.2.3 ToolHarness（工具安全框架）

工具安全框架是工具管理层的核心组件，负责工具的注册、权限控制、危险命令检测和审批管理。该框架借鉴 Hermes Agent 的安全设计理念，提供深度防御的工具体系。

**核心设计原则**

- **最小权限原则**：每个工具仅被授予完成其功能所需的最小权限集
- **纵深防御**：多层安全检查确保即使一层失效，其他层仍能提供保护
- **人类在环**：对高风险操作强制要求人工确认
- **可审计性**：所有工具调用记录完整日志，支持事后审计

**三层权限模型**

框架定义三层权限级别，与 OpenClaw 的权限模型对齐：

| 权限级别 | 描述 | 示例工具 |
|---------|------|---------|
| Level 0: 读取（read） | 仅获取信息，不修改任何数据 | 搜索、查询、文件读取 |
| Level 1: 写入（write） | 创建或修改数据 | 文件写入、数据库写入、HTTP POST/PUT |
| Level 2: 执行（execute） | 执行任意代码或命令 | shell 命令、代码执行、系统管理 |

**权限授予方式**

工具的权限通过三种机制授予：

- **角色授予**：基于用户角色（Owner、Admin、User、Guest）分配默认权限集
- **会话授予**：在特定会话中临时授予权限，可设置过期时间
- **工具授予**：针对特定工具单独配置权限，可覆盖角色默认设置

优先级顺序：工具授予 > 会话授予 > 角色授予

#### 4.2.4 用户模型管理器

用户模型管理器（HonchoAdapter）负责收集和整理用户偏好信息，为个性化服务提供数据支撑。

**用户模型数据结构**

```python
@dataclass
class UserModel:
    user_id: str
    preferences: Dict[str, Any]  # 偏好设置
    interaction_style: Dict[str, Any]  # 交互风格
    topics_of_interest: List[str]  # 感兴趣的话题
    habits: List[str]  # 常用指令模式
    last_updated: datetime
```

### 4.3 数据流设计

#### 4.3.1 对话处理数据流

用户消息进入系统后，首先经过技能检索阶段。技能管理器查询相关技能，将匹配结果注入上下文。然后，对话处理器结合上下文、技能和记忆生成回复。回复生成后，执行轨迹记录器保存完整的执行过程。

```
用户消息 → 技能检索 → 上下文构建 → 回复生成 → 执行记录
                                    ↓
                            技能评估（触发）
                                    ↓
                            技能提取（可选）
```

#### 4.3.2 记忆整合数据流

Dreaming 周期触发后，Light Sleep 阶段读取近期会话记录，进行去重和分类整理，输出候选条目到候选池。REM Sleep 阶段分析候选池中的主题模式，生成反思性洞察和强化信号。Deep Sleep 阶段结合候选条目和强化信号进行多维评分，过滤低分条目后晋升高分条目到长期记忆。

```
会话记录 → Light Sleep → 候选池
                        ↓
              REM Sleep → 主题洞察 + 强化信号
                        ↓
              Deep Sleep → 评分 → 晋升 → MEMORY.md
```

#### 4.3.3 工具调用数据流

工具调用经过多层安全检查，确保操作的合法性和安全性：

```
用户请求 → 工具注册表查询 → 权限级别检查 → 角色权限验证
                                              ↓
                    危险命令检测 ← 危险模式匹配
                           ↓
                    人工审批（如果需要）
                           ↓
                    参数验证 → 安全执行 → 审计日志
```

## 五、详细改造方案

### 5.1 改造策略

#### 5.1.1 渐进式改造原则

本次改造遵循渐进式改造原则，确保原有业务逻辑不受破坏。具体措施包括：

**向后兼容优先**：所有新增组件保持与现有接口的兼容性。`AgentEngine` 的 `chat` 方法签名保持不变，内部实现可以调用新的组件。

**功能开关控制**：新增功能通过配置项控制，默认为关闭状态。确保现有用户可以平滑升级，不受新功能影响。

**数据库隔离**：新增表结构与现有表保持独立，通过外键关联。确保数据库迁移安全可控。

#### 5.1.2 改造优先级

**第一优先级**（核心功能）：梦境引擎实现、评分机制集成、工具安全框架基础

**第二优先级**（增强功能）：技能管理系统、用户模型基础、危险命令检测

**第三优先级**（优化功能）：混合检索升级、审批工作流、Dreaming UI 集成

### 5.2 数据库改造

#### 5.2.1 新增表结构

**候选记忆表**（dream_candidates）

```sql
CREATE TABLE dream_candidates (
    id TEXT PRIMARY KEY,
    source_session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    source_type TEXT NOT NULL,  -- 'conversation', 'reflection', 'skill'
    concept_tags TEXT,  -- JSON array of tags
    recall_count INTEGER DEFAULT 0,
    unique_query_count INTEGER DEFAULT 0,
    query_diversity_score FLOAT DEFAULT 0.0,
    relevance_score FLOAT DEFAULT 0.0,
    recency_score FLOAT DEFAULT 0.0,
    consolidation_score FLOAT DEFAULT 0.0,
    conceptual_richness_score FLOAT DEFAULT 0.0,
    total_score FLOAT DEFAULT 0.0,
    phase_signal_light FLOAT DEFAULT 0.0,
    phase_signal_rem FLOAT DEFAULT 0.0,
    final_score FLOAT DEFAULT 0.0,
    status TEXT DEFAULT 'pending',  -- 'pending', 'promoted', 'rejected', 'expired'
    created_at TEXT NOT NULL,
    updated_at TEXT,
    promoted_at TEXT,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id)
);
```

**阶段信号表**（phase_signals）

```sql
CREATE TABLE phase_signals (
    id TEXT PRIMARY KEY,
    sweep_id TEXT NOT NULL,
    phase TEXT NOT NULL,  -- 'light', 'rem', 'deep'
    entry_id TEXT NOT NULL,
    reinforcement_value FLOAT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);
```

**技能表**（skills）

```sql
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    trigger_conditions TEXT,  -- JSON array
    execution_steps TEXT,  -- JSON array
    expected_outcome TEXT,
    usage_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    success_rate FLOAT DEFAULT 0.0,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',  -- 'active', 'archived', 'deprecated'
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

**技能使用记录表**（skill_usage_log）

```sql
CREATE TABLE skill_usage_log (
    id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    trigger_context TEXT,
    execution_result TEXT,
    success BOOLEAN,
    feedback TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (skill_id) REFERENCES skills(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

**用户模型表**（user_models）

```sql
CREATE TABLE user_models (
    id TEXT PRIMARY KEY,
    user_identifier TEXT NOT NULL,
    model_type TEXT NOT NULL,  -- 'preferences', 'interaction_style', 'interests'
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    source TEXT,  -- 'explicit', 'implicit'
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE(user_identifier, model_type, key)
);
```

**梦境配置表**（dreaming_config）

```sql
CREATE TABLE dreaming_config (
    id TEXT PRIMARY KEY,
    config_key TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**工具注册表**（tool_registry）

```sql
CREATE TABLE tool_registry (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    category TEXT,  -- 'file', 'network', 'database', 'system', 'custom'
    permission_level INTEGER DEFAULT 0,  -- 0=read, 1=write, 2=execute
    enabled BOOLEAN DEFAULT TRUE,
    requires_approval BOOLEAN DEFAULT FALSE,
    approval_patterns TEXT,  -- JSON array of regex patterns that trigger approval
    config_schema TEXT,  -- JSON schema for tool parameters
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

**工具权限表**（tool_permissions）

```sql
CREATE TABLE tool_permissions (
    id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'owner', 'admin', 'user', 'guest'
    granted BOOLEAN DEFAULT TRUE,
    conditions TEXT,  -- JSON object with additional conditions
    granted_by TEXT,
    granted_at TEXT,
    expires_at TEXT,
    FOREIGN KEY (tool_id) REFERENCES tool_registry(id),
    UNIQUE(tool_id, role)
);
```

**工具调用日志表**（tool_audit_log）

```sql
CREATE TABLE tool_audit_log (
    id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    session_id TEXT,
    user_id TEXT,
    action TEXT NOT NULL,  -- 'execute', 'approve', 'reject', 'timeout'
    parameters TEXT,  -- JSON object (sensitive data masked)
    result TEXT,  -- 'success', 'failed', 'pending_approval', 'approved', 'rejected'
    error_message TEXT,
    risk_level TEXT,  -- 'low', 'medium', 'high', 'critical'
    approval_status TEXT,  -- 'not_required', 'approved', 'rejected', 'pending'
    approved_by TEXT,
    approved_at TEXT,
    execution_time_ms INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (tool_id) REFERENCES tool_registry(id)
);
```

**工具审批表**（tool_approvals）

```sql
CREATE TABLE tool_approvals (
    id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    parameters TEXT NOT NULL,  -- JSON object
    risk_assessment TEXT,  -- JSON object with risk analysis
    status TEXT DEFAULT 'pending',  -- 'pending', 'approved', 'rejected', 'expired'
    approval_mode TEXT DEFAULT 'manual',  -- 'manual', 'smart', 'auto'
    expires_at TEXT,
    approved_by TEXT,
    approved_at TEXT,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (tool_id) REFERENCES tool_registry(id)
);
```

### 5.3 核心模块改造

#### 5.3.1 AgentEngine 改造

`AgentEngine` 类保持现有接口不变，内部新增对梦境引擎、技能管理器和工具安全框架的引用。在 `chat` 方法执行过程中，增加技能检索和执行记录环节。

**新增初始化逻辑**

```python
class AgentEngine:
    def __init__(self, llm=None):
        # 保留原有初始化代码
        
        # 新增：梦境引擎初始化
        self.dreaming_engine = None
        if config.get('dreaming_enabled', False):
            self.dreaming_engine = DreamingEngine(
                memory_storage=self.memory_storage,
                vector_store=self._get_vector_store(),
                llm=self._llm_manager.get_current_llm()
            )
        
        # 新增：技能管理器初始化
        self.skill_manager = None
        if config.get('skills_enabled', False):
            self.skill_manager = SkillManager(
                memory_storage=self.memory_storage,
                llm=self._llm_manager.get_current_llm()
            )
        
        # 新增：工具安全框架初始化
        self.tool_harness = None
        if config.get('tool_harness_enabled', False):
            self.tool_harness = ToolHarness(
                memory_storage=self.memory_storage
            )
```

**新增技能检索方法**

```python
async def retrieve_skills(self, query: str, session_id: str) -> List[Dict]:
    """检索与当前任务相关的技能"""
    if not self.skill_manager:
        return []
    
    skills = await self.skill_manager.search_skills(query)
    relevant_skills = []
    
    for skill in skills:
        usage_log = await self.skill_manager.log_skill_usage(
            skill_id=skill.id,
            session_id=session_id,
            trigger_context=query
        )
        relevant_skills.append({
            'skill': skill,
            'usage_log_id': usage_log.id
        })
    
    return relevant_skills
```

**新增工具执行方法**

```python
async def execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    session_id: str,
    user_role: str = 'user'
) -> ToolExecutionResult:
    """安全执行工具"""
    if not self.tool_harness:
        raise ToolHarnessDisabledError("工具安全框架未启用")
    
    # 权限检查
    permission_result = await self.tool_harness.check_permission(
        tool_name=tool_name,
        user_role=user_role,
        parameters=parameters,
        session_id=session_id
    )
    
    if not permission_result.allowed:
        return ToolExecutionResult(
            success=False,
            error=permission_result.denial_reason,
            requires_approval=False
        )
    
    # 危险命令检测
    if permission_result.requires_approval:
        approval = await self.tool_harness.request_approval(
            tool_name=tool_name,
            parameters=parameters,
            session_id=session_id,
            risk_level=permission_result.risk_level
        )
        
        if not approval.approved:
            await self.tool_harness.log_execution(
                tool_name=tool_name,
                parameters=parameters,
                session_id=session_id,
                result='rejected',
                approved_by=approval.approved_by
            )
            return ToolExecutionResult(
                success=False,
                error="工具执行被用户拒绝",
                requires_approval=True
            )
    
    # 执行工具
    return await self.tool_harness.execute_tool(
        tool_name=tool_name,
        parameters=parameters,
        session_id=session_id
    )
```

#### 5.3.2 DreamingEngine 实现

梦境引擎实现三阶段记忆整合流程，核心算法如下：

**Light Sleep 实现**

```python
async def _light_sleep(self):
    """Light Sleep：读取近期会话，去重，暂存候选"""
    lookback_days = self.config.get('lookback_days', 7)
    cutoff_date = datetime.now() - timedelta(days=lookback_days)
    
    # 读取近期会话
    sessions = await self.memory_storage.get_sessions_updated_after(cutoff_date)
    
    # 摄入会话内容到语料库
    corpus_entries = []
    for session in sessions:
        messages = await self.memory_storage.get_messages(session.id)
        # 提取有价值的片段
        for msg in messages:
            if self._is_significant_content(msg):
                corpus_entries.append(msg)
    
    # Jaccard 去重
    deduped_candidates = self._jaccard_deduplicate(corpus_entries, threshold=0.9)
    
    # 写入候选池
    for entry in deduped_candidates:
        candidate = await self._create_candidate(entry, source_type='conversation')
        self.phase_signals[f"light_{candidate.id}"] = PhaseSignal(
            entry_id=candidate.id,
            source_phase='light',
            reinforcement_value=1.0,
            reason='fresh_candidate'
        )
    
    # 写入 Light Sleep 块到梦境日记
    await self._write_dream_log('light', deduped_candidates)
```

**REM Sleep 实现**

```python
async def _rem_sleep(self):
    """REM Sleep：分析主题模式，生成反思性洞察"""
    candidates = await self.memory_storage.get_pending_candidates()
    
    # 分析概念标签频率
    tag_frequencies = Counter()
    for candidate in candidates:
        tags = json.loads(candidate.concept_tags or '[]')
        tag_frequencies.update(tags)
    
    # 提取高频主题
    dominant_themes = tag_frequencies.most_common(5)
    
    # 识别候选真理（反复出现的模式）
    candidate_truths = await self._identify_patterns(candidates, dominant_themes)
    
    # 生成反思性洞察
    insights = []
    for truth in candidate_truths:
        insight = await self.llm.generate_insight(truth)
        insights.append(insight)
        
        # 为相关候选添加 REM 强化信号
        for related_candidate in truth.related_entries:
            self.phase_signals[f"rem_{related_candidate.id}"] = PhaseSignal(
                entry_id=related_candidate.id,
                source_phase='rem',
                reinforcement_value=truth.confidence * 0.5,
                reason=f'related_to_theme: {truth.theme}'
            )
    
    # 写入 REM Sleep 块到梦境日记
    await self._write_dream_log('rem', insights)
```

**Deep Sleep 实现**

```python
async def _deep_sleep(self):
    """Deep Sleep：多维评分，晋升高质量内容"""
    candidates = await self.memory_storage.get_pending_candidates()
    promoted = []
    
    for candidate in candidates:
        # 获取阶段强化信号
        light_signal = self.phase_signals.get(f"light_{candidate.id}")
        rem_signal = self.phase_signals.get(f"rem_{candidate.id}")
        
        # 计算六维评分
        scores = await self._calculate_dimensions(candidate)
        
        # 应用加权公式
        final_score = (
            scores.relevance * 0.30 +
            scores.frequency * 0.24 +
            scores.query_diversity * 0.15 +
            scores.recency * 0.15 +
            scores.consolidation * 0.10 +
            scores.conceptual_richness * 0.06
        )
        
        # 加上阶段强化信号
        if light_signal:
            final_score += light_signal.reinforcement_value * 0.1
        if rem_signal:
            final_score += rem_signal.reinforcement_value * 0.2
        
        candidate.final_score = final_score
        
        # 检查晋升阈值
        if (final_score >= self.config.min_score and
            candidate.recall_count >= self.config.min_recall_count and
            candidate.unique_query_count >= self.config.min_unique_queries):
            
            # 执行晋升
            await self._promote_to_memory(candidate)
            candidate.status = 'promoted'
            promoted.append(candidate)
        else:
            candidate.status = 'rejected'
        
        await self.memory_storage.update_candidate(candidate)
    
    # 写入 Deep Sleep 结果到梦境日记和 MEMORY.md
    await self._write_dream_log('deep', promoted)
    await self._update_memory_file(promoted)
```

#### 5.3.3 SkillManager 实现

技能管理器实现五阶段闭环学习流程：

```python
class SkillManager:
    async def execute_evaluate_extract_refine(self, session_id: str, execution_result: TaskResult):
        """执行评估提取优化流程"""
        # 评估阶段
        is_non_trivial = await self._evaluate_significance(execution_result)
        if not is_non_trivial:
            return None
        
        # 提取阶段
        skill_draft = await self._extract_skill(execution_result)
        
        # 检查是否已存在相似技能
        existing = await self.search_skills(skill_draft.name)
        if existing:
            # 优化阶段：更新现有技能
            optimized = await self._refine_skill(existing[0], skill_draft)
            return optimized
        else:
            # 创建新技能
            new_skill = await self._create_skill(skill_draft)
            return new_skill
    
    async def _extract_skill(self, execution_result: TaskResult) -> SkillDraft:
        """从执行轨迹中提取技能"""
        trajectory = execution_result.trajectory
        
        prompt = f"""
        从以下执行轨迹中提取可复用的技能：
        
        任务：{execution_result.task_description}
        
        执行步骤：
        {chr(10).join([f'{i+1}. {step}' for i, step in enumerate(trajectory.steps)])}
        
        结果：{execution_result.outcome}
        
        请提取：
        1. 触发条件（When to use）：在什么情况下应该使用此技能
        2. 执行步骤（How to do）：具体操作步骤
        3. 预期结果（Expected outcome）：预期的成功结果
        """
        
        response = await self.llm.chat([Message(role='user', content=prompt)])
        return self._parse_skill_draft(response)
```

#### 5.3.4 ToolHarness 实现

工具安全框架是整个工具管理系统的核心，负责工具注册、权限控制、危险检测和审批管理：

```python
class ToolHarness:
    """工具安全框架 - 实现深度防御的工具体系"""
    
    def __init__(self, memory_storage: MemoryStorage):
        self.memory_storage = memory_storage
        self.tool_registry = ToolRegistry(memory_storage)
        self.permission_manager = PermissionManager(memory_storage)
        self.dangerous_command_detector = DangerousCommandDetector()
        self.approval_manager = ApprovalManager(memory_storage)
        self.audit_logger = AuditLogger(memory_storage)
        
        # 注册内置工具
        self._register_builtin_tools()
    
    async def check_permission(
        self,
        tool_name: str,
        user_role: str,
        parameters: Dict[str, Any],
        session_id: str
    ) -> PermissionResult:
        """检查工具执行权限"""
        # 1. 工具是否存在且启用
        tool = await self.tool_registry.get_tool(tool_name)
        if not tool or not tool.enabled:
            return PermissionResult(
                allowed=False,
                denial_reason=f"工具 {tool_name} 不存在或已禁用"
            )
        
        # 2. 角色权限检查
        role_permission = await self.permission_manager.check_role_permission(
            tool_id=tool.id,
            role=user_role
        )
        
        if not role_permission.granted:
            return PermissionResult(
                allowed=False,
                denial_reason=f"角色 {user_role} 没有执行工具 {tool_name} 的权限"
            )
        
        # 3. 会话临时权限检查
        session_permission = await self.permission_manager.check_session_permission(
            tool_id=tool.id,
            session_id=session_id
        )
        
        if session_permission and not session_permission.granted:
            return PermissionResult(
                allowed=False,
                denial_reason="会话临时权限已撤销"
            )
        
        # 4. 危险命令检测
        risk_level = await self.dangerous_command_detector.assess_risk(
            tool_name=tool_name,
            parameters=parameters
        )
        
        requires_approval = (
            risk_level in ['high', 'critical'] or
            tool.requires_approval
        )
        
        return PermissionResult(
            allowed=True,
            risk_level=risk_level,
            requires_approval=requires_approval,
            permission_level=tool.permission_level
        )
    
    async def request_approval(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        session_id: str,
        risk_level: str
    ) -> ApprovalResult:
        """请求工具执行审批"""
        # 创建审批请求
        approval_request = await self.approval_manager.create_request(
            tool_name=tool_name,
            parameters=parameters,
            session_id=session_id,
            risk_level=risk_level
        )
        
        # 根据审批模式处理
        if self.approval_mode == 'auto':
            # 自动批准低风险操作
            if risk_level == 'low':
                return await self.approval_manager.auto_approve(approval_request.id)
        
        elif self.approval_mode == 'smart':
            # 智能审批：使用 LLM 辅助判断
            risk_assessment = await self._smart_assess_risk(
                tool_name=tool_name,
                parameters=parameters
            )
            await self.approval_manager.update_risk_assessment(
                approval_request.id,
                risk_assessment
            )
            
            if risk_assessment.approved:
                return await self.approval_manager.auto_approve(approval_request.id)
        
        # 手动审批：等待用户确认
        return ApprovalResult(
            approved=False,
            status='pending',
            approval_id=approval_request.id
        )
    
    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        session_id: str
    ) -> ToolExecutionResult:
        """安全执行工具"""
        start_time = time.time()
        
        try:
            # 获取工具实现
            tool_impl = self.tool_registry.get_implementation(tool_name)
            
            # 执行前钩子
            await tool_impl.pre_execute(parameters)
            
            # 执行工具
            result = await tool_impl.execute(parameters)
            
            # 执行后钩子
            await tool_impl.post_execute(result)
            
            # 记录成功日志
            execution_time = int((time.time() - start_time) * 1000)
            await self.audit_logger.log_execution(
                tool_name=tool_name,
                parameters=self._mask_sensitive_parameters(parameters),
                session_id=session_id,
                result='success',
                execution_time_ms=execution_time
            )
            
            return ToolExecutionResult(
                success=True,
                result=result,
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            # 记录失败日志
            await self.audit_logger.log_execution(
                tool_name=tool_name,
                parameters=self._mask_sensitive_parameters(parameters),
                session_id=session_id,
                result='failed',
                error_message=str(e)
            )
            
            return ToolExecutionResult(
                success=False,
                error=str(e)
            )
    
    def _mask_sensitive_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """屏蔽敏感参数"""
        sensitive_keys = ['password', 'token', 'api_key', 'secret', 'credential']
        masked = {}
        
        for key, value in parameters.items():
            if any(s in key.lower() for s in sensitive_keys):
                masked[key] = '***MASKED***'
            else:
                masked[key] = value
        
        return masked
```

**危险命令检测器实现**

```python
class DangerousCommandDetector:
    """危险命令检测器 - 基于模式匹配识别高风险操作"""
    
    def __init__(self):
        self.dangerous_patterns = [
            # 递归删除
            (r'rm\s+-rf\s+', 'critical', '递归删除操作可能导致永久数据丢失'),
            (r'rm\s+-r\s+/\s*$', 'critical', '删除根目录'),
            (r'find\s+.*-delete', 'high', 'find 删除操作'),
            (r'del\s+/[sfq]\s+', 'critical', 'Windows 递归删除'),
            
            # 磁盘操作
            (r'mkfs', 'critical', '格式化磁盘'),
            (r'dd\s+.*of=/dev/', 'critical', '直接写入设备'),
            (r'diskutil\s+eraseDisk', 'critical', 'macOS 磁盘格式化'),
            
            # 系统修改
            (r'sudo\s+', 'high', '权限提升'),
            (r'chmod\s+777', 'high', '开放完全权限'),
            (r'chmod\s+-R\s+777', 'critical', '递归开放完全权限'),
            
            # 网络危险操作
            (r'curl\s+.*\|\s*sh', 'critical', '远程代码执行'),
            (r'wget\s+.*-O-\s+.*\|\s*sh', 'critical', '远程代码执行'),
            (r'nc\s+-[el].*-reverse', 'high', '反向 shell'),
            
            # 进程操作
            (r'kill\s+-9', 'medium', '强制终止进程'),
            (r'pkill\s+', 'medium', '批量终止进程'),
            (r'taskkill', 'medium', 'Windows 终止进程'),
            
            # 危险函数
            (r'eval\s*\(', 'high', '动态代码执行'),
            (r'exec\s*\(', 'high', '动态代码执行'),
            (r'system\s*\(', 'high', '系统命令执行'),
            
            # 数据库危险操作
            (r'DROP\s+TABLE', 'critical', '删除数据库表'),
            (r'DROP\s+DATABASE', 'critical', '删除数据库'),
            (r'TRUNCATE\s+', 'high', '清空表数据'),
            
            # Git 危险操作
            (r'git\s+push\s+--force', 'high', '强制推送'),
            (r'git\s+push\s+--all\s+--force', 'critical', '强制推送所有分支'),
            (r'git\s+filter-branch', 'high', '重写 Git 历史'),
            
            # 容器危险操作
            (r'docker\s+rm\s+-f', 'medium', '强制删除容器'),
            (r'docker\s+rmi\s+-f', 'medium', '强制删除镜像'),
            (r'docker\s+stop\s+$(docker', 'high', '停止所有容器'),
        ]
    
    async def assess_risk(
        self,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> RiskAssessment:
        """评估工具执行风险"""
        # 转换为可检测的命令字符串
        command_str = self._parameters_to_command(tool_name, parameters)
        
        # 逐个匹配危险模式
        matched_patterns = []
        for pattern, level, description in self.dangerous_patterns:
            if re.search(pattern, command_str, re.IGNORECASE):
                matched_patterns.append({
                    'pattern': pattern,
                    'level': level,
                    'description': description
                })
        
        if not matched_patterns:
            return RiskAssessment(
                risk_level='low',
                matched_patterns=[],
                recommendation='安全，可执行'
            )
        
        # 确定最高风险级别
        level_priority = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
        max_level = max(matched_patterns, key=lambda p: level_priority.get(p['level'], 0))
        
        return RiskAssessment(
            risk_level=max_level['level'],
            matched_patterns=matched_patterns,
            recommendation=f"检测到 {len(matched_patterns)} 个危险模式，需要人工确认"
        )
    
    def _parameters_to_command(self, tool_name: str, parameters: Dict[str, Any]) -> str:
        """将工具参数转换为命令字符串"""
        if tool_name == 'shell':
            return parameters.get('command', '')
        elif tool_name == 'file_write':
            return parameters.get('content', '')
        elif tool_name == 'file_read':
            return parameters.get('path', '')
        else:
            return str(parameters)
```

**CLI 工具包装器实现**

```python
class CLIToolWrapper:
    """CLI 工具安全包装器 - 提供受限的命令执行环境"""
    
    def __init__(self, allowed_commands: List[str] = None):
        # 默认允许的命令白名单
        self.allowed_commands = allowed_commands or [
            'ls', 'cat', 'grep', 'find', 'git', 'npm', 'pip',
            'python', 'python3', 'node', 'cargo', 'make'
        ]
        
        # 禁止的命令黑名单
        self.forbidden_patterns = [
            r'rm\s+-rf\s+/',
            r'sudo\s+',
            r'chmod\s+777',
            r'curl.*\|.*sh',
            r'wget.*\|.*sh',
        ]
        
        # 命令超时（秒）
        self.default_timeout = 30
        
        # 输出最大行数
        self.max_output_lines = 1000
    
    async def execute(
        self,
        command: str,
        timeout: int = None,
        working_directory: str = None
    ) -> CLIExecutionResult:
        """安全执行 CLI 命令"""
        # 1. 命令白名单检查
        cmd_base = command.split()[0] if command.split() else ''
        if cmd_base not in self.allowed_commands:
            return CLIExecutionResult(
                success=False,
                error=f"命令 {cmd_base} 不在允许列表中",
                stdout='',
                stderr='',
                return_code=-1
            )
        
        # 2. 黑名单模式检查
        for pattern in self.forbidden_patterns:
            if re.search(pattern, command):
                return CLIExecutionResult(
                    success=False,
                    error=f"命令包含禁止的模式: {pattern}",
                    stdout='',
                    stderr='',
                    return_code=-1
                )
        
        # 3. 命令长度限制
        if len(command) > 1000:
            return CLIExecutionResult(
                success=False,
                error="命令长度超过限制",
                stdout='',
                stderr='',
                return_code=-1
            )
        
        # 4. 限制输出大小
        try:
            result = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_directory,
                limit=1024 * 1024  # 1MB 输出限制
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    result.communicate(),
                    timeout=timeout or self.default_timeout
                )
            except asyncio.TimeoutError:
                result.kill()
                return CLIExecutionResult(
                    success=False,
                    error="命令执行超时",
                    stdout='',
                    stderr='',
                    return_code=-1
                )
            
            # 限制输出行数
            stdout_lines = stdout.decode().split('\n')
            stderr_lines = stderr.decode().split('\n')
            
            truncated = False
            if len(stdout_lines) > self.max_output_lines:
                stdout_lines = stdout_lines[:self.max_output_lines] + ['...[输出已截断]...']
                truncated = True
            if len(stderr_lines) > 100:
                stderr_lines = stderr_lines[:100] + ['...[错误输出已截断]...']
                truncated = True
            
            return CLIExecutionResult(
                success=result.returncode == 0,
                stdout='\n'.join(stdout_lines),
                stderr='\n'.join(stderr_lines),
                return_code=result.returncode,
                truncated=truncated
            )
            
        except Exception as e:
            return CLIExecutionResult(
                success=False,
                error=str(e),
                stdout='',
                stderr='',
                return_code=-1
            )
```

### 5.4 调度系统改造

#### 5.4.1 后台任务调度

利用 FastAPI 的后台任务功能实现 Dreaming 的定时调度：

```python
from fastapi import BackgroundTasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

def setup_dreaming_scheduler(agent_engine: AgentEngine):
    """配置梦境调度器"""
    
    @scheduler.scheduled_job('cron', hour=3, minute=0)
    async def run_dreaming():
        if agent_engine.dreaming_engine:
            logger.info("开始执行梦境扫描...")
            await agent_engine.dreaming_engine.run_full_sweep()
            logger.info("梦境扫描完成")
    
    scheduler.start()
```

#### 5.4.2 技能优化调度

技能优化采用事件驱动与定时触发相结合的方式：

```python
async def trigger_skill_refinement(skill_id: str):
    """当技能使用达到一定次数后触发优化"""
    skill = await skill_manager.get_skill(skill_id)
    
    if skill.usage_count >= skill_manager.refinement_threshold:
        # 获取近期使用记录
        recent_logs = await skill_manager.get_recent_usage_logs(skill_id, limit=10)
        
        # 分析失败案例
        failures = [log for log in recent_logs if not log.success]
        if failures:
            # 生成优化建议
            await skill_manager.refine_skill(skill_id, failures)
```

### 5.5 前端改造

#### 5.5.1 Dreaming 状态面板

新增梦境状态展示面板，显示短期记忆数量、长期记忆数量、已晋升数量和下次巩固时间：

```tsx
const DreamingPanel: React.FC = () => {
  const [dreamingStatus, setDreamingStatus] = useState<DreamingStatus | null>(null);
  
  useEffect(() => {
    fetchDreamingStatus();
  }, []);
  
  return (
    <div className="dreaming-panel">
      <h3>🌙 梦境状态</h3>
      <div className="stats-grid">
        <StatCard label="短期记忆" value={dreamingStatus?.shortTermCount || 0} />
        <StatCard label="长期记忆" value={dreamingStatus?.longTermCount || 0} />
        <StatCard label="已晋升" value={dreamingStatus?.promotedCount || 0} />
        <StatCard label="下次巩固" value={dreamingStatus?.nextDreamingAt || '—'} />
      </div>
      <Button onClick={triggerDreaming}>手动触发梦境</Button>
    </div>
  );
};
```

#### 5.5.2 技能管理界面

新增技能管理界面，支持查看、编辑和删除技能：

```tsx
const SkillManagement: React.FC = () => {
  const [skills, setSkills] = useState<Skill[]>([]);
  
  return (
    <div className="skill-management">
      <header>
        <h2>⚡ 技能库</h2>
        <Button onClick={refreshSkills}>刷新</Button>
      </header>
      
      <div className="skills-grid">
        {skills.map(skill => (
          <SkillCard key={skill.id} skill={skill} />
        ))}
      </div>
    </div>
  );
};
```

#### 5.5.3 工具权限管理界面

新增工具权限管理界面，支持配置角色权限和审批规则：

```tsx
const ToolPermissionPanel: React.FC = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [selectedRole, setSelectedRole] = useState<string>('user');
  
  return (
    <div className="tool-permission-panel">
      <header>
        <h2>🔒 工具权限管理</h2>
        <RoleSelector
          roles={['owner', 'admin', 'user', 'guest']}
          selected={selectedRole}
          onChange={setSelectedRole}
        />
      </header>
      
      <div className="tools-list">
        {tools.map(tool => (
          <ToolPermissionCard
            key={tool.id}
            tool={tool}
            role={selectedRole}
            onPermissionChange={handlePermissionChange}
          />
        ))}
      </div>
    </div>
  );
};

const ApprovalQueue: React.FC = () => {
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  
  const handleApprove = async (approvalId: string) => {
    await api.approveTool(approvalId);
    setPendingApprovals(prev => prev.filter(a => a.id !== approvalId));
  };
  
  const handleReject = async (approvalId: string, reason: string) => {
    await api.rejectTool(approvalId, reason);
    setPendingApprovals(prev => prev.filter(a => a.id !== approvalId));
  };
  
  return (
    <div className="approval-queue">
      <h3>⚠️ 待审批操作</h3>
      {pendingApprovals.map(approval => (
        <ApprovalCard
          key={approval.id}
          approval={approval}
          onApprove={() => handleApprove(approval.id)}
          onReject={(reason) => handleReject(approval.id, reason)}
        />
      ))}
    </div>
  );
};
```

#### 5.5.4 审计日志界面

新增审计日志界面，支持查看工具调用历史和安全事件：

```tsx
const AuditLogPanel: React.FC = () => {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [filters, setFilters] = useState<AuditFilters>({
    riskLevel: 'all',
    toolName: 'all',
    dateRange: 'last_7_days'
  });
  
  return (
    <div className="audit-log-panel">
      <header>
        <h2>📋 审计日志</h2>
        <ExportButton onExport={exportLogs}>导出</ExportButton>
      </header>
      
      <FilterBar filters={filters} onChange={setFilters} />
      
      <div className="log-table">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>工具</th>
              <th>用户</th>
              <th>结果</th>
              <th>风险级别</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {logs.map(log => (
              <tr key={log.id} className={`risk-${log.riskLevel}`}>
                <td>{formatDate(log.createdAt)}</td>
                <td>{log.toolName}</td>
                <td>{log.userId}</td>
                <td><StatusBadge status={log.result} /></td>
                <td><RiskBadge level={log.riskLevel} /></td>
                <td><DetailsButton onClick={() => showDetails(log)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
```

## 六、实施计划

### 6.1 阶段一：基础设施搭建（第1-2周）

**目标**：完成数据库改造和核心组件基础框架搭建。

**任务清单**

- 创建数据库迁移脚本，新增候选记忆表、阶段信号表、技能表、工具注册表、权限表、审计日志表等
- 实现 `DreamingConfig` 配置类，支持数据库配置存储
- 实现 `PhaseSignal` 数据结构
- 实现基础的 `DreamingEngine` 骨架（不含具体逻辑）
- 实现基础的 `SkillManager` 骨架
- **新增**：实现 `ToolRegistry` 工具注册表基础框架
- **新增**：实现 `PermissionManager` 权限管理器基础框架
- 编写单元测试，覆盖新数据模型

**交付物**

- 数据库迁移脚本
- `DreamingEngine` 基础类
- `SkillManager` 基础类
- `ToolHarness` 基础框架
- 单元测试套件

### 6.2 阶段二：Dreaming 和工具安全核心实现（第3-5周）

**目标**：实现完整的三阶段梦境整合机制和工具安全框架。

**任务清单**

- 实现 Light Sleep：会话摄入、去重、候选池管理
- 实现 REM Sleep：主题模式识别、强化信号生成
- 实现 Deep Sleep：六维评分、阈值判断、记忆晋升
- 实现梦境日记写入逻辑
- 实现定时调度器配置
- 实现 Dreaming 配置管理 API
- 前端梦境状态面板开发
- **新增**：实现 `DangerousCommandDetector` 危险命令检测器
- **新增**：实现 `ApprovalManager` 审批管理器
- **新增**：实现 `AuditLogger` 审计日志记录器
- **新增**：实现 `CLIToolWrapper` CLI 工具包装器
- **新增**：前端工具权限管理界面和审批队列界面

**交付物**

- 完整的 `DreamingEngine` 实现
- 完整的 `ToolHarness` 实现
- 梦境状态展示面板
- 工具权限管理界面
- 审批队列界面
- 审计日志界面

### 6.3 阶段三：技能管理核心实现（第6-8周）

**目标**：实现五阶段闭环学习机制。

**任务清单**

- 实现技能数据结构定义和存储
- 实现技能检索（基于关键字和语义）
- 实现技能提取：执行轨迹转技能文档
- 实现技能优化：基于使用反馈的技能迭代
- 实现技能使用记录和统计
- 前端技能管理界面开发
- 用户模型基础功能（可选，如时间允许）

**交付物**

- 完整的 `SkillManager` 实现
- 技能管理界面
- 技能使用统计面板

### 6.4 阶段四：集成与优化（第9-10周）

**目标**：完成各组件集成和性能优化。

**任务清单**

- 将 Dreaming、Skill Management 和 Tool Harness 集成到 `AgentEngine`
- 实现技能检索与对话上下文的融合
- 实现执行轨迹记录与技能提取的联动
- 实现工具调用与对话的融合
- 性能优化：批量处理、缓存策略
- 安全审计：SQL 注入防护、权限控制
- 文档完善：API 文档、部署指南

**交付物**

- 集成后的 `AgentEngine`
- 性能优化报告
- 完整 API 文档

## 七、风险与对策

### 7.1 技术风险

#### 7.1.1 评分机制调优风险

Dreaming 的六维评分机制涉及多个可调参数，参数设置不当可能导致记忆晋升过少（系统过于保守）或过多（噪声污染）。参数的最优值取决于具体使用场景，难以通过理论推算确定。

**对策**：实施分阶段灰度发布策略，初期采用宽松阈值确保有足够的训练数据；收集用户反馈后逐步收紧阈值；提供管理界面允许管理员手动干预晋升决策。

#### 7.1.2 LLM 调用成本风险

技能提取和优化阶段依赖 LLM 调用，可能产生较高的 API 成本。

**对策**：实施调用频率限制，单次会话最多触发一次技能提取；实现缓存机制避免重复提取相似技能；支持配置使用本地模型降低成本。

#### 7.1.3 危险命令检测绕过风险

基于正则表达式的危险命令检测可能被复杂的命令组合绕过。

**对策**：实施多层次检测，结合语法分析和语义分析；容器隔离提供最后防线；保持危险模式库的持续更新；监控异常检测绕过尝试。

### 7.2 运维风险

#### 7.2.1 后台任务阻塞风险

Dreaming 的完整扫描可能耗时较长，如果实现不当可能占用大量系统资源影响前端响应。

**对策**：严格隔离后台任务与主请求处理线程；实施资源配额限制；提供任务取消和暂停机制。

#### 7.2.2 数据一致性风险

多表关联操作在异常情况下可能出现数据不一致。

**对策**：使用数据库事务确保原子性；实现数据修复脚本；定期执行一致性检查。

### 7.3 安全风险

#### 7.3.1 权限配置错误风险

错误的权限配置可能导致用户获得超出预期的权限，或被错误地限制。

**对策**：提供权限配置验证工具；实施权限变更审批流程；记录所有权限变更日志；定期审计权限配置。

#### 7.3.2 审批流程滥用风险

审批人员可能在未充分审查的情况下批准危险操作。

**对策**：提供审批决策辅助信息（风险评估、执行历史）；记录审批决策上下文；实施审批超时机制；定期审计审批决策质量。

### 7.4 用户体验风险

#### 7.4.1 行为不可预测风险

自我进化机制可能导致 Agent 行为在长期使用中发生不可预期的变化。

**对策**：保留用户干预能力，支持手动禁用或重置技能系统；技能变更记录可供管理员审计；提供行为变更通知。

#### 7.4.2 审批延迟风险

危险命令审批流程可能导致操作延迟，影响用户体验。

**对策**：实施审批超时机制，超时后自动拒绝；提供审批优先级设置；支持配置自动批准低风险操作；优化审批通知机制减少延迟。

## 八、总结

本改造方案通过融合 OpenClaw Dreaming 的睡眠式记忆巩固机制、Hermes Agent 的自我进化能力和工具安全框架，旨在将当前项目升级为具备持续学习、自我优化和安全可控能力的新一代智能 Agent。

方案的核心价值包括：通过六维评分机制实现记忆质量的智能把控；通过五阶段闭环学习实现技能的自生长；通过 Harness 思想实现工具调用的安全管控；通过深度防御安全模型确保系统安全；通过异步后台处理确保用户体验的流畅性；通过功能开关控制确保平滑升级和灵活部署。

工具安全框架作为新增的核心组件，实现了以下关键能力：

**工具注册与发现**：统一的工具注册中心，支持工具的动态注册和发现。

**多层权限控制**：基于角色的访问控制（RBAC），支持工具级、会话级和角色级的精细化权限配置。

**危险命令检测**：基于模式匹配和语义分析的混合检测机制，能够识别常见的危险操作。

**人工审批工作流**：支持手动、智能和自动三种审批模式，满足不同安全级别的需求。

**完整审计日志**：记录所有工具调用的完整轨迹，支持事后审计和合规检查。

**CLI 安全包装**：提供受限的命令执行环境，防止命令注入和权限提升攻击。

实施过程中应重点关注评分机制的调优、后台任务的资源管理、危险检测的准确性和审批流程的效率。建议采用渐进式改造策略，优先实现核心功能并通过灰度发布收集反馈，逐步完善和优化系统表现。