"""
W4-33 — System Prompt 精简回归测试

锁定精简后基线, 防 prompt 重新膨胀:
  - base 段 < 1.0 KB
  - 全拼 (base + cap + skills) < 3.0 KB
  - 实际注入 (含 domain) < 6.0 KB
  - 关键章节必须存在 (工具调用协议 / 禁止装执行 / 停止判断 / 总结格式)
  - 关键重复点 (身份/记忆/平台提示/调用形式详细枚举) 不能再出现
  - identity.md < 1.0 KB
"""
import re
from pathlib import Path


REPO = Path("/Users/linc/Documents/tongyong-agent/backend")
BASE = 1024


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── 1. 字节预算 ─────────────────────────────────────
class TestSizeBudget:
    def test_base_prompt_under_1kb(self):
        """精简后 base 段必须 < 1 KB (原 2.5KB)"""
        import sys
        sys.path.insert(0, str(REPO))
        from app.core.system_prompt import SystemPromptGenerator
        base = SystemPromptGenerator().generate_base_prompt()
        assert len(base) < BASE, f"base prompt {len(base)}B, 期望 < {BASE}B"

    def test_full_prompt_under_3kb(self):
        """base + cap + skills 拼起来 < 3 KB"""
        import sys
        sys.path.insert(0, str(REPO))
        from app.core.system_prompt import get_system_prompt
        full = get_system_prompt()
        assert len(full) < 3 * BASE, f"full prompt {len(full)}B, 期望 < {3*BASE}B"

    def test_actual_injection_under_6kb(self):
        """含 domain 全量 < 6 KB (原 9.3KB)"""
        import sys
        sys.path.insert(0, str(REPO))
        from app.core.system_prompt import get_system_prompt
        from app.domains import get_integrator
        total = len(get_system_prompt()) + len(get_integrator().get_all())
        assert total < 6 * BASE, f"actual injection {total}B, 期望 < {6*BASE}B"

    def test_identity_md_under_1kb(self):
        """identity.md 砍到 < 1KB (原 2.5KB)"""
        content = _read(REPO / "app/domains/identity/identity.md")
        assert len(content) < BASE, f"identity.md {len(content)}B, 期望 < {BASE}B"


# ── 2. 关键章节必须存在 ───────────────────────────
class TestRequiredSections:
    def _base(self) -> str:
        import sys
        sys.path.insert(0, str(REPO))
        from app.core.system_prompt import SystemPromptGenerator
        return SystemPromptGenerator().generate_base_prompt()

    def test_tool_calling_protocol(self):
        """工具调用必须明说走 message.tool_calls 结构化字段"""
        b = self._base()
        assert "tool_calls" in b
        assert "function calling" in b or "function-calling" in b

    def test_no_xml_pseudo_call_reminder(self):
        """W4-32 简版提醒: 仍要提一嘴 'content 文本里手写伪调用' 但不再列 6 个 XML 标签"""
        b = self._base()
        assert "content" in b
        # 不再列详尽标签 (那部分挪到代码层)
        # 6 个标签名中, 应只提到 0~1 个作为示例
        tag_examples = ["<minimax:tool_call>", "<tool_call>", "<function_calls>",
                        "<invoke", "[TOOL_CALL]", "<tool_use>"]
        present = sum(1 for t in tag_examples if t in b)
        assert present <= 1, f"XML 标签枚举过多 ({present} 个), 应挪到代码层"

    def test_execution_discipline_present(self):
        b = self._base()
        # 禁装执行
        assert "装执行" in b or "声称" in b
        # 停止判断
        assert "停止" in b
        # 前置检查
        assert "前置" in b or "先" in b

    def test_summary_format(self):
        b = self._base()
        # 三段式总结
        assert "已做" in b
        assert "可做" in b
        assert "建议下一步" in b


# ── 3. 关键重复点不能再出现 ──────────────────────
class TestNoRegressions:
    def _base(self) -> str:
        import sys
        sys.path.insert(0, str(REPO))
        from app.core.system_prompt import SystemPromptGenerator
        return SystemPromptGenerator().generate_base_prompt()

    def test_no_duplicate_identity_block(self):
        """base 不再写"身份"长块 (留给 identity.md)"""
        b = self._base()
        # 不能有 "## 身份" 整段
        assert "## 身份" not in b, "base 不应有 ## 身份 章节 (与 identity.md 重复)"

    def test_no_duplicate_memory_mechanism(self):
        """base 不再写记忆机制 (留给 MEMORY.md / USER.md 实际注入)"""
        b = self._base()
        assert "## 记忆机制" not in b
        assert "USER.md" not in b
        assert "MEMORY.md" not in b

    def test_no_platform_hint(self):
        """base 不再有 <platform_hint> 块 (跟 W4-30 markdown 渲染冲突)"""
        b = self._base()
        assert "<platform_hint>" not in b
        assert "platform_hint" not in b

    def test_no_tool_list_as_inventory(self):
        """base 不再列工具清单 (那走 function calling schema) — 但允许在示例句中提一两个具体工具名作为引导"""
        b = self._base()
        # 不应出现 "工具清单" / "## 工具" 之类的章节
        assert "工具清单" not in b
        # 检查不应有 ≥3 个具体工具名同时出现 (那就是在列清单)
        tool_names = ["read_file", "write_file", "edit_file", "glob",
                      "search_files", "execute_code", "browser", "web_search"]
        present = sum(1 for t in tool_names if t in b)
        assert present < 3, f"base 提到了 {present} 个具体工具名, 太多了 (≤2 允许作为示例)"

    def test_no_execution_claim_repeated_3_times(self):
        """'禁止装执行' 只讲 1 次, 不再分 4 章节重复 (执行纪律/节奏/校验/任务执行规则)"""
        b = self._base()
        # 检查不应有 4 个不同的标题都讲同一件事
        headings = re.findall(r"^### .+$", b, re.MULTILINE)
        for h in headings:
            assert "执行纪律" not in h
            assert "工具调用节奏" not in h
            assert "执行声明校验" not in h


# ── 4. 删掉的 cli/*.md 必须真的删了 ─────────────
class TestCLIFilesRemoved:
    def test_no_cli_md_files(self):
        """P4 同理: 工具描述走 function calling, cli/*.md 是冗余镜像"""
        cli_dir = REPO / "app/domains/cli"
        for f in cli_dir.glob("*.md"):
            pytest.fail(f"cli/{f.name} 不应存在, 工具走 function calling schema")

    def test_no_personality_dir(self):
        """personality.md 内容已合并到 identity.md, 整个目录可删"""
        p = REPO / "app/domains/personality"
        assert not p.exists(), "personality 目录应删除, 内容已合并到 identity.md"


# ── 5. 整体 prompt 拼接仍能跑通 ─────────────────
class TestPromptStillAssembles:
    def test_get_system_prompt_returns_nonempty(self):
        import sys
        sys.path.insert(0, str(REPO))
        from app.core.system_prompt import get_system_prompt
        full = get_system_prompt()
        assert isinstance(full, str)
        assert len(full) > 500  # 至少 0.5KB, 防止被误删空
        # 必须包含 base 段
        assert "工具调用" in full
        # 必须包含 cap 段
        assert "可用工具" in full
        # 必须包含 skills 段
        assert "Skill" in full or "skill" in full
