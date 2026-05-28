"""
TongYong Agent 主应用模块
FastAPI应用入口，配置路由、中间件和生命周期管理
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.api import chat, memory, chart, llm
from app.api import evaluation
from app.api import dreaming as dreaming_api
from app.api import skills as skills_api
from app.api import tool_harness as tool_harness_api
from app.api.stream import router as stream_router
from app.core.multi_agent.api import router as team_router
from app.core.agent import AgentEngine
from app.llm.base import BaseLLM
from app.hermes.routes import router as hermes_router
from app.hermes import MemoryFileManager, SkillFileManager
from app.gateway import openai_router
from app.gateway.config import GatewaySettings
from app.gateway.openai_api import init_gateway as init_gateway_api
from app.gateway.desktop_bridge import router as desktop_bridge_router
from app.api.gateway_profiles import router as profile_router
from app.gateway.profile_router import router as profile_gateway_router
import logging
import time
import sys

# 配置日志
logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    description="通用智能体 API - 支持对话、记忆检索和多模态处理",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None
)

# 初始化Agent引擎（不传 LLM，延迟注入）
agent_engine = AgentEngine(llm=None)
logger.info("AgentEngine初始化完成")

# 将 AgentEngine 同步到 LLMManager，使模型切换自动生效
from app.services.llm_manager import get_llm_manager
_llm_mgr = get_llm_manager()
_llm_mgr.bind_agent_engine(agent_engine)
# 尝试从保存的配置恢复上次使用的 provider（如 minimax），
# 恢复成功后会同步到 AgentEngine；失败则用默认 provider 创建并注入
restored = _llm_mgr.try_restore_saved_provider()
if not restored:
    from app.llm.factory import get_llm
    llm_instance = get_llm()
    logger.info(f"LLM初始化成功: {type(llm_instance).__name__}")
    _llm_mgr._seed_initial_llm(llm_instance, settings.default_llm_provider)
if agent_engine.llm is None:
    _llm_mgr._sync_to_agent()

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有HTTP请求"""
    start_time = time.time()
    
    # 记录请求
    logger.info(f"请求: {request.method} {request.url.path}")
    
    # 处理请求
    response = await call_next(request)
    
    # 记录响应
    process_time = time.time() - start_time
    logger.info(
        f"响应: {request.method} {request.url.path} "
        f"状态码: {response.status_code} "
        f"耗时: {process_time:.3f}s"
    )
    
    # 添加自定义响应头
    response.headers["X-Process-Time"] = str(process_time)
    
    return response

# 注册路由
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(chart.router, prefix="/api/chart", tags=["chart"])
app.include_router(llm.router, prefix="/api/llm", tags=["llm"])
app.include_router(hermes_router)
app.include_router(dreaming_api.router)
app.include_router(skills_api.router)
app.include_router(tool_harness_api.router)
app.include_router(stream_router, prefix="/api/chat")
app.include_router(openai_router, prefix="/v1")
app.include_router(desktop_bridge_router)
app.include_router(profile_router)
app.include_router(profile_gateway_router)
app.include_router(evaluation.router)
app.include_router(team_router, tags=["team"])

# 初始化 OpenAI-gateway 配置
_gateway_settings = GatewaySettings()
init_gateway_api(_gateway_settings)

# 初始化 Hermes 管理器并注入到路由
import app.hermes.routes as hermes_routes
hermes_routes.memory_manager = MemoryFileManager(base_dir="./data/hermes")
hermes_routes.skill_manager = SkillFileManager(base_dir="./data/hermes")

# 初始化 skills API 桥接
skills_api.init(hermes_routes.skill_manager)


def get_agent_engine():
    """获取Agent引擎的依赖函数"""
    return agent_engine


app.extra = {"agent_engine": agent_engine}


@app.get("/")
async def root():
    """API根路径"""
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": "1.0.0",
        "docs": "/docs" if settings.debug else "disabled"
    }


@app.get("/health")
async def health():
    """健康检查端点"""
    llm_status = "initialized" if agent_engine.llm else "unavailable"
    
    return {
        "status": "ok",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "llm": {
            "status": llm_status,
            "provider": type(agent_engine.llm).__name__ if agent_engine.llm else None
        },
        "memory": {
            "sessions": len(await agent_engine.get_sessions()) if agent_engine.memory_storage else 0
        }
    }


@app.get("/ready")
async def ready():
    """就绪检查端点"""
    checks = {
        "agent_engine": agent_engine is not None,
        "llm": agent_engine.llm is not None,
        "memory_storage": agent_engine.memory_storage is not None,
        "vector_store": agent_engine.vector_store is not None
    }
    
    all_ready = all(checks.values())
    
    return {
        "ready": all_ready,
        "checks": checks
    }


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info("=" * 50)
    logger.info(f"{settings.app_name} 启动中...")
    logger.info("=" * 50)

    # 发现并注册所有内置工具，同时生成 tools.md
    from app.tools import discover_builtin_tools
    from app.tools.registry import generate_tools_md
    discover_builtin_tools()
    generate_tools_md()

    # 动态发现 MCP 服务器工具
    try:
        from app.tools.mcp_client import discover_mcp_tools
        discover_mcp_tools()
    except Exception as e:
        logger.warning(f"MCP 工具发现失败: {e}")

    # 验证数据库连接
    try:
        sessions = await agent_engine.get_sessions()
        logger.info(f"数据库连接成功，当前会话数: {len(sessions)}")
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
    
    # 验证LLM连接
    if agent_engine.llm:
        try:
            is_available = await agent_engine.llm.initialize()
            logger.info(f"LLM连接验证: {'成功' if is_available else '失败'}")
        except Exception as e:
            logger.error(f"LLM连接验证失败: {e}")
    
    logger.info("=" * 50)
    logger.info("应用启动完成")
    logger.info("=" * 50)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("应用正在关闭...")
    
    # 清理资源
    if agent_engine:
        logger.info("清理Agent引擎资源...")
    
    logger.info("应用已关闭")


# 异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "服务器内部错误",
            "path": str(request.url.path),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    )
