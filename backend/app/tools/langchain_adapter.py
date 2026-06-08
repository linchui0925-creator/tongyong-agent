"""
Tool LangChain 适配器 — 把 ToolRegistry 工具转换为 LangChain StructuredTool

让现有工具可以直接用于 LangChain Agent。
"""

import json
import logging
from typing import Any, Dict, List, Optional, Type

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from app.tools.registry import ToolEntry, registry

logger = logging.getLogger(__name__)


def _json_type_to_python(json_type: str) -> Type:
    """JSON Schema type → Python type"""
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    return mapping.get(json_type, str)


def schema_to_pydantic(name: str, schema: dict) -> Type[BaseModel]:
    """JSON Schema → Pydantic BaseModel（动态生成）"""
    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    fields = {}
    for prop_name, prop_def in properties.items():
        prop_type = _json_type_to_python(prop_def.get("type", "string"))
        description = prop_def.get("description", "")
        is_required = prop_name in required_fields

        if is_required:
            fields[prop_name] = (prop_type, Field(description=description))
        else:
            default = prop_def.get("default")
            fields[prop_name] = (prop_type, Field(default=default, description=description))

    if not fields:
        # 无参数工具
        fields["dummy"] = (Optional[str], Field(default=None, description="无参数"))

    return create_model(f"{name}Args", **fields)


def entry_to_langchain_tool(entry: ToolEntry) -> StructuredTool:
    """单个 ToolEntry → LangChain StructuredTool"""
    args_schema = schema_to_pydantic(entry.name, entry.schema or {"type": "object", "properties": {}})

    async def _async_handler(**kwargs) -> str:
        # 移除 dummy 参数
        kwargs.pop("dummy", None)
        try:
            if entry.is_async:
                result = await entry.handler(**kwargs)
            else:
                result = entry.handler(**kwargs)
            max_chars = entry.max_result_size_chars
            if max_chars and isinstance(result, str) and len(result) > max_chars:
                result = result[:max_chars] + f"\n...（结果过长，已截断至 {max_chars} 字符）"
            return str(result)
        except Exception as e:
            logger.error(f"工具 '{entry.name}' 执行失败: {e}", exc_info=True)
            return f"工具执行失败: {e}"

    return StructuredTool(
        name=entry.name,
        description=entry.description or f"工具: {entry.name}",
        args_schema=args_schema,
        coroutine=_async_handler,
        func=None,  # 不提供同步版本
    )


def registry_to_langchain_tools(
    tool_names: Optional[List[str]] = None,
) -> List[StructuredTool]:
    """把 ToolRegistry 的工具转为 LangChain StructuredTool 列表

    Args:
        tool_names: 要转换的工具名列表。None = 所有可用工具。
    """
    if tool_names is None:
        tool_names = registry.get_all_tool_names()

    tools = []
    for name in sorted(tool_names):
        entry = registry.get_entry(name)
        if not entry:
            continue
        # 检查 check_fn
        if entry.check_fn:
            try:
                if not entry.check_fn():
                    continue
            except Exception:
                continue
        tools.append(entry_to_langchain_tool(entry))

    logger.info(f"[LangChain] 转换了 {len(tools)} 个工具: {[t.name for t in tools]}")
    return tools
