"""Helpers for Agent prompt and memory injection.

These helpers keep the `AgentEngine` class focused on orchestration
instead of prompt assembly details.
"""

from __future__ import annotations

import logging
from app.core.base import Message
from app.paths import data_path

logger = logging.getLogger(__name__)


def get_cli_executor(agent):
    """Lazily create and cache the CLI executor."""
    if getattr(agent, "_cli_executor", None) is None:
        try:
            from app.domains import CLIExecutor
            agent._cli_executor = CLIExecutor(working_dir=".")
            logger.info("CLIExecutor 已初始化")
        except Exception as e:
            logger.warning(f"CLIExecutor 初始化失败: {e}")
    return agent._cli_executor


def try_fallback_llm(agent):
    """Try other providers when the current LLM provider is unavailable."""
    try:
        from app.services.llm_manager import LLMManager
        llm_mgr = LLMManager()
        available = ["openai", "anthropic", "deepseek", "google"]
        for provider in available:
            if provider == getattr(agent.llm, "provider", None):
                continue
            api_key = llm_mgr.get_api_key(provider)
            if api_key:
                from app.llm.factory import get_llm
                fallback_llm = get_llm(provider, api_key)
                if fallback_llm:
                    logger.info(f"找到 fallback LLM: {provider}")
                    return fallback_llm
    except Exception as e:
        logger.warning(f"获取 fallback LLM 失败: {e}")
    return None


async def inject_domain_prompts(agent, session_id: str):
    """Inject domain knowledge prompts to reduce default-model drift."""
    try:
        from app.domains import get_integrator
        integrator = get_integrator()
        prompt = integrator.get_all()
        if prompt:
            agent.context.messages.insert(0, Message(role="system", content=prompt, created_at=""))
            logger.info(f"注入全部领域认知 ({len(integrator.get_domain_keys())} 个领域)")
        logger.warning(f"[DOMAIN] injected | context.messages count after={len(agent.context.messages)}")
    except Exception as e:
        logger.warning(f"领域认知注入失败: {e}")


def inject_base_system_prompt(agent):
    """Inject the base system prompt last so it lands at the top of the stack."""
    try:
        from app.core.system_prompt import get_system_prompt
        full_prompt = get_system_prompt()
        if not full_prompt:
            return
        agent.context.messages.insert(0, Message(role="system", content=full_prompt, created_at=""))
        logger.warning(
            f"[SYS_PROMPT] injected | bytes={len(full_prompt)} | context.messages count after={len(agent.context.messages)}"
        )
    except Exception as e:
        logger.warning(f"基础 system prompt 注入失败: {e}")


async def inject_memory(agent, session_id: str):
    """Inject long-term file memory and user preference memory."""
    try:
        from app.hermes.memory_file import MemoryFileManager
        mfm = MemoryFileManager(base_dir=data_path("hermes"))
        mem_content = mfm.read_memory()
        user_content = mfm.read_user()
        if mem_content:
            agent.context.messages.insert(0, Message(role="system", content=f"[长期事实记忆]\n{mem_content}", created_at=""))
            logger.info("注入 MEMORY.md 长期记忆")
        if user_content:
            agent.context.messages.insert(0, Message(role="system", content=f"[用户偏好]\n{user_content}", created_at=""))
            logger.info("注入 USER.md 用户画像")
        logger.warning(f"[MEMORY] injected | context.messages count after={len(agent.context.messages)}")
    except Exception as e:
        logger.debug(f"平文件记忆注入跳过: {e}")
