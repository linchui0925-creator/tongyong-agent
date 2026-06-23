"""
P2-4 W4-20: security_config 热加载测试
"""

import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_default_allowed_contains_builtins():
    """内置白名单包含常见命令"""
    from app.tools.security_config import _ALLOWED_COMMANDS
    for cmd in ["ls", "cat", "grep", "git", "python", "docker", "tar"]:
        assert cmd in _ALLOWED_COMMANDS, f"内置白名单应当含 {cmd}"


def test_default_forbidden_contains_dangerous():
    """内置黑名单含危险 pattern"""
    from app.tools.security_config import _FORBIDDEN_PATTERNS
    joined = " ".join(_FORBIDDEN_PATTERNS)
    assert "sudo" in joined
    assert "rm" in joined
    assert "/etc/" in joined


def test_whitelist_file_loading(tmp_path):
    """外部白名单文件追加"""
    from app import tools
    from app.tools import security_config

    # 写一个临时白名单文件
    wl = tmp_path / "terminal_whitelist.txt"
    wl.write_text("# comment\nkubectl\n\n  # 注释\nhelm\nignored # inline\n")
    bl = tmp_path / "terminal_blacklist.txt"
    bl.write_text("")

    # monkeypatch 文件路径 + 强制 reload
    with patch.object(security_config, "_WHITELIST_FILE", wl), \
         patch.object(security_config, "_BLACKLIST_FILE", bl):
        security_config.reload_security_config()
        assert "kubectl" in security_config._ALLOWED_COMMANDS
        assert "helm" in security_config._ALLOWED_COMMANDS
        # inline # 后面整行被当注释 skip 掉, "ignored" 不在
        assert "ignored" not in security_config._ALLOWED_COMMANDS


def test_blacklist_file_loading(tmp_path):
    """外部黑名单文件追加"""
    from app.tools import security_config
    wl = tmp_path / "terminal_whitelist.txt"
    wl.write_text("")
    bl = tmp_path / "terminal_blacklist.txt"
    bl.write_text(r"rm\s+-rf\s+~\n")
    with patch.object(security_config, "_WHITELIST_FILE", wl), \
         patch.object(security_config, "_BLACKLIST_FILE", bl):
        security_config.reload_security_config()
        joined = " ".join(security_config._FORBIDDEN_PATTERNS)
        assert "rm" in joined
        # 新增的 pattern 必须在
        assert any("~" in p for p in security_config._FORBIDDEN_PATTERNS)


def test_invalid_regex_skipped(tmp_path):
    """非法 regex 被 skip 掉, 不抛"""
    from app.tools import security_config
    wl = tmp_path / "terminal_whitelist.txt"
    wl.write_text("")
    bl = tmp_path / "terminal_blacklist.txt"
    bl.write_text("[invalid(regex\n")  # 非法 regex
    with patch.object(security_config, "_WHITELIST_FILE", wl), \
         patch.object(security_config, "_BLACKLIST_FILE", bl):
        # 不应抛
        security_config.reload_security_config()
        # 非法 regex 不应进
        assert "[invalid(regex" not in " ".join(security_config._FORBIDDEN_PATTERNS)


def test_missing_files_noop():
    """白名单/黑名单文件不存在时, 用默认 (不抛)"""
    from app.tools import security_config
    fake_wl = Path("/nonexistent/wl.txt")
    fake_bl = Path("/nonexistent/bl.txt")
    with patch.object(security_config, "_WHITELIST_FILE", fake_wl), \
         patch.object(security_config, "_BLACKLIST_FILE", fake_bl):
        security_config.reload_security_config()
        # 应当含内置, 不抛
        assert "ls" in security_config._ALLOWED_COMMANDS


def test_terminal_sees_hot_reload(tmp_path):
    """terminal.py 旧 import 引用在 reload 后能看到新命令"""
    from app.tools import security_config
    from app.tools.implementations import terminal

    # 加 'kubectl' 到白名单
    wl = tmp_path / "terminal_whitelist.txt"
    wl.write_text("kubectl\n")
    with patch.object(security_config, "_WHITELIST_FILE", wl):
        security_config.reload_security_config()
    # terminal 持有的引用跟 security module 是同一个 list
    assert terminal._ALLOWED_COMMANDS is security_config._ALLOWED_COMMANDS
    assert "kubectl" in terminal._ALLOWED_COMMANDS
