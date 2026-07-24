"""
TongYong Agent 主应用模块 (P2-1 W4-22 拆分后)

职责: app factory + middleware + route 注册 + global exception handler.
启动/关闭 → app/lifespan.py
健康端点 → app/routes/health.py
LLM/AgentEngine 初始化 → app/startup.py
"""

import logging
import sys
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api import chat, memory, chart, llm, evaluation
from app.api import proxy
from app.api import dreaming as dreaming_api
from app.api import proxy
from app.api import skills as skills_api
from app.api import proxy
from app.api import marketplace as marketplace_api
from app.api import hub as hub_api
from app.api import trace as trace_api
from app.api import plan as plan_api
from app.api import proxy
from app.api import tool_harness as tool_harness_api
from app.api import proxy
from app.api import files as files_api
from app.api import proxy
from app.api import attachments as attachments_api
from app.api import proxy
from app.api import contact as contact_api
from app.api import coze_skills as coze_skills_api
from app.api import mcp as mcp_api
from app.api import proxy
from app.api.stream import router as stream_router
from app.core.multi_agent.api import router as team_router
from app.hermes.routes import router as hermes_router
from app.gateway import openai_router
from app.gateway.config import GatewaySettings
from app.gateway.openai_api import init_gateway as init_gateway_api
from app.gateway.desktop_bridge import router as desktop_bridge_router
from app.api.gateway_profiles import router as profile_router
from app.gateway.profile_router import router as profile_gateway_router
from app.routes.health import router as health_router
from app.startup import init_agent_engine
from app.lifespan import lifespan
from app.paths import data_path

# ── 日志配置 ──
logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """App factory (P2-1) — 替代模块级 app 变量, 便于测试"""
    app = FastAPI(
        title=settings.app_name,
        description="通用智能体 API - 支持对话、记忆检索和多模态处理",
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # ── 请求日志中间件 ──
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        logger.info(f"请求: {request.method} {request.url.path}")
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(
            f"响应: {request.method} {request.url.path} "
            f"状态码: {response.status_code} 耗时: {process_time:.3f}s"
        )
        response.headers["X-Process-Time"] = str(process_time)
        return response

    # ── AgentEngine + LLM 初始化 (抽到 app/startup.py) ──
    agent_engine = init_agent_engine()
    app.extra = {"agent_engine": agent_engine}

    # ── 路由注册 ──
    app.include_router(health_router)
    app.include_router(proxy.router, prefix="/api/proxy", tags=["proxy"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
    app.include_router(chart.router, prefix="/api/chart", tags=["chart"])
    app.include_router(llm.router, prefix="/api/llm", tags=["llm"])
    app.include_router(hermes_router)
    app.include_router(dreaming_api.router)
    app.include_router(skills_api.router)
    app.include_router(coze_skills_api.router)
    app.include_router(mcp_api.router)
    app.include_router(marketplace_api.router)
    app.include_router(hub_api.router)
    app.include_router(trace_api.router)
    app.include_router(plan_api.router)
    app.include_router(tool_harness_api.router)
    app.include_router(files_api.router)
    app.include_router(attachments_api.router)
    app.include_router(contact_api.router)
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
    # Voice API
    from app.api.voice import router as voice_router
    app.include_router(voice_router, prefix="/api/voice", tags=["voice"])

    # ── Gateway + Hermes 初始化 ──
    _init_gateway_and_hermes()

    # ── 全局异常处理器 ──
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"未处理的异常: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "服务器内部错误",
                "path": str(request.url.path),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

    app.state.agent_engine = agent_engine
    return app


def _init_gateway_and_hermes() -> None:
    """OpenAI-gateway 配置 + Hermes 管理器注入 (P2-1 抽到独立函数)"""
    _gateway_settings = GatewaySettings()
    init_gateway_api(_gateway_settings)

    import app.hermes.routes as hermes_routes
    from app.hermes import MemoryFileManager, SkillFileManager
    hermes_routes.memory_manager = MemoryFileManager(base_dir=data_path("hermes"))
    hermes_routes.skill_manager = SkillFileManager(base_dir=data_path("hermes"))
    skills_api.init(hermes_routes.skill_manager)


# ── 模块级 app (供 uvicorn app.main:app) ──
app = create_app()


def get_agent_engine():
    """兼容旧依赖注入路径"""
    return getattr(app.state, "agent_engine", app.extra.get("agent_engine"))


# 向后兼容: 11 个 call sites 用 `from app.main import agent_engine` (stream.py / ask.py /
# delegate_task.py / memory.py / evaluation.py 等). P2-1 重构后, 内部全部走 get_agent_engine(),
# 这里保留 module-level alias 避免批量改 call sites.
agent_engine = app.extra.get("agent_engine")


