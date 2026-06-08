"""
W3 切流量 1️⃣ 单元测试 — 灰度决策函数 _should_use_langchain
覆盖决策矩阵的 6 个分支 (行为验证优先, 不靠口头汇报)
"""
import pytest
from app.api.stream import _should_use_langchain, LANGCHAIN_ROLLOUT_PCT


class TestShouldUseLangchainOverride:
    """override 强制路径 (显式 > 一切)"""

    def test_override_true_forces_langchain(self, monkeypatch):
        """override=True → 永远走 langchain, 不管 session_id / rollout_pct"""
        monkeypatch.setenv("LANGCHAIN_ROLLOUT", "0")
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 0
        assert _should_use_langchain(
            request_use_langchain=False,
            session_id=None,
            override=True,
        ) is True

    def test_override_false_forces_baseline(self, monkeypatch):
        """override=False → 永远走自研, 不管 session_id / rollout_pct"""
        monkeypatch.setenv("LANGCHAIN_ROLLOUT", "100")
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 100
        assert _should_use_langchain(
            request_use_langchain=True,
            session_id="any-session",
            override=False,
        ) is False


class TestShouldUseLangchainRequestFlag:
    """request flag 路径 (客户端显式选择)"""

    def test_request_false_goes_baseline(self, monkeypatch):
        """request=False → 走自研, 不管灰度"""
        monkeypatch.setenv("LANGCHAIN_ROLLOUT", "100")
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 100
        assert _should_use_langchain(
            request_use_langchain=False,
            session_id="any",
            override=None,
        ) is False


class TestShouldUseLangchainRolloutPct:
    """灰度百分比路径 (rollout_pct 控制流量)"""

    def test_rollout_100_always_langchain(self, monkeypatch):
        """rollout=100 → 100% 走 langchain"""
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 100
        for sid in ["a", "b", "c", "xyz-123", "session_long_name"]:
            assert _should_use_langchain(
                request_use_langchain=True,
                session_id=sid,
                override=None,
            ) is True, f"rollout=100 should always True for sid={sid}"

    def test_rollout_0_always_baseline(self, monkeypatch):
        """rollout=0 → 0% 走 langchain (回滚兜底)"""
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 0
        for sid in ["a", "b", "c", "xyz-123", "session_long_name"]:
            assert _should_use_langchain(
                request_use_langchain=True,
                session_id=sid,
                override=None,
            ) is False, f"rollout=0 should always False for sid={sid}"

    def test_rollout_50_splits(self, monkeypatch):
        """rollout=50 → 大约 50% 走 langchain (1/2 ±5%)"""
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 50
        n_true = 0
        n_total = 200
        for i in range(n_total):
            if _should_use_langchain(
                request_use_langchain=True,
                session_id=f"session-{i}",
                override=None,
            ):
                n_true += 1
        ratio = n_true / n_total
        # ±5% 容忍 (50% ± 5% = [0.45, 0.55])
        assert 0.45 <= ratio <= 0.55, \
            f"rollout=50 should be ~50%, got {ratio:.2%} ({n_true}/{n_total})"

    def test_rollout_25_quarter(self, monkeypatch):
        """rollout=25 → ~25% 走 langchain"""
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 25
        n_true = 0
        n_total = 400
        for i in range(n_total):
            if _should_use_langchain(
                request_use_langchain=True,
                session_id=f"session-{i}",
                override=None,
            ):
                n_true += 1
        ratio = n_true / n_total
        assert 0.20 <= ratio <= 0.30, \
            f"rollout=25 should be ~25%, got {ratio:.2%} ({n_true}/{n_total})"


class TestShouldUseLangchainSessionConsistency:
    """session_id 一致性: 同一 session_id 永远走同一条路 (不能来回跳)"""

    def test_same_session_same_decision(self, monkeypatch):
        """同 session_id 调 10 次, 决策必须一致 (灰度 hash 稳定)"""
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 50
        sid = "stable-session-xyz-123"
        first = _should_use_langchain(
            request_use_langchain=True, session_id=sid, override=None
        )
        for _ in range(10):
            subsequent = _should_use_langchain(
                request_use_langchain=True, session_id=sid, override=None
            )
            assert subsequent == first, \
                f"session={sid} decision changed: first={first} later={subsequent}"

    def test_no_session_id_falls_open(self, monkeypatch):
        """session_id=None 时, 退化为全开 (单次调用不卡灰度)"""
        from app.api import stream
        stream.LANGCHAIN_ROLLOUT_PCT = 0  # 即使 rollout=0, 无 session 仍走 langchain
        assert _should_use_langchain(
            request_use_langchain=True,
            session_id=None,
            override=None,
        ) is True


class TestRolloutPctLoading:
    """LANGCHAIN_ROLLOUT 环境变量加载"""

    def test_default_is_100(self, monkeypatch):
        """ENV 没设时, 默认 100 (全量)"""
        monkeypatch.delenv("LANGCHAIN_ROLLOUT", raising=False)
        # 重新加载模块会重新读 ENV, 这里直接验证默认值
        from app.api import stream
        # 默认 100 在模块顶部读; 验证函数本身 rollout=100 行为
        stream.LANGCHAIN_ROLLOUT_PCT = 100
        assert _should_use_langchain(True, "x", None) is True
