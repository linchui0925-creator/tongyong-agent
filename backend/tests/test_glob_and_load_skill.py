"""
glob 工具 + load_skill 别名回归测试 (W4-15 2026-06-22)

覆盖范围：
- glob: 注册 / schema 完整 / 跨目录递归 / 跳过 _PRUNE_DIRS / 隐藏文件 / max_results
- load_skill: 注册 / 与 skill_view 返回相同内容 / 都在 schemas 中

历史:
- 用户问"load_skill 是否有", 项目里叫 skill_view; 加别名让用户熟悉的命名直接命中
- glob 是新工具, 跟 ls 互补: ls 列目录, glob 按模式跨目录匹配
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 1. glob 工具注册与基础行为 ─────────────────────────

def test_glob_tool_is_registered():
    """glob 工具应注册到 toolset=terminal"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    entry = registry.get_entry("glob")
    assert entry is not None, "glob 工具未注册"
    assert entry.toolset == "terminal"
    assert entry.is_async is True


def test_glob_schema_exposes_pattern_as_required():
    """glob schema 必须有 pattern 必填, 与 Anthropic 工具签名一致"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    entry = registry.get_entry("glob")
    schema = entry.schema
    assert "pattern" in schema["properties"]
    assert "pattern" in schema["required"]
    # 可选参数也都暴露
    assert "path" in schema["properties"]
    assert "include_hidden" in schema["properties"]
    assert "max_results" in schema["properties"]


def test_glob_exposed_in_llm_schemas():
    """glob 应出现在 LLM 可见的 schemas 列表中"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    schemas = registry.get_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "glob" in names, f"glob 未暴露给 LLM, 当前: {names}"


# ── 2. glob 实际行为 ─────────────────────────────────

@pytest.mark.asyncio
async def test_glob_matches_py_files_recursively(tmp_path):
    """**/*.py 应跨目录找到所有 py 文件"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    # 造文件
    (tmp_path / "a.py").write_text("# a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("# b", encoding="utf-8")
    (tmp_path / "sub" / "deep").mkdir()
    (tmp_path / "sub" / "deep" / "c.py").write_text("# c", encoding="utf-8")
    (tmp_path / "readme.md").write_text("# md", encoding="utf-8")

    out = await registry.execute("glob", {"pattern": "**/*.py", "path": str(tmp_path)})
    assert "a.py" in out
    assert str(Path("sub/b.py")) in out
    assert str(Path("sub/deep/c.py")) in out
    assert "readme.md" not in out


@pytest.mark.asyncio
async def test_glob_skips_prune_dirs(tmp_path):
    """glob 应自动跳过 .git / .venv / node_modules / __pycache__"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    for d in [".git", ".venv", "node_modules", "__pycache__"]:
        (tmp_path / d).mkdir()
        (tmp_path / d / "skip_me.py").write_text("# skip", encoding="utf-8")
    # 但有 1 个保留的
    (tmp_path / "keep.py").write_text("# keep", encoding="utf-8")

    out = await registry.execute("glob", {"pattern": "**/*.py", "path": str(tmp_path)})
    assert "keep.py" in out
    assert "skip_me.py" not in out, f"应跳过 _PRUNE_DIRS, 实际: {out}"


@pytest.mark.asyncio
async def test_glob_excludes_hidden_by_default(tmp_path):
    """默认不显示 . 开头的文件"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    (tmp_path / "visible.py").write_text("# v", encoding="utf-8")
    (tmp_path / ".hidden.py").write_text("# h", encoding="utf-8")

    out = await registry.execute("glob", {"pattern": "*.py", "path": str(tmp_path)})
    assert "visible.py" in out
    assert ".hidden.py" not in out


@pytest.mark.asyncio
async def test_glob_includes_hidden_when_requested(tmp_path):
    """include_hidden=True 时应显示 . 开头的文件"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    (tmp_path / "visible.py").write_text("# v", encoding="utf-8")
    (tmp_path / ".hidden.py").write_text("# h", encoding="utf-8")

    out = await registry.execute("glob", {
        "pattern": "*.py", "path": str(tmp_path), "include_hidden": True
    })
    assert "visible.py" in out
    assert ".hidden.py" in out


@pytest.mark.asyncio
async def test_glob_truncates_at_max_results(tmp_path):
    """max_results 应限制返回数并提示"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    for i in range(10):
        (tmp_path / f"file{i:02d}.py").write_text("# f", encoding="utf-8")

    out = await registry.execute("glob", {
        "pattern": "*.py", "path": str(tmp_path), "max_results": 3
    })
    # 截断提示
    assert "已截断" in out
    # 最多 3 个 .py 加上截断提示
    py_count = sum(1 for line in out.split("\n") if line.endswith(".py"))
    assert py_count == 3, f"应返回 3 个, 实际 {py_count}"


@pytest.mark.asyncio
async def test_glob_empty_pattern_returns_error():
    """空 pattern 应返回 error 而不是空匹配"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    out = await registry.execute("glob", {"pattern": ""})
    assert "[error]" in out


@pytest.mark.asyncio
async def test_glob_nonexistent_path_returns_error():
    """不存在的 path 应返回 error"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    out = await registry.execute("glob", {
        "pattern": "**/*", "path": "/nonexistent_dir_xyz_abc"
    })
    assert "[error]" in out


@pytest.mark.asyncio
async def test_glob_no_match_returns_helpful_message():
    """无匹配应返回明确提示"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    out = await registry.execute("glob", {"pattern": "**/*.nope", "path": "."})
    assert "无匹配" in out


# ── 3. load_skill 别名 ─────────────────────────────────

def test_load_skill_is_registered():
    """load_skill 应当注册到 toolset=skill"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    entry = registry.get_entry("load_skill")
    assert entry is not None, "load_skill 未注册"
    assert entry.toolset == "skill"


def test_load_skill_and_skill_view_both_in_schemas():
    """两个名字都应暴露给 LLM (description 里说 alias, 不冲突)"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    names = [s["function"]["name"] for s in registry.get_schemas()]
    assert "load_skill" in names
    assert "skill_view" in names


def test_load_skill_description_mentions_alias():
    """load_skill description 应说明是 skill_view 的别名, 避免 LLM 误判为新工具"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    entry = registry.get_entry("load_skill")
    assert "alias" in entry.description.lower() or "skill_view" in entry.description


@pytest.mark.asyncio
async def test_load_skill_returns_same_content_as_skill_view():
    """load_skill 应与 skill_view 返回完全一致的内容"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    r1 = await registry.execute("load_skill", {"name": "code-review"})
    r2 = await registry.execute("skill_view", {"name": "code-review"})
    assert r1 == r2, "load_skill 与 skill_view 应返回相同内容"
    assert len(r1) > 0


@pytest.mark.asyncio
async def test_load_skill_handles_missing_skill():
    """不存在的 skill 应与 skill_view 一样返回 error 消息"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    r = await registry.execute("load_skill", {"name": "_does_not_exist_xyz_"})
    assert "[error]" in r


# ── 4. 总数 sanity check ─────────────────────────────

def test_total_tool_count_includes_new_tools():
    """验证 glob 和 load_skill 都进了总注册表"""
    from app.tools import registry, discover_builtin_tools
    discover_builtin_tools()
    all_names = registry.get_all_tool_names()
    assert "glob" in all_names
    assert "load_skill" in all_names
    # glob 在 terminal toolset
    assert "glob" in registry.get_tool_names_for_toolset("terminal")
    # load_skill 在 skill toolset
    assert "load_skill" in registry.get_tool_names_for_toolset("skill")
