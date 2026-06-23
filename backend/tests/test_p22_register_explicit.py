"""
P2-2 W4-21: 工具模块 _register_tools() 显式注册测试
"""

import pytest


def test_register_tools_function_exists():
    """所有有 registry.register 的实现模块应当有 _register_tools 函数"""
    from app.tools.registry import _module_registers_tools
    import app.tools.implementations as impl
    from pathlib import Path
    impl_dir = Path(impl.__file__).parent
    for py in sorted(impl_dir.glob("*.py")):
        if py.name.startswith("_") or py.name == "registry.py":
            continue
        # 只检查会触发注册的模块 (有 registry.register / _register_tools)
        if not _module_registers_tools(py):
            continue
        mod = __import__(f"app.tools.implementations.{py.stem}", fromlist=["*"])
        assert hasattr(mod, "_register_tools"), \
            f"{py.name} 应当有 _register_tools() 函数 (P2-2 显式注册)"


def test_register_tools_idempotent():
    """多次调 _register_tools() 不应抛 (registry 内部处理重复)"""
    from app.tools.implementations import terminal
    terminal._register_tools()
    terminal._register_tools()  # 第二次应 no-op
    from app.tools.registry import registry
    assert "terminal" in registry.get_all_tool_names()


def test_discover_calls_register_tools(monkeypatch):
    """discover_builtin_tools 显式调 _register_tools"""
    from app.tools.registry import registry
    from app.tools import discover_builtin_tools
    from app.tools.implementations import terminal

    called = []
    orig = terminal._register_tools
    def spy():
        called.append("terminal")
        orig()
    monkeypatch.setattr(terminal, "_register_tools", spy)

    registry.clear()
    discover_builtin_tools()
    assert "terminal" in called, "discover_builtin_tools 应当显式调 terminal._register_tools()"


def test_mock_register_tools_no_registration(monkeypatch):
    """测试可 mock _register_tools 来不注册"""
    from app.tools.registry import registry
    from app.tools import discover_builtin_tools
    from app.tools.implementations import terminal

    monkeypatch.setattr(terminal, "_register_tools", lambda: None)
    registry.clear()
    discover_builtin_tools()
    assert "terminal" not in registry.get_all_tool_names(), \
        "mock _register_tools=空函数时, terminal 不应被注册"
