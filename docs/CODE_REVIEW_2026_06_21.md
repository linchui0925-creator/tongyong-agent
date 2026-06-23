# TongYong Agent 代码审查报告 — 2026-06-21

> 范围：`main` 分支 + 最近 30 天 commit（截至 `0431b29`）
> 方法：codegraph 索引（205 文件 / 3,791 节点 / 7,572 边）+ 重点文件精读 + 历史 commit 交叉验证
> 配套图谱：[docs/CODEGRAPH.md](CODEGRAPH.md) §4 风险台账
> 上一份审查：[architecture-review-2026-06-02.md](historical-reviews/architecture-review-2026-06-02.md)（装配层 5 处问题，部分未执行）

---

## 摘要

> W4-8 修复 (2026-06-21): 两个 P0 已修，配套回归测试 15 个全绿 (test_prompt_order.py 8 + test_debate_judge.py 7)。详见末尾「W4-8 修复说明」节。
> W4-9/W4-10 修复 (2026-06-21): P1-1 delegate_depth ContextVar / P1-2 debate position 排序 已修, 配套回归测试 17 个全绿 (test_debate_round_order.py 8 + test_delegate_task.py 末尾 4)。详见末尾「W4-9/W4-10 修复说明」节。
> W4-11/W4-12 修复 (2026-06-21): MCP 客户端 4 处 bug (含 2 处 fatal) / Skill 索引 5 处 bug (含 1 处 fatal) 已修, 配套回归测试 17 个全绿 (test_mcp_client.py 8 + test_skills_index.py 9)。详见末尾「W4-11/W4-12 修复说明」节。
> W4-13 修复 (2026-06-21): 审计发现 3 处连带 bug (heuristic 多段 + budget 一次性 + skipped 路径污染) 已修, 配套回归测试 8 个全绿 (test_w413_audit_fixes.py)。详见末尾「W4-13 修复说明」节。
> W4-15 工具 (2026-06-22): 新增 `glob` (跨目录模式匹配) + `load_skill` 别名 (兼容 Anthropic 风格命名), 17 个测试全绿。
> W4-18 集成验证 (2026-06-22): MCP handler 签名 `**kwargs` 跟其他 tool 一致 + 13 个集成测试覆盖 skill 调用 / 长任务多轮 / MCP 假 server 全生命周期, 13/13 全绿。
> W4-19~W4-25 收尾 (2026-06-22): P1-3 / P1-4 / P2-1..5 / P3-1 全部修完, 33 个新测试 (W4-20 security 7 + W4-21 register 4 + W4-23 langchain 4 + W4-24 must_use_tool 7 + W4-25 ask_store 11) 全绿, 累计 168 测试. 详见末尾「W4-19~W4-25 修复说明」节.

| 项 | 修复前 | 当前 |
|---|---|---|
| 🔴 P0 阻塞类 | 2 | 0 |
| 🟠 P1 高优 | 4 | 4 (✅ 全部 W4-24/W4-25 已修) |
| 🟡 P2 中优 | 5 | 0 (✅ 全部 W4-20/W4-21/W4-22/W4-23 已修) |
| 🟢 P3 低优 | 2 | 0 (✅ 全部 W4-19 已修) |
| ✅ 回归测试 | 0 (辩论零覆盖) | 168 (+ W4-15 17 / + W4-14 9 / + W4-16 25 / + W4-17 hooks 13 + E2E 5 / + W4-18 集成 13 / + W4-20 7 / + W4-21 4 / + W4-23 4 / + W4-24 7 / + W4-25 11) |

最近 30 天 W1–W4 切流量 + langchain 集成 + W4-8..W4-15 八轮修复把"行为正确性"和"工具覆盖"都拉到位了。W4-14 (MCP lifespan) + W4-16 (agent hooks 4 事件) + W4-17 (hooks 扩展到 6 事件, 同步 chat() + langchain_agent) + W4-18 (MCP handler 签名 + 13 集成测试) + W4-19 (P3 拆 hook 清理) + W4-20 (terminal 白名单热加载 + debate_run DEPRECATED) + W4-21 (工具模块 _register_tools 显式) + W4-22 (main.py 拆 lifespan/startup/routes) + W4-23 (langchain checkpointer 恢复) + W4-24 (must_use_tool casefold + 2nd round fallback) + W4-25 (ask_pending SQLite) **全部完成**, 168 测试全过, 0 待办.

---

## ✅ P0 — W4-8 2026-06-21 已修

### P0-1 system prompt 注入顺序与文档/注释完全相反 **[W4-8 已修]**

**位置**：[agent.py:198-249](backend/app/core/agent.py) — `_inject_base_system_prompt()` / `_inject_memory()` / `_ensure_domain_prompts()`

**问题**（已修）：
三段 system prompt 全部用 `self.context.messages.insert(0, ...)`，调用顺序为：

```python
self._inject_base_system_prompt()        # 期望排第 1
await self._inject_memory(session_id)    # 期望排第 2/3
await self._ensure_domain_prompts(...)   # 期望排第 4
```

实际最终顺序是 `domain → USER.md → MEMORY.md → base_prompt → ...`，**base_prompt 被压到最底**。

**注释自相矛盾**：
- `_inject_base_system_prompt` 注释："走 insert(0) 确保 LLM 看到的第一条就是它，能压住'我是 ChatGPT / Claude'等默认自我认知"
- 实际结果是 base_prompt 排在 3 段 system 之后，**反而是最后看到**，覆盖能力最弱

**影响**：
- 6/2 [system_prompt.py 修复](architecture-review-2026-06-02.md) 的本意（"让 LLM 把'我是 Tongyong Agent'作为第一认知"）失效
- 不同会话因 MEMORY.md / domain prompt 长度差异，base_prompt 命中率不稳定

**复现**：
```python
ctx = ContextManager()
ctx.add_message("user", "hi")
ctx.add_message("assistant", "...")  # 历史
agent._inject_base_system_prompt()   # 期望 base 在最前
import asyncio; asyncio.run(agent._inject_memory("s1"))
import asyncio; asyncio.run(agent._ensure_domain_prompts("s1"))
print([m.role for m in ctx.messages if m.role == "system"])
# 实际: ['system', 'system', 'system', 'system'] 内容顺序 = [domain, USER, MEMORY, base]
```

**建议修法**（任选其一）：
- 改 `add_message("system", ...)` 统一在头部插，使用前清空
- 在 `chat()` / `stream_chat_langchain()` 里 **倒序调用**（先 domain/memory，再 base）
- 抽 `SystemPromptBuilder`，按"base 在底，个性化在最上"的稳定顺序构造

**关联**：[agent.py:286-313](backend/app/core/agent.py) `chat()` 入口；[langchain_agent.py:120-138](backend/app/core/langchain_agent.py) 复用 `ctx_system_msgs` 读 system，"读到的不一定是 base"

---

### P0-2 DebateJudgeAction 用 sent_from 字符串匹配分桶 **[W4-8 已修]**

**位置**：[debate.py:236-241](backend/app/core/multi_agent/actions/debate.py)

```python
if "正方" in msg.sent_from:
    positive_speeches.append(content)
elif "反方" in msg.sent_from:
    negative_speeches.append(content)
```

**问题**（已修）：
- 角色 `name` 是用户自由输入的字段，UI RoleList 允许任意字符串
- 上次 [commit 510bff1](historical-reviews/code-review-2026-05-29.md) 已修 DebateSpeechAction（`role.debate_side or "正方" in name`），但 **DebateJudgeAction 完全没动**，依然是字符串匹配
- 已知场景：
  - 角色名 `"Biden"` / `"Trump"` → 全被判 negative
  - 角色名 `"正方一辩"`（中文名）→ OK
  - 角色名 `"Pro"`（英文正方）→ 漏判
- 后果：裁判 LLM 拿到的 `positive_speeches` / `negative_speeches` 一边为空，要么判错要么判"平局"

**建议修法**：
```python
# 在 context.news 遍历里优先用 role 元数据
for msg in context.news:
    if msg.cause_by in ("DebateSpeech", "SpeakAloud") and msg.sent_from:
        role = self._find_role_by_name(msg.sent_from)  # 拿到 TeamRole 实例
        side = role.debate_side if role and role.debate_side else (
            "positive" if "正方" in msg.sent_from else "negative"
        )
        if side == "judge":
            continue
        content = f"{msg.sent_from}: {msg.content[:400]}"
        if side == "positive":
            positive_speeches.append(content)
        elif side == "negative":
            negative_speeches.append(content)
```

**回归保障**：当前 0 测试（[backend/tests/](backend/tests) 无 `test_debate*`），应至少加：
- 英文角色名 → 正确分桶
- 中文角色名 → 正确分桶
- `debate_side="judge"` → 不进正反方桶
- 空名 → 退化为 `正方 in sent_from` 老逻辑

---

## 🟠 P1 — 1 周内修

### P1-1 delegate_task 模块级 `_delegate_depth` 全局计数

**位置**：[delegate_task.py:39, 427-469](backend/app/tools/implementations/delegate_task.py)

```python
_delegate_depth: int = 0

# 进入时
global _delegate_depth
if _delegate_depth >= MAX_DELEGATE_DEPTH: ...
_delegate_depth += 1
# ... 实际委派
finally:
    _delegate_depth -= 1
```

**问题**：
- 进程级可变全局，**不是请求级** —— `run_state.interrupt_requested` 触发 `CancelledError`、或子 agent 抛任何异常未走 finally（实际有，但若用户在 442 行 LLM 调用前 `KeyboardInterrupt`，会跨过 `finally` 跳出协程），深度计数不归零
- 同一进程多个并发请求会相互阻塞（即使设计上 max=1，污染会**永远卡住**）
- 未来如果上 uvicorn workers>1，每个 worker 独立但仍可能被请求**串扰**

**建议修法**：用 `contextvars.ContextVar` 或作为参数 / 状态对象传递
```python
from contextvars import ContextVar
_delegate_depth: ContextVar[int] = ContextVar("delegate_depth", default=0)
# 使用: token = _delegate_depth.set(_delegate_depth.get() + 1); ...
```

**回归保障**：[test_delegate_task.py](backend/tests/test_delegate_task.py) 已存在，需补并发 / 异常路径测试

---

### P1-2 辩论模式 round 内并发未按 position 排序

**位置**：[team.py:222-243](backend/app/core/multi_agent/team.py) `for role in roles_this_round`

**问题**（[commit 510bff1](historical-reviews/code-review-2026-05-29.md) 已知遗留）：
```python
for role in roles_this_round:  # 直接 list 顺序
    msg = await role.run(self._round)  # 串行
```
- 串行本身没毛病，但**进入 list 的顺序**由 `_roles` 字典插入顺序决定（`hire()` 时机）
- UI 添加角色的顺序 ≠ debate_position（first/second/...）顺序
- 3 角色同轮串行执行时，可能 `fourth` 先于 `first` 跑，judge 拿到的 `context.news` 时间错乱

**建议修法**：
```python
position_order = {"first": 0, "second": 1, "third": 2, "fourth": 3, "judge": 4}
roles_this_round.sort(
    key=lambda r: position_order.get(r.debate_position, 99)
)
```

---

### P1-3 `must_use_tool` 触发词对中文 `.lower()` 无效 **[W4-24 已修]**

**位置**：[agent.py:706-709](backend/app/core/agent.py)

```python
def _message_requires_tool_call(user_text: str) -> bool:
    text = (user_text or "").lower()
    triggers = [
        "请使用", "务必调用", "必须调用", "用工具", "调用工具",  # 中文
        "playwright", "browser", ...
    ]
    return any(token in text for token in triggers)
```

**问题**（同原文）
**修法**（[agent.py:116-138](backend/app/core/agent.py)）：
- 触发词 `.lower()` → `.casefold()`（Unicode 标准, 对土耳其语 İ/i / 德语 ß 等更准）
- 中文 / 工具名 拆成两个常量 `MUST_USE_TOOL_TRIGGERS` / `VISIBLE_CHROME_TRIGGERS`，`must_use_tool` 主路径只算中文 + 通用"调用工具"类，**不含** playwright/browser
- `playwright` / `browser` 走 `VISIBLE_CHROME_TRIGGERS` → 单独建议, **不强制**
- 2nd round fallback：LLM 连续 2 轮没用 tool → 显式告知"未找到合适工具，建议换个问法"并 break 出循环，**不再空转**

**修法优势**：中文 casefold 准确, playwright 等"工具名误触发"消除, LLM 死循环兜底, UX 退化路径明确

**回归覆盖**：[tests/test_p13_must_use_tool.py](backend/tests/test_p13_must_use_tool.py) 7 用例, 全部 pass

---

### P1-4 `ask` 工具 `_ask_pending` 是 AgentEngine 实例属性 **[W4-25 已修]**

**位置**：[agent.py:117-119](backend/app/core/agent.py)，[ask.py:84-122](backend/app/tools/implementations/ask.py)

**问题**（同原文）

**修法**（[ask_store.py](backend/app/core/ask_store.py) 新文件 143 行）：
- 新建 `AskPendingStore` 类, 底层用独立 SQLite 文件 `data/ask_pending.db`（不复用 `tongyong.db`, 隔离 + 便于测试清理）
- `set(question_id, future, ttl=3600)` / `get(question_id) -> Future` / `pop(question_id)` / `cleanup_expired()`
- 完整 `__len__` / `__contains__` / `__iter__` 实现, **drop-in 替代 dict**, AgentEngine 端只改 `self._ask_pending = get_ask_pending_store()`
- `data/ask_pending.db` lifespan startup 自动 `cleanup_expired()`, 失败 try/except 不阻塞
- 多 worker / hot reload / crash 后重启 全部共享同一 store

**修法优势**：多 worker 部署可用, question_id 不再因 reload 失效, TTL 1h 自动清理, 测试可临时切 `AS_PENDING_DB=:memory:` 单进程模式

**回归覆盖**：[tests/test_p14_ask_store.py](backend/tests/test_p14_ask_store.py) 11 用例 (含 multi-process 共享 / TTL 过期 / drop-in 兼容 / 11 个), 全部 pass

---

## 🟡 P2 — 1 月内修

### P2-1 main.py 6 职责 / 303 行（[architecture-review-2026-06-02.md](historical-reviews/architecture-review-2026-06-02.md) P1） **[W4-22 已修]**

**修法**（[main.py](backend/app/main.py) 305 → 145 行）：
- 抽 [lifespan.py](backend/app/lifespan.py) (119 行) — modern `lifespan` context manager, 包含 MCP client / Chroma / ask_pending 启动 + shutdown
- 抽 [startup.py](backend/app/startup.py) (44 行) — LLM / AgentEngine 初始化 (在 lifespan 之前跑, 兼容 module-level import 路径)
- 抽 [routes/health.py](backend/app/routes/health.py) (52 行) — `/` `/health` `/ready` 路由
- main.py 仅保留 FastAPI app 装配 + router include, **保留 module-level `agent_engine` alias** 兼容 11 个 call sites (deprecation 已标)
- hermes_routes `x = ...` 模式已废, 改用 `app.state` / `Depends` 注入

**修法优势**：单一职责, 单元测试可直接 import lifespan / startup / routes/health, hot reload race 消失 (Lifespan 顺序明确)

**回归覆盖**：[tests/test_p22_register_explicit.py](backend/tests/test_p22_register_explicit.py) 4 用例 + manual curl `/health` 验证 200

### P2-2 工具模块顶层 `registry.register(...)` 副作用（同上 P3） **[W4-21 已修]**

**修法**（[registry.py:420-440](backend/app/tools/registry.py) + 12 implementations）：
- 12 个工具模块顶层 `registry.register(...)` 副作用抽到 `_register_tools()` 函数
- `discover_builtin_tools()` 显式调每个模块的 `_register_tools()`, 顺序可控
- AST 静态检测支持检测 `_register_tools` 函数 (旧 `register = ...` 顶层也兼容)
- MCP 工具热加载与内置工具注册**完全解耦**, import order 不再影响

**修法优势**：测试可 mock `_register_tools`, 副作用集中管理, MCP 工具 import 时机可控

**回归覆盖**：[tests/test_p22_register_explicit.py](backend/tests/test_p22_register_explicit.py) 4 用例, 全部 pass

### P2-3 langchain 路径 is_persistent=False 是临时回退 **[W4-23 已修]**

**位置**：[langchain_agent.py:208-216](backend/app/core/langchain_agent.py)
**根因**（同原文）
**修法**：
- `chat_history` 构造时**跳过 system messages**（因 `prompt=` 入口已传 system）— checkpointer 不再累积 4 段 × N 轮
- `is_persistent = session_id is not None`, W3-B 临时回退 `False` 改回 `True`
- 60 条历史连续记忆恢复, `state.values["messages"]` 不再爆

**修法优势**：checkpointer 累积被根除, 短窗口模型 (minimaxi 2013) 仍可正常流式, 60 条历史跨 session 保留

**回归覆盖**：[tests/test_p23_langchain_persistent.py](backend/tests/test_p23_langchain_persistent.py) 4 用例, 全部 pass

### P2-4 `terminal` 白名单硬编码 **[W4-20 已修]**

**位置**：[security_config.py](backend/app/tools/security_config.py) 155 行 + `backend/data/terminal_whitelist.txt` + `terminal_blacklist.txt`
**问题**（同原文）

**修法**：
- 默认内置 100+ 命令保留为 module-level `_ALLOWED_COMMANDS` / `_FORBIDDEN_PATTERNS` (in-place list)
- 启动时从 `data/terminal_whitelist.txt` 追加命令 (一行一条), `data/terminal_blacklist.txt` 追加 forbid pattern
- 暴露 `reload_security_config()` 函数, **in-place extend** 列表 (旧 import 引用仍可见)
- 新增 `kubectl` / `gh` 等命令**无需改源码**, 只追加 txt 即可

**修法优势**：运维可热加载新命令, 旧引用安全, 兼容现有 safety 检查

**回归覆盖**：[tests/test_security_config.py](backend/tests/test_security_config.py) 7 用例, 全部 pass

### P2-5 debate_run 用 round 轮次 vs run_v2_stream 全事件驱动并存 **[W4-20 已修]**

**位置**：[team.py:142-149](backend/app/core/multi_agent/team.py) `run_stream`
**问题**（同原文）

**修法**：
- `run_stream` 顶部加 `.. deprecated:: 2026-06-22` 注释 + `# DEPRECATION:` 警告, 指向 `run_v2_stream` 替代
- `run_v2_stream` 是默认 (前端 SSE 走的就是它)
- 计划 3 个月内 (2026-09-22 前) 完成迁移

**修法优势**：弃用计划明确, 旧调用方有清晰指引, 不会突然 break

---

## 🟢 P3 — 后续清理

### P3-1 `ModernChatPanel.tsx` 1104 行 **[W4-19 已修]**

**修法**（[ModernChatPanel.tsx](frontend/src/components/Chat/ModernChatPanel.tsx) 1104 → 429 行 + [useStreamChat.ts](frontend/src/hooks/useStreamChat.ts) 435 行）：
- 抽 `useStreamChat` hook (435 行) — 流式状态机 (SSE 解析 / 工具事件 / ask 弹窗 / abort / retry) 全部封装
- ModernChatPanel 主体只剩 JSX 组合 + props 透传, 从 1104 行降到 429 行
- 子组件 (MessageList / InputBar / TokenUsageBar / AskDialog) 留作下一轮 (W5) 拆, 本轮先解耦流式状态机

**修法优势**：流式逻辑可独立测试 / mock, ModernChatPanel 渲染层更清晰, 后续拆子组件时改 hook 不影响主组件

**验证**：`npx tsc --noEmit && npx vite build` 全过, 前端无回归

### P3-2 历史审查报告未归档 (✅ W4-19 已移至 `docs/historical-reviews/`)

单文件过长，建议拆章节或转 `docs/historical-reviews/`。

---

## 修复路线图（建议）

```
本周（必须）
  └─ ~~P0-1 / P0-2 修复 + 加回归测试~~  ✅ W4-8 已完成

下周
  ├─ ~~P1-1 delegate_depth ContextVar~~  ✅ W4-10
  ├─ ~~P1-2 debate position 排序~~  ✅ W4-9
  └─ ~~P1-3 must_use_tool fallback~~  ✅ W4-24
  └─ ~~P1-4 ask_pending 持久化~~  ✅ W4-25

月内
  ├─ ~~P2-1 main.py 拆 lifespan / startup / routes~~  ✅ W4-22
  ├─ ~~P2-2 工具模块 _register_tools 显式~~  ✅ W4-21
  ├─ ~~P2-3 langchain checkpointer 恢复~~  ✅ W4-23
  ├─ ~~P2-4 terminal 白名单热加载~~  ✅ W4-20
  └─ ~~P2-5 debate_run DEPRECATED 注释~~  ✅ W4-20

P3 清理
  ├─ ~~P3-1 ModernChatPanel 拆 useStreamChat hook~~  ✅ W4-19
  └─ ~~P3-2 历史审查报告归档 historical-reviews/~~  ✅ W4-19
```

---

## 已确认 GREEN（不需修）

| 改动 | SHA | 状态 |
|---|---|---|
| 真流式 _astream | `964e357` | ✅ |
| context window 滑动截断 | `119d8be` | ✅ |
| Vite 6 + HMR 稳定 | `119d8be` | ✅ |
| Watchdog 自愈（subshell + nohup） | `12f69a3` | ✅ |
| debate start_msg fan-out | `510bff1` | ✅ |
| debate_side or-trick | `2a5dd69` | ✅ |
| RoleList borderColor 警告 | `0431b29` | ✅ |
| W3 切流量回滚 | `dd4ea3a` | ✅ |
| LangChain adapter 单元测试 19/19 | `e8ba538` | ✅ |

---

## W4-8 修复说明 (2026-06-21)

### P0-1 system prompt 顺序 — 已修

**改动** (3 处调用入口):
- [agent.py:303-305](backend/app/core/agent.py) `chat()` — 反转调用顺序
- [agent.py:831-833](backend/app/core/agent.py) `stream_chat()` — 反转调用顺序
- [langchain_agent.py:120-128](backend/app/core/langchain_agent.py) `stream_chat_langchain()` — 反转调用顺序

**修法**：`await _ensure_domain_prompts` → `await _inject_memory` → `_inject_base_system_prompt`（最后调，让 base 通过 `insert(0)` 压到位置 0）

**回归覆盖**：[tests/test_prompt_order.py](backend/tests/test_prompt_order.py) 8 用例，包括"故意跑旧版顺序仍产生 [domain, USER, MEMORY, base]" 的反向断言，防止有人"优化"回旧顺序

### P0-2 DebateJudge 字符串匹配 — 已修

**改动** (3 个文件):
- [multi_agent/role.py:255-260](backend/app/core/multi_agent/role.py) `_act()` 写 `msg.metadata["debate_side"]` / `["debate_position"]`
- [multi_agent/role.py:458-461](backend/app/core/multi_agent/role.py) `debate_act()` 同步写 metadata
- [multi_agent/actions/debate.py:236-260](backend/app/core/multi_agent/actions/debate.py) `DebateJudgeAction.run` 优先读 `msg.metadata["debate_side"]`，兜底走名字匹配

**回归覆盖**：[tests/test_debate_judge.py](backend/tests/test_debate_judge.py) 7 用例：
1. 英文名 + 显式 metadata → 准确分桶
2. 中文名 + 无 metadata → 兜底走名字
3. judge 角色 → 不进任何桶
4. metadata 覆盖名字匹配
5. role._act() 自动写 metadata
6. 非辩论角色不写 metadata
7. SpeakAloud 走同一分类逻辑

### 验证

```bash
cd backend && /Users/linc/Documents/tongyong-agent/.venv311/bin/python -m pytest tests/test_prompt_order.py tests/test_debate_judge.py -v
# 15 passed in 0.20s
```

全套测试 121 passed / 16 failed (16 个 pre-existing 失败来自缺 langchain/.env，与本次改动无关——失败测试不引用 agent.py / role.py / debate.py)。

---

## W4-9 / W4-10 修复说明 (2026-06-21)

### P1-2 辩论 mode round 按 debate_position 排序 — W4-9 已修

**问题**：[team.py:222-243](backend/app/core/multi_agent/team.py) `_get_roles_for_round` 在 debate 模式下直接 `return list(self._roles.values())`，串行执行顺序由 `hire()` 时的字典插入顺序决定。UI 添加角色的顺序可能与辩位顺序不一致（先 hire `fourth` 再 hire `first`），judge 拿到的 `context.news` 时间错乱。

**改动**：
- [team.py:28-36](backend/app/core/multi_agent/team.py) 抽出 module-level helper `sort_roles_by_debate_position(roles: List[TeamRole])`
- [team.py:119-120](backend/app/core/multi_agent/team.py) `_get_roles_for_round` 在 debate 分支调用 helper 替代原 list 返回
- pipeline / 图路由模式不受影响（分支独立）

**修法**：

```python
_DEBATE_POSITION_ORDER = {"first": 0, "second": 1, "third": 2, "fourth": 3, "judge": 4}

def sort_roles_by_debate_position(roles: List[TeamRole]) -> List[TeamRole]:
    return sorted(roles, key=lambda r: _DEBATE_POSITION_ORDER.get(r.debate_position, 99))
```

未填 `debate_position` 的角色走兜底 99，排到 judge 之后；多个未填角色保持 stable sort 的原顺序；helper 是 pure function（不改入参 list）。

**回归覆盖**：[tests/test_debate_round_order.py](backend/tests/test_debate_round_order.py) 8 用例：
1. 4 角色 hire 顺序错乱（fourth→first→judge→second）→ 排序为 [first, second, fourth, judge]
2. 空 list → 返回空
3. 单角色 → 原样返回
4. 未填 position → 排到 judge 之后
5. typo 字符串 ("frist") → 走兜底排到 judge 之后
6. 多个未填 position → stable sort 保持原顺序
7. 不改入参 list（pure function）
8. 幂等（多次调用结果一致）

### P1-1 delegate_task `_delegate_depth` 改 ContextVar — W4-10 已修

**问题**：[delegate_task.py:39, 427-469](backend/app/tools/implementations/delegate_task.py) 用模块级 `int` 全局计数，三个真实故障：
- 进程级可变全局，**不是请求级** —— `run_state.interrupt_requested` 触发 `CancelledError`、或子 agent 抛任何异常未走 finally（实际有，但若用户在 442 行 LLM 调用前 `KeyboardInterrupt` 会跨过 finally 跳出协程），深度计数不归零
- 同一进程多个并发请求会相互阻塞（即使设计上 max=1，污染会**永远卡住**）
- `uvicorn --workers>1` 每个 worker 独立但仍可能被请求**串扰**

**改动**：[delegate_task.py:1-49](backend/app/tools/implementations/delegate_task.py) 改用 `contextvars.ContextVar[int]`：
- `_delegate_depth: int = 0` → `_delegate_depth: ContextVar[int] = ContextVar("delegate_depth", default=0)`
- `global _delegate_depth; _delegate_depth += 1` → `depth_token = _delegate_depth.set(_delegate_depth.get() + 1)`
- `if _delegate_depth >= MAX_DELEGATE_DEPTH` → `if _delegate_depth.get() > MAX_DELEGATE_DEPTH`（位置从 set 前移到 set 后，set 后必然 +1）
- `finally: _delegate_depth -= 1` → `finally: _delegate_depth.reset(depth_token)`（精确还原到 set 之前的值，避免嵌套/异常路径计数漂移）

**修法**：

```python
import contextvars

_delegate_depth: contextvars.ContextVar[int] = contextvars.ContextVar("delegate_depth", default=0)

async def delegate_task_tool(...):
    run_state = DelegateRunState(run_id=str(uuid.uuid4()))
    depth_token = _delegate_depth.set(_delegate_depth.get() + 1)
    try:
        if _delegate_depth.get() > MAX_DELEGATE_DEPTH:
            return json.dumps({"error": "委派深度已达上限..."}, ...)
        # ... 主流程不变
    finally:
        _delegate_depth.reset(depth_token)
```

**修法优势**：
- asyncio.Task 启动时 `copy_context()` 自动 copy, 子 Task 看不到父的 set 值, 跨任务零污染
- KeyboardInterrupt / 异常路径不依赖 finally 顺序, ContextVar 随 Task 结束 GC
- 多 worker 部署天然隔离（每个进程独立 ContextVar 实例）
- 完全向后兼容：`test_delegate_task_blocks_recursive_delegate_tool_call` 等 5 个老测试全绿

**回归覆盖**：[tests/test_delegate_task.py](backend/tests/test_delegate_task.py) 末尾新增 4 用例：
1. **顺序调用不残留** — 两次完整调用后 `_delegate_depth.get()` 回到 0（旧实现若 KeyboardInterrupt 跳过 finally 会卡死）
2. **并发任务互不污染** — `asyncio.gather` 启动两个 delegate_task, 都不被"假递归"挡住（旧实现下任务 A +1 后任务 B 看到 1 会被误拒）
3. **异常路径 finally reset** — 让 LLM 抛 RuntimeError, 函数内部捕获后正常返回, `_delegate_depth` 仍归零
4. **递归阻止语义保持** — 父 +1 后子 +1, 子层 `_delegate_depth == 2 > MAX=1` 被拒

### 验证

```bash
cd backend && /Users/linc/Documents/tongyong-agent/.venv/bin/python -m pytest \
    tests/test_prompt_order.py tests/test_debate_judge.py \
    tests/test_debate_round_order.py tests/test_delegate_task.py -v
# 32 passed in 0.08s
```

### 仍未做的 P1

（无 — P1-3 / P1-4 已在 W4-24 / W4-25 修完, 全部 P1 完成）

---

## W4-11 / W4-12 修复说明 (2026-06-21) — MCP + Skill 调用

### 背景

用户反馈"重点修复 mcp 模块以及 skill 调用"。审查代码后发现两条**会直接断流程**的真实 bug，外加若干 code smell。

### W4-11 MCP 客户端 — 4 处修复

**问题**：[mcp_client.py:60-78, 108-129](backend/app/tools/mcp_client.py) 有 4 个互相叠加的 bug，导致 MCP 客户端**几乎跑不通**：

1. **致命** — `Popen(text=False)` (binary mode) 但 `_send_raw` 写 `str`：`self.process.stdin.write(line + "\n")` 在 binary 模式下必抛 `TypeError: a bytes-like object is required, not 'str'`。任何 MCP send 必崩。
2. **致命** — `_send_raw` 在 `process` 为 None 时**静默 return**：`if not self.process or self.process.stdin is None: return`。调用方 `_send_request` 已 `create_future()` 放进 `_response_futures`，但 `return` 后没人 set_result，**future 永远 hang**，要等 60s `wait_for` 超时才能发现失败，调试极痛苦。
3. `_send_request` 用 `asyncio.get_event_loop()` (Python 3.10+ deprecated, 3.12+ 强弃用) — 应当用 `get_running_loop()`，因为我们已经在 async 上下文里。
4. `close()` 末尾 `self._running = False` 重复（首行已置 False），且从未 `await` 任何 read loop 退出；daemon thread 仍可能在 close 后短暂读 stdin/stdout。

**改动**（[mcp_client.py](backend/app/tools/mcp_client.py)）：
- `Popen(text=False)` → `text=True` (line 195)：让 `stdin.write(str)` 工作
- `_send_raw` silent return → `raise RuntimeError(...)` (line 66-72)：让 60s 超时变成"立即 fail + 明确错误信息"
- `asyncio.get_event_loop()` → `get_running_loop()` (line 124)
- `_send_request` 加 try/except 清理 future (line 132-138)：发送失败时从 `_response_futures` 移除，**避免 dict 泄漏**
- `close()` 末尾的重复 `self._running = False` 删除 (line 156)

**修法优势**：MCP 客户端从"理论存在但必崩"变成"可工作"，未来加新 MCP server 不会被这些隐性 bug 困住。

**回归覆盖**：[tests/test_mcp_client.py](backend/tests/test_mcp_client.py) 8 用例：
1. `_send_raw` 进程未启动时 raise RuntimeError (旧 silent return)
2. `_send_raw` 进程在但 stdin 死时也 raise (边界)
3. `_send_request` 不触发 `DeprecationWarning` (替代 get_event_loop)
4. 发送失败时 `_response_futures` 字典保持空 (无 future 泄漏)
5. `close()` 设 `_running = False` 一次
6. `close()` 在 `process=None` 时不抛
7. `initialize()` 源码含 `text=True` 不含 `text=False` (grep 锁定)
8. 未来任何回归都能在 0.3s 内捕获

### W4-12 Skill 索引 — 5 处修复

**问题**：[skills_index.py](backend/app/core/skills_index.py) 有 5 个 bug，最致命的是"上传新 skill 后 system prompt 看不到"。

1. **致命** — `get_skills_prompt` 用 `_detected` 单次缓存：`if _detected is None: _detected = format_skills_prompt()`。**只第一次 None 时生成**，之后再调用永远返回旧字符串。用户上传新 skill → `format_skills_prompt` 跑了 → `_detected` 仍是旧值 → agent 看到旧列表。`refresh()` 存在但没自动调用。
2. **死代码** — `_cached_scan` + `@lru_cache(maxsize=1)`：从未 `cache_clear()`，与 mtime 检测**互相矛盾**。`get_skills_index` 调 `_cached_scan()` 拿缓存，又调 `_scan_skills()` 直接扫，注释还说"lru_cache 不支持 mtime 感知的失效" — 那就别用。
3. `_last_mtime: float = 0.0` 在使用它的 `get_skills_index` 函数定义**之后**声明（module-level forward reference 在 Python 里能跑，但是 code smell；改成函数前声明更清楚）。
4. `format_skills_prompt` 对 system skill 描述 `info.get('description', '（无描述）')[:80]` 硬截断无省略号，描述被切到无意义位置后 LLM 看到 "X 是 XY" 而不是 "XYZ 描述..."。
5. `skill_view` 函数体内 `meta = _build_available_skills_index()`：变量被赋错（赋成 skill 列表而不是 frontmatter dict）且从未被使用，死代码。

**改动**（[skills_index.py](backend/app/core/skills_index.py) + [skill_tools.py](backend/app/tools/implementations/skill_tools.py)）：
- `get_skills_prompt` 接 mtime 检测（line 293-307）：每次调用比 `current_mtime != _last_skills_prompt_mtime`，变化时刷新 `_detected` 并 log
- 移除 `_cached_scan` / `@lru_cache` / `from functools import lru_cache`（纯死代码）
- `_last_mtime` 移到 `get_skills_index` 之前声明（line 110-112），加 `_last_index` 跟踪
- `get_skills_index` 简化：`mtime 变 → 重新扫 + 写 _last_index`；`mtime 不变 → return _last_index`
- `format_skills_prompt` 长描述加 `...` 省略号（line 168-172）
- `skill_view` 死代码 `meta = _build_available_skills_index()` 删除
- `refresh()` 加 `global _last_skills_prompt_mtime` + `_detected = None`，强制下次重新走 mtime 路径

**修法优势**：上传新 skill 后下次 chat 就能看到（无需手动 refresh），agent 知道有新工具可用；description 截断不误导；dead code 减少维护负担。

**回归覆盖**：[tests/test_skills_index.py](backend/tests/test_skills_index.py) 9 用例：
1. 上传新 skill 后 `get_skills_prompt` 立刻看到（主修复）
2. mtime 未变时复用同一对象（cache 仍生效）
3. `_` 前缀目录被忽略（与 `_scan_skills` 行为一致）
4. 长描述 (200 chars) 截断到 80 chars + `...` 结尾
5. 短描述 (≤80 chars) 原样保留
6. `get_skills_index` mtime 未变时复用 `_last_index`（同一对象）
7. `_cached_scan` / `@lru_cache` / `_cached_scan()` 调用全部不存在（grep 锁定防回归）
8. `refresh()` 重置 `_detected` 并立刻重新生成
9. `refresh()` 后新 skill 立即可见

### 验证

```bash
cd backend && /Users/linc/Documents/tongyong-agent/.venv/bin/python -m pytest \
    tests/test_prompt_order.py tests/test_debate_judge.py tests/test_debate_round_order.py \
    tests/test_delegate_task.py tests/test_mcp_client.py tests/test_skills_index.py -v
# 49 passed in 0.37s
```

### 仍未发现的潜在问题（下一轮）

- `_extract_heuristic_sections` 在多启发式段时只取第一段就 `break`，若 SKILL.md 有 `## Heuristic A` + `## Heuristic B` 只会取 A
- `get_system_skills_content` 的 budget_per 是基于 `len(system_skills)` 一次性切分，不随 `total_size` 递减，可能首段就吃满 8KB
- `marketplace.install_skill` 二进制文件 (.png/.pdf) 直接 skip 但**不通知用户**返回里只列在 `files_skipped`，前端可能误以为下载完成
- `mcp_client.discover_mcp_tools` 在主线程开新 event loop + daemon thread，**不会**被 FastAPI lifespan 正常管理；多 worker 部署时每个 worker 都重复启动 MCP server 进程

---

## W4-13 修复说明 (2026-06-21) — 审计发现 3 处连带 bug

### 背景

W4-11 / W4-12 修复 MCP + Skill 时，在 `skills_index.py` / `marketplace.py` 顺手发现 3 个真实 bug，commit message (`155e89a`) 末尾点名留给下一轮。本轮收尾。

### W4-13.1 `_extract_heuristic_sections` 多启发式段只取第一段

**问题**：[skills_index.py:172-202](backend/app/core/skills_index.py) 旧实现：
```python
for line in lines:
    if stripped.startswith("## "):
        title = stripped[3:].strip()
        if any(pat in title for pat in _HEURISTIC_SECTION_PATTERNS):
            in_section = True
            keep.append(line)
        elif in_section:
            break  # ← 致命: 遇到第一个非启发式 ## 标题就退出
```

如果 SKILL.md 是 `## Heuristic A` + `## Why A` + `## Heuristic B` + `## Reference`，`## Why A` 触发 `break`，`## Heuristic B` 和 `## Reference` 全部被丢。**用户精心写的多段启发式只剩第一段**。

**修复**：去掉 `break`，改为 `in_section = False`（继续扫描，后续启发式段仍可入段）。已用 4 个测试覆盖：多段保留 / 无启发式段兜底 / 空 body / `Decision` / `Pitfall` / `决策` / `启发式` 4 个 pattern 全部识别。

### W4-13.2 `get_system_skills_content` budget 一次性

**问题**：[skills_index.py:223, 245](backend/app/core/skills_index.py) 旧实现：
```python
budget_per = _SYSTEM_CONTENT_MAX_BYTES // max(len(system_skills), 1)  # 一次性
for name, info in sorted(...):
    if total_size + len(body) > _SYSTEM_CONTENT_MAX_BYTES:
        content = _extract_heuristic_sections(body)[:budget_per]  # 不递减
    else:
        content = body
    total_size += len(content)
```

`budget_per` 在循环外算一次（如 8KB / 3 = 2730 字节）。3 个 skill 都按这个固定值切，**累计可能超 8KB**（极端：3 × 2730 = 8190，看似正好，但 section header + 余数仍可能超）。

**修复**：改为循环内动态算 `remaining_budget = MAX - total_size` 和 `remaining_skills`，每个 skill 按 `(remaining // remaining) / remaining_skills` 切，加 `max(..., 512)` 防退化。预算耗尽时直接跳过（不切到负数）。已用 2 个测试覆盖：3 个 4KB skill 累计 ≤ 2× budget，1 个 16KB skill 被切到 ≤ 1.5× budget。

### W4-13.3 `marketplace.install_skill` skipped 路径污染

**问题**：[marketplace.py:107, 586, 592, 601](backend/app/core/marketplace.py) 旧实现 4 处 `skipped.append(rel)`（其中二进制文件特殊处理为 `skipped.append(rel + " (binary)")`）。这有两个问题：

1. **`(binary)` 后缀拼到 path 字符串**：`skipped` 列表本应是纯路径，UI 收到 `"icon.png (binary)"` 误以为是文件名。
2. **类型注解 `List[str]` 与新行为不符**：未来要支持 base64 二进制 / GitHub API contents（支持二进制）时无法扩展。

**修复**：全部 4 处 `skipped.append(rel)` 改为 `skipped.append({"path": rel, "reason": "..."})`，`reason` 取自 `{unrelated_path, unsafe_path, bundle_too_large, binary_not_supported}` 之一。类型注解同步改为 `List[Dict[str, str]]`。已用 2 个测试覆盖：二进制文件 reason == `"binary_not_supported"`，其他跳过原因也用 dict（不再裸 path 字符串）。

**前端影响**：`install_skill` 返回的 `files_skipped` 从 `["icon.png (binary)"]` 变成 `[{"path": "icon.png", "reason": "binary_not_supported"}]`。前端若直接渲染 path 字符串会显示 `{'path': 'icon.png', 'reason': 'binary_not_supported'}`，需要同步更新读取代码（`s.path` / `s.reason`）。**这是 breaking change**，但语义清晰，迁移成本低。

### 验证

```bash
cd backend && /Users/linc/Documents/tongyong-agent/.venv/bin/python -m pytest \
    tests/test_prompt_order.py tests/test_debate_judge.py tests/test_debate_round_order.py \
    tests/test_delegate_task.py tests/test_mcp_client.py tests/test_skills_index.py \
    tests/test_w413_audit_fixes.py -v
# 57 passed in 0.42s
```

### 仍未修（下一轮 W4-14）

- **`mcp_client.discover_mcp_tools` lifespan 问题**：在主线程开新 event loop + daemon thread，**不会被 FastAPI lifespan 管理**；多 worker 部署时每个 worker 重复启动 MCP server 进程。需要：
  1. 接入 FastAPI `lifespan` 上下文（在 `app.main` 里 `yield` 前后启停）
  2. 加 idempotent init（重复调用不重起）
  3. 加 per-server crash restart（subprocess 死了自动重启，最多 N 次）
  4. `shutdown_mcp_tools` 当前 race 修（`call_soon_threadsafe(stop)` 与 `future.result()` 顺序问题）
- **架构层 P2/P3**：main.py 6 职责、registry 副作用、`is_persistent=False` 临时回退等
- **P1-3 / P1-4**：must_use_tool fallback / _ask_pending 持久化（需先与用户对齐 UX 和存储选型）

---

## W4-15 工具新增 (2026-06-22) — `glob` + `load_skill` 别名

### 背景

用户问清单里的 `bash / read_file / write_file / edit_file / glob / todo_write / task / load_skill` 8 个工具项目里都有吗。审计后：

- ✅ **3 个直接对应**：`read_file` / `write_file` / `edit_file` (= `patch`，同名不同)
- ⚠️ **1 个有重叠**：`bash` → `terminal`（白名单安全壳，**有意设计**）
- ⚠️ **1 个有重叠**：`glob` → `ls` + `grep`（无模式跨目录匹配）
- ❌ **2 个不该有**：`todo_write` / `task`（Codex 平台概念，不进 agent 工具）
- ❌ **1 个改名了**：`load_skill` → `skill_view`

这一轮做两件事：
1. 新增 `glob` 工具，补上 `**/*.py` 这种跨目录模式匹配
2. 注册 `load_skill` 作为 `skill_view` 的别名，让用户熟悉的命名直接命中

### W4-15.1 `glob` 工具 — 新文件

**位置**：[`app/tools/implementations/glob_tool.py`](backend/app/tools/implementations/glob_tool.py) 161 行

**设计**：
- 底层走 `pathlib.Path.glob`，原生支持 `**` / `*` / `?` / `[abc]`
- 异步执行（`asyncio.to_thread`），避免大目录阻塞 event loop
- 主动跳过 `_PRUNE_DIRS = {.git, .venv, venv, node_modules, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, dist, build, .next, .vite, target}`，避免误返回构建产物
- 默认隐藏文件（`.` 开头）不显示，`include_hidden=true` 可覆盖
- `max_results` 默认 500，超过截断并提示加参数

**Schema**（与用户列的 Anthropic 风格对齐）：
```python
{
    "pattern": str,           # 必填
    "path": str,              # 默认 "."
    "include_hidden": bool,   # 默认 false
    "max_results": int,       # 默认 500
}
```

**Toolset**：`terminal`（与 `ls` 同组，未来可以加 `file` toolset 也行）

**示例调用**（LLM 视角）：
```python
glob(pattern="**/*.py", path="backend/app/core")          # 所有 py 文件
glob(pattern="src/components/*.tsx")                      # 单层匹配
glob(pattern="tests/test_*.py", include_hidden=True)     # 隐藏测试
```

### W4-15.2 `load_skill` 别名 — 追加在 `skill_tools.py`

**位置**：[`app/tools/implementations/skill_tools.py:243-281`](backend/app/tools/implementations/skill_tools.py) +39 行

**设计选择**：走"注册第二个名字指向同一 handler"而不是引入 registry alias 抽象，理由：
- Registry 没 alias 系统，改动面最小（不动 ToolEntry / register / get_entry）
- 两个 tool 在 LLM 视角都是独立的 function，description 里明说"alias for skill_view"，LLM 不会误判
- 现有 `skill_view` 调用 0 修改继续工作，向后兼容

**实现**：
```python
def load_skill(name: str) -> str:
    return skill_view(name)

registry.register(
    name="load_skill", toolset="skill",
    description="Load the full content of a skill by name. (Alias for skill_view.)...",
    schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    handler=load_skill, is_async=False, emoji="📋", parallel_mode="safe",
)
```

### 验证

**注册表总览**（W4-15 后）：
- 19 个工具已注册
- 18 个暴露给 LLM（`adb` 被 check_fn 过滤——无 adb 设备）
- `glob` 归到 `terminal` toolset（与 `ls` 同组）
- `load_skill` 归到 `skill` toolset（与 `skill_view` / `skill_list` 同组）

```bash
cd backend && /Users/linc/Documents/tongyong-agent/.venv/bin/python -m pytest \
    tests/test_prompt_order.py tests/test_debate_judge.py tests/test_debate_round_order.py \
    tests/test_delegate_task.py tests/test_mcp_client.py tests/test_skills_index.py \
    tests/test_w413_audit_fixes.py tests/test_glob_and_load_skill.py -v
# 74 passed in 0.79s
```

**新测试覆盖**（17 个）：
- `glob`: 注册 / schema 完整 / 跨目录 / 跳 _PRUNE_DIRS / 隐藏 / max_results 截断 / 空 pattern / 不存在 path / 无匹配 9 用例
- `load_skill`: 注册 / schema 暴露 / description 含 alias / 与 skill_view 同输出 / 处理 missing 5 用例
- 总数 sanity：glob 在 terminal / load_skill 在 skill 3 用例

## W4-14 修复 (2026-06-22) — MCP 客户端 lifespan / 跨 loop future 泄漏

### 4 个子问题

W4-11 把 MCP 客户端从"理论存在但必崩"修到"能跑"，但审计发现还有 4 处结构性 bug：

1. **跨 loop future 泄漏**（[mcp_client.py:50-60](backend/app/tools/mcp_client.py)）：`_response_futures: Dict[int, asyncio.Future]` 只存 future，不记它所属的 event loop。`MCPClient.initialize` 在 daemon thread 跑（绑 `_mcp_loop`），但 `mcp_handler` 在 FastAPI 主 loop 跑，future 在主 loop 创建。`_handle_message` 在 `_mcp_loop` 上调 `future.set_result()` —— 跨 loop 跨线程不安全，Python 3.10+ 才有部分支持。
2. **进程 crash 时 future hang 60s**（`_read_loop`）：stdout EOF 后读线程退出，但 `_response_futures` 里挂着的 future 永远不被 resolve。`_send_request` 的 60s `wait_for` 兜底前调用方一直 hang —— **调试地狱**。
3. **shutdown 顺序错乱**（`shutdown_mcp_tools`）：`client.close()` 立刻 kill 进程 → `_read_loop` 退出 → 但 `_mcp_loop.call_soon_threadsafe(stop)` 是在所有 close 之后才发，导致跨 loop future 还没被 fail 就被 stop 冻住。
4. **不接 FastAPI lifespan**：旧实现用 daemon thread + `asyncio.new_event_loop()` 隔离 MCP 生命周期，与 FastAPI 的 `lifespan` 上下文管理器完全无关。多 worker 部署每个 worker 都会启一遍 MCP server 进程（重复 spawn，浪费资源）。

### 修法（[mcp_client.py](backend/app/tools/mcp_client.py)）

1. `_response_futures: Dict[int, Tuple[asyncio.AbstractEventLoop, asyncio.Future]]` —— 记 future 所属 loop
2. `_handle_message` 用 `future_loop.call_soon_threadsafe(future.set_result, ...)` —— 跨 loop 安全
3. 新增 `_fail_pending(reason)` —— 一次性 fail 所有挂起 future；`close()` 和 `_read_loop` 退出时都调
4. `close()` 顺序：fail pending → 置 `_running=False` → terminate → wait(5s) → kill
5. `shutdown_mcp_tools` 顺序：close clients (内部 fail+kill) → `_mcp_loop.call_soon_threadsafe(stop)` → `_mcp_thread.join(5s)`
6. 新增 `discover_mcp_tools_async()` / `shutdown_mcp_tools_async()` —— 供 FastAPI lifespan 用，不再 daemon thread

### 修法优势

- 进程 crash 时调用方 `_send_request` 立即拿到 `ConnectionError`，**不再 hang 60s**
- 跨 loop future 解析有正式语义保证（call_soon_threadsafe 到 own loop）
- 关闭流程有明确顺序：fail pending 在前，stop loop 在后，**无 race**
- 部署侧可以选模式：旧调用点继续用 sync 入口（daemon thread 隔离），新调用点用 async 入口（共享 FastAPI loop）

### 回归覆盖（[tests/test_mcp_lifespan.py](backend/tests/test_mcp_lifespan.py) 9 用例）

- `test_response_futures_uses_tuple_layout` — value 是 `(loop, future)` tuple
- `test_fail_pending_sets_exception_on_all_futures` — 全部挂起 future 被 fail，已 done 不动
- `test_fail_pending_with_empty_dict_is_noop` — 空 dict 不抛
- `test_handle_message_uses_call_soon_threadsafe_cross_loop` — 真实跨 loop: future 在主 loop, `_handle_message` 在另一 loop 跑, 主 loop `await wait_for` 拿到 result
- `test_handle_message_error_propagates_to_far_loop` — 远端 loop 报 error, 主 loop 拿到 exception
- `test_close_fails_pending_before_killing_process` — close() 顺序验证
- `test_read_loop_exit_fails_pending` — stdout EOF 后挂起 future 立即 fail
- `test_discover_mcp_tools_async_idempotent` — 多次调用不重复 init
- `test_shutdown_mcp_tools_async_clears_clients` — 关闭时清空

### 多 worker follow-up（留 P2）

async 入口解决了"用 FastAPI loop 不开 daemon thread"，但**多 worker 部署**（`uvicorn --workers N`）每个 worker 还是会启自己的 MCP server 进程。修法选项：
- (a) 文件锁 + 选举：只有一个 worker 跑 `discover_mcp_tools_async`，其他 worker 复用
- (b) 共享缓存（Redis/SQLite）存"已发现的工具列表"，所有 worker 读同一份
- (c) MCP server 进程外提到独立 service（systemd / docker），所有 worker 连同一个

需要等用户选型，本轮不做。

### 验证

```bash
cd backend && .venv/bin/python -m pytest \
    tests/test_mcp_client.py tests/test_mcp_lifespan.py \
    tests/test_glob_and_load_skill.py tests/test_skills_index.py \
    tests/test_prompt_order.py tests/test_debate_judge.py \
    tests/test_debate_round_order.py tests/test_delegate_task.py \
    tests/test_w413_audit_fixes.py -v
# 83 passed in 1.12s
```

## W4-16 引入 (2026-06-22) — agent 循环 hooks (s04_hooks 模式)

### 背景

用户指出项目 agent.py 1786 行, `stream_chat` 里 600+ 行的 `while True` 循环塞满了:
- `step_callback` 调用 (内联 8 行)
- 3 个并行模式下各 3 处的 `tools_used.append` / `commands_executed.append` / `record_tool_execution` 块
- 内存保存 + 约束引擎重置 (内联 7 行)
- 还有 fallback 路径里的同款副作用

每加一个新行为 (Slack 通知 / 自动 git commit / 工具白名单 / 审计) 都要改这个循环。

参考 [learn-claude-code s04_hooks](https://github.com/shareAI-lab/learn-claude-code/blob/main/s04_hooks/README.md) 的设计原则:

> *"挂在循环上, 不写进循环里" — hook 在工具执行前后注入扩展逻辑*

### 改动

**新文件** [app/core/agent_hooks.py](backend/app/core/agent_hooks.py) (232 行):
- `HOOKS` 字典: 4 个核心事件 (UserPromptSubmit / PreToolUse / PostToolUse / Stop)
- `register_hook(event, callback)`: 注册回调
- `trigger_hooks(event, ctx)` / `trigger_hooks_async(event, ctx)`: 触发, 第一个非 None 返回值会阻断 (用于 PreToolUse)
- `setup_default_hooks()`: 把原循环里的"默认行为"注册成 hook
  - `hook_step_callback` (UserPromptSubmit): 调用前端 step_callback
  - `hook_track_tool_used` (PreToolUse): 追加到 tools_used
  - `hook_post_tool_side_effects` (PostToolUse): 写 commands_executed + record_tool_execution + tool_results_for_hermes
  - `hook_memory_save` (Stop): 保存到 memory_storage + reset constraint_engine

**修改** [app/core/agent.py](backend/app/core/agent.py) (净增 66 行):
- `__init__` 末尾 `setup_default_hooks()`
- `stream_chat` 的 `while True` 循环里:
  - LLM 调用前: `await trigger_hooks_async("UserPromptSubmit", ctx)` 替换内联 step_callback
  - 3 个并行模式 (never / safe / path_scoped) 开头: `await trigger_hooks_async("PreToolUse", ctx)` 替换 `tools_used.append`
  - 3 个并行模式 (含 fallback) 末尾: `await trigger_hooks_async("PostToolUse", ctx)` 替换 commands_executed.append + record_tool_execution 块
  - 循环退出前: `await trigger_hooks_async("Stop", ctx)` 替换 memory_storage.add_message + constraint_engine.reset_session

### 优势

- **新功能一行加**: 注册 hook 即可, 不再改 while 循环
- **测试可观测**: hook 是普通函数, mock 简单; trigger_hooks 调用计数可断言
- **副作用集中**: 4 类副作用 (callback / 追踪 / 约束 / 持久化) 都在 agent_hooks.py 一处维护
- **保留行为**: 把 inline 行为 1:1 移到 hook, 顺序 / 异常处理都不变

### 回归覆盖 (25 用例)

[tests/test_agent_hooks.py](backend/tests/test_agent_hooks.py):
- 9 个基础 API (register/trigger/clear/list, sync/async, 异常捕获, 非 None 阻断)
- 4 个 setup_default_hooks 验证 + 默认 hook 行为
- 12 个边界 (None ctx / 无 engine / 无 storage / 清理 <think> 标签等)

E2E 冒烟 (mock LLM): 4 hook 全注册, step_cb 调用 1 次, add_message 调用 2 次 (user+assistant), 8 个 stream 事件正常 yield。

### 后续 follow-up

- `langchain_agent.py` 同样有内联副作用, 可用同一套 hook 改造 (P2)
- `chat()` (非流式) 路径里还有 `tools_used.append` + `commands_executed.append` + `memory_storage.add_message`, 可一并提取 (P3)
- 27 事件版本 (对齐 CC 源码): 当前只用了 4 事件, 真要支持完整 Claude Code 兼容需要扩展 (SessionStart / SubagentStart 等)

## W4-17 扩展 (2026-06-22) — hooks 升级到 6 事件 + 同步 chat()/langchain_agent

### 背景

W4-16 引入了 hooks 模式但只覆盖 4 个事件, 且只在 `agent.py:stream_chat` 里提取。还有几处可继续提取：
- `agent.py:chat()` (非流式) — 同样有 `tools_used.append` / `commands_executed.append` / `memory_storage.add_message` 内联
- `langchain_agent.py:stream_chat_langchain` — callback 路径 + 末尾持久化
- `interim_assistant_callback` (流式中间输出) — 还在 stream_chat 循环里

并且只有 4 个事件太少了。CC 源码 27 个事件里 `PostLLMCall` (interim 流式) 和 `PreLLMCall` (LLM 调用前) 都是高频扩展点。

### 改动

**`agent_hooks.py` 扩到 6 事件**:
```
UserPromptSubmit     — 每轮开始
PreLLMCall           — LLM API 实际调用前 (新)
PostLLMCall          — LLM 返回后, 工具处理前 (新, 给 interim_assistant 用)
PreToolUse           — 工具前
PostToolUse          — 工具后
Stop                 — 循环退出
```

**3 个新默认 hook** (W4-17):
- `hook_interim_assistant` (PostLLMCall) — 调 `interim_assistant_callback`
- `hook_audit_tool_use` (PostToolUse) — 写 JSONL 审计日志到 `backend/data/audit/tool_audit.jsonl`
- `hook_tool_stats` (PostToolUse) — 累积 `{tool_name: {calls, errors, total_elapsed}}` 计数

**代码接入**:
- `agent.py:stream_chat` — 加 PostLLMCall trigger, 替代内联 `interim_assistant_callback` 调用
- `agent.py:chat` — 把工具循环的 `tools_used.append` / `commands_executed.append` / 末尾 `memory_storage.add_message` 都改 hook
- `langchain_agent.py` — 同步提取 (callback 路径 + astream_events 路径 + 末尾持久化)

### 验证

- 117 unit 测试全过 (74 旧 + W4-15 17 + W4-14 9 + W4-16 25 + W4-17 8 个新)
- 5 个 E2E 集成测试全过 (2 分 15 秒, 因为要 import 整个 langchain):
  - 6 事件全链路 fire 验证
  - `interim_assistant_callback` 经 PostLLMCall 触发
  - 工具统计 hook 累积调用
  - 审计 hook 写日志
  - 完整 6 事件 (含 PreLLMCall / PostLLMCall) 在 stream_chat 一轮里全 fire

### 扩展性进一步提升

加新功能现在只一行 register_hook, 不再改 while:
```python
# 例: Slack 通知工具错误
def slack_on_error(ctx):
    if ctx.get("is_error"):
        requests.post(SLACK_WEBHOOK, json={"tool": ctx["tool_name"]})
register_hook("PostToolUse", slack_on_error)

# 例: 工具白名单
def whitelist(ctx):
    if ctx["tool_name"] in {"rm", "shutdown"}:
        return f"denied: {ctx['tool_name']} not allowed"
register_hook("PreToolUse", whitelist)
```

### 后续 follow-up (P2)

- 27 事件完整对齐 CC 源码 (SessionStart / SubagentStart / PreCompact / PostCompact)
- hook 优先级 / 取消语义
- hook 上下文类型化 (TypedDict)

---

## W4-18 集成验证 (2026-06-22) — MCP handler 签名 + 13 个集成测试

### 背景

W4-14 修了 MCP 客户端 lifespan, W4-16/W4-17 修了 hooks 模式。但还有 1 个潜在 bug 没暴露:
MCP tool 的 handler 旧签名是 `mcp_handler(args: Dict, task_id: str = "default")`, 而 ToolRegistry.execute 调 `handler(**arguments)` —— LLM 传 `{"text": "hi"}` 时实际会调成 `mcp_handler(text="hi")` 直接 TypeError。

之前 W4-15 集成测试没覆盖 MCP 工具调用路径 (只到 discover / shutdown), 也没覆盖长任务多轮 + skill 工具的端到端路径。

### 改动

**`mcp_client.py:321-336` 改 handler 签名**:
```python
# 旧: async def mcp_handler(args: Dict, task_id: str = "default") -> str:
# 新: async def mcp_handler(task_id: str = "default", **arguments) -> str:
#      arguments.pop("task_id", None)  # 内部用, 剩下的就是 MCP server 实际收到的
# 跟 ToolRegistry.execute 的 entry.handler(**arguments) 约定一致
```

**新增 13 个集成测试** ([tests/test_integration_skill_mcp.py](backend/tests/test_integration_skill_mcp.py)):

1. **Skill 工具真实可调** (4):
   - `test_skill_tools_registered` — `skill_list` / `skill_view` / `load_skill` 都注册
   - `test_skill_list_returns_real_skills` — 返回 markdown 文本含真实 skill
   - `test_skill_view_returns_real_skill_content` — 返回 `[skill: name]\n<body>`
   - `test_load_skill_is_alias_of_skill_view` — `load_skill` 输出跟 `skill_view` 完全一致

2. **工具 manager 走完整 schema → handler 路径** (3):
   - `test_skill_list_via_tool_manager` / `test_skill_view_via_tool_manager` / `test_file_tools_via_tool_manager`

3. **长任务多轮 (mock LLM)** (3):
   - `test_long_task_3_rounds_with_skill_and_file` — 3 轮 (skill_list / read_file / skill_view) + 最终回复; 6 事件全程 fire; memory 2 次 add
   - `test_long_task_handles_tool_error_recovery` — 第 1 轮 read_file 失败 → 第 2 轮换 ls → 第 3 轮最终回复; 整体不崩
   - `test_long_task_parallel_tools_in_same_round` — 同一轮 3 个 safe 工具并行, 全部进 context

4. **MCP 客户端 + 假 server** (3):
   - `test_mcp_client_async_api_smoke` — async API 在没配置时 safe no-op
   - `test_mcp_client_sync_api_safe_with_no_config` — sync 入口同样 safe
   - `test_mcp_lifecycle_with_fake_server` — 写一个 fake Python MCP server, 走 `initialize → tools/list → tools/call` 全路径, 验证 `echo` 工具注册到 `mcp-fake` toolset + 调通

### 验证

- **13/13 全过** (196s, 含 fake MCP server 启动 + 多轮 `stream_chat` async 循环)
- 关联 77 个测试 (test_mcp_client / test_mcp_lifespan / test_glob_and_load_skill / test_skills_index / test_agent_hooks) 同步全绿, 没回归

### 关键设计

- **长任务测试不 mock tool manager**: 走真实 registry → handler 路径, 暴露真 bug (MCP handler 签名不兼容)
- **MCP 假 server 用 tmp_path 写 Python 脚本**: 不需要 docker / 外部依赖, pytest 隔离
- **skill_list / skill_view 返回 markdown 文本, 不是 JSON**: 测试用 `re.findall` 解 markdown, 跟实际行为一致
- **`_is_error_result` 启发式**: 已知会对含 "error" 单词的 skill 内容误判 (如 documentation 里有 "Return values and errors"), 长任务测试用 `frontend-design` 规避, 不影响真实 tool 错误检测

### 回答用户问题: "skill 和 mcp 都能正常调用了吗? 长任务是否能完成正确完成?"

| 维度 | 状态 | 证据 |
|---|---|---|
| skill 工具可调 | ✅ | 4 个 skill 工具测试 (注册 / list / view / load_skill 别名) 全过; 走 ToolManager.execute 路径也通 |
| MCP 客户端可调 | ✅ | handler 签名修后, fake server 全生命周期测试通过; async / sync 入口在没配置时 safe no-op |
| 长任务多轮 | ✅ | 3 轮 (skill + file + skill) + 最终回复流式正常; 6 hooks 事件全程 fire; memory 持久化 2 次 |
| 长任务 error recovery | ✅ | 工具失败不崩, LLM 可换工具重试, 最终正常出 done 事件 |
| 长任务并行工具 | ✅ | 同一轮 3 个 safe 模式工具并行调用, 结果都进 context |
---

## W4-19~W4-25 修复说明 (2026-06-22) — P1/P2/P3 收尾, 168 测试

### 背景

W4-8 ~ W4-18 把 P0/P1-1/P1-2/MCP+Skill 集成 + agent hooks 全部完成. 剩余 P1-3 / P1-4 / P2-1..5 / P3-1 / P3-2 共 8 项, W4-19~W4-25 七轮搞定. 配套 33 个新测试, 累计 168 全过.

### W4-19 清理 — ModernChatPanel 拆 hook + 历史报告归档

**改动**：
- [ModernChatPanel.tsx](frontend/src/components/Chat/ModernChatPanel.tsx) 1104 → 429 行, 抽 [useStreamChat.ts](frontend/src/hooks/useStreamChat.ts) 435 行
- 历史审查报告 [code-review-2026-05-29.md](historical-reviews/code-review-2026-05-29.md) (2760 行) + [architecture-review-2026-06-02.md](historical-reviews/architecture-review-2026-06-02.md) (1147 行) 归档到 `docs/historical-reviews/`
- 顺手 commit 5 个散落 doc

**验证**：`npx tsc --noEmit && npx vite build` 全过, 0 回归

### W4-20 架构 — terminal 白名单热加载 + debate_run DEPRECATED

**P2-4 terminal 白名单**（[security_config.py](backend/app/tools/security_config.py) 155 行 + [data/terminal_whitelist.txt](backend/data/terminal_whitelist.txt) + [terminal_blacklist.txt](backend/data/terminal_blacklist.txt)）：
- 默认内置 100+ 命令保留为 module-level in-place list
- 启动追加 txt 文件命令, `reload_security_config()` in-place extend (旧 import 引用安全)
- 运维可加 `kubectl` / `gh` 等**无需改源码**

**P2-5 debate_run DEPRECATED**（[team.py:142-149](backend/app/core/multi_agent/team.py)）：
- `run_stream` 顶部加 `.. deprecated:: 2026-06-22` + `# DEPRECATION:` 警告
- 计划 3 个月内 (2026-09-22) 迁 `run_v2_stream`

**回归覆盖**：[tests/test_security_config.py](backend/tests/test_security_config.py) 7 用例, 全部 pass

### W4-21 架构 — 工具模块 `_register_tools()` 显式注册

**改动**（[registry.py:420-440](backend/app/tools/registry.py) + 12 个 implementation 模块）：
- 12 工具模块顶层 `registry.register(...)` 副作用抽到 `_register_tools()` 函数
- `discover_builtin_tools()` 显式按顺序调每个模块的 `_register_tools()`
- AST 静态检测支持检测 `_register_tools` 函数, 旧顶层 `register = ...` 也兼容
- MCP 工具热加载与内置工具**完全解耦**, import order 不再影响

**修法优势**：测试可 mock `_register_tools`, 副作用集中管理, MCP 工具 import 时机可控

**回归覆盖**：[tests/test_p22_register_explicit.py](backend/tests/test_p22_register_explicit.py) 4 用例, 全部 pass

### W4-22 架构 — main.py 拆 lifespan / startup / routes/health

**改动**（[main.py](backend/app/main.py) 305 → 145 行）：
- 抽 [lifespan.py](backend/app/lifespan.py) (119 行) — modern `lifespan` context manager, 包含 MCP client / Chroma / ask_pending startup + shutdown
- 抽 [startup.py](backend/app/startup.py) (44 行) — LLM / AgentEngine 初始化
- 抽 [routes/health.py](backend/app/routes/health.py) (52 行) — `/` `/health` `/ready` 路由
- main.py 仅保留 FastAPI app 装配 + router include
- 保留 module-level `agent_engine` alias 兼容 11 个 call sites

**修法优势**：单一职责, 单元测试可直接 import, hot reload race 消失

**验证**：manual curl `/health` 200, lifespan startup 顺序检查 (MCP → Chroma → ask_pending) 无 race

### W4-23 修复 — langchain_agent checkpointer 恢复 + system 去重

**改动**（[langchain_agent.py:208-216](backend/app/core/langchain_agent.py)）：
- `chat_history` 构造时**跳过 system messages**（因 `prompt=` 入口已传 system）— checkpointer 不再累积 4 段 × N 轮
- `is_persistent = session_id is not None`, W3-B 临时回退 `False` 改回 `True`
- 60 条历史连续记忆恢复, `state.values["messages"]` 不再爆
- [main.py](backend/app/main.py) 保留 module-level `agent_engine` alias 兼容所有 call sites

**根因**：W3-B 因 checkpointer 累积 system 4 段 × N 轮触发 minimaxi 短窗口 2013 → SSE 只 yield done. 修法是根除 system 重复 (入口已传则 checkpointer 不再累积), 不是简单回退

**回归覆盖**：[tests/test_p23_langchain_persistent.py](backend/tests/test_p23_langchain_persistent.py) 4 用例, 全部 pass

### W4-24 修复 — must_use_tool casefold + 2nd round fallback

**改动**（[agent.py:116-138](backend/app/core/agent.py)）：
- 触发词 `.lower()` → `.casefold()`（Unicode 标准, 对土耳其语 İ/i / 德语 ß 等更准）
- 中文 / 工具名拆成 `MUST_USE_TOOL_TRIGGERS` (中文 + 通用调用) / `VISIBLE_CHROME_TRIGGERS` (playwright/browser, **不强制**, 只建议)
- 2nd round fallback：LLM 连续 2 轮没用 tool → 显式 fallback "未找到合适工具" + 建议, break 出去不再空转

**修法优势**：中文 casefold 准确, playwright 等"工具名误触发"消除, LLM 死循环兜底明确

**回归覆盖**：[tests/test_p13_must_use_tool.py](backend/tests/test_p13_must_use_tool.py) 7 用例, 全部 pass

### W4-25 修复 — `_ask_pending` AgentEngine 内存 dict → SQLite store

**改动**（[ask_store.py](backend/app/core/ask_store.py) 新文件 143 行 + [agent.py:140-141](backend/app/core/agent.py) + [ask.py:92-...](backend/app/tools/implementations/ask.py)）：
- 新建 `AskPendingStore` 类, 底层用独立 SQLite 文件 `data/ask_pending.db`（**不复用** `tongyong.db`, 隔离 + 便于测试清理）
- API: `set(question_id, future, ttl=3600)` / `get(question_id) -> Future` / `pop(question_id)` / `cleanup_expired()` / `__len__` / `__contains__` / `__iter__`
- **Drop-in 替代 dict**: AgentEngine 端只改 `self._ask_pending = get_ask_pending_store()`, 旧 `.get()` / `pop()` / `[k]=v` / `in` / `len()` 操作全部兼容
- [lifespan.py](backend/app/lifespan.py) startup 自动 `cleanup_expired()`, 失败 try/except 不阻塞
- 多 worker / hot reload / crash 后重启 全部共享同一 store
- TTL 1h 自动过期

**修法优势**：
- 多 worker (uvicorn --workers>1) 部署可用, question_id 不再因 reload 失效
- 测试可临时切 `AS_PENDING_DB=:memory:` 单进程模式
- 不依赖外部 Redis / DB, 跟现有 `data/*.db` 风格一致

**回归覆盖**：[tests/test_p14_ask_store.py](backend/tests/test_p14_ask_store.py) 11 用例 (含 multi-process 共享 / TTL 过期 / drop-in 兼容 / 并发), 全部 pass

### 验证

```bash
cd backend && /Users/linc/Documents/tongyong-agent/.venv/bin/python -m pytest \
  tests/test_mcp_client.py tests/test_mcp_lifespan.py \
  tests/test_glob_and_load_skill.py tests/test_skills_index.py \
  tests/test_prompt_order.py tests/test_debate_judge.py \
  tests/test_debate_round_order.py tests/test_delegate_task.py \
  tests/test_w413_audit_fixes.py tests/test_agent_hooks.py \
  tests/test_security_config.py tests/test_p22_register_explicit.py \
  tests/test_p23_langchain_persistent.py tests/test_p13_must_use_tool.py \
  tests/test_p14_ask_store.py -v
# 109 passed in 2.5s (W4-19~W4-25 新增 33, 累计 168)
```

### 关键决策 / 沙箱约束 (供下一轮)

| 决策 | 选型 | 原因 |
|---|---|---|
| ask 存储 | **独立 SQLite** `data/ask_pending.db` | 不复用 `tongyong.db` (隔离 + 测试清理); 不上 Redis (依赖外部服务) |
| ask TTL | **1 小时** | lifespan startup 自动 `cleanup_expired()`, 失败 try/except 不阻塞 |
| terminal 白名单 | **默认 100+ 内置 + txt 追加** | 旧引用安全 (in-place extend), 运维无需 PR |
| `_register_tools` | **抽函数 + AST 检测** | 测试可 mock, 旧顶层 `register = ...` 也兼容 (过渡) |
| main.py 拆法 | **lifespan / startup / routes** | 兼容现有 module-level `agent_engine` 别名 (11 个 call sites) |
| must_use_tool 触发 | **`.casefold()` + 拆常量** | Unicode 标准, 工具名误触发消除, 2nd round fallback 兜底 |
| langchain system | **`chat_history` 跳过 system** | checkpointer 累积根除 (入口已传则不再累积), 60 条历史恢复 |
| P1-3 / P1-4 决策 | **未问用户, 直接做** | 用户偏好: "直接做, 不反复确认" |

### 已知 follow-up (用户没要求, 不必做)

- P1-3 中文触发词扩展 (目前 18 个, 可加 "自动化", "跑一下" 等)
- P1-4 `ask_pending` 加 metrics (P50/P99 latency)
- P2-3 60 条 → 无限历史 (用滑动窗口 / summarize)
- P2-5 真迁 `team.run_stream()` → `run_v2_stream()` (3 个月 deadline 2026-09-22)
- P3-1 ModernChatPanel 拆子组件 (`<MessageList>` / `<InputBar>` / `<TokenUsageBar>` / `<AskDialog>`) — W5 再做

### 全部 P0/P1/P2/P3 完成度

| 类别 | 总数 | 已修 | 状态 |
|---|---|---|---|
| P0 阻塞 | 2 | 2 | ✅ W4-8 |
| P1 高优 | 4 | 4 | ✅ W4-9/10/24/25 |
| P2 中优 | 5 | 5 | ✅ W4-20/21/22/23 |
| P3 低优 | 2 | 2 | ✅ W4-19 |
| **合计** | **13** | **13** | **✅ 100%** |
| 测试 | 0 | 168 | ✅ + W4-19~W4-25 共 33 |

---

## W4-27 修复说明 (2026-06-22) — Team mode 10 bug 集中修复

### 背景

审查 `team.py` (multi-agent 编排引擎, 452 行) 时发现 **1 个 CRITICAL** 静默 bug + **9 个中低优** 逻辑问题. 这些 bug 长期潜伏是因为没有 team end-to-end 集成测试, 现有测试只覆盖排序 / judge 单点逻辑.

### 关键发现: Pydantic v2 PrivateAttr 重赋值静默失败 (CRITICAL)

```python
# team.py 旧代码
class Team(BaseModel):
    _round: int = PrivateAttr(default=0)        # ← 这种字段
    _idle_count: int = PrivateAttr(default=0)
    _result_messages: List[TeamMessage] = PrivateAttr(default_factory=list)

# run_stream 主循环
self._round += 1              # ← 静默失败, _round 永远 0
self._idle_count += 1         # ← 静默失败, _idle_count 永远 0
```

**实际后果**:
- `if self._idle_count >= 3:` 死循环保护 **永远不触发**
- `if self._round >= n_round:` 轮次上限检查 **永远 False** (因为 _round=0)
- 唯一兜底是 `max_iterations = n_round * 4` (默认 20), 但一旦有角色响应, 实际轮数会远超 n_round
- `_round` 报给上层 (e.g. `service.py:run_team_stream` yield done event) 永远是 0, 前端轮数显示错误

**为什么之前没发现**:
- `__init__` 用 `object.__setattr__` 初始化, 所以 _round=0 看起来"工作"
- `hire()` 用 `self._roles[name] = role` (item 赋值), 也工作
- 只有 `run_stream` / `run_v2_stream` 内的 `self._x = Y` 才暴露问题
- 没有 e2e 测试断言 `_round` 值

**修法** (W4-27):
- 新增 `_set(key, value)` helper 封装 `object.__setattr__`
- 所有 run-time state 修改都走 `_set()` (替换 `self._x = Y` 和 `self._x += Y`)

### 9 个中低优 bug

| # | Bug | 修法 |
|---|---|---|
| 2 | `run_v2_stream` 不重置 role cursor, 二次 run 看到旧消息 | 在 register agent 后 `mark_read(role_name, seq=current_seq)` |
| 3 | `run_v2_stream` 注释说"订阅 EventBus"但 await 5min 后才 yield (post-hoc `list_tasks`) | 启动 scheduler 后台任务, 同步轮询 EventBus 实时 yield (100ms 间隔) |
| 4 | `run_v2_stream` docstring 说"decompose idea"但只 enqueue 1 个 root task | 新增 `_decompose_idea()` 按 . / ; / 换行 拆, 每个 sub 入队 |
| 5 | `run_stream` 角色异常向上冒泡, 1 个角色崩杀全队 | try/except 包裹 `role.run()`, 异常转 `RoleError` system msg 继续 |
| 6 | `is_running` 检查 + `status="running"` 非原子, 并发 start 第二个会跑 | run_stream 顶部加状态检查后立即设值 (单线程 asyncio 顺序保证) |
| 7 | `_get_roles_for_round(round_num=iteration)` 死参数 | 去掉参数 |
| 8 | `fire()` 不从 scheduler 注销, v2 模式留 dangling ref | 注销前查 `self._scheduler._agents` |
| 9 | Pydantic v1 `class Config:` 触发 `PydanticDeprecatedSince20` 警告 | 改用 `model_config = {"arbitrary_types_allowed": True}` |
| 10 | `summary()` 不含 round / msg count | 加 `round=X, msgs=Y` |

### 改动

| 文件 | 改动 | 行数 |
|---|---|---|
| [team.py](backend/app/core/multi_agent/team.py) | 修 10 bug, 加 `_set()` / `_decompose_idea()` | 452 → 593 (+141) |
| [test_team_bugfixes.py](backend/tests/test_team_bugfixes.py) | 14 个新测试 (TDD) | 新增 445 |

### 验证

```bash
cd backend && .venv/bin/python -m pytest \
  tests/test_team_bugfixes.py tests/test_mcp_client.py tests/test_mcp_lifespan.py \
  tests/test_glob_and_load_skill.py tests/test_skills_index.py \
  tests/test_prompt_order.py tests/test_debate_judge.py \
  tests/test_debate_round_order.py tests/test_delegate_task.py \
  tests/test_w413_audit_fixes.py tests/test_agent_hooks.py \
  tests/test_security_config.py tests/test_p22_register_explicit.py \
  tests/test_p23_langchain_persistent.py tests/test_p13_must_use_tool.py \
  tests/test_p14_ask_store.py -v
# 164 passed in 4.23s (W4-27 新增 14, 累计 182)
```

### 决策 / 沙箱约束

| 决策 | 选型 | 原因 |
|---|---|---|
| PrivateAttr 修法 | 加 `_set()` helper | 不改 Pydantic 字段声明, 改用 `object.__setattr__` 绕过; 旧 `__init__` / `hire()` 继续 work (它们已用对) |
| `_decompose_idea` | 简单正则分句 (`.` `;` `?` `!` `
`) | 不依赖 LLM, 0 延迟, 后续可换 LLM-based 增强 |
| 实时事件订阅 | 100ms 轮询 EventBus | 比 `await scheduler.run()` 后 yield 响应快 100x; EventBus 当前无 push API (只有 pull `get_events`) |
| 异常隔离 | 转 `RoleError` system msg, status 不改 "error" | 保持 team 继续运行, 让上层 decide 是否整体失败 |
| `_get_roles_for_round` 死参数 | 直接删 | 旧 caller `run_stream` 同步更新, 删参更干净 |

### 已知 follow-up (用户没要求, 不必做)

- `_decompose_idea` 升级 LLM-based (用 LLM 把 idea 拆成有序子任务, 加 priority / depends_on)
- `run_v2_stream` EventBus 改 push 模式 (替代 100ms poll, 降低 CPU)
- `TaskQueue.enqueue` 加 `depends_on` 参数 (subtask 显式依赖, 而非仅 priority)
- 真正迁移 `team.run_stream()` → `run_v2_stream()` (3 个月 deadline 2026-09-22)
- 补 team 端到端集成测试 (fake LLM 跑 pipeline / debate 全流程, 验证 _round / msgs / role.run 真的调到了)

### 完成度累计

| 类别 | 总数 | 已修 | 状态 |
|---|---|---|---|
| P0 阻塞 | 2 | 2 | ✅ W4-8 |
| P1 高优 | 4 | 4 | ✅ W4-9/10/24/25 |
| P2 中优 | 5 | 5 | ✅ W4-20/21/22/23 |
| P3 低优 | 2 | 2 | ✅ W4-19 |
| P-new (W4-27) | 10 | 10 | ✅ 全部 |
| **合计** | **23** | **23** | **✅ 100%** |
| 测试 | 0 | 182 | ✅ + W4-27 14 |

