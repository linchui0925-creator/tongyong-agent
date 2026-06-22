# TongYong Agent 代码审查报告 — 2026-06-21

> 范围：`main` 分支 + 最近 30 天 commit（截至 `0431b29`）
> 方法：codegraph 索引（205 文件 / 3,791 节点 / 7,572 边）+ 重点文件精读 + 历史 commit 交叉验证
> 配套图谱：[docs/CODEGRAPH.md](CODEGRAPH.md) §4 风险台账
> 上一份审查：[architecture-review-2026-06-02.md](architecture-review-2026-06-02.md)（装配层 5 处问题，部分未执行）

---

## 摘要

> W4-8 修复 (2026-06-21): 两个 P0 已修，配套回归测试 15 个全绿 (test_prompt_order.py 8 + test_debate_judge.py 7)。详见末尾「W4-8 修复说明」节。
> W4-9/W4-10 修复 (2026-06-21): P1-1 delegate_depth ContextVar / P1-2 debate position 排序 已修, 配套回归测试 17 个全绿 (test_debate_round_order.py 8 + test_delegate_task.py 末尾 4)。详见末尾「W4-9/W4-10 修复说明」节。

| 项 | 修复前 | 当前 |
|---|---|---|
| 🔴 P0 阻塞类 | 2 | 0 |
| 🟠 P1 高优 | 4 | 2 (P1-1/P1-2 ✅) |
| 🟡 P2 中优 | 5 | 5 |
| 🟢 P3 低优 | 2 | 2 |
| ✅ 回归测试 | 0 (辩论零覆盖) | 32 (P0 15 + P1-2 8 + P1-1 9) |

最近 30 天 W1–W4 切流量 + langchain 集成把"行为正确性"拉到位了。W4-8 (2026-06-21) 修了 2 个 P0, W4-9/W4-10 又推进 2 个 P1, 还剩 P1 (must_use_tool / _ask_pending) / P2 / P3 共 9 项待办。

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
- 上次 [commit 510bff1](代码审查报告与修复方案.md) 已修 DebateSpeechAction（`role.debate_side or "正方" in name`），但 **DebateJudgeAction 完全没动**，依然是字符串匹配
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

**问题**（[commit 510bff1](代码审查报告与修复方案.md) 已知遗留）：
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

### P1-3 `must_use_tool` 触发词对中文 `.lower()` 无效

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

**问题**：
- `"请使用".lower() == "请使用"`（Python str.lower 对非字母字符无影响）
- 但 `text = (user_text or "").lower()` 对中文 message 也是恒等
- **实际**这部分对中文 trigger 是 OK 的（语义对得上）
- **真正问题**：函数名暗示"必须使用工具"，但 trigger 列表里有 `"playwright" / "browser"`，用户写"我想用浏览器"也会触发强制工具流程 → 在没有 playwright 环境的 LXC 上必失败
- 且 `must_use_tool` 路径一旦触发，没有 fallback（`chat()` 失败后直接 `response = "智能体已收到消息"`），UX 劣化

**建议修法**：
- 区分"用户显式指定工具"（playwright/browser）与"用户要 agent 行为"（"请使用工具"）
- 加 fallback：如果 `must_use_tool` 触发但工具执行失败，自动降级到普通 LLM 调用

---

### P1-4 `ask` 工具 `_ask_pending` 是 AgentEngine 实例属性

**位置**：[agent.py:117-119](backend/app/core/agent.py)，[ask.py:84-122](backend/app/tools/implementations/ask.py)

**问题**：
- 进程内单例，多 worker 部署（`uvicorn --workers 4`）会丢问题
- 即便单 worker，agent_engine 重新初始化（main.py hot reload）也丢
- 已知遗留，[W4-PROOF 验证日志](代码审查报告与修复方案.md) 多次提示 question_id 失效

**建议修法**：
- 短期：把 `_ask_pending` 提到 module-level + 加 thread-safe
- 中期：写 SQLite / Redis（与 session 持久化保持一致）

---

## 🟡 P2 — 1 月内修

### P2-1 main.py 6 职责 / 303 行（[architecture-review-2026-06-02.md](architecture-review-2026-06-02.md) P1）

未执行。**风险**：hot reload 时 `agent_engine` / `_llm_mgr` 重新构造竞态；`hermes_routes.x = ...` 模式不易测试。

### P2-2 工具模块顶层 `registry.register(...)` 副作用（同上 P3）

未执行。**风险**：测试时 import order 影响；MCP 工具热加载时与内置工具一起被 import。

### P2-3 langchain 路径 is_persistent=False 是临时回退

**位置**：[langchain_agent.py:220-227](backend/app/core/langchain_agent.py)
**根因**（W3-B 注释）：checkpointer 把 4 段 system prompt × N 轮累积，触发 minimaxi 短窗口 2013 → SSE 只 yield done
**当前状态**：丢失 60 条历史的连续记忆
**正确修法**：
- checkpointer 用 message 摘要而非全量
- 或在 astream 入口把 input.messages 去重（vs state.values）
- 或 session_id-based 压缩阈值

### P2-4 `terminal` 白名单硬编码

**位置**：[security_config.py](backend/app/tools/security_config.py) `_ALLOWED_COMMANDS`
**问题**：新增命令（如 `kubectl` / `gh`）需改源码 + 重启
**建议**：从 `data/terminal_whitelist.txt` 读，热加载

### P2-5 debate_run 用 round 轮次 vs run_v2_stream 全事件驱动并存

**位置**：[team.py:129-280](backend/app/core/multi_agent/team.py) `run_stream` 与 [team.py:282-385](backend/app/core/multi_agent/team.py) `run_v2_stream`
**问题**：两套并存，无明确弃用计划
**建议**：在 `team.py` 顶部加 `DEPRECATION` 注释，3 个月内迁移完成

---

## 🟢 P3 — 后续清理

### P3-1 `ModernChatPanel.tsx` 1104 行

`frontend/src/components/Chat/ModernChatPanel.tsx` 已是 god component。**建议**：
- 拆 `<MessageList>` / `<InputBar>` / `<TokenUsageBar>` / `<AskDialog>` 子组件
- 拆 hooks：`useStreamChat` / `useTokenUsage` / `useContextStats`

### P3-2 `代码审查报告与修复方案.md` 2760 行历史报告未归档

单文件过长，建议拆章节或转 `docs/historical-reviews/`。

---

## 修复路线图（建议）

```
本周（必须）
  └─ ~~P0-1 / P0-2 修复 + 加回归测试~~  ✅ W4-8 已完成

下周
  ├─ ~~P1-1 delegate_depth ContextVar~~  ✅ W4-10
  ├─ ~~P1-2 debate position 排序~~  ✅ W4-9
  └─ P1-3 must_use_tool fallback

月内
  └─ P2-1..P2-5 按 architecture-review 推进
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

- **P1-3** `must_use_tool` 触发词对工具名 (`playwright`/`browser`) 不应触发强制工具流程；触发后无 fallback，需要先和用户对齐 UX 降级策略
- **P1-4** `_ask_pending` 改 SQLite/Redis（多 worker 共享），需要先和用户对齐存储选型
