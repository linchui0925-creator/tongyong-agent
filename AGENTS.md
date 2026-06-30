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
| 默认 LLM | **deepseek / deepseek-v4-flash** (W4-38 切换, 用户提供 sk-d3a5fa6f...411a) — reasoning model, W4-39 加 reasoning_content + XML 兜底 |
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

---

## 6. 最近变更 (滚动 10 commit)

| SHA | W4 | 摘要 |
|---|---|---|
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
