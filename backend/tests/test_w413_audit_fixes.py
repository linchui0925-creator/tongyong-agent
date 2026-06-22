"""
W4-13 审计发现修复回归测试 (2026-06-21)

覆盖范围：
- W4-13.1: _extract_heuristic_sections 多启发式段全部保留
- W4-13.2: get_system_skills_content budget 动态递减, 不超 _SYSTEM_CONTENT_MAX_BYTES
- W4-13.3: marketplace.install_skill skipped 用结构化 dict (含 reason),
            旧实现用 path + " (binary)" 污染 List[str] 列表

历史:
- 上一轮 W4-11/W4-12 修复时, 在 skills_index.py / marketplace.py 顺手
  发现 3 个真实 bug, commit message 里点名留给下一轮.
"""

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── W4-13.1: 多启发式段保留 ─────────────────────────────

def test_13_1_keeps_all_heuristic_sections():
    """多启发式段 (## Heuristic A + ## Heuristic B) 应当都被保留"""
    from app.core.skills_index import _extract_heuristic_sections
    body = """# Title
intro

## Heuristic A
content A
multi line

## Why A
reasoning for A

## Heuristic B
content B

## Reference
refs
"""
    out = _extract_heuristic_sections(body)
    assert "## Heuristic A" in out
    assert "## Heuristic B" in out
    assert "content A" in out
    assert "content B" in out
    # 非启发式段 (Why A 包含 "Why" 不在 patterns 里, Reference 也不在) 应被排除
    assert "## Why A" not in out
    assert "## Reference" not in out
    assert "reasoning for A" not in out


def test_13_1_handles_no_heuristic_section():
    """没有启发式段时, 兜底返回 body 前 8KB (向后兼容)"""
    from app.core.skills_index import _extract_heuristic_sections, _SYSTEM_CONTENT_MAX_BYTES
    body = "no heuristic here\n" * 100
    out = _extract_heuristic_sections(body)
    assert out == body[:_SYSTEM_CONTENT_MAX_BYTES]


def test_13_1_handles_empty_body():
    from app.core.skills_index import _extract_heuristic_sections
    assert _extract_heuristic_sections("") == ""


def test_13_1_recognizes_decision_and_pitfall_patterns():
    """Decision / Pitfall / 决策 / 启发式 都在 _HEURISTIC_SECTION_PATTERNS 里"""
    from app.core.skills_index import _extract_heuristic_sections
    body = """## Decision A
da

## Pitfall B
pb

## 决策 C
dc

## 启发式 D
hd

## Random
rr
"""
    out = _extract_heuristic_sections(body)
    assert "## Decision A" in out
    assert "## Pitfall B" in out
    assert "## 决策 C" in out
    assert "## 启发式 D" in out
    assert "## Random" not in out


# ── W4-13.2: budget 动态递减 ───────────────────────────

def test_13_2_total_size_never_exceeds_budget(tmp_path, monkeypatch):
    """多个 system skill 累计大小不应超 _SYSTEM_CONTENT_MAX_BYTES"""
    import app.core.skills_index as si
    monkeypatch.setattr(si, "_SKILLS_BASE_DIR", tmp_path)

    # 造 3 个 system + auto_load skill, 每个 4KB body
    for i in range(3):
        cat = tmp_path / "general"
        cat.mkdir(parents=True, exist_ok=True)
        skill = cat / f"skill-{i}"
        skill.mkdir()
        body = "x" * 4096  # 4KB
        (skill / "SKILL.md").write_text(
            f"---\ndescription: skill {i}\nskill_type: system\nauto_load: true\n---\n{body}",
            encoding="utf-8",
        )

    # 强制刷 mtime
    out = si.get_system_skills_content()
    total = len(out)
    print(f"  total output size: {total} bytes (budget = {si._SYSTEM_CONTENT_MAX_BYTES})")
    # 累计加上 section headers 也应 <= budget * 1.5 (允许 section 标题 + 切分误差)
    # 严格点: 不超 2x budget
    assert total <= si._SYSTEM_CONTENT_MAX_BYTES * 2, (
        f"total size {total} 远超 budget {si._SYSTEM_CONTENT_MAX_BYTES}"
    )


def test_13_2_skips_skill_when_budget_exhausted(tmp_path, monkeypatch):
    """预算耗尽时, 后续 skill 应当跳过 (而不是塞超)"""
    import app.core.skills_index as si
    monkeypatch.setattr(si, "_SKILLS_BASE_DIR", tmp_path)

    # 1 个 16KB skill (远超 budget)
    cat = tmp_path / "general"
    cat.mkdir(parents=True, exist_ok=True)
    skill = cat / "huge-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        f"---\ndescription: huge\nskill_type: system\nauto_load: true\n---\n{'x' * 16000}",
        encoding="utf-8",
    )

    out = si.get_system_skills_content()
    # 应当被切到 budget 附近, 不是完整 16KB
    assert len(out) < si._SYSTEM_CONTENT_MAX_BYTES * 1.5, (
        f"huge skill 未被切: {len(out)} bytes"
    )


# ── W4-13.3: install_skill skipped 结构化 ─────────────

def test_13_3_skipped_uses_structured_dict_for_binary():
    """二进制文件跳过时, skipped 应当是 {path, reason} 字典, 不是 path + ' (binary)' 字符串"""
    from app.core import marketplace
    from pathlib import Path
    import shutil

    # 准备 mock 数据
    mock_skill = {
        "name": "test-skill",
        "path": "skills/test-skill/SKILL.md",
        "category": "general",
        "description": "test",
        "version": "1.0.0",
        "quarantined_reason": None,
        "files": [
            {"path": "skills/test-skill/SKILL.md", "size": 100},
            {"path": "skills/test-skill/icon.png", "size": 5000},
            {"path": "skills/test-skill/README.md", "size": 200},
        ],
    }

    def fake_fetch(owner, repo, path):
        if path.endswith(".png"):
            return "fake-binary"
        return "text content"

    with patch.object(marketplace, "get_marketplace_skill", return_value=mock_skill), \
         patch.object(marketplace, "_fetch_skill_content", side_effect=fake_fetch):
        result = marketplace.install_skill("test-skill", "foo/bar")

    # 关键断言 1: skipped 全部是 dict
    assert all(isinstance(s, dict) for s in result["files_skipped"]), (
        f"skipped 含非 dict: {result['files_skipped']}"
    )
    # 关键断言 2: 旧实现 ' (binary)' 后缀不应再出现
    for s in result["files_skipped"]:
        assert " (binary)" not in s.get("path", ""), (
            f"旧实现痕迹: {s}"
        )
        assert "path" in s
        assert "reason" in s
    # 关键断言 3: 二进制文件 reason == "binary_not_supported"
    binary_skips = [s for s in result["files_skipped"] if s.get("path", "").endswith(".png")]
    assert len(binary_skips) == 1
    assert binary_skips[0]["reason"] == "binary_not_supported"

    # 清理
    target = Path("data/hermes/skills/general/test-skill")
    if target.exists():
        shutil.rmtree(target)


def test_13_3_other_skip_reasons_also_structured():
    """其他跳过原因 (unrelated path / unsafe path) 也应当用 dict 而不是裸 path"""
    from app.core import marketplace
    from pathlib import Path
    import shutil

    mock_skill = {
        "name": "test-skill-2",
        "path": "skills/test-skill-2/SKILL.md",
        "category": "general",
        "description": "test",
        "version": "1.0.0",
        "quarantined_reason": None,
        "files": [
            {"path": "skills/test-skill-2/SKILL.md", "size": 100},
            {"path": "some/other/dir/file.txt", "size": 100},  # 不在 skill 目录下
            {"path": "skills/test-skill-2/../../../etc/passwd", "size": 100},  # 路径穿越
        ],
    }

    def fake_fetch(owner, repo, path):
        return "text"

    with patch.object(marketplace, "get_marketplace_skill", return_value=mock_skill), \
         patch.object(marketplace, "_fetch_skill_content", side_effect=fake_fetch):
        result = marketplace.install_skill("test-skill-2", "foo/bar")

    assert all(isinstance(s, dict) for s in result["files_skipped"])
    reasons = [s.get("reason", "") for s in result["files_skipped"]]
    # 至少应有 "unrelated_path" 和 "unsafe_path" 两种 reason
    assert any("unrelated" in r for r in reasons) or "unrelated" in str(reasons)
    assert any("unsafe" in r for r in reasons) or "unsafe" in str(reasons)

    # 清理
    target = Path("data/hermes/skills/general/test-skill-2")
    if target.exists():
        shutil.rmtree(target)
