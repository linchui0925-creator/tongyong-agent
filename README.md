# 维知 Agent

维知是一个面向真实业务场景的智能体系统，支持多模型切换、上下文追溯、工具执行、记忆管理和技能扩展。

## 核心特性

- **多模型支持**：支持通义千问、OpenAI、DeepSeek、Anthropic、MiniMax 等多种 LLM
- **上下文可追溯**：每轮 turn 都会记录 runtime、context snapshot、model request/response、tool settlement 和 turn manifest
- **多智能体/多策略扩展**：支持在上层引入任务理解、决策与编排策略
- **记忆管理**：持久化记忆存储，支持上下文压缩和检索
- **技能扩展**：可扩展的工具系统和技能市场
- **现代化 Web UI**：支持实时对话、计划模式、附件上传和流式反馈

## 快速开始

### 使用 Docker（推荐）

```bash
# 复制并配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env 填入你的 API 密钥

# 启动服务
docker-compose up -d

# 访问 http://localhost:8000
```

### 本地开发

```bash
# 前端
cd frontend && npm install && npm run dev

# 后端（新终端）
cd backend && uv sync && uvicorn app.main:app --reload
```

## 环境变量

| 变量名 | 描述 | 必需 |
|--------|------|------|
| TONGYI_API_KEY | 通义千问 API 密钥 | 是 |
| OPENAI_API_KEY | OpenAI API 密钥 | 否 |
| ANTHROPIC_API_KEY | Anthropic API 密钥 | 否 |
| DEEPSEEK_API_KEY | DeepSeek API 密钥 | 否 |
| MINIMAX_API_KEY | MiniMax API 密钥 | 否 |

## 项目结构

```
维知 Agent/
├── backend/          # Python 后端
│   ├── app/          # 应用代码
│   ├── llm/          # LLM 适配器
│   ├── tools/        # 工具实现
│   └── data/         # 本地数据与证据文件
├── frontend/         # React 前端
│   └── src/          # 源代码
├── docs/             # 文档
└── Dockerfile        # Docker 配置
```

## 关键设计说明

- **数据优先**：系统围绕 turn 级数据追溯展开，强调证据链完整性和可回放性
- **中层已结构化**：上下文组装、运行态、artifact 存储和终局 manifest 已形成统一链路
- **上层持续演进**：AgentPolicy 承接任务理解、决策和编排逻辑
- **执行层沙盒**：`terminal` / `workspace_terminal` 支持 `sandbox_mode`、`sandbox_preset`、`sandbox_profile`，默认可由策略层回填

## 沙盒说明

### 可用参数

- `sandbox_mode`
  - `off`：不启用沙盒
  - `macos`：使用 macOS `sandbox-exec`
- `sandbox_preset`
  - `read_only`
  - `workspace_only`
  - `network_off`
- `sandbox_profile`
  - 自定义 `sandbox-exec` profile 文本

### 规则

- `sandbox_preset` 与 `sandbox_profile` 只能二选一
- 当工具调用未显式传入沙盒参数时，会优先读取当前 turn strategy 的默认值
- `workspace_terminal` 默认仍在会话工作区内执行，沙盒是额外约束

## API 文档

启动后访问 http://localhost:8000/docs 查看完整的 API 文档。

## License

MIT