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
- 工具能力描述通过 env_capabilities.py 动态生成
- 工具 discovery 通过 grep/ls 方式自我感知（读 tools.md 或 registry）
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


def generate_tools_md():
    """将所有已注册工具生成 domains/tools/tools.md，供 Agent 动态检索"""
    _pkg = Path(__file__).resolve().parent.parent
    _TOOLS_MD_PATH = _pkg / "domains" / "tools" / "tools.md"

    tools_by_toolset = {}
    for entry in registry._snapshot_entries():
        if entry.check_fn:
            try:
                if not entry.check_fn():
                    continue
            except Exception:
                pass
        tools_by_toolset.setdefault(entry.toolset, []).append(entry)

    toolset_labels = {
        "file": "📁 文件操作",
        "terminal": "💻 终端命令",
        "browser": "🌐 浏览器自动化",
        "web": "🔍 网络搜索",
        "desktop": "🖥️ macOS 桌面",
        "android": "📱 Android 设备",
        "interactive": "❓ 交互提问",
        "skill": "🎯 Skill 工具",
        "agent": "🔀 多 Agent 委派",
    }

    lines = [
        "你内置了工具执行框架，通过 **function calling（函数调用）** 执行操作。",
        "",
        "## 核心规则：必须用 function calling，不要在文字中假装执行",
        "",
        "在文字中描述工具操作 = 没有实际执行。你必须直接调用对应的函数（tool_calls）。",
        "",
        "## 可用工具清单",
        "",
        "遇到任务时，如果不确定该用什么工具，**先读取以下清单**，根据工具的 description 判断最合适的工具。",
        "工具描述中的 **必填参数**（required）和 **可选参数**（optional）来自工具的 JSON schema。",
        "",
    ]

    for ts, label in toolset_labels.items():
        entries = tools_by_toolset.get(ts, [])
        if not entries:
            continue
        lines.append(f"### {label}\n")
        for e in sorted(entries, key=lambda x: x.name):
            lines.append(f"#### `{e.name}`")
            lines.append(e.description.strip())
            schema = e.schema if isinstance(e.schema, dict) else {}
            params = schema.get("properties", {})
            required = schema.get("required", [])
            if params:
                lines.append("")
                lines.append("**参数：**")
                for pname, pinfo in params.items():
                    ptype = pinfo.get("type", "any")
                    pdesc = pinfo.get("description", "").replace("\n", " ")
                    req = "【必填】" if pname in required else "【可选】"
                    enum = pinfo.get("enum")
                    enum_str = f"（枚举: {', '.join(enum)}）" if enum else ""
                    default = f"，默认: {pinfo.get('default')}" if "default" in pinfo else ""
                    lines.append(f"- `{pname}` ({ptype}) {req} {pdesc}{enum_str}{default}")
            lines.append("")

    lines.extend([
        "## 使用规则",
        "1. 直接调函数，不要用文字描述执行过程",
        "2. 工具结果会自动展示，你基于结果回复即可",
        "3. 只说不做 = 欺骗用户",
    ])

    content = "\n".join(lines)
    try:
        _TOOLS_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOOLS_MD_PATH.write_text(content, encoding="utf-8")
        logger.info(f"tools.md 已生成，共 {len(registry.get_all_tool_names())} 个工具")
    except Exception as ex:
        logger.warning(f"生成 tools.md 失败: {ex}")


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
