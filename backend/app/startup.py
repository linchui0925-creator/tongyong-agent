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
    4. 如果没保存, 用 default provider 创建
    5. 同步 LLM 到 AgentEngine
    """
    # 1. AgentEngine
    engine = AgentEngine(llm=None)
    logger.info("AgentEngine 初始化完成")

    # 2. LLMManager 绑定
    from app.services.llm_manager import get_llm_manager
    llm_mgr = get_llm_manager()
    llm_mgr.bind_agent_engine(engine)

    # 3. 恢复 saved provider
    from app.config import settings
    restored = llm_mgr.try_restore_saved_provider()
    if not restored:
        from app.llm.factory import get_llm
        llm_instance = get_llm()
        logger.info(f"LLM 初始化成功: {type(llm_instance).__name__}")
        llm_mgr._seed_initial_llm(llm_instance, settings.default_llm_provider)
    if engine.llm is None:
        llm_mgr._sync_to_agent()

    return engine
