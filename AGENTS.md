# AGENTS.md — AI 智能体协作上下文

> **目的**: 让任何 AI agent (Codex / Claude Code / Cursor / etc.) 在 ~2 分钟内掌握项目全貌,
> 不用从零探索代码库就能开干。
>
> **维护**: 每次重要变更后, 跟 commit 同步更新本文档的 "最近变更" + "已知坑" 节。
> 详细架构 / 模块关系 / 风险台账看 [docs/CODEGRAPH.md](docs/CODEGRAPH.md) (323 行, 完整版)。

---

## 1. 项目 1 分钟理解

**TongYong Agent** — 通用 AI 助手, FastAPI 后端 + React 前端, 支持多 LLM (通义/OpenAI/DeepSeek/MiniMax) + 多 Agent 协作 + 记忆/技能。

| 维度 | 现状 |
|---|---|
| 后端规模 | ~165 个 .py 文件, 35+ 个 API 路由, 19 个内置工具 |
| 前端规模 | 39 个 .tsx, React 18 + Vite 6 + TypeScript |
| 测试规模 | 200+ 个 pytest 用例 (安全子集 ~170 个 ~5s, 完整 ~30s) |
| 部署形态 | 单进程 uvicorn (Docker 可选) |
| LLM 路由 | 通过 `LLMManager` 统一, 支持运行时切换 provider |
| Agent 协作 | `app/core/multi_agent/team.py` 593 行 — Leader + 多个角色 |
| 持久化 | SQLite (`backend/data/agent.db`), ChromaDB 向量, langgraph checkpoint |
| 默认 LLM | **edgefn / GLM-4.5V** (W5-2 硬编码, sk-HJVebvMXb0d...6217 明文进 git) — edgefn.net 聚合代理, 部署不配 .env / llm_config.json 也跑 GLM-4.5V; `edgefn.py:43` `HARDCODED_API_KEY` 是最后兜底, `config.py:63` `edgefn_api_key` 默认值是主入口 |
| 协议端口 | backend 8000, frontend 5173 (vite dev proxy /api → 8000) |

---

## 2. 关键路径速查 (不重复 ls)

```
/Users/linc/Documents/tongyong-agent/
├── backend/
│   ├── app/main.py                 # FastAPI app 入口, 145 行
│   ├── app/lifespan.py             # startup/shutdown (W4-22 拆出)
│   ├── app/startup.py              # AgentEngine + LLM init
│   ├── app/routes/health.py        # / /health /ready
│   ├── app/api/                    # 业务路由
│   │   ├── chat.py                # POST /api/chat (非流式)
│   │   ├── stream.py              # POST /api/chat/stream (SSE, W3 切流量)
│   │   ├── memory.py              # 会话/记忆 CRUD
│   │   └── ...                    # 14 个路由文件, 见 openapi.json
│   ├── app/core/
│   │   ├── agent.py               # AgentEngine, hooks 触发点
│   │   ├── langchain_agent.py     # W3 切流量后的 ReAct agent
│   │   ├── multi_agent/team.py    # 593 行 team 协作
│   │   ├── agent_hooks.py         # W4-16 hooks 系统
│   │   ├── ask_store.py           # W4-25 SQLite 持久化 ask pending
│   │   └── ...
│   ├── app/tools/                  # 19 个工具, 显式 _register_tools() 模式 (W4-21)
│   │   ├── registry.py
│   │   ├── mcp_client.py          # W4-14 修过 lifespan
│   │   └── ...
│   ├── app/llm/                    # LLM 适配
│   │   ├── base.py                # BaseLLM 抽象
│   │   └── openai_compatible.py   # 通用 OpenAI 兼容
│   ├── app/services/llm_manager.py
│   ├── app/core/community_hub.py      # W5-1 Community Hub 核心 (194行 + scrape)
│   ├── app/api/hub.py                 # W5-1 /api/hub/* 路由
│   ├── .venv311/                   # 3.11 生产 venv (跑 uvicorn)
│   ├── .venv/                      # 3.13 dev venv (含 langchain_core, 跑 pytest)
│   ├── tests/                      # gitignored 但 git 跟踪, 200+ 用例
│   ├── data/                       # 运行时数据 (agent.db, ask_pending.db, hermes/, chroma/)
│   └── requirements.txt            # 含 langchain / langgraph
├── frontend/
│   ├── src/App.tsx                 # 8 个 tab: chat/memory/skills/personality/dreaming/profiles/evaluation/team
│   ├── src/components/Chat/ModernChatPanel.tsx   # W4-29 重设计, 518 行
│   ├── src/components/Chat/MarkdownContent.tsx   # W4-30 markdown 渲染
│   ├── src/components/Theme/ThemeSwitcher.tsx     # W4-30 4 套主题切换
│   ├── src/theme/themes.ts         # 4 套主题: dark-stone/light-clean/sepia-warm/midnight-blue
│   ├── src/hooks/useStreamChat.ts  # 435 行, 流式状态机
│   ├── vite.config.ts              # proxy /api → localhost:8000
│   ├── public/                     # vite 静态资源
│   └── node_modules/               # 已有 react-markdown + remark-gfm + rehype-sanitize
├── docs/
│   ├── CODEGRAPH.md                # ⭐ 完整代码图 (323 行, 模块/调用/风险)
│   ├── CODE_REVIEW_2026_06_21.md   # 最近一次全面审查 (1227 行)
│   ├── API.md                      # API 速查
│   └── historical-reviews/         # 旧审查归档
├── .claude/settings.local.json     # 旧 Claude Code 痕迹
├── .codegraph/                     # codegraph MCP 工具数据 (gitignore)
├── USER.md                         # 用户偏好 (位置/角色/口吻)
└── AGENTS.md                       # ⭐ 本文件
```

---

## 3. 一键命令

### 启服务 (推荐用 screen, exec 退出不杀子进程)

```bash
# backend (生产 venv .venv311)
cd /Users/linc/Documents/tongyong-agent/backend && \
  CHROMA_PERSIST_DIRECTORY=/private/tmp/tongyong-agent-chroma \
  SKIP_LLM_VALIDATION=1 \
  screen -dmS backend bash -c "exec ../.venv311/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info"

# frontend
cd /Users/linc/Documents/tongyong-agent/frontend && \
  screen -dmS frontend bash -c "exec npm run dev"

# 看
screen -ls
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN

# 日志
screen -S backend -p 0 -X hardcopy -h /tmp/u.log; tail -20 /tmp/u.log
screen -r backend   # 进入 (Ctrl-A D 退出)
```

### 跑测试 (dev venv .venv, 跑得快)

```bash
cd /Users/linc/Documents/tongyong-agent/backend && \
  CHROMA_PERSIST_DIRECTORY=/private/tmp/tongyong-agent-test-chroma \
  .venv/bin/python -m pytest \
    tests/test_lifespan_skip_llm.py \
    tests/test_team_bugfixes.py \
    tests/test_mcp_client.py tests/test_mcp_lifespan.py \
    tests/test_glob_and_load_skill.py tests/test_skills_index.py \
    tests/test_prompt_order.py tests/test_debate_judge.py \
    tests/test_debate_round_order.py tests/test_delegate_task.py \
    tests/test_w413_audit_fixes.py tests/test_agent_hooks.py \
    tests/test_security_config.py tests/test_p22_register_explicit.py \
    tests/test_p23_langchain_persistent.py tests/test_p13_must_use_tool.py \
    tests/test_p14_ask_store.py \
    -v   # ~170 用例, 5-8s
```

### 端到端 (in-process TestClient, sandbox 网络隔离下唯一可靠方式)

```bash
cd /Users/linc/Documents/tongyong-agent/backend && \
  CHROMA_PERSIST_DIRECTORY=/private/tmp/tongyong-agent-verify-chroma \
  /Users/linc/Documents/tongyong-agent/.venv311/bin/python -c "
import sys; sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    for p in ['/', '/health', '/ready', '/docs', '/openapi.json']:
        r = c.get(p); print(f'{r.status_code}  GET {p}')
"
```

### 截前端图 (chrome headless, 4 主题)

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --headless=new --no-sandbox --disable-gpu --window-size=1440,900 \
  --screenshot=/tmp/chat-screenshots/w30-X.png --hide-scrollbars \
  --virtual-time-budget=8000 http://127.0.0.1:5173/
```

---

## 4. 沙箱约束 (重要! 别踩)

| 限制 | 影响 | 绕道 |
|---|---|---|
| **无外网** (minimaxi.com / openai / github) | LLM 调用必败; npm/pip 装包能装 (有缓存) | LLM 相关测试用 `SKIP_LLM_VALIDATION=1` 或 in-process TestClient |
| **loopback 连不上** (sandbox 阻 `127.0.0.1` connect) | curl / Python socket 连 backend 8000 失败 | 用 in-process TestClient 验证 HTTP |
| **sandbox 默认禁 bind 端口** | 直接启 uvicorn/vite 报 "Operation not permitted" | `sandbox_permissions=require_escalated` |
| **ps 命令不可用** | 看不到进程列表 | `lsof -nP -iTCP:PORT -sTCP:LISTEN` + `screen -ls` |
| **后台进程在 exec 退出时被杀** | `nohup ... &` 不够, `setsid` macOS 没有 | 用 `screen -dmS name bash -c "exec ..."` 完全脱离 |
| **shell cwd 不持久** | 每次 exec 默认在项目根 | 命令前 `cd /Users/linc/...` |
| **`.git` read-only** | `git add/commit/push` 报错 | `sandbox_permissions=require_escalated` |
| **`backend/tests/` 在 .gitignore** | `git add` 提示 ignore, 但实际被 git 跟踪 | `git add -f backend/tests/X.py` |
| **commit 长 message 触发 auto-review timeout** | 自动审查跑 30s 没完 | 短 message, < 5 行 |
| **完整 pytest 会 hang** (langchain 真连 LLM) | `tests/test_*.py` 全跑死 | 只跑安全子集, 跳过 langchain 真连的 |
| **`.venv311` 缺 langchain_core** (历史) | `/api/chat/stream` 走 langchain 路径 ImportError | 装 `requirements.txt` 解决 (W4-28) |

---

## 5. 已知坑 (踩过的)

1. **Pydantic v2 PrivateAttr 静默失败** (W4-27 CRITICAL) — `_round` / `_idle_count` 改完不生效, 死循环保护死。修法: `_set(key, value)` helper 封装 `object.__setattr__`。
2. **`team.run_stream` 注释说实时实际 await 5min 才 yield** (W4-27) — 用 `EventBus` 订阅 + 100ms poll 替代。
3. **`_startup_llm` 无 timeout 卡 6min** (W4-28) — 加 `asyncio.wait_for(5.0)` + `SKIP_LLM_VALIDATION=1` env 跳过。
4. **角色异常向上冒泡杀全队** (W4-27) — try/except 包每个 role 循环, 转 `RoleError` system msg。
5. **`_get_roles_for_round(round_num=)` 死参数** (W4-27) — 删了。
6. **`must_use_tool` 触发词 Unicode** (W4-24) — `.lower()` → `.casefold()`。
7. **MCP handler `**kwargs` 签名** (W4-18) — `args: Dict` 跟 registry 不兼容, 全改 `**kwargs`。
8. **`_ask_pending` 多 worker 丢问题** (W4-25) — AgentEngine 实例属性 → SQLite store。
9. **langgraph checkpointer 累积 system** (W4-23) — `chat_history` 跳过 system messages。
10. **agent_hooks 模块顶层副作用** (W4-21) — 抽 `_register_tools()` 显式调, 测试可 mock。
11. **Team mode 旧 `team.run_stream` 标 DEPRECATED** (W4-20) — 3 个月内迁 `run_v2_stream()`。
12. **`MultiMax` / `minimaxi` 是真实 provider 名称** — 配置里有真 key, 别当 typo 改。
13. **`backend/data/` 包含持久化数据** — 不能 git clean -fdx。
14. **5 个 provider 不传 tools / 不解析 tool_calls** (W4-34) — baichuan/wenxin/xfyun/chatglm/ollama 改继承 `OpenAICompatibleLLM`,自动获得 tools + tool_calls 解析。ollama 切到 `/v1` OpenAI 兼容端点(0.1.14+),保留 embedding/init 的原生 /api 端点。
15. **agent 写 HTML 端到端阻塞** (W4-35) — (a) `agent.py:1538` path_scoped 调 `_format_tool_result_text` 传 `success=False` hardcode + `error_msg=error_msg` unbound (try 成功路径), ReAct 循环 UnboundLocalError 死掉; (b) `_is_sensitive_write` 把 macOS per-user TMPDIR `/private/var/folders/...` 误判成 `/private/var/` 敏感路径, 拒绝写。修法: 跟 line_scoped 一致用 `is_error` 决 success / result / error_msg; `_SENSITIVE_PATH_PREFIXES` 拆细 + 加 `_SAFE_PATH_PREFIXES` 白名单。
16. **minimax 嵌套 XML tool_call 解析 (W4-32 只覆盖平展)** (W4-36) — minimax 实际输出是**嵌套**: `<minimax:tool_call>` 包多个 `<write_file>` / `<terminal>` 子块, 闭标签错配 (`<write_file>...</invoke>`), content 多行含 HTML 标签。W4-32 parser 3 处 fail: 整段当单条 / 把 HTML 标签当 tool_name / content 截到首行。修法: 3 路 fallback (平展 JSON / 平展 bash / 嵌套子块) + `_KNOWN_TOOLS` 白名单定位 + `_parse_kv_block` value 跨行。
17. **minimax 闭标签写错 + 装执行幻觉** (W4-37, 现已换 deepseek 默认) — minimax 5 种工具调用失败模式, 修不完. **W4-38 决策**: 默认 LLM 换 deepseek/deepseek-v4-flash, 用户提供 sk. minimax 修复作为兜底保留 (其他用户可能还在用). — (a) `<minimax:tool_call>...</minimax:_call>` 闭标签少了 "tool" 整段匹配不到; (b) minimax 偶尔纯文本写"已写入 /path 成功"但 0 tool_call, 用户看到"已写好"但文件没真写。修法: (a) `_find_close` 找不到精确 `</minimax:tool_call>` 时兜底任意 `</minimax:...>`; (b) `MiniMaxLLM.chat` override 检测"成功词+路径"组合触发 retry 1 次加 system reminder, 仅本类生效不污染其他 LLM。
18. **deepseek reasoning model 解析 (跟 minimax 一样的 XML 坑)** (W4-39) — deepseek-v4-flash 是 reasoning model, 响应 (a) `content=""` + `reasoning_content="..."` 真实内容在 reasoning_content, 原 `_parse_response_with_thinking` 只读 content 拿不到; (b) 工具调用走 `<minimax:tool_call>` XML 不走 `tool_calls` 字段. 修法: 1) content 空 fallback reasoning_content; 2) 路径 B 加 XML 兜底 (跟 MiniMaxLLM 一致). 5 个新 test.
19. **LangChain ReAct stream 丢 tool_calls + 长任务不可续跑** (W4-47) — `TongYongLLMAdapter._astream()` 旧版只读 `base_llm.stream_chat()` 文本, reasoning/XML 解析出的 `LLMResponse.tool_calls` 没传给 LangChain chunk, agent 0 工具调用；同时 LangGraph recursion limit 只报错, 前端不能继续。修法: `_astream()` 改走 `chat()` 拿完整响应并在 final chunk 带 `tool_calls`; SSE `done` 增加 `needs_continue/stop_reason/continue_prompt`; 前端显示“继续执行”。另: XML attrs 只在顶层 `<path>...</path>` 参数集合时启用, 避免把老 kv 格式里的 HTML `<h1>` 误当参数。
20. **真实前端长任务仍会假完成/伪调用** (W4-48) — GLM-5.2 实测会输出 `<tool_call>terminal(command="...")` 无闭合、`<tool_call>write_file<arg_key>...` 伪调用, 且长任务只读文件后把大段计划/源码输出到聊天。修法: parser 支持函数式伪调用 + arg_key/arg_value + 缺闭合 final content; `write_file` 缺 path/content 不执行; agent/langchain 收尾加交付证据门禁, 前端写文件/build 缺证据时 `needs_continue=true`, 不再假装完成。
21. **新会话隔离 + 跨会话检索工具化** (W4-49) — `_get_or_create_session()` 旧版在无 `session_id` 时复用最近会话, 且 `_load_operation_habits()` 自动注入 shared vector memory, 新会话可能串入其它会话内容。修法: 无 `session_id` 永远创建新会话；shared/session/cross memory 只允许通过 `memory_search` / `memory_list` 显式工具检索。
22. **长任务 checklist + 高风险 terminal 审批门禁** (W4-49) — 新增 `todo_write` / `todo_read` planning 工具供模型维护长任务进度；`terminal` 对 `rm -rf`、`git reset --hard`、`git clean -f`、递归 `chmod/chown` 先创建审批, 未携带匹配命令的 approved `approval_id` 不执行；补 `/api/tools/approvals/pending` 和 `/api/tools/approvals` 后端闭环。
23. **单 agent workspace + LangChain 压缩对齐** (W4-50) — 代码/网页/数据任务新增 `workspace_*` 隔离工作区工具, `workspace_terminal` 使用 async subprocess 并 `await communicate()` 等完整输出；self-built 和 LangChain 路径都设置 tool runtime session, 避免不同会话落到 default workspace；LangChain 路径补真实 summarization 压缩和前端 `context` schema。
24. **会话内附件渲染层 MVP** (W4-51) — 新增 `/api/chat/attachments/upload` 上传与 opaque id serve, 前端支持点击/拖拽/粘贴上传图片/PDF/文本等, 用户消息内直接渲染图片/文件卡片；`/api/chat/stream` 接收 `attachment_ids` 并把附件元数据注入本轮消息上下文。

---

## 6. 最近变更 (滚动 10 commit)

| SHA | W4 | 摘要 |
|---|---|---|
| (pending) | W5-10 | 修"安装 skill 时 agent 一直重复调用": (根因) 无外部 skill 安装工具, 模型只能用 web_search/web_extract 空转; 且 Hermes 循环护栏只在 consecutive_valid>=3 且相邻完全重复时才停, 交替/变参空转能跑到 max_rounds=50。(修法) 新增 `skill_install` 工具 (skill_tools.py) 包装 marketplace.install_skill, 只给 name 时经 skill_search 实时解析 owner/repo, 解析不到给候选不空转; system_prompt 指引安装 skill 用 skill_install; constraint.py 循环护栏加两道通用兜底(工具无关): (a) 同一(工具,参数)累计调用>=3 次即停; (b) 不同工具/参数但反复拿回相同结果签名(前200字归一)>=3 次即停 → 覆盖"以后缺任何合适工具时模型换法子空转"的通用场景, 停时提示可能缺工具。(补) skill_install 加 GitHub URL 归一化 + topics/搜索页兜底: source 支持完整 URL / owner\repo, 遇到 github.com/topics/xxx 或 search 页自动抽主题词转 skill_search 检索真实仓库(修"把 topics 页当仓库装失败"); prompt 指引优先 skill_install, 仅其明确失败且是普通代码仓库时才 git clone。12 test |
| (pending) | W5-9 | 会话文件预览/读取体验修复: (1) /api/files/serve+/preview 裸文件名/相对路径解析改与 file_tools._resolve_path 一致 (锚项目根, 不再锚 backend/), 兜底在会话工作区 data/workspaces/** 递归查同名文件 -> 修文件实际位置与预览链接不一致/画布空白; (2) read_file 与 workspace_read 默认 limit 200 -> 2000 行 (仍受 200KB 字符上限约束), 减少大 HTML 反复分页重读; (3) system_prompt 明确代码/网页默认走 workspace_write (会话工作区隔离), 非用户明确要求不写项目根, 避免生成文件污染主项目 |
| (pending) | W5-8 | Runtime 核心三大件 + plan mode 前端: 同上 + `POST /api/plan/build` 端点; 前端 `PlanModeToggle` pill 开关 + `PlanCard` 计划卡片 (步骤列表 + 批准/重规划按钮); plan mode 下用户消息先建计划 → 审批 → 计划上下文追加到消息执行; 共 30 新 test |
| (pending) | W5-7 | Runtime trace 框架 + 整合进 runtime 维护: 新增 `app/core/runtime/` (Trace/Span + contextvar 传播 + 自建 SQLite `runtime_trace.db`), 每次 `/api/chat/stream` = 一条 trace, SSE `start`/`done` 带 `trace_id`; PostToolUse hook 自动产 tool span, agent.py LLM 调用产 `llm_call` span; `/api/trace/*` 只读时间线查询; scheduler 按 `runtime_trace_retention_days` 清理; 全局开关关闭零开销, 落库失败绝不影响主流程 |
| (pending) | W5-6 | Skill 安装 no_source_mapping / 找不到 skill 修复: 显式 source 安装改单次仓库树解析 (按目录名→frontmatter name 精准定位, 不再全仓库扫描), _http_get 加 SSL/URLError 指数退避重试, skillId≠目录名时明确报错并列出可用 skill; 前端透传后端 detail.error |
| (pending) | W5-5 | 会话 HTML 预览修复: browser 导航远程 `.html/.htm/.xhtml` 不再误当本地文件路径, 直接使用原始 URL 预览/打开; `/api/files/*` 明确拒绝远程 URL 走本地文件代理; MCP 市场为全部条目补中文说明并支持中文搜索 |
| (pending) | W5-3 | 会话压缩状态 + MCP Registry 安装修复: 新流式请求先创建持久会话, 前端接收 `done.session_id` 并刷新 context stats; Registry 安装保留 runtime arguments, 支持 remote-only HTTP server, 启动失败回滚配置 |
| (pending) | W5-4 | 实时全局 Skill 搜索 + 完整原子安装: 搜索代理 `skills.sh/api/search`, 结果不写本地 catalog; 安装支持 `source` 显式传入, 完整下载配套文件(含二进制/嵌套目录), 5MB 限制, 失败回滚保留原安装; 前端 400ms 防抖搜索 + 上游结果卡片直接 install |
| (pending) | W5-2 | edgefn/GLM-4.5V 硬编码部署默认: edgefn.py HARDCODED_API_KEY + config.py edgefn_api_key 默认值 + llm_manager._default_model() 兜底, 全新部署不配 .env / llm_config.json 也跑 GLM-4.5V; .env + llm_config.json 同步切到 edgefn/GLM-4.5V; ⚠️ API key 明文进 git, public repo 前先在 edgefn 控制台 rotate |
| (pending) | W5-1 | Skill Community Hub: catalog sync 跟 install 严格分离; browse layer (.lol/.cn) active mapping miner; UI 3rd sub-tab "✨ Community (Hub)"; 4 种卡片状态 (Available/Installed/Updated/Browse-Only); install 必须用户主动 + 二次确认 toast; default whitelist 2 个 (anthropics + ComposioHQ), 待 linc 跑 HEAD probe 验证真假后再扩 |
| (pending) | W4-51 | 会话附件渲染层 MVP: 上传/安全 serve/图片直显/文件卡片/拖拽粘贴/stream attachment_ids |
| (pending) | W4-50 | 单 agent 隔离 workspace 工具; workspace_terminal 等完整输出; LangChain tool session 上下文 + 自动压缩/context 事件对齐 |
| (pending) | W4-49 | 新会话隔离: 无 session_id 创建新会话; 跨会话记忆改 memory_search/list 工具; 新增 todo_write/read; terminal 高风险命令审批门禁 |
| (pending) | W4-48 | 真实前端长任务修复: 解析 `<tool_call>fn(...)` / `<arg_key>` 伪调用; 缺写文件/build 证据时标记未完整交付并给 continue |
| (pending) | W4-47 | LangChain ReAct stream 保留 tool_calls; reasoning_content XML attrs 兜底; 长任务 recursion limit 返回可继续状态 + 前端继续按钮 |
| `23a80dd` | W4-41 | edgefn.net 聚合 provider: GLM-5.2 (reasoning + 原生 function call) + DeepSeek; AddModelDialog 加 edgefn 选项 |
| `29f44e1` | W4-40 | chat 文件路径可点击链接 (Codex/Claude 风格 pill): pathDetector + remarkFilePaths + FilePathLink, 5 种 icon + 颜色 accent |
| `85c0d66` | W4-39 | deepseek reasoning model 解析: content 空 → reasoning_content fallback + XML 兜底 |
| (W4-38) | 切 LLM | 默认从 minimax 换 deepseek/deepseek-v4-flash, 用户提供 sk-d3a5fa6f...411a. minimax 5 种工具调用幻觉修了不赢, 换原生 OpenAI 兼容 function call |
| `ed9d196` | W4-37 | minimax 闭标签容错 (`</minimax:_call>` 等) + 装执行纯文本 retry 1 次 (MiniMaxLLM.chat override, 仅本类生效) |
| `3b18b82` | W4-36 | minimax 嵌套 XML tool_call 解析: 3 路 fallback (平展 JSON/bash/嵌套) + 已知工具名白名单 + value 跨行, 写 HTML 端到端真跑通 |
| `65e08d0` | W4-35 | agent 端到端写 HTML: 修 path_scoped UnboundLocalError + macOS TMPDIR 误判, + E2E 测试 (mock LLM → 真实写文件 → 字节级验证) |
| `135bd6a` | W4-34 | 5 provider 改继承 OpenAICompatibleLLM, 恢复 tools 传 + tool_calls 解析 (-70% LOC), 加 CI gate 测试 |
| `e263351` | W4-33 | prompt 精简 10.4KB → 5.3KB (-49%), 删 cli/*.md + personality.md |
| `2bcb54b` | W4-32 | XML 工具调用兜底 — 修 minimax/MiniMax-Text-01 幻觉 (parser + system_prompt) |
| `f7e5f20` | W4-30 | chat 字体 + markdown (react-markdown) + 4 套主题切换 |
| `b6fea2d` | W4-29 | chat UI 改 WeChat/iMessage 风格, 加 header/avatar |
| `3beb4f3` | W4-28 | `_startup_llm` 5s fast-fail + `SKIP_LLM_VALIDATION=1` |
| `88bf256` | W4-27 | Team mode 10 bug 集中修 (CRITICAL Pydantic v2) |
| `d35fd14` | W4-26 | docs: CODEGRAPH + CODE_REVIEW 同步 W4-19~W4-25 |
| `41f5d49` | W4-25 | `_ask_pending` AgentEngine dict → SQLite store |
| `04b43d2` | W4-24 | `must_use_tool` casefold + 2nd round fallback |
| `fe4fb15` | W4-23 | langchain checkpointer 恢复 + system 去重 |
| `7dbac80` | W4-22 | main.py 拆 lifespan / startup / routes/health |
| `b0df7af` | W4-21 | 工具模块 `_register_tools()` 显式注册 |

历史 commit 看 `git log --oneline -50`。

---

## 6.5 已知坑 (按 W4 倒序)

### W5-8: Runtime 核心三大件 (IPC 隔离 / Planner / Reflection)

- **动机**: 对照参考 runtime 架构盘点, 最缺三块 —— IPC/进程隔离层、显式 Planner、独立 Reflection 模块。本次全部落在 `app/core/runtime/` 下, 都接入 W5-7 trace。
- **IPC 隔离层** (`ipc.py`):
  - `SubprocessBroker.call(target, func, args, timeout)` 在 **spawn 子进程**里执行可 pickle 的 callable, 超时 **硬 kill** 子进程, 结构化返回 `IPCResult` (ok/value/error/timed_out/short_circuited), 绝不抛给主流程。
  - `CircuitBreaker` 每 target 一个: 连续失败 `failure_threshold` 次 → OPEN 短路; 冷却 `reset_timeout` 秒 → HALF_OPEN 放一个试探; 成功回 CLOSED, 失败立刻回 OPEN。
  - 每次调用产 `ipc.call` span (带 target/ok/timed_out/breaker 状态)。
  - **进程级隔离取舍**: 不引容器/命名空间 (环境不具备), 用 `multiprocessing spawn` 拿纯 Python 最强隔离; 工具是否可 pickle 由调用方保证 (顶层函数最稳)。
  - `get_broker()` 进程级单例复用同一组熔断器; `reset_broker()` 测试用。
- **Planner** (`planner.py`):
  - `Plan`/`PlanStep`/`StepStatus` 一等公民数据结构 + 状态机 (start/complete/fail/skip/replan); `progress()` / `current_step()` / `is_complete`。
  - `build_plan_from_llm(goal, llm)` 结构化 JSON 拆解 (最多 20 步), 解析失败/无 llm → `build_plan_heuristic` 单步兜底, runtime 永远有可跟踪计划。
  - `plan.build` + 每步 `plan.step` span。跟 `todo_tools` 区别: todo 是给**模型**维护 checklist 的工具, Planner 是 **runtime 侧**可被循环/反思/trace 直接消费的结构。
- **Reflection** (`reflection.py`):
  - `Reflector.reflect(user_message, response_text, tools_used, commands_executed, last_tool_result)` → `ReflectionVerdict{decision, reasons, correction, missing_evidence}`。
  - 判定顺序: 工具错误→RETRY / 执行声明不符→REVISE / 缺交付证据→RETRY / 空回复→RETRY / 否则→COMPLETE。
  - **复用** `delivery_gate` 原子函数 (`_validate_execution_claim` / `_missing_tool_evidence` / `_is_error_result`), 只做编排+trace, 不重复实现规则。异常保守判 COMPLETE, 不打断主流程。
- **config 开关** (`config.py`): `runtime_ipc_enabled=False` / `runtime_ipc_default_timeout=30` / `runtime_ipc_failure_threshold=3` / `runtime_ipc_reset_timeout=30` / `runtime_planner_enabled=False` / `runtime_reflection_enabled=True`。ipc/planner 默认关 (接入 agent 主循环属高风险改动, 先备而不启); reflection 默认开。
- **接入现状**:
  - ✅ **Reflection 已接入 agent 收尾** (W5-8): `agent.py` `stream_chat` 收尾调 `get_reflector().reflect(...)` 做一次结果校验 (纯观测, 不改控制流), verdict 通过 `_done({"reflection": ...})` → `stream.py` SSE `done.reflection` → 前端 `StreamEvent.reflection`。config `runtime_reflection_enabled` 默认开; 失败 fail-safe 跳过。
  - ✅ **IPC 工具治理已接入 ToolManager**: `app/tools/manager.py` `execute()` 对高风险工具 (terminal/workspace_terminal/browser/cdp/desktop/adb) 经 `AsyncCallGuard.run()` 执行 (超时熔断 + `tool.guard` span)。`config.runtime_tool_guard_enabled=True` 默认开。安全工具直通 registry, 零开销。
  - ✅ **Plan mode 前端已接入**: 聊天输入框新增 `PlanModeToggle` pill (📋 计划), 跟模型/推理强度/思考模式并列。开启后发送消息 → `POST /api/plan/build` 生成计划 → `PlanCard` 组件展示步骤列表 (编号/动作/所需工具) → 用户点"批准执行" → 计划上下文追加到消息后走正常 stream 流。点"重新规划"清空计划, 可编辑消息重试。`config.runtime_planner_enabled` 默认关 (启发式兜底); 开则走 LLM 结构化拆解。
  - ⏳ **`SubprocessBroker` (真 spawn 子进程隔离)** 仍为可用库, 未接入主循环 (工具 handler 依赖 event loop + contextvar 会话, 不适用)。
- **测试**: `tests/test_w58_runtime_core.py` 27 个 + `tests/test_w58_plan_api.py` 3 个 (plan build heuristic/空 goal/缺参)。回归 91 passed; 前端 `npm run build` 通过。

### W5-7: Runtime trace 框架 (整合进 runtime 维护)

- **目标**: 每条 chat 请求一个 `trace_id`, 关联该请求下所有 span (LLM 调用/工具调用/压缩/子 agent) 成时间线, 落库可查询。
- **包**: `backend/app/core/runtime/` (新)。`trace.py` = `Trace`/`Span` dataclass + contextvar 传播 + `TraceStore` (自建 SQLite `data/runtime_trace.db`, 复用 ask_store 的 per-thread conn + `CREATE TABLE IF NOT EXISTS` 模式, **不走**未接线的 m001 migration runner)。
- **传播**: contextvars (`_CURRENT_TRACE` / `_CURRENT_SPAN`), 跟 `app/tools/runtime_context.py` 一致。`start_trace` 产一个 **root span** (name=trace 名) 落库但**不设为 `_CURRENT_SPAN`**, 所以第一层 `start_span` 的 `parent_id=None`。
- **开关**: `configure_runtime(enabled=...)` 全局控制; 关闭时 `start_trace/start_span` 仍返回可用 id 但**不落库** (零开销)。`config.py`: `runtime_trace_enabled=True` / `runtime_trace_retention_days=14`; `lifespan._startup_runtime` 首个启动步骤调 `configure_runtime`。
- **埋点**:
  - `stream.py`: session_id 后生成 `trace_id`, `start`/`done` SSE 带 `trace_id`; agent stream 循环包在 `_rt.start_trace(...)` (手动 `__enter__`/`__exit__`, inner-except + `finally` 双关闭, `_rt_cm` 在 try(343) 前所有路径已绑定)。
  - `agent_hooks.py`: 模块级 `hook_trace_tool_span(ctx)` 注册在 `PostToolUse`, 每个工具调用自动产 tool span (log 行 "8 hooks")。
  - `agent.py` (~941): 主流式 LLM 调用后用 `record_span("llm_call", ...)` 手动计时 (不 re-indent 复杂 fallback 块), 带 model/round/tokens。
- **查询**: `app/api/trace.py` — `GET /api/trace/{trace_id}` (trace + span 时间线), `GET /api/trace/session/{session_id}` (列会话 trace), `GET /api/trace` (全局列表); 注册在 `main.py` hub_router 后。store 未启用返回空/404, 查询失败降级空结果。
- **保留期清理**: `scheduler/__init__.py::scheduled_cleanup` 末尾加 `purge_older_than(now - retention_days*86400)` (独立 db, 失败不影响主清理)。
- **铁律**: trace/落库代码**任何异常都 fail silently** (save_*/finish_* 全 try/except debug log), 绝不能打断主 chat 流。
- **遗留**: 前端暂无 trace 时间线 UI (只有后端 API + SSE `trace_id`); LangChain 路径的 LLM span 未单独埋 (走 root trace + tool hook span)。
- **测试**: `tests/test_w54_runtime_trace.py` (8, 模型传播/落库查询/error span/关闭 noop/record_span/hook span) + `tests/test_w54_trace_api.py` (5, 路由). 回归 75 passed (含 agent_hooks/lifespan/security 子集), in-process TestClient 验证 `/api/trace/*` 挂载 + `enabled=True`。


### W5-7b: done 到达但气泡空白 (从未 emit content) 修复

- **现象**: 前端 `[流式完成] {type:'done', content:undefined, full_content:undefined, usage:{}, tools_used:[]}` — 收到 done 但助手气泡空白。
- **根因**: 某些路径 (如 delivery_gate 拦截"声称执行"回复 → 存进 context 但不 emit; 下一轮模型返回空 content → 循环 break) 会让 `final_response_chunks` 为空且**从未 yield 过 content 事件**; 后端从 context 兜底恢复 `final_reply` 存库, 但没补发给前端。
- **修法** (三层, 任一层都能兜住):
  1. `agent.py`: `_content()` 置位 `_content_emitted[0]`; 收尾若从未 emit 且 `final_reply` 非空/非"（无回复内容）", 补发一个 `_content(final_reply)` 再 `_done()`。
  2. `langchain_agent.py`: 收尾若 `collected_content` 与 `display_text` 皆空, 补发一句占位内容。
  3. `useStreamChat.ts`: `onDone` 兜底 — 气泡与 trace 都无可见文本时填占位文案, 永不留空气泡。
- **测试**: `tests/test_w55_empty_response_fallback.py` (mock LLM 复现拦截+空回复两轮, 断言 done 前必有 content 事件); 前端 `npm run build` 通过。
- **遗留失败**: `tests/test_w413_audit_fixes.py` 2 个 (`files_skipped` KeyError) 是 W5 skill-install 重构 (commit 7cd9e0a) 的既存回归, 与本次改动无关。

### W5-6: Skill 安装 no_source_mapping / 找不到 skill 修复

- **现象**: 从实时搜索结果点 Install 报 `⚠️ 无 source repo 映射. Click ↗ View 或 contribute mapping.`, 或后台大量 `SSL: UNEXPECTED_EOF_WHILE_READING` 后报 `marketplace 中找不到 skill`。
- **三层根因**:
  1. `_http_get` 对 GitHub raw/api 偶发 SSL `UNEXPECTED_EOF` / URLError **无重试**, 一断就整单失败。
  2. 显式 `source` 安装走 `refresh_source` **全仓库扫描** (逐个拉 22 个 SKILL.md), 慢且放大 SSL 失败概率。
  3. skills.sh 的 `skillId` 与仓库真实目录名 **不一定一致** (如 `native-data-fetching` 仓库里其实是 `expo-data-fetching`), 目录名匹配不到就报笼统错误。
- **修法** (`backend/app/core/marketplace.py`):
  - `_http_get` 加 `_HTTP_MAX_RETRIES=3` 指数退避 (HTTPError 不重试, URLError/SSLError/timeout/OSError 重试); `urllib` 提到模块级便于测试。
  - 新增 `_resolve_skill_in_repo(owner, repo, skill_id)`: 只调一次 tree API, 先按目录名匹配, 再按 SKILL.md frontmatter `name` 匹配, 命中后只解析该 skill。
  - `install_skill` 缓存未命中时调 `_resolve_skill_in_repo` 而非 `refresh_source`; 找不到时报错列出全部可用 skill 目录名。
- **前端** (`CommunityHubView.tsx`): install 失败时优先透传后端 `detail.error` (含可用 skill 列表), 不再只显示通用 axios message。
- **端到端验证** (升级权限真连 GitHub): `expo-router` 完整安装 8 文件 (嵌套 `references/` + `agents/` 全保留); `native-data-fetching` 明确报"仓库中找不到 + 列出 21 个可用 skill" (upstream 索引与仓库目录不一致, 非本地 bug)。
- **测试**: `tests/test_w53_complete_skill_install.py` 加 3 个 (直接解析/找不到列候选/HTTP 重试), 焦点回归 52 passed; 前端 `npm run build` 通过。

### W5-5: 会话 HTML 预览远程 URL 误判 + MCP 中文说明

- **场景**: browser 工具打开 `http://gold.qqday.com/silver.htm` 后, 会话 artifact 卡片把 URL 截成 `//gold.qqday.com/silver.htm`, 再送入 `/api/files/preview`, 最终报"路径不在白名单内"。同时 MCP 市场条目缺少中文说明, 中文关键词无法检索。
- **根因**: `delivery_gate._artifact_preview_from_write_result()` 对 browser 导航 JSON 继续走本地路径正则兜底, 且模块漏导入 `json`, 结构化分支异常被宽泛捕获；MCP 搜索直接把中文 query 发给只含英文元数据的官方 registry。
- **修法**: 对结构化 browser 导航的远程 HTML URL 直接返回原始 `preview_url/open_url`; `/api/files/_resolve_path()` 防御性拒绝远程 URL; MCP 市场始终拉取列表后在前端中英文过滤, 专有映射与分类兜底保证每个条目都有中文说明。
- **测试**: `tests/test_w5_artifact_preview_urls.py` 4 passed; 前端 `npm run build` 通过。相邻 W4-50 回归有 3 个既存接口漂移失败, 与本次改动无关。

### W5-3: 会话压缩状态与 MCP Registry 安装链

- **压缩状态根因**: 无 `session_id` 的流式请求进入 LangChain 临时会话, 且前端忽略 `done.session_id`, 导致压缩按钮持续查询空会话并显示 0。
- **压缩状态修法**: stream 入口统一先创建持久会话；`useStreamChat` 接收后端返回的 session id、同步到页面/侧栏，并按真实 session 刷新 context stats。
- **MCP 安装根因**: 前端自行拼装启动命令时遗漏 Registry `runtimeArguments`; remote-only 条目被误判为“无安装包”; 后端在验证启动前保存坏配置且只返回笼统错误。
- **MCP 安装修法**: 安装 API 接收 Registry package/remote 元数据并在后端构建启动配置；支持 Streamable HTTP JSON-RPC MCP；启动失败回滚配置并透传 stderr/初始化错误。
- **测试**: `tests/test_w5_chat_session_and_mcp_install.py` 覆盖持久会话、npm 参数、remote-only 配置和失败回滚；同时回归 MCP client/lifespan 与前端 build。

### W5-4: 实时全局 Skill 搜索 + 完整原子安装

- **场景**: 用户要求实现实时搜索社区 Skill（不依赖本地 catalog 同步），以及完整下载 Skill 配套文件（二进制/嵌套目录，不丢文件）。
- **核心决策**:
  1. 搜索上游: `https://skills.sh/api/search?q=<query>&limit=<limit>` — 实时查询，不写本地 catalog
  2. 搜索结果不自动 install，必须用户主动点击
  3. 搜索结果的 install 传 `source: owner/repo`，不写 slug_mappings
  4. 完整安装: 递归下载所有配套文件，SKILL.md 重写（UTF-8 + quarantined 元数据），其他文件保持原始字节
  5. 原子替换: 在同一分区的 staging 目录完整落盘后原子替换，失败回滚，保留原安装
  6. 安全: 拒绝隐藏路径/遍历路径/5MB 总大小限制
- **新增文件**:
  - `backend/app/core/skill_search.py` — 搜索服务，可注入 fetcher 用于测试
  - `backend/tests/test_w53_realtime_search.py` — 搜索 9 个测试（空白查询/上游错误/502 映射）
  - `backend/tests/test_w53_complete_skill_install.py` — 安装 5 个测试（二进制保留/嵌套路径/失败回滚/超限/不安全路径）
- **修改文件**:
  - `backend/app/api/hub.py` — `GET /api/hub/search` + `/api/hub/install` 接受可选 `source`
  - `backend/app/core/community_hub.py` — `install_from_slug(..., source=None)` 支持显式 source
  - `backend/app/core/marketplace.py` — 完整 bundle 安装: staging/原子替换/备份/安全路径/5MB 限制
  - `frontend/src/api/hub.ts` — 搜索类型 + API
  - `frontend/src/components/Skills/CommunityHubView.tsx` — 400ms 防抖全局搜索，上游结果卡片显示
- **测试**: 29 passed（搜索 9 + 完整安装 6 + hub install 14），均用 injectable fetcher 不依赖网络

### W5-2: edgefn/GLM-4.5V 硬编码部署默认 (明文 API Key 进 git)

- **场景**: 用户要求把 edgefn 那个 GLM-4.5V 模型 (sk-HJVebvMXb0d...6217) 明文写死进代码, 部署完不配置 API 也能默认跑这个模型。
- **核心铁律**:
  1. **兜底链 4 级**: 调用方显式 `api_key` > `EDGEFN_API_KEY` 环境变量 / `.env` / `settings.edgefn_api_key` > **`EdgeFnLLM.HARDCODED_API_KEY`** (代码常量, 最后兜底) > 报错
  2. **`edgefn.py` 的 `HARDCODED_API_KEY` 是 absolute fallback**: 即使 .env / llm_config.json / settings 全空, `EdgeFnLLM()` 不传 key 也能用
  3. **`config.py` 的 `edgefn_api_key: str = "sk-..."` 是 pydantic 默认**: 走 `Settings` 类的 .env 加载链, 部署时 .env 没写也会用这个默认值
  4. **`llm_manager.py:_default_model()` 兜底改 GLM-4.5V**: 配合 `try_restore_saved_provider` 失败路径, 跟 `factory.get_llm()` 串成完整 fallback
- **修改文件 (4 个)**:
  - `backend/app/llm/edgefn.py`: 加 `HARDCODED_API_KEY = "sk-HJVebvMXb0d..."`; `__init__(api_key=None, model=None)` 没传 key 自动用 hardcoded
  - `backend/app/services/llm_manager.py`: `_default_model()` 默认值 `glm-5.2` → `GLM-4.5V`; builtin edgefn `default_model` `GLM-5.2` → `GLM-4.5V` (models 列表顺序调整, GLM-5.2 仍可用)
  - `backend/app/config.py`: `default_llm_provider: tongyi` → `edgefn`; 加 `default_llm_model: str = "GLM-4.5V"`; `edgefn_api_key: Optional=None` → `str="sk-..."` 硬编码默认
  - `backend/.env` + `backend/data/llm_config.json`: 当前 dev 实例同步切到 edgefn/GLM-4.5V (这两个 gitignored, 不进 git)
- **安全警告 ⚠️**: API key 明文进了 `app/llm/edgefn.py` + `app/config.py` 两个源文件, 即将进 git 历史。
  - 当前仓库 `git remote` 是 local, 暂时安全
  - **push 到 GitHub public 前**: 必须先去 edgefn 控制台 rotate 这把 key, 然后同步更新两处源文件
  - 已在两个文件顶部 docstring + 字段注释都加了 `⚠️ rotate` 提醒
- **测试**: 173 passed (安全子集回归), in-process TestClient 验证 `current_provider=edgefn, current_model=GLM-4.5V`; 全新部署场景 (删 `llm_config.json` + 临时空 `.env` + unset `EDGEFN_API_KEY`) 验证 `factory.get_llm()` 拿到 `EdgeFnLLM(model=GLM-4.5V, key=sk-HJVebv...)`
- **遗留**: `engine.llm is None at startup` 是预存行为 (`try_restore_saved_provider` 阶段不构造实例, 首次 chat 才建), 不在本次范围


- **场景**: 用户反馈本地 skill 不够用, 想从社区 (skillhub.lol / skillhub.cn) 自动拉取最新 skill 到本地, 多样性 + 实时更新 + 按需下载。
- **核心铁律 (spec §0 §3 §7)**:
  1. **catalog 同步永远不动本地** — HubScheduler 后台跑 sync, 只写 `marketplace_registry.json` + `community_hub.json`, 不 install
  2. **install 必须用户主动触发** — 二次确认 toast (纯 UX 增强, 后端不依赖), UI 显式点击 ⬇ Install
  3. **browse layer (.lol/.cn) 是 active mapping miner, 不是装饰** — 详情页暴露 `github.com/owner/repo`, 挖出来写 `slug_mappings` + 动态加 scraped source
- **数据流**:
  - `community_hub.json` (schema v2): `github_sources[]` (default/user/scraped) + `browse_layers[]` (默认 enabled=false) + `slug_mappings{}` (slug → {source, path, scraped_from, confidence})
  - 6 个新 config 字段: `community_hub_sync_interval_hours=6`, `community_hub_sync_on_startup=True`, `community_hub_browse_lol_enabled=False`, `community_hub_browse_cn_enabled=False`, `community_hub_scrape_rate_per_sec=1.0`, `community_hub_max_repos=50`, `community_hub_frontend_install_confirm=True`
- **API 路由** (`app/api/hub.py`, ~340 行):
  - `GET /api/hub/info` — Hub Status card
  - `GET/POST/DELETE /api/hub/sources` — 增删 GitHub source (默认源保护 400, 重复 409)
  - `POST /api/hub/sources/{owner_repo}/toggle` — enable/disable
  - `POST /api/hub/sync` — 触发 background catalog sync
  - `GET /api/hub/browse-layers` + `POST /api/hub/browse-layers/{id}/toggle` — browse layer 启停
  - `POST /api/hub/install {slug}` — **唯一 install 入口**, 查 slug_mappings 走 marketplace.install_skill
  - `GET/POST /api/hub/slug-mapping` — 用户补 mapping
  - `GET /api/hub/diff` — 跨源聚合 catalog
- **前端** (`CommunityHubView.tsx` ~600 行, `SkillManagement.tsx` 加 3rd sub-tab "✨ Community (Hub)"):
  - 5 panel: Hub Status / Browse Layers / Filters / Skill Grid (4 种卡片状态) / Detail Modal
  - 卡片 4 状态: Available (⬇ Install) / Installed (✓, 灰化) / Updated (⬆ Update) / Browse-Only (↗ View on skillhub.lol, 无 source)
  - Install 二次确认 toast 走 UI 模态, 后端不强制
  - 主题: 4 套 (dark-stone/light-clean/sepia-warm/midnight-blue) 通过 CSS variables 自动适配
- **测试**: 64 个新 test (S1-S7):
  - S1 config 持久化 7 个 / S2 HubScheduler 8 个 / S3 sync_all_sources 7 个
  - S4 API 13 个 / S5 install 12 个 / S6 scrape + browse-layer API 15 个 / S7 lifespan 2 个
  - 关键: **测试隔离 bug** — `_empty_config()` 之前用 `list(DEFAULT_BROWSE_LAYERS)` 浅 copy, 测试间共享 dict 引用导致 `enabled` 状态泄漏; 改 `copy.deepcopy()` 修掉
- **关键文件**:
  - `backend/app/core/community_hub.py` (~480 行) — config + scheduler + scrape + install
  - `backend/app/api/hub.py` (~340 行) — 上述 11 个 endpoint
  - `backend/app/lifespan.py` — `_startup_hub` / `_shutdown_hub` 用全局 `_HUB_SCHEDULER_REF`
  - `frontend/src/api/hub.ts` — 11 个 API wrapper
  - `frontend/src/components/Skills/CommunityHubView.tsx` — 主壳
  - `frontend/src/components/Skills/SkillManagement.tsx` — 加 3rd sub-tab
- **沙箱限制**: skillhub.lol/.cn 沙箱外网不通, 测试用 `_HTTP_FETCHER` 全局 hook 注入 fixture; sandbox 跑 sync 会全部 timeout, 这是预期, 生产环境正常
- **默认 whitelist 待验证**: 目前只 2 个 (anthropics/skills, ComposioHQ/awesome-claude-skills), 用户跑 HEAD probe 验证真假后扩
- **回归**: 165 + 64 = 229 tests passing (含 W4-* 全子集), in-process TestClient 验证 hub router 挂在主 app 上

### W4-51: 会话内附件渲染层 MVP

- **场景**: 用户要求 TongYong 会话页支持模型/后端结构化输出经 Markdown/安全组件树渲染, 图片/截图等直接显示在会话窗口, 用户也能上传/拖拽图片等文件到会话里。
- **修法**:
  - 后端新增 `app/api/attachments.py`: `POST /api/chat/attachments/upload`, `GET /api/chat/attachments/{id}/content`, `GET /api/chat/attachments/{id}/meta`；文件落 `data/attachments/`, 元数据进 SQLite `data/attachments.db`, 只按 opaque attachment id serve, 不暴露用户原始路径。
  - 前端新增 `Attachment` 类型和 `api/attachments.ts`, `ModernChatPanel` 支持点击加号上传、拖拽上传、粘贴上传；用户消息气泡里图片直接 `<img>` 预览, PDF/文本/其他允许类型用文件卡片打开。
  - `/api/chat/stream` 请求新增 `attachment_ids`, 后端把附件名/mime/size/id/url 注入本轮消息上下文；MVP 先让模型看附件元数据, 不假装读取图片像素内容。
- **安全边界**: 允许 image/png/jpeg/gif/webp/svg、PDF、txt/markdown/csv/json；默认 25MB 上限；文件名 sanitize；serve 设置 `X-Content-Type-Options: nosniff`。
- **测试**: `tests/test_w451_attachments.py` 覆盖上传+serve、文件名清洗、拒绝不支持 MIME；前端 `npm run build` 通过。

### W4-50: 单 agent workspace 隔离 + LangChain 压缩对齐

- **场景**: 用户要求“代码等任务用单独 workspace，不污染主进程 agent 会话；主进程异步等到子进程输出结果后继续输出；确认自动压缩是否存在、是否激活、前端是否实时展示压缩进度。”
- **修法**:
  - 新增 `workspace_info` / `workspace_list` / `workspace_read` / `workspace_write` / `workspace_terminal` 工具，默认按当前 stream session 建 `data/workspaces/t_<session_id>/` 隔离目录，显式 `session_id` / `task_id` 可覆盖。
  - `workspace_terminal` 在 workspace 根目录运行命令，使用 `asyncio.create_subprocess_shell()` + `await process.communicate()` + `wait_for(timeout)`，所以工具结果返回前主流程不会提前 `done`。
  - `AgentEngine.stream_chat()` 与 `stream_chat_langchain()` 都设置 `runtime_context.tool_session_id`，让 workspace 工具在 self-built / LangChain 两条路径都拿到当前会话，而不是落到 `"default"`。
  - 系统提示增加 workspace 隔离规则：代码、网页、脚本、数据处理、构建/测试默认用 `workspace_*`；只有明确要改 repo 或绝对路径时才用 direct `write_file` / `patch` / `terminal`。
  - LangChain 路径补真实 `ContextCompressor.compress()` summarization 自动压缩，并把 `context` 事件改成前端 `TokenUsageBar` 需要的 `chars / estimated_tokens / threshold_tokens / percent / approaching` schema；self-built 路径原本已有压缩进度 SSE。
  - 交付证据门禁接受 `workspace_write` / `workspace_terminal`；workspace 写出的 HTML/SVG/图片也会进入 `artifact_previews`，前端可在会话窗口 iframe 预览并点击打开。
- **压缩状态确认**:
  - 自动压缩存在于 `ContextCompressor`：默认达到模型 context window 50% 触发，且不足 30000 字符不会压；保护前 3 条和后 20 条消息，中间消息由 LLM summarization 压成摘要。
  - self-built stream 路径已激活，并通过 `progress` 推 “📦 上下文过长，正在压缩...” / “📦 压缩完成...” 和 `context` 事件；前端 `useStreamChat` / `TypingIndicator` / `TokenUsageBar` 会实时展示。
  - LangChain 路径本次补齐自动压缩和正确 `context` 事件；此前只做滑动窗口截断，不能算真正自动压缩。
- **测试**: `tests/test_w450_workspace_and_compression.py` 6 passed；连同 W4-49 回归共 15 passed；`py_compile` 覆盖 `agent.py` / `langchain_agent.py` / `agent_hooks.py` / `workspace_tools.py` / `runtime_context.py`。

### W4-49: 新会话隔离 / memory tools / todo_write / terminal 审批门禁

- **场景**: 用户要求“跨会话检索改造成 tools 能力；特定场景才检索；其它时候只注入身份 MEMORY.md / USER.md / base system prompt / env prompt / domain prompts，其它内容都不注入。”
- **根因**:
  1. `_get_or_create_session()` 在调用方不传 `session_id` 时复用最近会话，导致“新会话”可能加载旧 session history。
  2. `_load_operation_habits()` 自动读取 shared vector memory 并注入 system，上下文隔离不彻底。
  3. 长任务没有结构化 checklist 工具，模型容易输出计划后中断或截断后不知道进度。
  4. `ApprovalManager` / `PermissionManager` 有数据层和前端队列雏形，但单 agent `terminal` 工具执行链没有真实审批门禁。
- **修法**:
  - `_get_or_create_session()` 改为无 `session_id` 必定创建“新会话”，只有显式 session_id 才加载历史。
  - `_load_operation_habits()` 停止自动注入 shared memory；跨会话/共享记忆只通过 `memory_search` / `memory_list` 工具进入当前轮上下文。
  - 新增 `todo_write` / `todo_read` 工具，session-scoped in-memory checklist，限制同一时间最多一个 `in_progress`。
  - `terminal` 对高风险命令创建 `tool_approvals` pending 记录；审批 API 补齐 `GET /api/tools/approvals/pending` 与 `POST /api/tools/approvals`；approved `approval_id` 必须匹配原始命令，禁止复用到其它命令。
- **测试**: `tests/test_w449_planning_and_session_isolation.py` + `tests/test_w449_terminal_approval_gate.py` 共 9 passed；`py_compile` 覆盖 `agent.py` / `todo_tools.py` / `terminal.py` / `approval.py` / `tool_harness.py` / `security_config.py`。
- **遗留**: 已在 W4-50 为单 agent 接入 per-session workspace；后续可继续做真实 git worktree 级隔离和 workspace 文件浏览 UI。

### W4-48: 真实前端长任务 function call 兼容 + 交付证据门禁

- **场景**: 用户明确要求“让 TongYong 自己从前端真实测试完成一个带粒子特效、手势控制识别的 React UI, 一个轮回复内完整完成, 不能假装完成”。
- **实测失败模式**:
  1. `<tool_call>terminal(command="find ...")` 无 `</tool_call>` 闭合, 旧 parser 0 tool call。
  2. `<tool_call>write_file<arg_key>path</arg_key><arg_value>...</arg_value>...` 伪调用, 旧 parser 不识别。
  3. 大段 TSX 输出被截断时最后一个 `<arg_value>` 缺闭合, 旧 parser 只拿到 path 或只拿到 content, 造成无效 `write_file`。
  4. LangChain 路径只读文件后输出计划/源码, 没有 `write_file/patch` 和 `npm run build`, 但前端看到 `done`。
- **修法**:
  - `xml_tool_call_parser.py` 增加函数式伪调用解析和 `<arg_key>/<arg_value>` 解析; final `arg_value` 缺闭合时按尾部 content 捕获。
  - `write_file` 缺 `path` 或 `content` 时不再发无效工具调用。
  - `agent.py` + `langchain_agent.py` 增加交付证据门禁: 前端/React/UI + build 类任务必须有 `write_file|patch` 和 `terminal npm run build` 证据; 缺证据时最终回复改为“任务未完整交付”, `done.needs_continue=true`。
- **测试**: parser/must-use-tool 54 passed; 安全子集 173 passed。
- **E2E 证据**: `/api/chat/stream` 真实请求 `codex-evidence-gate-test` 最终 `needs_continue=true`, `stop_reason` 明确缺 `write_file/patch` 与 `npm run build`; 不再假装完成。遗留: 模型仍倾向把源码输出到 content 而非原生 tool_calls, 下一步应继续压制 content 伪调用或强制工具优先。

### W4-47: LangChain ReAct function call 兼容 + 长任务续跑

- **现象**: 用户反馈 ReAct/function call 格式跟大模型不兼容, 长任务无法一次完成。已有未提交修复显示 GLM/deepseek 会输出 `<write_file><path>...</path><content>...</content></write_file>` 或把 XML 放在 `reasoning_content`。
- **根因**:
  1. `TongYongLLMAdapter._astream()` 旧版走 `base_llm.stream_chat()` 只流文本, 丢掉 `LLMResponse.tool_calls`, LangChain 累积后 0 tool call。
  2. XML attrs parser 太宽会把老 kv 格式 `content: <h1>...</h1>` 里的 HTML 标签误当参数。
  3. LangGraph recursion limit 对前端只是 error/done, 没有可续跑协议。
- **修法**:
  - `_astream()` 改走 `chat()` 拿完整 `LLMResponse`, 文本逐字 yield, 最后一个 `AIMessageChunk` 带 `tool_calls`。
  - `_parse_response_with_thinking` 从 `reasoning_content` 再兜底解析 XML; XML attrs 只接受顶层 `<key>...</key>` 参数集合。
  - `stream.py` 的 done 透传 `needs_continue / stop_reason / continue_prompt`; `ModernChatPanel` 增加“继续执行”状态栏按钮。
  - 修前端 build 阻塞: `filePathRemark.ts` mdast 类型收窄误报; `RoleList.tsx` style 重复 key。
- **测试**: `tests/test_w2_event_alignment.py` 增加 done 续跑字段测试; `tests/test_w447_xml_attrs.py` 增加 HTML kv 回归。
- **回归**: 38 passed (W2/W439/W447/langchain adapters); 安全子集 170 passed; frontend `npm run build` passed; in-process TestClient 5 个端点 200 (LLM 外网验证因 sandbox DNS 失败, 预期)。

---

### W4-41: edgefn.net 聚合 provider (GLM-5.2 + DeepSeek)

- **场景**: 用户提供 edgefn.net 代理 sk-HJVebvMXb0d...6217, 一个 key 走 GLM + DeepSeek 等多模型
- **支持模型测试** (2026-06-30):
  - ✅ **GLM-5.2**: 200, reasoning_content + 原生 `tool_calls` 字段, finish_reason="tool_calls" (完美 function call)
  - ❌ **deepseek-v4-pro**: 403 ModelNotAllowed (key 没权限)
  - (待测 deepseek-v4-flash, 之前走 deepseek.com 直连 OK)
- **修法**:
  - 新建 `backend/app/llm/edgefn.py` EdgeFnLLM 继承 OpenAICompatibleLLM
  - DEFAULT_API_BASE = https://api.edgefn.net/v1, DEFAULT_MODEL = GLM-5.2
  - `_parse_response` 走 `_parse_response_with_thinking` (W4-39 兼容 reasoning model)
  - `factory.py` 注册 + `config.py` 加 `edgefn_api_key` + AddModelDialog 加 edgefn 选项
  - `llm_config.json` (不 in git) 切到 edgefn/GLM-5.2
- **测试**: 7 个新 test (注册/默认/自定义 model/native tool_calls/reasoning_content fallback/XML fallback/factory 拿实例), 7/7 过
- **回归**: 94 passed 8 skipped (含 W4-37/39/41/provider contract)
- **E2E 证明**: 模拟 GLM-5.2 真实响应 (content 空 + tool_calls 完整) → _parse_response → AgentEngine → write_file → /tmp/hello_glm.html 字节级写成功; 真 API 调 tool_calls 原生返回
- **前端切换**: LLM tab → AddModelDialog → 选 EdgeFn 聚合 → 填 key 即可添加; ModelSelector 切已保存模型

---

### W4-39: deepseek reasoning model 解析

- **现象**: 切到 deepseek/deepseek-v4-flash 后用户实测"写 hello.html" 仍报 minimax 格式. 排查 backend log 发现:
  - HTTP POST https://api.deepseek.com/v1/chat/completions 200 OK
  - 但响应 `content=""` + `reasoning_content="..."` (空 content)
  - 工具调用走 `<minimax:tool_call>` XML 不走 `tool_calls` 字段
  - `tool_count: 0` — agent 0 工具调用
- **根因**: `_parse_response_with_thinking` (DeepSeekLLM 用) 只读 `content` + `tool_calls`, reasoning_content 拿不到, XML 也没兜底
- **修法**:
  1. `_parse_response_with_thinking` 加 `reasoning_content` fallback — content 空时用 reasoning_content
  2. 加路径 B XML 兜底 (跟 MiniMaxLLM 一致) — reasoning model 也可能输出 minimax 风格 XML
- **测试**: `tests/test_w439_deepseek_reasoning_xml.py` 5 个
- **回归**: 84 passed 8 skipped
- **遗留**: 真正治本是换 deepseek-chat (V3) 而不是 deepseek-v4-flash (reasoning), reasoning 模型天生不擅长工具调用

---

### W4-37: minimax 闭标签容错 + 装执行 retry

- **现象**: W4-36 修完嵌套 XML 之后用户前端再实测"写 hello.html" 仍报"已写好"但文件没真出现. 两种 minimax 失败模式:
  1. **闭标签写错**: LLM 输出 `<minimax:tool_call>...</minimax:_call>` (少 "tool"), 整段因闭标签不匹配被丢弃, 0 tool_call
  2. **装执行纯文本**: LLM 直接在 content 文本里写"已写入 /tmp/hello.html 成功" (成功词 + 路径), 但 0 tool_call, 用户看到"已写好"实际没调工具
- **修法**:
  1. `xml_tool_call_parser._find_close` 找不到精确 `</minimax:tool_call>` 时, fallback 任意 `</minimax:...>` 闭标签 (`re.search(r"</minimax:[^>]*>", content[start:])`)
  2. `MiniMaxLLM.chat` override (子类, 不影响其他 LLM) 检测 `_looks_like_fake_execution` (16 成功词 + 路径正则), 命中时拼 system reminder retry 1 次, reminder 明确说"不要在 content 文本里描述虚假执行, 不能调就如实说换模型"
- **测试**: `tests/test_w436_minimax_nested_xml.py` 加 5 个 (W4-37 闭标签 typo / 闭标签中划线 / 装执行 retry / 普通文本不触发 / 有 tool_call 不触发)
- **回归**: 13/13 W4-37 测试过 + 211/211 安全子集过
- **遗留风险**: minimax 模型整体 function call 不靠谱, 装执行启发式 (成功词+路径) 可能误判用户问句, 后续建议换 deepseek/yi (原生 OpenAI 兼容 function call, 不需要 XML 兜底)

---

### W4-36: minimax 嵌套 XML tool_call 解析 (写 HTML 端到端真跑通)

- **现象**: 用户前端实测"写一个 hello.html" 报"已经写好了", 但 `hello.html` 实际没写出来. backend log 看 LLM 输出 `<minimax:tool_call>\n<write_file>\npath: hello.html\ncontent: <!DOCTYPE html>...\n</invoke>\n<terminal>\nls hello.html\n</terminal>\n</minimax:tool_call>`, agent 把它当纯文本显示, 0 个 tool_call 被执行.
- **根因**: W4-32 parser 3 处 fail 处理这种格式
  1. 整段当单条 tool_call -> 启发式成 `terminal` + `command: "path: hello.html"` (错)
  2. 按 `<name>` 切子块 -> 错把 HTML 标签 (`<head>` `<title>` `<h1>`) 当 tool_name, content 截到 `<!DOCTYPE html>`
  3. `key: value` 按行只取首行 value -> content 多行被截
- **修法** (W4-36):
  1. `parse_xml_tool_calls` 加 kind=="minimax" 三路 fallback: 平展 JSON (走原 `_parse_inner`) / 平展 bash (无 `<` 时整段当 terminal command) / 嵌套子块 (调 `_parse_minimax_nested`)
  2. `_parse_minimax_nested` 用 `_KNOWN_TOOLS` 白名单定位子块起始, body 不再按 `<` 切, 闭标签错配容忍
  3. `_parse_kv_block` 改 value 跨行, 续行到下一个 `^[a-zA-Z_]\w*:\s` 模式
  4. `system_prompt.py` 调强: 明确禁止 XML 伪调用, 必须用 `message.tool_calls` 字段, 即便 minimax 模型倾向输出 XML 也要改
- **测试**: `tests/test_w436_minimax_nested_xml.py` 8 个覆盖嵌套/平展/MiniMaxLLM 真实解析路径
- **回归**: W4-32 老测试 28 个 + W4-36 新测试 8 个 + 88 安全子集 = **124 passed 9 skipped**

---

### W4-35: Agent 端到端写 HTML (修 2 真 bug)

- **现象**: 用户让 agent 写 HTML 文件, 实际跑不通, 40s 后 budget 耗尽退出
- **根因 1 (CRITICAL)**: `app/core/agent.py:1538` path_scoped 工具执行后调 `_format_tool_result_text` 传 `success=False` hardcode + `error_msg=error_msg` (unbound 在 try 成功路径), 触发 UnboundLocalError, 整个 ReAct 循环死掉, agent 永远到不了 final text
- **根因 2**: `app/tools/implementations/file_tools.py` `_SENSITIVE_PATH_PREFIXES` 含 `"/private/var/"` 太宽, 把 macOS per-user TMPDIR `/private/var/folders/...` 误判成敏感路径, 拒绝写任何文件到 pytest tmp_path
- **修法**:
  - `agent.py` L1538 改跟 L1376 (line_scoped) 一致, 用 `is_error` 决 `success` / `result` / `error_msg`; 顺手 PostToolUse hook 的 `is_error` 也用真实值
  - `file_tools.py` 拆 `/private/var/` → `log/db/audit/root/lib`; 加 `_SAFE_PATH_PREFIXES` (`/private/var/folders/`, `/private/var/tmp/`, `/tmp/`, `/var/folders/`, 用户家) 优先放行
- **E2E 测试**: `tests/test_w434_agent_writes_html.py` 3 个
  - `test_agent_writes_html_file_and_content_verified`: mock LLM 决策 `write_file` → 真实 `AgentEngine.stream_chat` 走 ReAct → 真实 `write_file_tool` 写文件 → 字节级读回验证
  - `test_agent_writes_html_then_serves_via_http_and_curl_200`: 写 + 启 `python -m http.server` + curl 200 + 内容匹配 (`needs_network` skipif, sandbox bind 不上时自动 skip, 真实环境跑)
  - `test_write_file_tool_writes_html_directly`: 直接调 `write_file_tool` 验证工具本身
- **结果**: 2 passed 1 skipped (sandbox), 116 passed 9 skipped 全量安全子集无回归

---

### W4-34: 5 Provider Function Call 适配审计修复

- **现象**: 审计 15 个注册 provider,8 个 `chat()` 签名接 `tools` 但 body 完全不传,LLM 永远只回纯文本:
  - baichuan / wenxin / xfyun / chatglm: OpenAI 兼容端点但 `json={"model", "messages"}` 不带 `tools`
  - ollama: 走原生 `/api/chat`, 协议不带 `tools` 字段
  - 另: anthropic / google 走自家非 OpenAI 协议(待 W4-35)
- **修法**: 5 文件改继承 `OpenAICompatibleLLM`,只设 `DEFAULT_API_BASE` / `DEFAULT_MODEL`,吃基类完整实现
  - 5 文件: -281 / +74 行 (-70%)
  - ollama 额外切 `/v1` OpenAI 兼容端点(0.1.14+ 稳定),保留 embedding / initialize 的 `/api` 原生端点
- **CI gate**: `tests/test_provider_function_call_contract.py` — 用 `inspect` 沿 MRO 静态扫所有 15 provider,验证 `chat()` 接受 `tools` 形参 / body 塞 `tools` / `_parse_response` 读 `tool_calls`。38 passed 8 skipped (anthropic/google/openai/tongyi 明确豁免,待 W4-35)
- **结果**: 11/15 provider 完整 function call 适配 (含默认 minimax); 4 个非 OpenAI 协议待 W4-35

---

### W4-33: System Prompt 精简 (-49%)

- **现象**: 4 层 prompt (domains + base + cap + skills) 实际注入 10.4KB, 重复点 ≥ 5 处, 3 处自相矛盾
  - 身份讲 2 遍 (base.## 身份 + identity.md)
  - 工具讲 4 遍 (base.## 工具调用 + env_capabilities + cli/commands.md + 5 个 cli/*.md)
  - 记忆讲 4 遍 (base + personality + memory_system + _inject_memory 实际内容)
  - 禁装执行讲 3 遍 (执行纪律 / 节奏 / 校验 / identity.## 任务执行规则)
  - 矛盾: base 说"专业友好的 AI 助手" vs identity 说"通义千问驱动"
  - 矛盾: base.## 平台提示 说"用纯文本回复" vs W4-30 markdown 渲染
- **修法**:
  - base.py 2.5KB → 762B (-70%), 删 ## 身份/## 记忆机制/## 平台提示/### 调用形式详尽枚举
  - identity.md 2.5KB → 784B (-68%), 删 ## 任务执行规则 (与 base 重复)
  - 删 cli/*.md (5 个) + personality.md, 与 P4 (删 tools.md) 同理
- **实际注入**: 10.4KB → 5.3KB (-49%)
- **锁基线**: `tests/test_prompt_slim.py` 16 用例 (字节预算 + 章节必须存在 + 重复点不能再出现)
- **已知坑**: cron.md 仍每次都注入 (~1.5KB) — 后续可改成 `integrator.get_filtered(message)` 按需加载

---

## 7. 用户偏好 (来自 USER.md)

- **中文沟通**, 简洁, 不绕
- **直接做**, 不反复确认
- 修完给 **commit SHA + 简要总结**
- 用 `::git-commit{cwd="..."}` directive 在 final 报 commit
- 真正需要决策 (UX / 存储选型) 时才停下问
- 喜欢看 **真实证据** (log / 测试输出 / commit SHA), 不要空话
- 项目记忆点: 靖江, 魔法数字 4711, 喜欢路明非 (《龙族》)

---

## 8. AI agent 工作流 (推荐)

1. **读本文档** (~2 min) — 不要 `ls` 整个项目
2. **关键改动前** 翻 `docs/CODEGRAPH.md` 相应模块
3. **改完跑安全子集 pytest** (见 §3), 不跑全量
4. **端到端用 in-process TestClient** (见 §3)
5. **前端改完截 chrome headless 验证** (见 §3)
6. **commit 短 message** + 更新本文档 §5/§6
7. **push 需 escalate** (`sandbox_permissions=require_escalated`)

---

## 9. 一句话总结

FastAPI + React 全栈 AI 助手, 19 工具, 8 tab UI, 4 主题, 流式对话, Team 协作, 记忆持久化; 沙箱无外网用 in-process TestClient, 跑测试用 .venv, 启服务用 screen -dmS。
