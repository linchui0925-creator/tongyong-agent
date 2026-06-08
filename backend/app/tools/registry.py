"""
ToolRegistry - 工具注册中心（Hermes 风格重构版）

Architecture:
- 每个工具属于一个 toolset（工具集），如 file/terminal/browser/web/skill/mcp
- 工具模块在模块级调用 registry.register() 自注册
- registry 自动发现 implementations/ 下的工具模块
- MCP/Plugin 工具可动态注册/注销
- 线程安全：所有状态变更通过锁保护

Key differences from hermes-agent:
- 不把工具清单写死进 system prompt
- Agent 通过 registry.get_schemas() 获取 function calling schema
- 工具能力描述通过 env_capabilities.py 动态生成（按 toolset 分组的人类可读清单）
- 工具集清单 + schema 都走结构化 API（registry / API tools 参数），**没有** tools.md 这类 markdown 镜像
  （P4 2026-06-02 删了 generate_tools_md() 写盘——那是反模式）
"""

import ast
import importlib
import json
import logging
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Any

logger = logging.getLogger(__name__)

_TOOLS_DIR = Path(__file__).resolve().parent / "implementations"


def _is_registry_register_call(node: ast.AST) -> bool:
    """Return True when *node* is a ``registry.register(...)`` call expression."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "register"
        and isinstance(func.value, ast.Name)
        and func.value.id == "registry"
    )


def _module_registers_tools(module_path: Path) -> bool:
    """Return True when the module contains a top-level ``registry.register(...)`` call."""
    try:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
    except (OSError, SyntaxError):
        return False
    return any(_is_registry_register_call(stmt) for stmt in tree.body)


class ToolEntry:
    """单个工具的元数据"""

    __slots__ = (
        "name", "toolset", "schema", "handler", "check_fn",
        "requires_env", "is_async", "description", "emoji",
        "max_result_size_chars", "parallel_mode",
    )

    def __init__(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
        requires_env: Optional[List[str]] = None,
        is_async: bool = True,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: Optional[int] = None,
        parallel_mode: str = "never",
    ):
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.check_fn = check_fn
        self.requires_env = requires_env or []
        self.is_async = is_async
        self.description = description
        self.emoji = emoji
        self.max_result_size_chars = max_result_size_chars
        self.parallel_mode = parallel_mode  # "never" | "safe" | "path_scoped"


class ToolRegistry:
    """工具注册中心（线程安全单例）"""

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._toolset_checks: Dict[str, Callable] = {}
        self._toolset_aliases: Dict[str, str] = {}
        self._lock = threading.RLock()

    def _snapshot_entries(self) -> List[ToolEntry]:
        """Return a stable snapshot of registered tool entries."""
        with self._lock:
            return list(self._tools.values())

    def _snapshot_state(self) -> tuple:
        with self._lock:
            return list(self._tools.values()), dict(self._toolset_checks)

    def _evaluate_toolset_check(self, toolset: str, check: Optional[Callable]) -> bool:
        if not check:
            return True
        try:
            return bool(check())
        except Exception:
            logger.debug("Toolset %s check raised; marking unavailable", toolset)
            return False

    # ── 注册 ──────────────────────────────────────────────

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
        requires_env: Optional[List[str]] = None,
        is_async: bool = True,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: Optional[int] = None,
        parallel_mode: str = "never",
    ):
        """注册工具（模块级调用，或 MCP/Plugin 动态注册）"""
        with self._lock:
            existing = self._tools.get(name)
            if existing and existing.toolset != toolset:
                # Allow MCP-to-MCP overwrites
                both_mcp = (
                    existing.toolset.startswith("mcp-")
                    and toolset.startswith("mcp-")
                )
                if not both_mcp:
                    logger.error(
                        "Tool '%s' (toolset '%s') would shadow existing tool from '%s'. "
                        "Deregister first if intentional.",
                        name, toolset, existing.toolset,
                    )
                    return
            self._tools[name] = ToolEntry(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env or [],
                is_async=is_async,
                description=description or schema.get("description", ""),
                emoji=emoji,
                max_result_size_chars=max_result_size_chars,
                parallel_mode=parallel_mode,
            )
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn
        logger.debug("Registered tool: %s (toolset: %s)", name, toolset)

    def deregister(self, name: str) -> None:
        """注销工具（用于 MCP 动态刷新）"""
        with self._lock:
            entry = self._tools.pop(name, None)
            if entry is None:
                return
            toolset_still_exists = any(
                e.toolset == entry.toolset for e in self._tools.values()
            )
            if not toolset_still_exists:
                self._toolset_checks.pop(entry.toolset, None)
                self._toolset_aliases = {
                    alias: target
                    for alias, target in self._toolset_aliases.items()
                    if target != entry.toolset
                }
        logger.debug("Deregistered tool: %s", name)

    def register_toolset_alias(self, alias: str, toolset: str) -> None:
        """注册 toolset 别名（如 "browser" → "browser_tools"）"""
        with self._lock:
            self._toolset_aliases[alias] = toolset

    # ── 查询 ──────────────────────────────────────────────

    def get_entry(self, name: str) -> Optional[ToolEntry]:
        with self._lock:
            return self._tools.get(name)

    def get_all_tool_names(self) -> List[str]:
        """返回所有已注册工具名（排序）"""
        return sorted(entry.name for entry in self._snapshot_entries())

    def get_schema(self, name: str) -> Optional[dict]:
        """返回工具原始 schema（绕过 check_fn），用于 token 估算"""
        entry = self.get_entry(name)
        return entry.schema if entry else None

    def get_toolset_for_tool(self, name: str) -> Optional[str]:
        entry = self.get_entry(name)
        return entry.toolset if entry else None

    def get_tool_to_toolset_map(self) -> Dict[str, str]:
        return {entry.name: entry.toolset for entry in self._snapshot_entries()}

    def get_toolset_alias_target(self, alias: str) -> Optional[str]:
        with self._lock:
            return self._toolset_aliases.get(alias)

    def get_registered_toolset_names(self) -> List[str]:
        return sorted({entry.toolset for entry in self._snapshot_entries()})

    def get_tool_names_for_toolset(self, toolset: str) -> List[str]:
        return sorted(
            entry.name for entry in self._snapshot_entries()
            if entry.toolset == toolset
        )

    def is_toolset_available(self, toolset: str) -> bool:
        with self._lock:
            check = self._toolset_checks.get(toolset)
        return self._evaluate_toolset_check(toolset, check)

    def check_toolset_requirements(self) -> Dict[str, bool]:
        """返回 {toolset: available_bool}"""
        entries, toolset_checks = self._snapshot_state()
        toolsets = sorted({entry.toolset for entry in entries})
        return {
            toolset: self._evaluate_toolset_check(toolset, toolset_checks.get(toolset))
            for toolset in toolsets
        }

    def get_available_toolsets(self) -> Dict[str, dict]:
        """返回 toolset 元数据（用于 UI 显示）"""
        toolsets: Dict[str, dict] = {}
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts not in toolsets:
                toolsets[ts] = {
                    "available": self._evaluate_toolset_check(ts, toolset_checks.get(ts)),
                    "tools": [],
                    "description": "",
                    "requirements": [],
                }
            toolsets[ts]["tools"].append(entry.name)
            for env in entry.requires_env:
                if env not in toolsets[ts]["requirements"]:
                    toolsets[ts]["requirements"].append(env)
        return toolsets

    def get_toolset_requirements(self) -> Dict[str, dict]:
        """返回 toolset 详细信息（向后兼容）"""
        result: Dict[str, dict] = {}
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts not in result:
                result[ts] = {
                    "name": ts,
                    "env_vars": [],
                    "check_fn": toolset_checks.get(ts),
                    "setup_url": None,
                    "tools": [],
                }
            if entry.name not in result[ts]["tools"]:
                result[ts]["tools"].append(entry.name)
            for env in entry.requires_env:
                if env not in result[ts]["env_vars"]:
                    result[ts]["env_vars"].append(env)
        return result

    def check_tool_availability(self, quiet: bool = False) -> tuple:
        """返回 (available_toolsets, unavailable_info)"""
        available = []
        unavailable = []
        seen = set()
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts in seen:
                continue
            seen.add(ts)
            if self._evaluate_toolset_check(ts, toolset_checks.get(ts)):
                available.append(ts)
            else:
                unavailable.append({
                    "name": ts,
                    "env_vars": entry.requires_env,
                    "tools": [e.name for e in entries if e.toolset == ts],
                })
        return available, unavailable

    # ── Schema 检索 ──────────────────────────────────────────

    def get_definitions(self, tool_names: Set[str], quiet: bool = False) -> List[dict]:
        """返回 OpenAI-format tool schemas（只包含 check_fn 通过的工具）

        格式：{
          "type": "function",
          "function": {
            "name": "tool_name",
            "description": "工具描述",
            "parameters": { /* JSON Schema */ }
          }
        }
        """
        result = []
        check_results: Dict[Callable, bool] = {}
        entries_by_name = {entry.name: entry for entry in self._snapshot_entries()}
        for name in sorted(tool_names):
            entry = entries_by_name.get(name)
            if not entry:
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    try:
                        check_results[entry.check_fn] = bool(entry.check_fn())
                    except Exception:
                        check_results[entry.check_fn] = False
                if not check_results[entry.check_fn]:
                    if not quiet:
                        logger.debug("Tool %s unavailable (check failed)", name)
                    continue
            # OpenAI function calling 格式：description + parameters 分开
            # entry.schema 是 JSON Schema（type, properties, required）
            func_obj: Dict[str, Any] = {
                "name": entry.name,
                "description": entry.description or "",
                "parameters": entry.schema or {"type": "object", "properties": {}},
            }
            result.append({"type": "function", "function": func_obj})
        return result

    def get_schemas(self) -> List[Dict[str, Any]]:
        """返回所有可用工具的 OpenAI function calling schema（向后兼容）"""
        return self.get_definitions(set(self.get_all_tool_names()))

    # ── 执行 ──────────────────────────────────────────────

    async def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        entry = self.get_entry(name)
        if not entry:
            logger.warning(f"工具 '{name}' 未注册，当前已注册工具: {list(self._tools.keys())}")
            return f"未知工具: {name}"
        try:
            if entry.is_async:
                result = await entry.handler(**arguments)
            else:
                result = entry.handler(**arguments)
            max_chars = entry.max_result_size_chars
            if max_chars and isinstance(result, str) and len(result) > max_chars:
                result = result[:max_chars] + f"\n...（结果过长，已截断至 {max_chars} 字符）"
            return str(result)
        except Exception as e:
            logger.error(f"工具 '{name}' 执行失败: {e}", exc_info=True)
            return f"工具执行失败: {e}"

    def dispatch(self, name: str, args: dict) -> str:
        """同步执行工具（向后兼容 agent.py 用）"""
        entry = self.get_entry(name)
        if not entry:
            return json.dumps({"error": f"未知工具: {name}"})
        try:
            if entry.is_async:
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(
                    entry.handler(**args)
                )
            else:
                result = entry.handler(**args)
            max_chars = entry.max_result_size_chars
            if max_chars and isinstance(result, str) and len(result) > max_chars:
                result = result[:max_chars] + f"\n...（结果过长，已截断至 {max_chars} 字符）"
            return str(result)
        except Exception as e:
            logger.error(f"工具 '{name}' 执行失败: {e}", exc_info=True)
            return json.dumps({"error": f"工具执行失败: {e}"})

    def get_emoji(self, name: str, default: str = "⚡") -> str:
        entry = self.get_entry(name)
        return entry.emoji if entry and entry.emoji else default

    def get_parallel_mode(self, name: str) -> str:
        entry = self.get_entry(name)
        return entry.parallel_mode if entry else "never"

    def classify_tool_calls(self, tool_calls: List[Dict]) -> Dict[str, List[Dict]]:
        """按并行模式对工具调用进行分组"""
        groups: Dict[str, List[Dict]] = {"never": [], "safe": [], "path_scoped": []}
        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name") or tc.get("name", "")
            mode = self.get_parallel_mode(tool_name)
            groups.get(mode, groups["never"]).append(tc)
        return groups

    def get_max_result_size(self, name: str, default: Optional[int] = None) -> Optional[int]:
        entry = self.get_entry(name)
        if entry and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        return default

    def clear(self):
        with self._lock:
            self._tools.clear()
            self._toolset_checks.clear()
            self._toolset_aliases.clear()


# 全局单例
registry = ToolRegistry()


def discover_builtin_tools() -> List[str]:
    """自动发现并导入所有内置工具模块"""
    if not _TOOLS_DIR.exists():
        logger.warning(f"工具目录不存在: {_TOOLS_DIR}")
        return []

    imported = []
    for py_file in sorted(_TOOLS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        if py_file.name in ("registry.py",):
            continue
        if not _module_registers_tools(py_file):
            continue
        mod_name = f"app.tools.implementations.{py_file.stem}"
        try:
            importlib.import_module(mod_name)
            imported.append(py_file.stem)
        except Exception as e:
            logger.warning(f"导入工具模块失败 {mod_name}: {e}")

    if imported:
        logger.info(f"已加载工具模块: {', '.join(imported)}")

    return imported


# MCP tool discovery (可被 model_tools.py 调用)
def discover_mcp_tools():
    """从配置发现 MCP 服务器并注册工具"""
    try:
        from app.tools.mcp_client import discover_mcp_tools as _discover
        _discover()
    except ImportError:
        logger.debug("MCP client not available")
    except Exception as e:
        logger.debug("MCP tool discovery failed: %s", e)


# Tool result helpers (向后兼容 skill_tools 用 tool_result)
def tool_error(message, **extra) -> str:
    result = {"error": str(message)}
    if extra:
        result.update(extra)
    return json.dumps(result, ensure_ascii=False)


def tool_result(data=None, **kwargs) -> str:
    if data is not None:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(kwargs, ensure_ascii=False)
