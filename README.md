# TongYong Agent

通用智能助手系统，支持多模型切换、多智能体协作、记忆管理和技能扩展。

## 功能特性

- **多模型支持**: 支持通义千问、OpenAI、DeepSeek、Anthropic、MiniMax 等多种 LLM
- **多智能体协作**: 内置团队协作系统，支持多智能体分工合作
- **记忆管理**: 持久化记忆存储，支持上下文压缩和检索
- **技能扩展**: 可扩展的工具系统和技能市场
- **Web UI**: 现代化 Web 界面，支持实时对话和团队协作

## 快速开始

### 使用 Docker (推荐)

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

# 后端 (新终端)
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
tongyong-agent/
├── backend/          # Python 后端
│   ├── app/          # 应用代码
│   ├── llm/          # LLM 适配器
│   ├── tools/        # 工具实现
│   └── data/         # 本地数据
├── frontend/        # React 前端
│   └── src/          # 源代码
├── docs/             # 文档
└── Dockerfile        # Docker 配置
```

## API 文档

启动后访问 http://localhost:8000/docs 查看完整的 API 文档。

## License

MIT