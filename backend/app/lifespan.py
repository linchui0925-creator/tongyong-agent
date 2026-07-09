"""
应用生命周期 (P2-1 W4-22)

替代 main.py 的 @app.on_event("startup") / @app.on_event("shutdown") 装饰器.
用现代 lifespan context manager (FastAPI 推荐).
"""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭钩子"""
    # ── Startup ──
    logger.info("=" * 50)
    logger.info(f"{app.title} 启动中...")
    logger.info("=" * 50)

    await _startup_tools(app)
    await _startup_database(app)
    await _startup_llm(app)
    await _startup_hub(app)
    await _startup_im_gateway(app)

    logger.info("=" * 50)
    logger.info("应用启动完成")
    logger.info("=" * 50)

    yield  # ── 应用运行中 ──

    # ── Shutdown ──
    logger.info("应用正在关闭...")
    await _shutdown_hub()
    await _shutdown_im_gateway()
    logger.info("应用已关闭")


async def _startup_tools(app: FastAPI) -> None:
    """注册内置工具 + MCP 工具"""
    from app.tools import discover_builtin_tools
    discover_builtin_tools()
    # W4-25 P1-4: 清理过期的 ask_pending (跨进程崩溃残留)
    try:
        from app.core.ask_store import get_ask_pending_store
        get_ask_pending_store().cleanup_expired()
    except Exception as e:
        logger.warning(f"[startup] ask_pending 清理失败: {e}")
    try:
        from app.tools.mcp_client import discover_mcp_tools_async
        await discover_mcp_tools_async()
    except Exception as e:
        logger.warning(f"MCP 工具发现失败: {e}")


async def _startup_database(app: FastAPI) -> None:
    """验证数据库连接"""
    engine = app.extra.get("agent_engine") if hasattr(app, "extra") else None
    if not engine:
        return
    try:
        sessions = await engine.get_sessions()
        logger.info(f"数据库连接成功，当前会话数: {len(sessions)}")
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")


async def _startup_llm(app: FastAPI) -> None:
    """验证 LLM 连接 (P2 增强: 支持 SKIP 跳过 + 5s 快速失败)"""
    if os.environ.get("SKIP_LLM_VALIDATION") == "1":
        logger.info("[skip] LLM 启动期验证已跳过 (SKIP_LLM_VALIDATION=1)")
        return
    engine = app.extra.get("agent_engine") if hasattr(app, "extra") else None
    if not engine or not engine.llm:
        return
    try:
        # 5s 快速失败: 启动期只验可达性, 不等真实生成
        import asyncio
        is_available = await asyncio.wait_for(
            engine.llm.initialize(), timeout=5.0
        )
        logger.info(f"LLM连接验证: {'成功' if is_available else '失败'}")
    except asyncio.TimeoutError:
        logger.warning("[startup] LLM 验证 5s 超时, 跳过 (chat 时会重试)")
    except Exception as e:
        logger.error(f"LLM连接验证失败: {e}")


async def _startup_hub(app: FastAPI) -> None:
    """启动 Community HubScheduler (W5-1) — catalog sync + browse layer scrape"""
    from app.config import settings
    if not getattr(settings, "community_hub_sync_on_startup", True):
        logger.info("[skip] HubScheduler 启动期同步已禁用 (community_hub_sync_on_startup=False)")
    try:
        from app.core.community_hub import HubScheduler, sync_all_sources, scrape_browse_layers

        interval_h = float(getattr(settings, "community_hub_sync_interval_hours", 6))
        sync_on_start = bool(getattr(settings, "community_hub_sync_on_startup", True))
        sched = HubScheduler(
            interval_seconds=interval_h * 3600,
            sync_on_start=False,  # 我们手控, fire-and-forget 在下面
            sync_body=None,
        )

        # 注入 sync body — catalog only, 不 install
        async def _sync_body():
            result = await sync_all_sources(force=False)
            # scrape 是同步函数, 在 executor 跑
            import asyncio
            loop = asyncio.get_running_loop()
            scrape_result = await loop.run_in_executor(
                None, _sync_scrape_sync, None
            )
            return {
                "ok": result.get("ok", False) and scrape_result.get("ok", True),
                "count": result.get("count", 0),
                "scrape": scrape_result,
            }
        sched.install_sync_body(_sync_body)
        app.state.hub = sched
        global _HUB_SCHEDULER_REF
        _HUB_SCHEDULER_REF = sched
        await sched.start()

        # 启动期 fire-and-forget 一次
        if sync_on_start:
            import asyncio
            asyncio.create_task(sched.sync_now())
        logger.info(f"HubScheduler 已启动: interval={interval_h}h, sync_on_start={sync_on_start}")
    except Exception as e:
        logger.warning(f"HubScheduler 启动失败 (无害): {e}")


def _sync_scrape_sync(config_path):
    """同步包装 scrape_browse_layers (在 executor 跑)"""
    import asyncio
    from app.core import community_hub
    return asyncio.run(community_hub.scrape_browse_layers(config_path=config_path))


_HUB_SCHEDULER_REF = None  # 全局引用, _shutdown_hub 拿得到


async def _shutdown_hub() -> None:
    """停 HubScheduler — cancel 后台 loop"""
    global _HUB_SCHEDULER_REF
    if _HUB_SCHEDULER_REF is None:
        return
    try:
        await _HUB_SCHEDULER_REF.stop()
        logger.info("HubScheduler 已停止")
    except Exception as e:
        logger.warning(f"HubScheduler 关闭失败 (无害): {e}")
    _HUB_SCHEDULER_REF = None


async def _startup_im_gateway(app: FastAPI) -> None:
    """启动 IM Gateway (飞书/企业微信/微信)"""
    try:
        from app.gateway.im import im_gateway_manager, inject_agent_engine, IMPlatform, IMPlatformConfig
        from app.config import settings as app_settings

        engine = app.extra.get("agent_engine")
        if engine:
            inject_agent_engine(engine)

        feishu_app_id = getattr(app_settings, "feishu_app_id", "") or ""
        feishu_app_secret = getattr(app_settings, "feishu_app_secret", "") or ""
        if feishu_app_id and feishu_app_secret:
            im_gateway_manager.set_platform_config(
                IMPlatform.FEISHU,
                IMPlatformConfig(
                    platform=IMPlatform.FEISHU,
                    enabled=getattr(app_settings, "feishu_enabled", False),
                    allowed_users=getattr(app_settings, "feishu_allowed_users", []),
                    allow_all_users=getattr(app_settings, "feishu_allow_all_users", False),
                    default_profile=getattr(app_settings, "feishu_default_profile", "default"),
                    extra={
                        "app_id": feishu_app_id,
                        "app_secret": feishu_app_secret,
                        "verification_token": getattr(app_settings, "feishu_verification_token", ""),
                        "encrypt_key": getattr(app_settings, "feishu_encrypt_key", ""),
                        "domain": getattr(app_settings, "feishu_domain", "feishu"),
                    },
                ),
            )

        results = await im_gateway_manager.start_all()
        if results:
            logger.info(f"IM Gateway 启动结果: {results}")
    except Exception as e:
        logger.error(f"IM Gateway 启动失败: {e}", exc_info=True)


async def _shutdown_im_gateway() -> None:
    """停止 IM Gateway"""
    try:
        from app.gateway.im import im_gateway_manager
        await im_gateway_manager.stop_all()
    except Exception as e:
        logger.error(f"IM Gateway 关闭异常: {e}")
