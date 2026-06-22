"""
Skills 索引回归测试 (W4-12 修复 2026-06-21)

覆盖范围：
- get_skills_prompt 上传新 skill 后能感知 mtime 变化 (旧实现 _detected 永久缓存)
- format_skills_prompt 长描述 80 字符截断加 ... (旧实现硬切无省略号)
- _last_mtime / _last_index 跟踪 (移除死代码 _cached_scan)
- refresh() 同时清 _last_skills_prompt_mtime

历史:
- skills_index.py 旧实现 _detected 只在首次 None 时生成, 之后再调用永远返回旧字符串
  上传新 skill 后 system prompt 看不到, 排查起来以为是 agent 没读到
- _cached_scan / @lru_cache(maxsize=1) 死代码, 从未 cache_clear, 注释还说
  "lru_cache 不支持 mtime 感知的失效" — 那就别用了
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.core.skills_index as si
from app.core.skills_index import (
    format_skills_prompt,
    get_skills_index,
    get_skills_prompt,
    refresh,
)


@pytest.fixture
def clean_skill_env(tmp_path, monkeypatch):
    """用 tmp_path 替换 hermes_skills_dir, 测试后还原"""
    monkeypatch.setattr(si, "_SKILLS_BASE_DIR", tmp_path)
    si._detected = None
    si._last_skills_prompt_mtime = 0.0
    si._last_mtime = 0.0
    si._last_index = {}
    yield tmp_path
    # 清理
    si._detected = None
    si._last_skills_prompt_mtime = 0.0
    si._last_mtime = 0.0
    si._last_index = {}


# ── 1. mtime-aware prompt refresh (主修复) ─────────────────

def test_get_skills_prompt_refreshes_on_new_skill_upload(clean_skill_env):
    """上传新 skill 后, get_skills_prompt 应当感知 mtime 变化, 生成新内容"""
    base = clean_skill_env

    # 第一次调用: 空目录
    p1 = get_skills_prompt()
    assert "新上传的 skill" not in p1

    # 上传新 skill
    skill_dir = base / "general"
    skill_dir.mkdir(parents=True)
    new_skill = skill_dir / "新上传的 skill"
    new_skill.mkdir()
    (new_skill / "SKILL.md").write_text(
        "---\ndescription: 上传后应当被感知\n---\nbody", encoding="utf-8"
    )
    # mtime 精度问题, 强制等一下
    time.sleep(0.05)

    # 第二次调用: 应当刷新
    p2 = get_skills_prompt()
    assert "新上传的 skill" in p2, (
        f"上传后 get_skills_prompt 未刷新, 旧实现 _detected 永久缓存"
    )
    assert p1 is not p2, "应当返回新对象"


def test_get_skills_prompt_returns_same_object_when_mtime_unchanged(clean_skill_env):
    """mtime 没变时, 多次调用应当返回同一对象 (cache 仍然有效)"""
    p1 = get_skills_prompt()
    p2 = get_skills_prompt()
    p3 = get_skills_prompt()
    assert p1 is p2 is p3, "mtime 未变时应当复用缓存"


def test_get_skills_prompt_does_not_pollute_index_with_underscore_dirs(clean_skill_env):
    """以下划线开头的目录应当被忽略 (与 _scan_skills 行为一致)"""
    base = clean_skill_env
    # _ 开头目录: 应被忽略
    (base / "_hidden").mkdir()
    (base / "_hidden" / "x").mkdir()
    (base / "_hidden" / "x" / "SKILL.md").write_text("---", encoding="utf-8")
    time.sleep(0.05)

    out = format_skills_prompt()
    assert "_hidden" not in out
    assert "x" not in out.split("</available_skills>")[1] if "</available_skills>" in out else True


# ── 2. 长描述截断加省略号 ─────────────────────────────────

def test_long_description_truncated_with_ellipsis(clean_skill_env):
    """>80 字符的 system skill 描述应当被截断到 80 字符, 末尾加 ..."""
    base = clean_skill_env
    skill_dir = base / "general"
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "long-desc-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        f"---\ndescription: {'A' * 200}\nskill_type: system\nauto_load: true\n---\nbody",
        encoding="utf-8",
    )
    time.sleep(0.05)

    out = format_skills_prompt()
    for line in out.split("\n"):
        if "long-desc-skill" in line and "🔒" in line:
            # 实际行: - 🔒 `long-desc-skill`: AAAAA...A...
            assert line.rstrip().endswith("..."), (
                f"长描述未加省略号: ...{line[-20:]!r}"
            )
            # 描述部分: 80 字符限制 = "AAA...AAA..." 中 AAA 77 个 + "..."
            # 整行合理长度 < 110 (前缀 "- 🔒 `long-desc-skill`: " 大约 28 字符)
            assert len(line) < 110, f"行过长, 截断未生效: {len(line)}"


def test_short_description_not_truncated(clean_skill_env):
    """≤80 字符的描述应当原样保留, 不加省略号"""
    base = clean_skill_env
    skill_dir = base / "general"
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "short-skill"
    skill.mkdir()
    short_desc = "Short description under 80 chars"
    (skill / "SKILL.md").write_text(
        f"---\ndescription: {short_desc}\nskill_type: system\nauto_load: true\n---\nbody",
        encoding="utf-8",
    )
    time.sleep(0.05)

    out = format_skills_prompt()
    assert short_desc in out
    # 不该出现 ... 在 short 描述后
    for line in out.split("\n"):
        if "short-skill" in line and "🔒" in line:
            assert not line.rstrip().endswith("..."), f"短描述不该被加省略号: {line!r}"


# ── 3. _last_mtime / _last_index 跟踪 (死代码移除) ─────────

def test_get_skills_index_uses_last_index_when_mtime_unchanged(clean_skill_env):
    """mtime 未变时, get_skills_index 应当复用 _last_index"""
    base = clean_skill_env
    skill_dir = base / "general"
    skill_dir.mkdir(parents=True)
    (skill_dir / "a").mkdir()
    (skill_dir / "a" / "SKILL.md").write_text("---", encoding="utf-8")
    time.sleep(0.05)

    idx1 = get_skills_index()
    assert "a" in idx1
    # 再次调用: mtime 没变, 应当返回同一对象
    idx2 = get_skills_index()
    assert idx1 is idx2, "mtime 未变应当复用 _last_index"


def test_cached_scan_dead_code_removed(clean_skill_env):
    """_cached_scan / @lru_cache 死代码已被移除"""
    # 模块不应有 _cached_scan 函数
    assert not hasattr(si, "_cached_scan"), "_cached_scan 死代码未删除"
    # 检查源码: 没有 @lru_cache 装饰器 (允许 docstring 提到历史)
    import app.core.skills_index as m
    with open(m.__file__, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    # 检查真正的 @lru_cache 装饰器语法: 行首有 @lru_cache( 或 @lru_cache

    decorator_lines = [l for l in lines if l.lstrip().startswith("@lru_cache")]
    assert len(decorator_lines) == 0, f"lru_cache 装饰器残留: {decorator_lines}"
    # 没有 _cached_scan 函数定义
    def_lines = [l for l in lines if l.startswith("def _cached_scan")]
    assert len(def_lines) == 0, f"_cached_scan 函数残留: {def_lines}"
    # 没有 _cached_scan() 调用
    call_lines = [l for l in lines if "_cached_scan(" in l]
    assert len(call_lines) == 0, f"_cached_scan() 调用残留: {call_lines}"


# ── 4. refresh() 也清 _last_skills_prompt_mtime ───────────

def test_refresh_resets_detected_and_regenerates(clean_skill_env):
    """refresh() 应当重置 _detected 并重新生成, 让当前 mtime 立刻生效

    关键点: refresh 内部把 _detected = None 后调 get_skills_prompt(), 
    那里会重新计算 current_mtime 并写回 _last_skills_prompt_mtime.
    所以 _last_skills_prompt_mtime 在 refresh 后 = current_mtime, 不是 0.
    """
    base = clean_skill_env
    p1 = get_skills_prompt()
    pre_mtime = si._last_skills_prompt_mtime
    assert pre_mtime > 0  # 第一次调用后已经写入

    # refresh 触发新一轮
    out = refresh()
    # _detected 被 reset 后重新生成, 不为 None
    assert si._detected is not None
    # _last_skills_prompt_mtime 应当被重新写为当前 mtime
    assert si._last_skills_prompt_mtime > 0
    # 核心断言: 第二次 refresh 后, 调用应当复用缓存 (mtime 没变)
    p2 = get_skills_prompt()
    assert p2 is out, "refresh 后同一 mtime 应当复用 _detected"


def test_refresh_re_picks_up_new_skill(clean_skill_env):
    """refresh() 后新 skill 应当立即可见 (不需等 mtime 触发)"""
    base = clean_skill_env
    refresh()  # baseline

    # 上传新 skill
    skill_dir = base / "general"
    skill_dir.mkdir(parents=True)
    new_skill = skill_dir / "refresh-test-skill"
    new_skill.mkdir()
    (new_skill / "SKILL.md").write_text(
        "---\ndescription: refresh 应当立即看到\n---\nbody", encoding="utf-8"
    )

    out = refresh()
    assert "refresh-test-skill" in out
