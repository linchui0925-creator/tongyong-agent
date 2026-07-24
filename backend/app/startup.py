"""
启动初始化 (P2-1 W4-22)

从 main.py 抽出的 AgentEngine + LLM 初始化逻辑.
跟 lifespan.py 配合: lifespan 负责"启动 hook", startup 负责"资源构造".
"""

import logging
from app.core.agent import AgentEngine

logger = logging.getLogger(__name__)


def init_agent_engine() -> AgentEngine:
    """构造 AgentEngine + 注入 LLM.

    顺序:
    1. 构造 AgentEngine(llm=None) (LLM 延迟注入)
    2. 绑定到 LLMManager (model switch 自动同步)
    3. 尝试恢复上次保存的 provider (从 llm_config.json)
    4. 用 factory.get_llm() 真造一个 LLM 实例 (W5-2 修: 之前 saved 路径下不构造,
       agent_engine.llm 一直是 None, LangChain adapter 包 None 第一次 chat 就报
       'NoneType' object has no attribute 'model')
    5. 同步 LLM 到 AgentEngine

    fallback 链: saved provider/model -> settings.default -> 报错
    """
    # 1. AgentEngine
    engine = AgentEngine(llm=None)
    logger.info("AgentEngine 初始化完成")

    # 2. LLMManager 绑定
    from app.services.llm_manager import get_llm_manager
    llm_mgr = get_llm_manager()
    llm_mgr.bind_agent_engine(engine)

    # 3. 恢复 saved provider (只设 manager 状态: provider/model 字符串)
    from app.config import settings
    restored = llm_mgr.try_restore_saved_provider()

    # 4. 用恢复出的完整 runtime config 直接重建当前 LLM。
    from app.llm.factory import get_llm
    if restored:
        try:
            llm_instance = llm_mgr._llm_from_runtime_config(restored)
            provider = restored.get("provider", settings.default_llm_provider)
            model = restored.get("model", settings.default_llm_model)
            logger.info(f"LLM 初始化成功 (restored runtime): {provider}/{model} -> {type(llm_instance).__name__}")
        except Exception as e:
            logger.warning(f"restored runtime LLM 构造失败 ({restored.get('provider')}/{restored.get('model')}: {e}), 降级 default")
            llm_instance = get_llm(provider=settings.default_llm_provider, model=settings.default_llm_model)
            provider = settings.default_llm_provider
    else:
        llm_instance = get_llm(provider=settings.default_llm_provider, model=settings.default_llm_model)
        provider = settings.default_llm_provider
        logger.info(f"LLM 初始化成功 (default): {provider}/{settings.default_llm_model} -> {type(llm_instance).__name__}")

    llm_mgr._seed_initial_llm(llm_instance, provider)

    # 5. 同步到 AgentEngine
    if engine.llm is None:
        llm_mgr._sync_to_agent()
    logger.info(f"engine.llm 已注入: {type(engine.llm).__name__ if engine.llm else None}")

    return engine
