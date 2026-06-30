# TongYong Agent — CodeGraph 文档

> 用途：基于 [CodeGraph](https://codegraph.dev) 索引（205 文件 / 3,791 节点 / 7,572 边）维护的项目级代码图谱与风险台账。
> 维护人：linc（每 1–2 周 `codegraph sync` 后回写）
> 数据源：`.codegraph/codegraph.db`（SQLite 3，8.24 MB，schema v4）
> 配套审查报告：[docs/CODE_REVIEW_2026_06_21.md](CODE_REVIEW_2026_06_21.md)

---

## 0. 摘要

> 📝 W4-8 修复 (2026-06-21): P0-1 system prompt 顺序 / P0-2 DebateJudge 字符串匹配 已修
> 📝 W4-9/W4-10 修复 (2026-06-21): P1-2 辩论 mode round 按 debate_position 排序 / P1-1 delegate_depth 改 ContextVar, 详见 [CODE_REVIEW_2026_06_21.md](CODE_REVIEW_2026_06_21.md) §P1 节
> 📝 W4-11/W4-12 修复 (2026-06-21): MCP `_send_raw` silent return / text=False str write + SKILL `get_skills_prompt` 永久缓存不感知 mtime, 详见 [CODE_REVIEW_2026_06_21.md](CODE_REVIEW_2026_06_21.md) §P1 节
> 📝 W4-13 修复 (2026-06-21): 审计发现 3 处连带 bug (heuristic 多段只取第一 + budget 一次性 + skipped 路径污染), 详见 [CODE_REVIEW_2026_06_21.md](CODE_REVIEW_2026_06_21.md) §P1 节
> 📝 W4-15 工具 (2026-06-22): 新增 `glob` 工具 (按模式跨目录匹配, 跳 _PRUNE_DIRS) + `load_skill` 别名 (指向 skill_view, 兼容用户熟悉的 Anthropic 风格命名)
> 📝 W4-14 修复 (2026-06-22): MCP 客户端 4 处 bug — 跨 loop future 泄漏 / 进程 crash 时 future hang 60s / shutdown 顺序错乱 / 不接 FastAPI lifespan; 详见末尾 W4-14 节
> 📝 W4-16 引入 (2026-06-22): 借鉴 shareAI-lab/learn-claude-code s04_hooks 模式, agent.py 循环外行为 (step_callback / 工具 tracking / constraint engine / memory save) 全部注册为 hooks, 循环只调 trigger_hooks()
> 📝 W4-17 扩展 (2026-06-22): hooks 加 2 事件 (PreLLMCall/PostLLMCall) + 3 默认 hook (interim_assistant/audit_log/tool_stats) + chat() + langchain_agent.py 同步提取; 共 6 事件 7 默认 hook, 117 unit + 5 E2E 测试
> 📝 W4-18 集成验证 (2026-06-22): MCP handler 签名改为 `**kwargs` 跟其他 tool 一致 (旧 `args: Dict` 跟 ToolRegistry.execute 的 `handler(**arguments)` 不兼容) + 13 个集成测试覆盖 skill 调用 / 长任务多轮 / MCP 假 server 全生命周期; 13/13 全绿
> 📝 W4-19 清理 (2026-06-22): ModernChatPanel.tsx 1104 → 429 行 (抽 `useStreamChat` hook 435 行); 历史审查报告归档到 `docs/historical-reviews/` (2760+1147 行); 顺手 commit 5 个散落 doc
> 📝 W4-20 架构 (2026-06-22): terminal 白名单热加载 (`data/terminal_whitelist.txt` 追加 + `reload_security_config()` in-place 修改, 7 个测试); `team.py:run_stream()` 加 DEPRECATED 注释 (3 个月内迁 `run_v2_stream()`)
> 📝 W4-21 架构 (2026-06-22): 12 个工具模块顶层 `registry.register` 副作用抽到 `_register_tools()` 函数; `discover_builtin_tools` 显式调; AST 检测支持 `_register_tools` 函数; 4 个测试
> 📝 W4-22 架构 (2026-06-22): `main.py` 305 → 145 行: 拆 `lifespan.py` (modern lifespan context manager) + `startup.py` (LLM/AgentEngine init) + `routes/health.py` (/, /health, /ready)
> 📝 W4-23 修复 (2026-06-22): langchain_agent `is_persistent=False` 临时回退 (W3-B) 改回 `True`: `chat_history` 跳过 system messages (因 `prompt=` 已传), checkpointer 不再累积 system, 60 条历史连续记忆恢复
> 📝 W4-24 修复 (2026-06-22): `must_use_tool` 触发词 `.lower()` → `.casefold()` (Unicode 标准); 提取 `MUST_USE_TOOL_TRIGGERS` / `VISIBLE_CHROME_TRIGGERS` 模块常量; 2nd round LLM 仍不用 tool → 显式 fallback 错误
> 📝 W4-25 修复 (2026-06-22): `_ask_pending` AgentEngine 内存 dict → SQLite store (`app/core/ask_store.py`); 多 worker (uvicorn --workers>1) 部署共享; TTL 1h 自动过期; 11 个测试 (含 multi-process 共享)
> 📝 W4-27 修复 (2026-06-22): Team mode 10 个 bug 集中修复 (CRITICAL: Pydantic v2 PrivateAttr 静默失败导致 `_round`/`_idle_count` 永远 0, 死循环保护失效); `_decompose_idea()` 替代单 root task; `run_v2_stream` 实际订阅 EventBus 实时事件; per-role 异常隔离; 14 个新测试
> 📝 **W4-28 修复 (2026-06-23)**: `_startup_llm` 加 `SKIP_LLM_VALIDATION=1` env 跳过 + 5s 快速失败
> 📝 W4-29 重构 (2026-06-23): `ModernChatPanel.tsx` 改 WeChat/iMessage 社交对话风格, header + avatar, 518 行; `MarkdownContent.tsx` 引入 react-markdown
> 📝 W4-30 特性 (2026-06-23): 4 套主题 (`dark-stone` / `light-clean` / `sepia-warm` / `midnight-blue`) + 用户自主配色切换
> 📝 W4-32 修复 (2026-06-25): minimax/MiniMax-Text-01 工具调用幻觉 — content 不带 `message.tool_calls` 字段, 改成 XML 编码文本; 加 `xml_tool_call_parser.py` + system_prompt 提示
> 📝 W4-33 重构 (2026-06-29): System Prompt 精简 10.4KB → 5.3KB (-49%), 删 cli/*.md (5) + personality.md, 解决 4 层 prompt 重复点 ≥ 5 + 矛盾 3 处
> 📝 **W4-34 修复 (2026-06-29)**: provider function call 适配审计 — 5 provider (baichuan/wenxin/xfyun/chatglm/ollama) chat() 签名接 `tools` 但 body 不传, LLM 永远只回纯文本。改继承 `OpenAICompatibleLLM` (-281/+74 行, -70%), 加 `tests/test_provider_function_call_contract.py` CI gate 用 `inspect` 沿 MRO 扫 15 provider 验证 tools 传 + tool_calls 解析。38 passed 8 skipped (anthropic/google/openai/tongyi 豁免, 待 W4-35)。结果 11/15 provider 完整适配, 默认 minimax 不受影响

 (`asyncio.wait_for`): 之前外网不通时 120s×3 重试 ≈ 6min 卡死, 现在要么跳过要么 5s 内 fail; 启动 + in-process TestClient 端到端验证: GET /, /health, /ready, /docs, /openapi.json 全 200, POST /api/chat/stream (langchain + legacy 两条路径) SSE 管道通 (`event: start` → `progress` → LLM 调用, sandbox 无外网在 LLM 步失败属预期); 顺手补 `.venv311` 缺失的 `langchain_core` / `langgraph-checkpoint-sqlite` (生产 venv 一直没装, 启动后 chat 直接 ImportError)


| 维度 | 数值 |
|---|---|
| 文件总数 | 205 |
| Python 源文件 | 165 |
| TS/TSX 文件 | 39 |
| 节点 | 3,791（class 234 / function 781 / method 1,026 / interface 88 / type_alias 13） |
| 边 | 7,572（import 1,055 占 14%） |
| 索引状态 | ✅ up-to-date（`codegraph status`） |
| 最近同步 | 2026-06-10（参见 [codegraph 0.9.9](https://codegraph.dev)） |

> ⚠️ 索引由本地 `codegraph` 守护进程维护；仓库内 `.codegraph/` 已 gitignore。CI 流程请使用 `codegraph sync` 而非直接 commit `codegraph.db`。

---

## 1. 顶层模块边界

按 `codegraph files --filter backend/app --max-depth 3` 输出（去掉 metadata）：

```
backend/app/
├── api/                  # FastAPI 路由层（13 个 router）
│   ├── chat.py / memory.py / chart.py / llm.py
│   ├── evaluation.py / dreaming.py / skills.py
│   ├── marketplace.py / tool_harness.py / stream.py
│   └── im_gateway.py / gateway_profiles.py
├── core/                 # 业务核心
│   ├── agent.py            ← AgentEngine（自研 ReAct 循环）
│   ├── langchain_agent.py  ← stream_chat_langchain（LangGraph ReAct）
│   ├── system_prompt.py / env_capabilities.py / skills_index.py
│   ├── context_*.py / iteration_budget.py / project_context.py
│   ├── capabilities.py / marketplace.py / domain_prompts.py
│   └── multi_agent/        ← 5/28 重构的 v2 多 agent 子树
├── tools/                # 工具系统
│   ├── registry.py / manager.py / base.py
│   ├── permission.py / security_config.py / approval.py / audit.py
│   ├── mcp_client.py / langchain_adapter.py
│   └── implementations/    ← 14 个内置工具模块，模块级 registry.register()
├── memory/               # 记忆层
│   ├── storage.py          ← SQLite MemoryStorage（5 张表）
│   └── vector.py           ← ChromaDB VectorStore
├── llm/                  # LLM 适配器（11 个 provider）
│   ├── base.py / factory.py / model_metadata.py
│   ├── openai.py / openai_compatible.py / anthropic.py
│   ├── tongyi.py / baichuan.py / chatglm.py / gemini.py
│   ├── ollama.py / wenxin.py / xfyun.py
│   └── langchain_adapter.py ← TongYongLLMAdapter（接 LangChain BaseChatModel）
├── skills/               # 技能市场（models + manager）
├── dreaming/             # 后台反思引擎（engine / signals / backfill / config）
├── evaluation/           # 评估服务
├── hermes/               # 平文件记忆 + nudge + constraint
│   ├── memory_file.py / skill_file.py / constraint.py
│   ├── nudge.py            ← NudgeEngine（HermesConstraintEngine 同住）
│   └── routes.py           ← API 路由
├── gateway/              # IM 网关（飞书 / 企微 / 微信 / OpenAI API）
│   ├── im/ manager / openai_api / desktop_bridge
│   ├── profile_*.py / auth.py / config.py
├── domains/              # 领域层（system prompt 来源）
│   ├── cli / cron / identity / memory / personality / tools
│   ├── base.py / integrator.py
├── services/             # 跨模块服务（llm_manager 等）
├── scheduler/            # 占位
├── vision/               # 占位
├── db/migrations/
├── config.py
└── main.py               ← 303 行装配入口（参见架构审查 P1）
```

`frontend/src/` 顶层：

```
frontend/src/
├── api/                  # 10 个 API 客户端（含 stream.ts / team/）
├── components/           # 13 个组件目录
│   ├── Chat/ (含 ModernChatPanel.tsx 1104 行)
│   ├── Session/ (Sidebar) / Memory/ / Skills/ / Team/ / Dreaming/ / LLM/
│   ├── Personality/ / Evaluation/ / Marketplace/ / Approvals/ / ToolHarness/
│   └── common/ (含 ErrorBoundary)
├── services/ / types/
├── App.tsx / main.tsx
```

---

## 2. 关键运行链路（运行时调用图）

### 2.1 单 agent 流式对话（W3 默认 langchain=true → 100% 切量）

```
[Browser]
  └─> ModernChatPanel.tsx
        └─> api/stream.ts: streamChat()
              └─> POST /api/chat/stream        # FastAPI
                    └─> api/stream.py: generate_stream_response()
                          ├─> LANGCHAIN_ROLLOUT 灰度决策（100% 默认全开）
                          ├─> use_langchain=True
                          │     └─> core/langchain_agent.py: stream_chat_langchain()
                          │           ├─> TongYongLLMAdapter (llm/langchain_adapter.py)
                          │           │     └─> base_llm.stream_chat()  # 真 token 流
                          │           ├─> registry_to_langchain_tools()  # 14 内置工具
                          │           └─> langgraph.prebuilt.create_react_agent
                          │                 └─> AsyncSqliteSaver（W1-3 接入，目前 is_persistent=False）
                          └─> use_langchain=False
                                └─> core/agent.py: AgentEngine.stream_chat()
                                      └─> self.llm.chat() # 自研 ReAct 循环
```

### 2.2 多 agent 团队协作

```
[TeamPanel] ──> /api/team/sessions/{id}/run
  └─> multi_agent/api/router.py
        └─> multi_agent/api/service.py
              └─> Team.run_stream() / Team.run_v2_stream()
                    ├─> EventBusEnvironment（v2 SQLite WAL + EventBus）
                    │     ├─> EventBus（app/core/multi_agent/event_bus.py）
                    │     │     ├─> team_events 表（消息持久化）
                    │     │     └─> asyncio.Queue per agent
                    │     └─> TaskQueue（task_queue.py，原子 claim + TTL）
                    └─> Scheduler（v2 全事件驱动，run_v2_stream 走它）
                          └─> AgentTask → TaskExecutionContext
                                └─> LLM + ToolManager.execute()
```

### 2.3 IM 网关 / OpenAI 兼容 / Skills Marketplace / Dreaming

四块独立子系统，均通过 FastAPI router 挂载在 main.py，运行时与 AgentEngine 单向耦合（通过 `inject_agent_engine()` / `hermes_routes.x = ...` 模式注入，参见 P3 风险）。

---

## 3. 关键节点（按代码图谱中心性排序）

> 数据来自 `codegraph query -k class -l 30 ""` 抽样与最近 30 天 commit 触碰的模块。

| 节点 | 位置 | 中心性（incoming edges） | 备注 |
|---|---|---|---|
| `AgentEngine` | [agent.py:111](backend/app/core/agent.py:111) | 高 | 唯一单 agent 入口；被 main.py / 14 个 API router / delegate_task / scheduler 引用 |
| `Team` | [team.py:31](backend/app/core/multi_agent/team.py:31) | 高 | 多 agent 编排；run_stream 与 run_v2_stream 并存 |
| `Scheduler` | [scheduler.py](backend/app/core/multi_agent/scheduler.py) | 中 | v2 事件驱动主循环；目前 run_v2_stream 路径 |
| `TongYongLLMAdapter` | [langchain_adapter.py](backend/app/llm/langchain_adapter.py) | 中 | LangChain ↔ BaseLLM 桥；W4-2 修复真流式 |
| `TongyiLLM` | [tongyi.py:16](backend/app/llm/tongyi.py:16) | 中 | 默认 provider；W4-4 修了 usage 解析 |
| `MemoryStorage` | [storage.py](backend/app/memory/storage.py) | 高 | 5 张表，profile_id 路径分支 |
| `VectorStore` | [vector.py](backend/app/memory/vector.py) | 中 | ChromaDB 持久化 |
| `MemoryFileManager` | [memory_file.py](backend/app/hermes/memory_file.py) | 中 | MEMORY.md/USER.md 平文件管理 |
| `ToolRegistry` | [registry.py](backend/app/tools/registry.py) | 高 | 14 个内置工具 + MCP；模块级 register 副作用（参见 P3） |
| `ItertionBudget` | [iteration_budget.py](backend/app/core/iteration_budget.py) | 低 | 工具调用轮次控制；W1-3 修了 hasattr bug |
| `HermesConstraintEngine` | [hermes/constraint.py:50](backend/app/hermes/constraint.py:50) | 低 | 反幻觉校验 |
| `DreamingEngine` | [dreaming/engine.py:27](backend/app/dreaming/engine.py:27) | 中 | 后台反思 |
| `NudgeEngine` | [hermes/nudge.py:71](backend/app/hermes/nudge.py:71) | 低 | Hermes 提示 |
| `delegate_task_tool` | [delegate_task.py](backend/app/tools/implementations/delegate_task.py) | 中 | 子 agent 委派；模块级 `_delegate_depth`（风险） |
| `DebateJudgeAction.run` | [debate.py:218](backend/app/core/multi_agent/actions/debate.py:218) | 极低 | ⚠️ 字符串匹配正反方（待修） |

---

## 4. 已知风险台账（持续维护）

> 等级：🔴 P0 / 🟠 P1 / 🟡 P2。来源在每条尾部。

### 4.1 架构层

- 🟠 **main.py 6 职责 / 303 行 / 4 处跨模块 monkey-patch**（[architecture-review-2026-06-02.md](historical-reviews/architecture-review-2026-06-02.md) P1 / P2 提议，**未执行**）
- 🟠 **工具模块顶层 `registry.register(...)` 副作用**（同上 P3，未执行）
- 🟡 **agent → LLMManager.bind_agent_engine 单向注入**，多 router 又通过 `from app.main import agent_engine` 反向读取，形成**主从耦合**（参见 P2）
- 🟡 **langchain 路径 is_persistent=False 是临时回退**（[langchain_agent.py:220-227](backend/app/core/langchain_agent.py) 注释 W3-B，**根因未根治**）

### 4.2 业务逻辑层

- ✅ **[W4-8 已修] DebateJudgeAction 字符串匹配**（[debate.py:236-241](backend/app/core/multi_agent/actions/debate.py)）—— 当角色名不含"正方/反方"时全漏判，[commit 510bff1](historical-reviews/code-review-2026-05-29.md) 已点名未修
- ✅ **[W4-8 已修] system prompt 注入顺序与注释相反**（[agent.py:198-249](backend/app/core/agent.py)）—— `_inject_*` 全用 `messages.insert(0, ...)`，最后调用的反而占顶部，base_prompt 被压到最底
- ✅ **[W4-11 + W4-14 已修] MCP 客户端**（[mcp_client.py](backend/app/tools/mcp_client.py)）—— W4-11 修 4 处 (silent return / text mode / get_running_loop / future 清理); W4-14 修 4 处 (跨 loop future 跟踪 / 进程 crash fail pending / shutdown 顺序 / async 入口), 共 17 个测试（[mcp_client.py:65-78, 191-211, 109-118](backend/app/tools/mcp_client.py)）—— 旧实现 `Popen(text=False)` + str write 必 TypeError, `_send_raw` 进程未启动时 silent return 导致 future 永远 hang
- ✅ **[W4-13 已修] `_extract_heuristic_sections` 多启发式段全部保留**（[skills_index.py:172-202](backend/app/core/skills_index.py)）—— 旧实现遇到第一个非启发式 ## 标题就 break, 后续 ## Heuristic B 等全被丢
- ✅ **[W4-13 已修] `get_system_skills_content` 预算动态递减**（[skills_index.py:205-274](backend/app/core/skills_index.py)）—— 旧实现 `budget_per = 8KB // N` 一次性, 多个 skill 累计可能超 8KB
- ✅ **[W4-13 已修] `marketplace.install_skill` skipped 结构化**（[marketplace.py:587-619](backend/app/core/marketplace.py)）—— 旧实现 `skipped.append(rel + " (binary)")` 把 path 和 tag 拼成一个字符串, 污染 List[str] 列表
- ✅ **[W4-12 已修] SKILL `get_skills_prompt` mtime-aware refresh**（[skills_index.py:103-110, 291-305](backend/app/core/skills_index.py)）—— 旧实现 `_detected` 单次缓存, 上传新 skill 后 system prompt 看不到; 移除死代码 `_cached_scan` / `@lru_cache`, 统一用 `_last_mtime` + `_last_index` 跟踪
- ✅ **[W4-9 已修] 辩论 mode round 按 debate_position 排序**（[team.py:28-36, 119-120](backend/app/core/multi_agent/team.py)）—— 抽出 module-level helper `sort_roles_by_debate_position()`, first/second/third/fourth/judge 顺序保证, 未填 position 兜底 99
- ✅ **[W4-10 已修] delegate_task 改用 ContextVar 隔离委派深度**（[delegate_task.py:39, 433, 484](backend/app/tools/implementations/delegate_task.py)）—— `set/reset(token)` 配对, 异常路径仍 finally reset, 跨 Task 不串扰
- 🟡 **`must_use_tool` 触发词列表对中文小写化无意义**（[agent.py:706-709](backend/app/core/agent.py)），`.lower()` 对中文是恒等
- 🟡 **辩论模式上游仍是 round 轮次驱动**（[team.py:200-260](backend/app/core/multi_agent/team.py)），run_v2_stream 与 run_stream 并存，无明确弃用时间表

### 4.3 测试 / 覆盖率

- ✅ **[W4-8 已补] 辩论测试覆盖**（[tests/test_debate_judge.py](backend/tests/test_debate_judge.py)，7 用例: 英文名 + 兜底 + judge 排除 + metadata 覆盖 + SpeakAloud）
- ✅ **[W4-14] MCP 客户端 lifespan 测试**（[tests/test_mcp_lifespan.py](backend/tests/test_mcp_lifespan.py) 9 用例: _response_futures tuple layout / _fail_pending / 跨 loop call_soon_threadsafe / close 顺序 / _read_loop 退出 fail pending / async 入口幂等 / shutdown 清理)
- ✅ **[W4-11 已补] MCP 客户端测试**（[tests/test_mcp_client.py](backend/tests/test_mcp_client.py)，8 用例: silent return + future 清理 + get_running_loop 无 deprecation + close 不重复 + text=True）
- ✅ **[W4-13 已补] 审计发现修复测试**（[tests/test_w413_audit_fixes.py](backend/tests/test_w413_audit_fixes.py)，8 用例: heuristic 多段 + Decision/Pitfall 模式 + budget 不超 8KB + skipped 结构化）
- ✅ **[W4-12 已补] Skill 索引测试**（[tests/test_skills_index.py](backend/tests/test_skills_index.py)，9 用例: mtime refresh + 长描述省略号 + 死代码移除 + refresh 重置 + 缓存复用）
- ✅ **[W4-9 已补] 辩论 round 排序测试**（[tests/test_debate_round_order.py](backend/tests/test_debate_round_order.py)，8 用例: 正常排序 + 空 list + 单角色 + 未填 position 兜底 + typo 兜底 + stable sort + 不改入参 + 幂等）
- ✅ **[W4-10 已补] delegate_depth ContextVar 测试**（[tests/test_delegate_task.py](backend/tests/test_delegate_task.py) 末尾 4 用例: 顺序调用不残留 + 并发任务互不污染 + 异常路径 finally reset + 递归阻止语义保持）
- 🟡 **W3-4 切量回滚测试单文件**（[test_w3_rollback.py](backend/tests/test_w3_rollback.py)），未覆盖 hot reload
- 🟡 **前端 E2E 仅 Playwright PDF 验证首页**（[package.json scripts](frontend/package.json)），无 chat 流式断言

### 4.4 工具 / 基础设施

- 🟡 **`terminal` 工具白名单 `_ALLOWED_COMMANDS` 是硬编码列表**（[security_config.py](backend/app/tools/security_config.py)），新增命令需改源码
- 🟡 **`ask` 工具 `_ask_pending` 是 AgentEngine 实例属性**（[agent.py:117-119](backend/app/core/agent.py)），多 worker 部署（uvicorn workers>1）会丢问题
- ✅ **[W4-14] MCP 客户端 lifespan 修复**（[mcp_client.py](backend/app/tools/mcp_client.py)）—— 4 处 bug: 跨 loop future 泄漏 / 进程 crash 时 future hang 60s / shutdown 顺序错乱 / 不接 FastAPI lifespan; 配套 9 个新测试
- ✅ **[W4-28] 启动期 LLM 验证 5s fast-fail + SKIP env 跳过**（[lifespan.py](backend/app/lifespan.py) `_startup_llm`）—— `asyncio.wait_for(..., 5.0)` 替代无 timeout 调用, 触发 `TimeoutError` 记 warning 继续; `SKIP_LLM_VALIDATION=1` env 跳过整段 (sandbox / air-gap 环境用); 顺带补 `.venv311` 缺的两个包 (`langchain_core` `langgraph-checkpoint-sqlite`)，生产 venv 启动后 `/api/chat/stream` 不再 ImportError
- ✅ **[W4-27] Team mode 10 bug 集中修复**（[team.py](backend/app/core/multi_agent/team.py) 452→593 行 + 14 测试）—— CRITICAL: Pydantic v2 PrivateAttr 重赋值静默失败 (run_stream `_round`/`_idle_count`/`_result_messages` 全部失效, 死循环保护死), 加 `_set()` helper 封装 `object.__setattr__`; per-role 异常隔离 (1 个角色崩不杀全队); `_decompose_idea()` 把多句 idea 拆成多 task; `run_v2_stream` 实际订阅 EventBus 实时 yield (旧实现 await 5min 后才 yield); role cursor reset / fire unregister scheduler / Pydantic v2 ConfigDict / 死参数 / summary 加 round+msgs
- ✅ **[W4-25] ask_pending SQLite 持久化**（[ask_store.py](backend/app/core/ask_store.py)）—— 替代 AgentEngine 内存 dict, 多 worker 共享, TTL 1h
- ✅ **[W4-24] must_use_tool casefold + 2nd fallback**（[agent.py:116-138](backend/app/core/agent.py)）—— `.casefold()` 替代 `.lower()`, 触发词提模块常量, 2nd round LLM 不用 tool → 显式 fallback
- ✅ **[W4-23] langchain checkpointer 恢复**（[langchain_agent.py:208-216](backend/app/core/langchain_agent.py)）—— `chat_history` 跳过 system messages (因 `prompt=` 已传), `is_persistent = session_id is not None`, 60 条历史连续记忆恢复
- ✅ **[W4-22] main.py 拆 lifespan/startup/routes**（[main.py](backend/app/main.py) 305→145 + [lifespan.py](backend/app/lifespan.py) + [startup.py](backend/app/startup.py) + [routes/health.py](backend/app/routes/health.py)）—— modern lifespan context manager, app factory 模式
- ✅ **[W4-21] 工具模块 _register_tools 显式**（[registry.py:420-440](backend/app/tools/registry.py)）—— 12 模块顶层 register 抽到函数, 测试可 mock
- ✅ **[W4-20] terminal 白名单热加载**（[security_config.py](backend/app/tools/security_config.py)）—— `data/terminal_whitelist.txt` 追加, `reload_security_config()` in-place, 7 测试
- ✅ **[W4-20] team.run_stream DEPRECATED**（[team.py:142-149](backend/app/core/multi_agent/team.py)）—— 标记 3 个月内迁 run_v2_stream
- ✅ **[W4-19] ModernChatPanel 拆 hook**（[useStreamChat.ts](frontend/src/hooks/useStreamChat.ts) 435 行 + ModernChatPanel 1104→429）—— 流式状态机抽 hook
- ✅ **[W4-18] MCP handler 签名统一**（[mcp_client.py:321-336](backend/app/tools/mcp_client.py)）—— 旧 `mcp_handler(args: Dict)` 跟 ToolRegistry.execute 的 `handler(**arguments)` 不兼容 (LLM 传 `{"text": "hi"}` 时被调成 `mcp_handler(text="hi")` 直接 TypeError); 改为 `**arguments` 跟其他 tool 约定一致, 13 个集成测试覆盖
- ✅ **[W4-17] hooks 扩展 6 事件 7 默认 hook**（[agent_hooks.py](backend/app/core/agent_hooks.py)）—— +PreLLMCall/PostLLMCall 事件, +interim_assistant/audit_log/tool_stats 默认 hook; chat() + langchain_agent.py 同步提取
- ✅ **[W4-16] agent 循环外行为注册为 hooks**（[agent_hooks.py](backend/app/core/agent_hooks.py)）—— 4 事件 (UserPromptSubmit/PreToolUse/PostToolUse/Stop), 25 个测试
- ✅ **[W4-15] 新增 `glob` 工具'（[glob_tool.py](backend/app/tools/implementations/glob_tool.py)）—— 跨目录模式匹配, 跳 _PRUNE_DIRS (.git/.venv/node_modules/__pycache__), 限制 max_results
- ✅ **[W4-15] `load_skill` 别名**（[skill_tools.py:243-281](backend/app/tools/implementations/skill_tools.py)）—— 指向 skill_view, 兼容 Anthropic 风格命名, description 注明是 alias
- 🟢 **watchdog 自愈**（[scripts/dev-watchdog.sh](scripts/dev-watchdog.sh)）W4-5 已修
- 🟢 **Vite 6 升级 + HMR 稳定**（[frontend/package.json](frontend/package.json)）W3 末修

---

## 5. 维护协议

### 5.1 同步索引

```bash
# 项目根目录
codegraph sync                 # 增量同步（监听 11 文件改动后自动）
codegraph status               # 验证 up-to-date
codegraph index .              # 强制全量重建
```

### 5.2 引用规则

写新代码或评审时，引用图谱节点应使用：
- 路径 + 行号 + 类/方法名：`backend/app/core/agent.py:111 AgentEngine.__init__`
- 完整本地链接（GitHub 风格绝对路径，渲染层自动渲染）

### 5.3 更新本文档

| 触发事件 | 必改小节 | 节奏 |
|---|---|---|
| `codegraph sync` 后 nodes/edges 涨跌幅 > 5% | §0 摘要 | 周 |
| 新增 / 删除顶层目录 | §1 模块边界 | 即时 |
| 新接入 LLM provider / 工具 | §3 关键节点 | 即时 |
| 修 bug 加新风险项 | §4 风险台账 | 即时 |
| 重大架构变更（切框架 / 拆装） | 全文 | 触发即写 |

### 5.4 不要做的

- 不要把 `.codegraph/codegraph.db` 提交进 git（已在 `.codegraph/.gitignore`）
- 不要在 `docs/CODEGRAPH.md` 里贴大段源码（用行号 + 引用）
- 不要把测试覆盖度作为唯一质量指标（先看 §4 风险台账）

---

## 6. 附录

### 6.1 关键 commit 索引（最近 30 天）

| SHA | 标题 | 影响范围 |
|---|---|---|
| `510bff1` | 辩论 start_msg 不再 filter debate_side | team.py:158 |
| `2a5dd69` | DebateSpeechAction debate_side fallback 改 or-trick | debate.py:137 |
| `0431b29` | RoleList borderColor/borderBottomColor 混用修 React 警告 | frontend |
| `12f69a3` | 后端 watchdog 自愈 | scripts/dev-watchdog.sh |
| `964e357` | 修通 token usage 上 UI + 真流式分块 | agent.py / langchain_agent.py / openai_compatible.py / tongyi.py |
| `119d8be` | stream output, vite hmr crash, context window overflow | langchain_agent.py / ModernChatPanel / vite 升级 |
| `dd4ea3a` ~ `6571cd2` | W3 切流量系列 | stream.py |
| `9c1beca` ~ `9a61b38` | W2 行为对齐基线 | stream.py |
| `9586156` | fix(W4-14): MCP 客户端 lifespan 4 处 bug (跨 loop future / crash hang / shutdown 顺序 / async 入口) | mcp_client.py |
| `c209ba0` | feat(W4-15): 新增 glob 工具 + load_skill 别名 | glob_tool.py / skill_tools.py |
| `130ba63` | feat(W4-16): 引入 agent 循环 hooks 模式 (s04_hooks 风格) | agent_hooks.py / agent.py |
| `a906c3e` | feat(W4-17): 扩展 hooks 模式 - 6 事件 7 默认 hook + chat/langchain 同步 | agent_hooks.py / agent.py / langchain_agent.py |
| `65879c1` | fix(W4-18): MCP handler **kwargs 签名 + 集成测试 13 用例 | mcp_client.py / test_integration_skill_mcp.py |
| `727b34a` | refactor(W4-19): ModernChatPanel 拆 hook + 历史审查报告归档 | frontend + docs/historical-reviews |
| `3f06dd0` | feat(W4-20): terminal 白名单热加载 + debate_run DEPRECATED | security_config.py / team.py |
| `b0df7af` | refactor(W4-21): 工具模块 _register_tools() 显式注册 | 12 implementations + registry.py |
| `7dbac80` | refactor(W4-22): main.py 拆 lifespan / startup / routes/health | main.py / lifespan.py / startup.py / routes/health.py |
| `fe4fb15` | fix(W4-23): langchain_agent checkpointer 恢复 + system 去重 | langchain_agent.py / main.py |
| `04b43d2` | fix(W4-24): must_use_tool casefold + 2nd round fallback | agent.py (MUST_USE_TOOL_TRIGGERS) |
| `41f5d49` | fix(W4-25): _ask_pending AgentEngine 内存 dict → SQLite store | ask_store.py / agent.py / ask.py / lifespan.py |
| (W4-28)   | fix(W4-28): lifespan `_startup_llm` SKIP_LLM_VALIDATION + 5s fast-fail; .venv311 补 langchain_core / langgraph-checkpoint-sqlite | lifespan.py / requirements.txt |
| (W4-27)   | fix(W4-27): Team mode 10 bug (Pydantic v2 PrivateAttr + per-role exception + decompose + EventBus subscribe) | team.py / test_team_bugfixes.py |
| `8d07486` ~ `e8ba538` | W1 LangChain adapter 集成 + 回归基线 | langchain_adapter / test_phase1 |

### 6.2 索引命令速查

```bash
codegraph status                       # 整体状态
codegraph files --filter backend/app   # 文件树
codegraph query -k class "Engine"      # 按 kind 搜
codegraph callers FuncName             # 反向引用
codegraph callees FuncName             # 正向调用
codegraph impact FuncName              # 受影响节点
codegraph affected file1 file2         # 改文件后受影响的测试
```

### W4-32: XML 工具调用兜底 (P1 hallucination)

- 现象: 部分 LLM (典型 MiniMax-Text-01) 不返回结构化 `tool_calls`, 把调用编码成 XML 文本塞 content
- 修复: `app/llm/xml_tool_call_parser.py` + `MiniMaxLLM._parse_response` 兜底分支
- 监控: 关键词 `[MiniMax W4-32]` logger.warning
- 单元测试: `tests/test_xml_tool_call_parser.py` (28 用例)
