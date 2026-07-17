"""Reusable helpers for AgentEngine.

These helpers keep `agent.py` focused on orchestration while moving small,
repeatable pieces of logic into a dedicated module.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.core.base import Message
from app.paths import data_path

logger = logging.getLogger(__name__)


def get_cli_executor(agent) -> Any:
    """Lazy-create the CLI executor used for terminal extraction."""
    if getattr(agent, "_cli_executor", None) is None:
        try:
            from app.domains import CLIExecutor
            agent._cli_executor = CLIExecutor(working_dir=".")
            logger.info("CLIExecutor 已初始化")
        except Exception as exc:
            logger.warning(f"CLIExecutor 初始化失败: {exc}")
    return agent._cli_executor


def try_fallback_llm(agent):
    """Try provider fallback when the current LLM fails."""
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
    except Exception as exc:
        logger.warning(f"获取 fallback LLM 失败: {exc}")
    return None


async def inject_domain_prompts(agent, session_id: str):
    """Inject domain knowledge prompts into the working context."""
    try:
        from app.domains import get_integrator
        integrator = get_integrator()
        prompt = integrator.get_all()
        if prompt:
            agent.context.messages.insert(0, Message(
                role="system",
                content=prompt,
                created_at="",
            ))
            logger.info(f"注入全部领域认知 ({len(integrator.get_domain_keys())} 个领域)")
        logger.warning(f"[DOMAIN] injected | context.messages count after={len(agent.context.messages)}")
    except Exception as exc:
        logger.warning(f"领域认知注入失败: {exc}")


def inject_base_system_prompt(agent):
    """Inject the base system prompt that defines the agent identity."""
    try:
        from app.core.system_prompt import get_system_prompt
        full_prompt = get_system_prompt()
        if not full_prompt:
            return
        agent.context.messages.insert(0, Message(
            role="system",
            content=full_prompt,
            created_at="",
        ))
        logger.warning(
            f"[SYS_PROMPT] injected | bytes={len(full_prompt)} | "
            f"context.messages count after={len(agent.context.messages)}"
        )
    except Exception as exc:
        logger.warning(f"基础 system prompt 注入失败: {exc}")


async def inject_memory(agent, session_id: str):
    """Inject MEMORY.md and USER.md content into the prompt stack."""
    try:
        from app.hermes.memory_file import MemoryFileManager
        mfm = MemoryFileManager(base_dir=data_path("hermes"))
        mem_content = mfm.read_memory()
        user_content = mfm.read_user()
        if mem_content:
            agent.context.messages.insert(0, Message(
                role="system",
                content=f"[长期事实记忆]\n{mem_content}",
                created_at="",
            ))
            logger.info("注入 MEMORY.md 长期记忆")
        if user_content:
            agent.context.messages.insert(0, Message(
                role="system",
                content=f"[用户偏好]\n{user_content}",
                created_at="",
            ))
            logger.info("注入 USER.md 用户画像")
        logger.warning(f"[MEMORY] injected | context.messages count after={len(agent.context.messages)}")
    except Exception as exc:
        logger.debug(f"平文件记忆注入跳过: {exc}")


def message_requires_tool_call(user_text: str) -> bool:
    text = (user_text or "").casefold()
    triggers = ("请使用", "务必调用", "必须调用", "用工具", "调用工具")
    return any(token in text for token in triggers)


def message_requires_visible_chrome(user_text: str) -> bool:
    text = (user_text or "").casefold()
    triggers = ("可视化", "可见窗口", "可见浏览器", "真实浏览器", "本地chrome", "本地 chrome", "google浏览器", "google chrome", "chrome浏览器", "用我的浏览器", "用我的 chrome", "在 chrome 里", "在浏览器里")
    return any(token in text for token in triggers)


def has_cdp_url(user_text: str) -> bool:
    text = user_text or ""
    return "ws://" in text and ("/json" in text or "/devtools/page/" in text)


def clean_thinking(text: str):
    """Remove <think>...</think> blocks and return cleaned text plus thoughts."""
    match = re.search(r'<think>([\s\S]*?)</think>', text)
    if match:
        thinking = match.group(1)
        cleaned = re.sub(r'<think>[\s\S]*?</think>', '', text, count=1).strip()
        return cleaned, thinking
    return text, ""


def format_tool_result_text(
    name: str,
    success: bool,
    result: str,
    error_msg: str = "",
    error_type: str = "",
    suggestion: str = "",
    tool_call_id: str = "",
) -> str:
    """Format tool execution results for downstream model consumption."""
    import json as _json

    emoji = "🔧"
    if success:
        preview = result.strip()[:500]
        if len(result.strip()) > 500:
            preview += "\n...[结果已截断]"
        content = f"[{emoji} {name}] 执行成功:\n{preview}"
    else:
        lines = [f"[{emoji} {name}] 执行失败: {error_msg}"]
        if error_type:
            lines.append(f"错误类型: {error_type}")
        if suggestion:
            lines.append(f"建议: {suggestion}")
        content = "\n".join(lines)

    return _json.dumps({"tool_call_id": tool_call_id, "content": content}, ensure_ascii=False)
