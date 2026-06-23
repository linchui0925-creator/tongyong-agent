# Architecture Review & Refactor Plan — 2026-06-02

> 审查范围：tongyong-agent 后端的"模块注册 / 启动装配 / 跨模块耦合"
> 审查者：linc + Hermes（self-review）
> 触发事件：5/28 multi_agent 重构完成后，审视更大一层（runtime / 装配）耦合度
> 状态：**Plan, not yet executed**（等 linc 确认 scope）

---

## 0. TL;DR

5 处屎山集中在**装配层**（main.py + import-time 副作用 + 跨模块 monkey-patch），
不影响业务逻辑（agent / multi_agent / dreaming / IM / LLM 都各自分明）。
**4 个 Phase 渐进重构**，每 Phase 独立可验证、可回滚。
**建议执行顺序：P1 → P2 → P3 → P4**（风险递增）。
**可以只做 P1 停下来**而不破坏后续。

### 5 处屎山速览

| # | 位置 | 性质 | 风险 |
|---|---|---|---|
| 1 | `main.py` L9-26, 56-67, 132-137, 145, 194-268 | 303 行单文件，6 职责 | 中 |
| 2 | `app/tools/implementations/*.py` 顶层 `registry.register(...)` | import-time 副作用 | 高 |
| 3 | `main.py` L132-137 等 4 处 `hermes_routes.x = ...` 模式 | 跨模块 monkey-patch | 中 |
| 4 | `env_capabilities.py` L104-106 在读 system prompt 时偷偷 `discover_builtin_tools()` | 隐式副作用 | 中 |
| 5 | `generate_tools_md()` 启动时写 `domains/tools/tools.md` | 运行期状态→源码位置 | 低 |

### 4 Phase 总览

| Phase | 范围 | 估时 | 风险 | 业务代码改动 | 可独立停 |
|---|---|---|---|---|---|
| **P1** | main.py 拆为 lifespan + 工厂函数 | 2-3h | 低 | 0 | ✅ |
| **P2** | 引入 `app/runtime.py` 显式 hook 协议 | 3-4h | 中 | 0 | ✅ |
| **P3** | 工具自注册改"声明+显式注册"两步 | 4-6h | 高 | 0（仅注册路径） | ✅ |
| **P4** | 干掉 `tools.md` 写盘，agent 改走 runtime API | 2-3h | 中 | 仅 agent 读 tools.md 那处 | ✅ |

---

## 1. 当前架构（事实层，2026-06-02 摸排）

### 1.1 模块清单（按职责）

```
backend/app/
├── main.py                  # 303 行，6 职责（route 装配 / agent factory / LLM 注入 / Hermes 注入 / IM 启停 / health）
├── api/                     # 16 个 router
│   ├── chat.py / memory.py / chart.py / llm.py
│   ├── evaluation.py / dreaming.py / skills.py
│   ├── marketplace.py / tool_harness.py / stream.py
│   └── im_gateway.py
├── core/
│   ├── agent.py             # AgentEngine（含工具调用循环）
│   ├── system_prompt.py     # base + capability + skills 拼装（5/28 修过，2026-06-02 进一步修）
│   ├── skills_index.py      # skills 索引（auto_load=true 的全量塞 system prompt）
│   ├── env_capabilities.py  # 环境检测 + 工具集索引生成
│   ├── marketplace.py       # 25KB，skill marketplace
│   ├── multi_agent/         # 5/28 重构过的 v2 多 agent 子树
│   └── ...
├── tools/
│   ├── registry.py          # ToolRegistry 单例
│   ├── manager.py           # ToolManager
│   ├── mcp_client.py        # MCP 动态发现
│   ├── permission.py / security_config.py / approval.py / audit.py
│   └── implementations/     # 14 个内置工具文件，每个模块级 registry.register(...)
│       ├── terminal.py / file_tools.py / grep_tool.py / ls_tool.py
│       ├── browser.py / cdp.py / web_tools.py
│       ├── delegate_task.py / desktop.py / adb.py
│       ├── ask.py / skill_tools.py
│       └── _module_registers_tools() AST 预检
├── memory/
│   ├── storage.py           # SQLite MemoryStorage
│   └── vector.py            # ChromaDB VectorStore
├── hermes/                  # 平文件层（独立于 SQLite/向量库）
│   ├── memory_file.py / skill_file.py / constraint.py
│   ├── nudge.py             # 后台反思引擎
│   └── routes.py            # router 内部用模块级 memory_manager / skill_manager
├── llm/                     # 11 个 LLM provider（已模块化良好）
├── domains/                 # 领域层（部分 system prompt 来源）
├── gateway/                 # IM Gateway（飞书/企微/微信，3 adapter）
│   ├── im/manager.py        # IMGatewayManager 单例
│   └── openai_api.py / profile_router.py / desktop_bridge.py
└── services/llm_manager.py  # LLM 切换 + bind_agent_engine
```

### 1.2 启动时序（实际跑出来的）

```
进程加载
  ↓
[1] main.py 顶层 import
    - from app.api import ...         ← 16 个 router import chain
    - 这些 router 内部 import 触达 app/tools/implementations/*.py
    - 每个 implementation 文件**模块级**调 registry.register(...)
    - 此时 registry 已有 N 个工具
  ↓
[2] main.py 顶层手动拼装（L51-68）
    - agent_engine = AgentEngine(llm=None)
    - _llm_mgr = get_llm_manager(); _llm_mgr.bind_agent_engine(agent_engine)
    - 试恢复 saved provider / 失败则 _seed_initial_llm
  ↓
[3] main.py L132-137 手动注入（monkey-patch）
    - hermes_routes.memory_manager = MemoryFileManager(...)
    - hermes_routes.skill_manager = SkillFileManager(...)
    - skills_api.init(hermes_routes.skill_manager)
  ↓
[4] FastAPI middleware / router 注册
  ↓
[5] @app.on_event("startup") L194-268
    - discover_builtin_tools()        ← 显式二次保险（import-time 副作用不可靠）
    - generate_tools_md()             ← 写 domains/tools/tools.md
    - discover_mcp_tools() (try)
    - DB 连接验证 / LLM 连接验证
    - IM Gateway 启动（飞书配置注入 + start_all）
  ↓
[6] 接收请求
  ↓
[7] @app.on_event("shutdown")
    - stop_all() IM Gateway
    - 清理资源（仅 log，无实际清理）
```

### 1.3 关键证据

#### 屎山 #1：main.py 6 职责

文件长度 303 行。具体职责分布：
- L9-26：16 个 router import
- L43-49：FastAPI app 构造
- L51-68：AgentEngine + LLMManager 手动拼装
- L70-77：CORS 中间件
- L80-102：请求日志中间件
- L104-125：16 个 router include
- L127-129：OpenAI-gateway init
- L131-137：Hermes manager 注入（**monkey-patch**）
- L140-145：get_agent_engine() / app.extra
- L148-191：root / health / ready 端点
- L194-268：startup event（DB 验证 + LLM 验证 + IM 启停 + discover_builtin_tools）
- L271-287：shutdown event
- L291-303：全局异常处理器

**问题**：单文件 14+ 职责。无单元测试。无 integration test 覆盖 main.py（tests/ 下找不到 test_main / test_runtime）。

#### 屎山 #2：import-time 自注册副作用

**证据 1**：模块级直接调
```python
# app/tools/implementations/terminal.py L133
registry.register(name="terminal", toolset="terminal", schema=..., handler=terminal_handler, ...)
```

**证据 2**：为了"安全" import，`discover_builtin_tools()` 用 AST 预检
```python
# app/tools/registry.py（discover_builtin_tools 内）
def _module_registers_tools(py_file) -> bool:
    # AST parse + 查找 registry.register 调用
    ...
if not _module_registers_tools(py_file):
    continue
mod_name = f"app.tools.implementations.{py_file.stem}"
importlib.import_module(mod_name)
```

**证据 3**：import-time 副作用导致 startup 必须二次保险
```python
# main.py L201-205
discover_builtin_tools()    # ← import-time 已注册过，这里再扫一次
generate_tools_md()
```

**证据 4**：测试隔离零
- tests/test_delegate_task.py 用了 `from app.tools.registry import registry`
- 一旦 import chain 拉到 implementations/*.py，registry 单例就被污染
- 没有任何 fixture 在 test 前清空 registry

#### 屎山 #3：跨模块 monkey-patch 链

至少 4 处：
```python
# main.py L132-137
import app.hermes.routes as hermes_routes
hermes_routes.memory_manager = MemoryFileManager(base_dir="./data/hermes")  # ← 模块级 mutable
hermes_routes.skill_manager = SkillFileManager(base_dir="./data/hermes")
skills_api.init(hermes_routes.skill_manager)

# app/gateway/im/manager.py L173-176
def inject_agent_engine(engine: Any) -> None:
    """main.py lifespan 里调用一次"""
    # 同样模式

# main.py L57-58
_llm_mgr.bind_agent_engine(agent_engine)  # 这算"正常依赖注入"
```

**问题**：`hermes.routes` 模块把 `memory_manager` / `skill_manager` 暴露为模块级 mutable 单例，
等 main 帮它赋值。**路由本身应该自己 init 或通过 FastAPI Depends 注入**。

#### 屎山 #4：env_capabilities 偷偷 discover

```python
# app/core/env_capabilities.py L104-106（在 generate_capability_prompt() 内）
from app.tools.registry import registry, discover_builtin_tools
discover_builtin_tools()   # ← 读 system prompt 时偷偷扫盘 + import
toolsets = registry.get_available_toolsets()
```

**问题**：调 `get_system_prompt()` 会触发工具发现——意味着 system_prompt 路径不是纯函数。
我们 6/2 刚修的 `_inject_base_system_prompt` 间接受这个影响。

#### 屎山 #5：tools.md 写盘

```python
# main.py L201-205
discover_builtin_tools()
generate_tools_md()  # 写 backend/app/domains/tools/tools.md
```

**问题**：
- `domains/tools/tools.md` 位置在 `app/domains/` 下，跟"领域定义"混淆
- 运行期状态写到**源码树**里，违反 12-factor
- agent 用 `read_file('domains/tools/tools.md')` 读——这是个**笨办法**，应该走 runtime API

---

## 2. Phase 1：main.py 拆为 lifespan + 工厂函数

### 2.1 目标

把 main.py 从 303 行缩到 ~80 行。**纯重构，不改业务**。

### 2.2 改动范围

#### 2.2.1 新建 `app/bootstrap.py`

把所有"启动装配逻辑"抽到 `app/bootstrap.py`：

```python
# app/bootstrap.py（计划新增，约 150 行）
"""
bootstrap - 应用启动装配

替代 main.py 里散落的 LLM 注入 / Hermes 注入 / IM 启停。
提供 build_agent_engine() / configure_hermes() / configure_im_gateway() / lifespan()
四个纯函数，供 main.py lifespan 调用。
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

logger = logging.getLogger(__name__)


def build_agent_engine():
    """构造 + 注入 LLM 的 AgentEngine（替代 main.py L51-68）"""
    from app.core.agent import AgentEngine
    from app.services.llm_manager import get_llm_manager
    from app.config import settings
    from app.llm.factory import get_llm

    engine = AgentEngine(llm=None)
    logger.info("AgentEngine 初始化完成")

    mgr = get_llm_manager()
    mgr.bind_agent_engine(engine)

    if not mgr.try_restore_saved_provider():
        llm_instance = get_llm()
        logger.info(f"LLM 初始化成功: {type(llm_instance).__name__}")
        mgr._seed_initial_llm(llm_instance, settings.default_llm_provider)
    if engine.llm is None:
        mgr._sync_to_agent()
    return engine


def configure_hermes():
    """构造 Hermes manager 并显式注入到所有依赖方（替代 main.py L131-137）"""
    from app.hermes import MemoryFileManager, SkillFileManager
    from app.api import skills as skills_api
    import app.hermes.routes as hermes_routes

    memory_manager = MemoryFileManager(base_dir="./data/hermes")
    skill_manager = SkillFileManager(base_dir="./data/hermes")
    hermes_routes.memory_manager = memory_manager
    hermes_routes.skill_manager = skill_manager
    skills_api.init(skill_manager)
    return memory_manager, skill_manager


async def configure_im_gateway(engine):
    """启动 IM Gateway（替代 main.py L229-264）"""
    try:
        from app.gateway.im import (
            im_gateway_manager, inject_agent_engine,
            IMPlatform, IMPlatformConfig,
        )
        from app.config import settings

        inject_agent_engine(engine)
        if getattr(settings, "feishu_app_id", "") and getattr(settings, "feishu_app_secret", ""):
            im_gateway_manager.set_platform_config(
                IMPlatform.FEISHU,
                IMPlatformConfig(...)
            )
        results = await im_gateway_manager.start_all()
        if results:
            logger.info(f"IM Gateway 启动结果: {results}")
    except Exception as e:
        logger.error(f"IM Gateway 启动失败: {e}", exc_info=True)


async def verify_db_and_llm(engine):
    """替代 main.py L214-227"""
    try:
        sessions = await engine.get_sessions()
        logger.info(f"数据库连接成功，当前会话数: {len(sessions)}")
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
    if engine.llm:
        try:
            ok = await engine.llm.initialize()
            logger.info(f"LLM 连接验证: {'成功' if ok else '失败'}")
        except Exception as e:
            logger.error(f"LLM 连接验证失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan（替代 @app.on_event("startup"/"shutdown")）"""
    from app.tools import discover_builtin_tools
    from app.tools.registry import generate_tools_md

    logger.info("=" * 50)
    logger.info(f"{app.title} 启动中...")
    logger.info("=" * 50)

    # [1] AgentEngine + LLM
    engine = build_agent_engine()
    app.state.agent_engine = engine

    # [2] Hermes 注入
    configure_hermes()

    # [3] Tools 显式注册
    discover_builtin_tools()
    generate_tools_md()
    try:
        from app.tools.mcp_client import discover_mcp_tools
        discover_mcp_tools()
    except Exception as e:
        logger.warning(f"MCP 工具发现失败: {e}")

    # [4] DB / LLM 验证
    await verify_db_and_llm(engine)

    # [5] IM Gateway
    await configure_im_gateway(engine)

    logger.info("=" * 50)
    logger.info("应用启动完成")
    logger.info("=" * 50)

    yield  # ── app 运行中 ──

    # ── shutdown ──
    try:
        from app.gateway.im import im_gateway_manager
        await im_gateway_manager.stop_all()
    except Exception as e:
        logger.error(f"IM Gateway 关闭异常: {e}")
    logger.info("应用已关闭")
```

#### 2.2.2 重写 `app/main.py`（从 303 行缩到 ~80 行）

```python
# app/main.py（重构后约 80 行）
"""
TongYong Agent 主应用入口

装配层薄壳：FastAPI app 构造 + lifespan 委托给 app.bootstrap。
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import time

from app.config import settings
from app.api import chat, memory, chart, llm
from app.api import evaluation, dreaming as dreaming_api
from app.api import skills as skills_api, marketplace as marketplace_api
from app.api import tool_harness as tool_harness_api
from app.api.stream import router as stream_router
from app.core.multi_agent.api import router as team_router
from app.hermes.routes import router as hermes_router
from app.gateway import openai_router
from app.gateway.config import GatewaySettings
from app.gateway.openai_api import init_gateway as init_gateway_api
from app.gateway.desktop_bridge import router as desktop_bridge_router
from app.api.gateway_profiles import router as profile_router
from app.gateway.profile_router import router as profile_gateway_router
from app.bootstrap import lifespan

logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# FastAPI app + lifespan（一次性委托）
app = FastAPI(
    title=settings.app_name,
    description="通用智能体 API",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174",
                   "http://localhost:3000", "http://127.0.0.1:5173",
                   "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time"] = str(time.time() - start)
    return response

# OpenAI 兼容网关 init
init_gateway_api(GatewaySettings())

# Router 批量注册
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(chart.router, prefix="/api/chart", tags=["chart"])
app.include_router(llm.router, prefix="/api/llm", tags=["llm"])
app.include_router(hermes_router)
app.include_router(dreaming_api.router)
app.include_router(skills_api.router)
app.include_router(marketplace_api.router)
app.include_router(tool_harness_api.router)
app.include_router(stream_router, prefix="/api/chat")
try:
    from app.api.im_gateway import router as im_gateway_router
    app.include_router(im_gateway_router)
except ImportError:
    pass
app.include_router(openai_router, prefix="/v1")
app.include_router(desktop_bridge_router)
app.include_router(profile_router)
app.include_router(profile_gateway_router)
app.include_router(evaluation.router)
app.include_router(team_router, tags=["team"])


def get_agent_engine():
    return app.state.agent_engine


# Health 端点（保留简单版）
@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.app_name}", "version": "1.0.0"}

@app.get("/health")
async def health():
    engine = app.state.agent_engine
    return {
        "status": "ok",
        "llm": {"status": "initialized" if engine.llm else "unavailable"},
        "memory": {"sessions": len(await engine.get_sessions()) if engine.memory_storage else 0},
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "path": str(request.url.path)},
    )
```

### 2.3 改动文件

| 文件 | 操作 | 行数变化 |
|---|---|---|
| `app/bootstrap.py` | 新建 | +180 |
| `app/main.py` | 重写 | -220 |
| `app/gateway/im/manager.py` | 不动 | 0（已有 `inject_agent_engine()` 复用） |

**业务代码改动：0**（仅装配层）

### 2.4 Verify（独立可验证）

```bash
# [V1.1] AST 解析
python -c "import ast; ast.parse(open('app/main.py').read()); ast.parse(open('app/bootstrap.py').read()); print('AST OK')"

# [V1.2] Import 链路
cd backend && python -c "from app.main import app; from app.bootstrap import lifespan; print('import OK')"

# [V1.3] 起 uvicorn，看 startup 日志包含 5 个标记
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info 2>&1 | grep -E "启动中|启动完成|IM Gateway|MCP|AgentEngine|Hermes" | head -20
# 期望看到：
#   "启动中..."
#   "AgentEngine 初始化完成"
#   "应用启动完成"
#   "IM Gateway 启动结果" 或 "IM Gateway 启动失败"（都不算错）

# [V1.4] health 端点
curl -s http://127.0.0.1:8000/health | python -m json.tool
# 期望：{"status": "ok", "llm": {...}, "memory": {...}}

# [V1.5] 回归 chat 路径
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "ping", "use_memory": false}' | python -m json.tool
# 期望：{"reply": "...", "session_id": "..."}

# [V1.6] 现有测试
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
# 期望：4 个测试文件全过（test_phase1/phase2/test_delegate_task/test_runtime_compat）
```

### 2.5 回滚方案

```bash
git diff app/main.py
git checkout app/main.py
rm app/bootstrap.py
# 业务代码 0 改动，回滚 = 删除 bootstrap.py + revert main.py
```

### 2.6 不动的东西（强 scope）

- 所有 router / agent / multi_agent / dreaming / IM / LLM provider
- tools/ registry / manager / implementations/*（P3 才动）
- env_capabilities.py（P2 才动）
- generate_tools_md() 写盘逻辑（P4 才动）
- 测试文件

---

## 3. Phase 2：引入 `app/runtime.py` 显式 hook 协议

### 3.1 目标

把"跨模块 monkey-patch 链"重构成**显式 hook 协议**。任何模块想"注入到别的模块"，
必须走 `runtime.register_hook(target, attr, value)` 协议，可追溯、可 mock。

### 3.2 改动范围

#### 3.2.1 新建 `app/runtime.py`

```python
# app/runtime.py（约 100 行）
"""
runtime - 全局 hook 注册表

替代 main.py / bootstrap.py 里的散落 monkey-patch：
- hermes_routes.memory_manager = ...
- skills_api.init(...)
- inject_agent_engine(engine)

改为显式 hook 协议：
- hook target 在自己模块里调 runtime.register("hermes.routes", "memory_manager", value)
- main.py / bootstrap.py 不再需要知道"谁需要什么"

好处：
- 依赖可追溯（runtime._hooks dict 一目了然）
- 测试可注入 mock
- 循环引用风险降低
"""
import logging
import threading
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


class RuntimeRegistry:
    def __init__(self):
        self._hooks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register(self, target: str, attr: str, value: Any) -> None:
        """显式 hook：把 value 注入到 target 模块的 attr 字段"""
        with self._lock:
            if target not in self._hooks:
                self._hooks[target] = {}
            self._hooks[target][attr] = value
            logger.info(f"[runtime] hook {target}.{attr} <- {type(value).__name__}")

    def apply(self, target_module, target_name: str = None) -> int:
        """把已注册的 hooks 应用到 target_module 对象/模块"""
        target_name = target_name or getattr(target_module, "__name__", str(target_module))
        hooks = self._hooks.get(target_name, {})
        applied = 0
        for attr, value in hooks.items():
            if hasattr(target_module, attr):
                setattr(target_module, attr, value)
                applied += 1
        if applied:
            logger.info(f"[runtime] applied {applied} hooks to {target_name}")
        return applied

    def get(self, target: str, attr: str, default=None) -> Any:
        return self._hooks.get(target, {}).get(attr, default)

    def list_hooks(self) -> Dict[str, Dict[str, Any]]:
        return {k: {kk: type(v).__name__ for kk, v in v.items()} for k, v in self._hooks.items()}


# 全局单例
runtime = RuntimeRegistry()
```

#### 3.2.2 改 4 个 monkey-patch 点为 hook 协议

**改动 A**：`hermes/routes.py` 暴露 `apply_hooks(runtime)`
```python
# app/hermes/routes.py 末尾新增
def apply_hooks(rt: "RuntimeRegistry") -> None:
    """应用外部 hook 到本模块的模块级 manager 字段"""
    rt.apply(sys.modules[__name__], "app.hermes.routes")
```

**改动 B**：`api/skills.py` 暴露 `apply_hooks(runtime)`
```python
# app/api/skills.py 末尾新增
def apply_hooks(rt: "RuntimeRegistry") -> None:
    """skill_manager 由外部 hook 注入"""
    mgr = rt.get("app.hermes.routes", "skill_manager")
    if mgr:
        init(mgr)
```

**改动 C**：`bootstrap.configure_hermes()` 改为注册 hook
```python
# app/bootstrap.py（重构）
def configure_hermes():
    from app.runtime import runtime
    from app.hermes import MemoryFileManager, SkillFileManager
    from app.hermes import routes as hermes_routes
    from app.api import skills as skills_api

    memory_manager = MemoryFileManager(base_dir="./data/hermes")
    skill_manager = SkillFileManager(base_dir="./data/hermes")

    # 显式 hook：目标模块 + 属性 + 值
    runtime.register("app.hermes.routes", "memory_manager", memory_manager)
    runtime.register("app.hermes.routes", "skill_manager", skill_manager)
    runtime.register("app.api.skills", "skill_manager", skill_manager)

    # 应用到实际模块对象
    hermes_routes.apply_hooks(runtime)
    skills_api.apply_hooks(runtime)
    return memory_manager, skill_manager
```

**改动 D**：IM gateway 的 `inject_agent_engine` 改为 hook
```python
# app/gateway/im/manager.py（保持现有 inject_agent_engine 不变，标记为"已通过 hook 协议"）
# 或：把 inject_agent_engine 内部改为 runtime.register("app.gateway.im", "agent_engine", engine)
# 然后 IM adapter 通过 rt.get("app.gateway.im", "agent_engine") 拿
```

### 3.3 改动文件

| 文件 | 操作 |
|---|---|
| `app/runtime.py` | 新建（+100 行） |
| `app/bootstrap.py` | 改 `configure_hermes()`（+5 / -3） |
| `app/hermes/routes.py` | 加 `apply_hooks()`（+5 行） |
| `app/api/skills.py` | 加 `apply_hooks()`（+5 行） |
| `app/gateway/im/manager.py` | 可选：把 `inject_agent_engine` 改成 hook（+5 / -3） |

### 3.4 Verify

```bash
# [V2.1] import 验证
cd backend && python -c "
from app.runtime import runtime
print('hooks:', runtime.list_hooks())
# 期望：{} (未注册时为空)
"

# [V2.2] 起 uvicorn，看 [runtime] hook 日志
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info 2>&1 | grep -E "runtime.*hook|runtime.*applied" | head -10
# 期望：3-4 条
#   [runtime] hook app.hermes.routes.memory_manager <- MemoryFileManager
#   [runtime] hook app.hermes.routes.skill_manager <- SkillFileManager
#   [runtime] hook app.api.skills.skill_manager <- SkillFileManager
#   [runtime] applied 2 hooks to app.hermes.routes

# [V2.3] 跑现有测试
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -15

# [V2.4] Hermes API 端点
curl -s http://127.0.0.1:8000/api/hermes/memory 2>&1 | head -5
# 期望：返回正常 JSON（说明 memory_manager 注入成功）

# [V2.5] /api/skills 端点
curl -s http://127.0.0.1:8000/api/skills 2>&1 | head -5
# 期望：返回正常 JSON（说明 skill_manager 注入成功）
```

### 3.5 回滚方案

```bash
# runtime.py 是新增文件，直接 rm 即可
rm app/runtime.py
git checkout app/bootstrap.py app/hermes/routes.py app/api/skills.py
```

### 3.6 不动的东西

- P1 还没做就跳过 P2（顺序强依赖）
- tools/ / memory/ / llm/
- 业务逻辑

---

## 4. Phase 3：工具自注册改"声明+显式注册"两步

### 4.1 目标

干掉 import-time 副作用。**声明和注册彻底分离**：
- `implementations/*.py` 末尾只写 `tool_def = ToolDef(name=..., toolset=..., schema=..., handler=...)`
- 显式注册放在 `app/tools/registry.py` 的 `BUILTIN_TOOL_DEFS` 列表里

### 4.2 改动范围

#### 4.2.1 新建 `app/tools/_defs.py`（声明 + 显式注册表）

```python
# app/tools/_defs.py（约 100 行）
"""
工具声明注册表（替代 implementation 文件模块级 registry.register）

每个工具是 ToolDef dataclass 实例，**不在 import-time 副作用**。
注册由 buildin_tools.bootstrap() 显式触发。
"""
from dataclasses import dataclass, field
from typing import Callable, Optional, List


@dataclass
class ToolDef:
    name: str
    toolset: str
    schema: dict
    handler: Callable
    check_fn: Optional[Callable] = None
    requires_env: Optional[List[str]] = None
    is_async: bool = True
    description: str = ""
    emoji: str = ""
    max_result_size_chars: Optional[int] = None
    parallel_mode: str = "never"


# ── 内置工具声明（按 toolset 分组）───────────────────────────────
# terminal
from app.tools.implementations.terminal import terminal_handler, terminal_check
TERMINAL = ToolDef(
    name="terminal",
    toolset="terminal",
    schema={...},  # 从原 implementation 文件搬过来
    handler=terminal_handler,
    check_fn=terminal_check,
    emoji="💻",
)

# file
from app.tools.implementations.file_tools import read_file_handler, write_file_handler, ...
FILE_TOOLS = [ToolDef(name=t["name"], toolset="file", schema=t["schema"], handler=t["handler"]) for t in [...]]

# ... 其余 12 个工具类似

# ── 全量列表（注册时遍历）───────────────────────────────
BUILTIN_TOOL_DEFS: List[ToolDef] = [
    TERMINAL,
    *FILE_TOOLS,
    # ...
]
```

#### 4.2.2 改 `app/tools/implementations/*.py`

每个文件**只暴露 `*_handler` 函数 + schema 字典**，不调 `registry.register()`：

```python
# app/tools/implementations/terminal.py（重构后）
import asyncio, logging, ...
from app.tools.registry import registry  # ← 不再在模块级调 register
# ... 保留所有 handler 函数和 check 函数
# 末尾：导出 terminal_handler / terminal_check / terminal_schema
__all__ = ["terminal_handler", "terminal_check", "terminal_schema"]
```

#### 4.2.3 改 `app/tools/registry.py`

`discover_builtin_tools()` 改为遍历 `_defs.BUILTIN_TOOL_DEFS`：

```python
# app/tools/registry.py（重构）
def discover_builtin_tools() -> List[str]:
    """从显式声明表注册所有内置工具（替代 importlib 扫描）"""
    from app.tools._defs import BUILTIN_TOOL_DEFS
    registered = []
    for td in BUILTIN_TOOL_DEFS:
        registry.register(
            name=td.name,
            toolset=td.toolset,
            schema=td.schema,
            handler=td.handler,
            check_fn=td.check_fn,
            requires_env=td.requires_env,
            is_async=td.is_async,
            description=td.description,
            emoji=td.emoji,
            max_result_size_chars=td.max_result_size_chars,
            parallel_mode=td.parallel_mode,
        )
        registered.append(td.name)
    if registered:
        logger.info(f"已注册 {len(registered)} 个内置工具: {', '.join(registered)}")
    return registered


# 删掉：
# - def _module_registers_tools(py_file) -> bool: ...
# - importlib.import_module 调用
# - _TOOLS_DIR.glob 扫描
```

#### 4.2.4 改 `app/core/env_capabilities.py`

**移除偷偷 discover**（P3 的副产物）：

```python
# app/core/env_capabilities.py L104-106 删除
#   discover_builtin_tools()   ← 删
# 改为只读已有 registry 状态
from app.tools.registry import registry
toolsets = registry.get_available_toolsets()
```

### 4.3 改动文件

| 文件 | 操作 |
|---|---|
| `app/tools/_defs.py` | 新建（+200 行，14 个工具声明） |
| `app/tools/registry.py` | `discover_builtin_tools` 重写（-30 行） |
| `app/tools/implementations/*.py` (14 个) | 每个 -3 行（删模块级 register 调用） |
| `app/core/env_capabilities.py` | L104-106 删 3 行（移除偷偷 discover） |

### 4.4 Verify

```bash
# [V3.1] import 不再带副作用
cd backend && python -c "
from app.tools.implementations import terminal  # ← 不应再自动注册
from app.tools.registry import registry
print(f'已注册工具数: {len(registry._tools)}')  # 期望：0
"

# [V3.2] 显式注册后
cd backend && python -c "
from app.tools.registry import discover_builtin_tools, registry
discover_builtin_tools()
print(f'已注册工具数: {len(registry._tools)}')  # 期望：≥10
print(f'工具名: {sorted(registry._tools.keys())}')
"

# [V3.3] env_capabilities 不再偷偷 discover
cd backend && python -c "
import logging; logging.basicConfig(level=logging.WARNING)
from app.core.env_capabilities import generate_capability_prompt
# 应当在 0.1s 内返回（不触发 import）
import time; t0 = time.time()
p = generate_capability_prompt()
print(f'耗时: {time.time()-t0:.3f}s, 长度: {len(p)} 字节')
"

# [V3.4] 起 uvicorn 跑完整 chat
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info 2>&1 | grep -E "已注册|应用启动" | head -5
# 期望：1 条 "已注册 N 个内置工具"

curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "ping", "use_memory": false}' | python -m json.tool

# [V3.5] 测试（应该有新的 test_tools.py 验证声明表）
cd backend && python -m pytest tests/test_tools.py -v  # 新增
cd backend && python -m pytest tests/ -v  # 全量回归
```

### 4.5 回滚方案

```bash
# 删 _defs.py + revert implementations/* 和 registry.py
rm app/tools/_defs.py
git checkout app/tools/registry.py app/tools/implementations/ app/core/env_capabilities.py
```

### 4.6 不动的东西

- P1 / P2 改的 main.py / bootstrap.py / runtime.py
- tools/manager.py（API 不变）
- 业务逻辑 / 路由
- mcp_client.py（MCP 走另一条路，**独立保留**动态注册）

---

## 5. Phase 4：干掉 `tools.md` 写盘

### 5.1 目标

agent 不再读 `domains/tools/tools.md` 文件，改为**运行时调 `runtime.list_tools()` / `registry.get_schemas()` API**。
`generate_tools_md()` 函数保留（向后兼容），但**不再自动调**，改为 opt-in。

### 5.2 改动范围

#### 5.2.1 改 `app/tools/registry.py`

```python
# generate_tools_md 加废弃警告
def generate_tools_md():
    """⚠️ DEPRECATED: 此函数在 P4 之后不再被 main.py 自动调用。
    Agent 改为通过 runtime API 查工具，路径 backend/app/domains/tools/tools.md 不再自动维护。
    如需手动生成：python -c "from app.tools.registry import generate_tools_md; generate_tools_md()"
    """
    import warnings
    warnings.warn("generate_tools_md() is deprecated, use runtime.get_schemas()", DeprecationWarning, stacklevel=2)
    # ... 原实现保留
```

#### 5.2.2 改 `app/bootstrap.py`

```python
# lifespan 里删掉 generate_tools_md() 调用
# discover_builtin_tools()
# generate_tools_md()   ← 删
# discover_mcp_tools()
```

#### 5.2.3 改 `app/core/agent.py`

agent 中所有 `read_file('domains/tools/tools.md')` 改成**调 API**：

```python
# 之前：
content = self.read_file("domains/tools/tools.md")

# 之后：
from app.tools.registry import registry
schemas = registry.get_schemas()  # 已经在 LLM 调 tools 参数里传了
# agent 想看 human-readable 描述时：
from app.tools.registry import registry
descriptions = []
for entry in registry._snapshot_entries():
    descriptions.append(f"- **{entry.name}** ({entry.toolset}): {entry.description}")
prompt = "\n".join(descriptions)
```

#### 5.2.4 改 `app/core/system_prompt.py`

`generate_capability_prompt()` 不再读 tools.md，**直接调 registry API**：

```python
def generate_capability_prompt() -> str:
    from app.tools.registry import registry
    toolsets = registry.get_available_toolsets()
    # ... 用 toolsets 数据生成描述
```

### 5.3 改动文件

| 文件 | 操作 |
|---|---|
| `app/tools/registry.py` | `generate_tools_md` 加 deprecation warning |
| `app/bootstrap.py` | lifespan 删 1 行 |
| `app/core/agent.py` | `read_file('domains/tools/tools.md')` 替换（按实际出现位置） |
| `app/core/system_prompt.py` | `generate_capability_prompt` 改 API（已部分实现） |

### 5.4 Verify

```bash
# [V4.1] 搜代码里所有 read_file('domains/tools/tools.md') —— 应为 0
cd backend && grep -rn "domains/tools/tools.md" app/ --include="*.py"
# 期望：0 行

# [V4.2] generate_tools_md 仍可手动调（向后兼容）
cd backend && python -c "
from app.tools.registry import generate_tools_md, discover_builtin_tools
discover_builtin_tools()
import warnings; warnings.simplefilter('always')
generate_tools_md()  # 应当出 DeprecationWarning
"

# [V4.3] 起 uvicorn，lifespan 日志无 "tools.md" 写入
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info 2>&1 | grep -E "tools.md|tools.md已生成" | head -3
# 期望：0 行（已不再自动写）

# [V4.4] system prompt 仍包含工具集描述
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "列出所有可用工具", "use_memory": false}' | python -m json.tool
# 期望：reply 里有工具列表（说明 runtime API 工作）

# [V4.5] 删掉 domains/tools/tools.md 后再 chat（验证不依赖文件）
rm backend/app/domains/tools/tools.md
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "ping", "use_memory": false}' | python -m json.tool
# 期望：正常返回
```

### 5.5 回滚方案

```bash
# 全部 revert
git checkout app/bootstrap.py app/core/agent.py app/core/system_prompt.py app/tools/registry.py
# 重新调一次 generate_tools_md() 恢复文件
cd backend && python -c "from app.tools.registry import generate_tools_md, discover_builtin_tools; discover_builtin_tools(); generate_tools_md()"
```

### 5.6 不动的东西

- `domains/tools/` 目录结构（保留，供向后兼容）
- tools.md 文件内容（不再自动更新，但保留手写能力）
- 业务逻辑

---

## 6. Phase 依赖 & 执行建议

### 6.1 依赖图

```
P1 (main.py 重构)
 └─→ P2 (runtime hook 协议)
      └─→ P3 (工具显式注册)
           └─→ P4 (干掉 tools.md)
```

**每个 Phase 都是后续的前置**：
- P2 的 hook 协议依赖 P1 的 bootstrap.py 提供 `configure_hermes()` 函数作为 hook 注册入口
- P3 的 `_defs.py` 注册表依赖 P2 的 `runtime.list_hooks()` 作为可观测性手段
- P4 删 `generate_tools_md()` 自动化调用依赖 P3 的 `discover_builtin_tools()` 显式注册

### 6.2 建议执行节奏

| 阶段 | 时间 | 验收 |
|---|---|---|
| Day 1 morning | P1 | 4-5 个 verify 全过 + 现有测试不退步 |
| Day 1 afternoon | P2 | runtime hook 日志出现 + Hermes/skills API 正常 |
| Day 2 | P3 | 测试隔离成功 + import 不带副作用 + 14 个工具全注册 |
| Day 3 morning | P4 | 删 tools.md 后 system prompt 仍含工具描述 |
| Day 3 afternoon | 写 `docs/post-refactor-2026-06-02.md` 总结 |

**强烈建议每个 Phase 完成后 git commit 一次**，便于回滚。

### 6.3 不要做的事

- ❌ **不要跨 Phase 改业务逻辑**（agent / multi_agent / dreaming / IM）
- ❌ **不要把 P1-P4 合并一次提交**——出问题定位困难
- ❌ **P3 不要在 P1/P2 没动时单独做**——P3 的 `_defs.py` 需要 bootstrap.py 里的 `discover_builtin_tools()` 显式调用入口
- ❌ **不要先动 `tools.md` 路径位置**（P4 不改 `domains/` 目录结构）

---

## 7. FAQ

### Q1: P3 改了 14 个 implementation 文件，每个都要小心，会不会把现有测试搞挂？

**A**: 风险评估：中。验证手段：每个 implementation 文件改完立刻
```bash
cd backend && python -c "from app.tools.implementations.terminal import terminal_handler; print('OK')"
```
+ 跑测试。如果某文件改完 import 失败，回滚该文件即可。**强烈建议改每个文件后 git commit**。

### Q2: P2 改了 hook 协议，但有些测试 fixture 直接 `hermes_routes.memory_manager = ...`，会冲突吗？

**A**: 会的。需要在测试里把 `hermes_routes.memory_manager = ...` 改为 `runtime.register("app.hermes.routes", "memory_manager", ...)`，或者用 `@pytest.fixture` 注入。如果测试 fixture 改了工作量太大，**P2 阶段可以保留"旧式 monkey-patch 兼容"——runtime.apply() 不覆盖已有字段**。

### Q3: P4 删 generate_tools_md 自动调用，会不会影响别处？

**A**: 不会——P4 已经把所有 `read_file('domains/tools/tools.md')` 替换为 API。如果发现 grep 还有残留，逐个替换。

### Q4: 重构过程中可以暂停吗？

**A**: 可以。每个 Phase 独立可验证。**建议 P1 必做，P2/P3/P4 可选**。
P3 风险最高，建议 P2 稳定运行 1-2 天后再做。

### Q5: 重构完预计代码量变化？

| Phase | 新增 | 删除 | 净增 |
|---|---|---|---|
| P1 | 180 | 220 | -40 |
| P2 | 100 | 0 | +100 |
| P3 | 200 | 50 | +150 |
| P4 | 0 | 10 | -10 |
| **合计** | **+480** | **+280** | **+200** |

P1/P4 净减，P2/P3 净增。**总体可控**。

---

## 8. 总结

| 维度 | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| **目标** | 拆 main.py | 显式 hook | 显式注册 | 去文件依赖 |
| **风险** | 低 | 中 | 高 | 中 |
| **业务改动** | 0 | 0 | 0 | 0 |
| **估时** | 2-3h | 3-4h | 4-6h | 2-3h |
| **可独立停** | ✅ | ✅ | ✅ | ✅ |
| **回滚难度** | 易 | 易 | 中 | 易 |

**最终建议**：先做 P1（最低风险最高收益），P1 跑稳后再讨论 P2-P4。

---

## 9. 附录：参考 / 历史

- 2026-05-28：multi_agent v2 重构（state_machine / event_bus / workspace / task_queue / scheduler），已在 `research/tongyong-agent-architecture/SKILL.md` 文档化
- 2026-06-02：system_prompt 死代码修复（`AgentEngine._inject_base_system_prompt`），同次 session
- 2026-06-02：本文档（架构审查 + 4 Phase 重构计划）

## 10. 待 linc 决策

1. **是否执行？** （A: 全做 / B: 只做 P1 / C: 暂停讨论 / D: 改计划）
2. **是否要写 plan audit doc** `docs/post-refactor-2026-06-02.md`？（A: 要 / B: 做完 P1 再说）
3. **是否要在 memory 存一条"tongyong 装配层架构陷阱"备忘？**（A: 存 / B: 不存，session_search 检索即可）
