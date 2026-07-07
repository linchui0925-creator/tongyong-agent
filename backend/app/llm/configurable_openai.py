"""
Configurable OpenAI-compatible LLM.

This is the runtime adapter for user-defined providers and relay APIs.  It keeps
the normal OpenAI chat-completions shape as the baseline, then lets each provider
profile add headers, default body fields, field aliases, response mapping, and a
tool-call parsing strategy without adding a new hardcoded provider class.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.base import Message
from app.llm.base import LLMError, LLMResponse, ToolCallResult
from app.llm.openai_compatible import OpenAICompatibleLLM

logger = logging.getLogger(__name__)


def _deep_get(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Read a dotted path such as choices.0.message.content from nested JSON."""
    if not path:
        return default
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        else:
            return default
    return cur


class ConfigurableOpenAICompatibleLLM(OpenAICompatibleLLM):
    """OpenAI-compatible adapter built from a provider profile."""

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        *,
        provider_id: str = "custom",
        base_url: str = "https://api.openai.com/v1",
        request_config: Optional[Dict[str, Any]] = None,
        model_overrides: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self.provider_id = provider_id
        self.api_base = (base_url or self.DEFAULT_API_BASE).rstrip("/")
        self.request_config = request_config or {}
        self.model_overrides = model_overrides or {}
        self.chat_path = self.request_config.get("chat_path") or "/chat/completions"
        self.models_path = self.request_config.get("models_path") or "/models"
        self.tool_call_mode = (
            self.model_overrides.get("tool_call_mode")
            or self.request_config.get("tool_call_mode")
            or "auto"
        )

    def _url(self, path: str) -> str:
        path = path or "/chat/completions"
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.api_base}/{path.lstrip('/')}"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.request_config.get("headers") or {})
        headers.update(self.model_overrides.get("headers") or {})
        return {k: str(v) for k, v in headers.items() if v is not None}

    def _request_max_tokens(self) -> int:
        override = self.model_overrides.get("max_tokens") or self.request_config.get("max_tokens")
        if override:
            return int(override)
        return super()._request_max_tokens()

    def _build_body(self, messages: List[Message], tools: Optional[List[Dict]] = None, *, stream: bool = False) -> Dict[str, Any]:
        openai_messages = self._normalize_messages(
            self._merge_system_messages(
                [{"role": m.role, "content": m.content} for m in messages]
            )
        )
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": getattr(self, "temperature", 0.7),
            "max_tokens": self._request_max_tokens(),
        }
        if tools:
            body["tools"] = tools
        if stream:
            body["stream"] = True

        for source in (
            self.request_config.get("body_defaults") or {},
            self.model_overrides.get("body_defaults") or {},
            self.request_config.get("body_overrides") or {},
            self.model_overrides.get("body_overrides") or {},
        ):
            body.update(source)

        mapping = self.request_config.get("field_mapping") or {}
        if mapping:
            for standard_key, mapped_key in list(mapping.items()):
                if standard_key in body and mapped_key and mapped_key != standard_key:
                    body[mapped_key] = body.pop(standard_key)
        return body

    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None) -> LLMResponse:
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")

        body = self._build_body(messages, tools)
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                    resp = await client.post(self._url(self.chat_path), headers=self._headers(), json=body)
                    resp.raise_for_status()
                    return self._parse_response(self._decode_json_response(resp))
            except httpx.TimeoutException:
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError("请求超时", "TIMEOUT")
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "自定义供应商 HTTP 错误 provider=%s status=%s body=%s",
                    self.provider_id,
                    e.response.status_code,
                    e.response.text[:300],
                )
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError(f"HTTP错误: {e.response.status_code}", "HTTP_ERROR", e.response.text[:500])
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError(f"请求失败: {e}", "REQUEST_FAILED")

        raise LLMError("请求失败", "REQUEST_FAILED")

    async def stream_chat(self, messages: List[Message]):
        body = self._build_body(messages, stream=True)
        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
            async with client.stream("POST", self._url(self.chat_path), headers=self._headers(), json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    try:
                        data = json.loads(line[5:])
                    except json.JSONDecodeError:
                        continue
                    delta = _deep_get(data, "choices.0.delta", {}) or {}
                    text = delta.get("content") or delta.get("reasoning_content") or ""
                    if text:
                        yield text

    async def fetch_models(self) -> List[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._url(self.models_path), headers=self._headers())
            resp.raise_for_status()
            data = self._decode_json_response(resp)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        models = []
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                models.append(str(item["id"]))
            elif isinstance(item, str):
                models.append(item)
        return models

    def _parse_response(self, result: Dict[str, Any]) -> LLMResponse:
        mapping = self.request_config.get("response_mapping") or {}
        content_path = mapping.get("content", "choices.0.message.content")
        reasoning_path = mapping.get("reasoning_content", "choices.0.message.reasoning_content")
        tool_calls_path = mapping.get("tool_calls", "choices.0.message.tool_calls")

        content = _deep_get(result, content_path, "") or ""
        reasoning_content = _deep_get(result, reasoning_path, "") or ""
        if not str(content).strip() and reasoning_content:
            content = reasoning_content

        raw_usage = result.get("usage") or {}
        usage = {
            "input_tokens": raw_usage.get("prompt_tokens", raw_usage.get("input_tokens", 0)),
            "output_tokens": raw_usage.get("completion_tokens", raw_usage.get("output_tokens", 0)),
            "total_tokens": raw_usage.get("total_tokens", 0),
        } if raw_usage else {}

        raw_tool_calls = _deep_get(result, tool_calls_path, []) or []
        if raw_tool_calls and self.tool_call_mode != "disabled":
            tool_calls = []
            for tc in raw_tool_calls:
                func = tc.get("function", {}) if isinstance(tc, dict) else {}
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCallResult(
                    tool_name=func.get("name", ""),
                    arguments=args,
                    tool_call_id=tc.get("id", "") if isinstance(tc, dict) else "",
                ))
            return LLMResponse(content=str(content), tool_calls=tool_calls, usage=usage)

        if self.tool_call_mode in {"auto", "xml_fallback", "minimax_xml"}:
            from app.llm.xml_tool_call_parser import parse_xml_tool_calls

            xml_calls, cleaned = parse_xml_tool_calls(str(content))
            if xml_calls:
                return LLMResponse(content=cleaned, tool_calls=xml_calls, usage=usage)
            if reasoning_content and reasoning_content != content:
                xml_calls, _ = parse_xml_tool_calls(str(reasoning_content))
                if xml_calls:
                    return LLMResponse(content=str(content), tool_calls=xml_calls, usage=usage)

        return LLMResponse(content=str(content), usage=usage)
