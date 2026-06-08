"""
W3 切流量 2️⃣ 单元测试 — 埋点类 _StreamMetrics
覆盖 latency / tool_count / error_code / log_success / log_error (行为验证优先)
"""
import json
import time
import logging
import io
import pytest
from app.api.stream import _StreamMetrics


class TestStreamMetricsInit:
    """初始化: 9 个 slot, t0 必须立即设置 (latency 才能算)"""

    def test_init_sets_t0(self):
        m = _StreamMetrics("sid-1", True, True, None, 100)
        assert isinstance(m.t0, float)
        assert m.t0 > 0

    def test_init_defaults(self):
        m = _StreamMetrics("sid-1", True, True, None, 100)
        assert m.tool_count == 0
        assert m.error_code is None
        assert m.error_message is None
        assert m.session_id == "sid-1"
        assert m.use_langchain is True
        assert m.request_flag is True
        assert m.override is None
        assert m.rollout_pct == 100

    def test_init_override_true(self):
        m = _StreamMetrics("sid-1", True, True, True, 50)
        assert m.override is True
        assert m.rollout_pct == 50

    def test_init_use_langchain_false(self):
        """use_langchain=False 表示走自研 (埋点要区分)"""
        m = _StreamMetrics("sid-1", False, True, None, 100)
        assert m.use_langchain is False
        assert m.request_flag is True  # client 要 langchain, 但被灰度拒了


class TestStreamMetricsToolCount:
    """tool_count 累加 (模拟 3 类 tool 事件)"""

    def test_tool_count_starts_zero(self):
        m = _StreamMetrics("sid", True, True, None, 100)
        assert m.tool_count == 0

    def test_tool_count_increment(self):
        """模拟连续 5 个 tool_start 事件"""
        m = _StreamMetrics("sid", True, True, None, 100)
        for _ in range(5):
            m.tool_count += 1
        assert m.tool_count == 5


class TestStreamMetricsSnapshot:
    """_snapshot 内部方法 (log_success / log_error 都用它)"""

    def test_snapshot_status(self):
        m = _StreamMetrics("sid-snap", True, True, False, 75)
        snap = m._snapshot("success")
        assert snap["status"] == "success"
        assert snap["metric"] == "stream_chat"
        assert snap["session_id"] == "sid-snap"
        assert snap["use_langchain"] is True
        assert snap["request_flag"] is True
        assert snap["override"] is False
        assert snap["rollout_pct"] == 75

    def test_snapshot_latency_positive(self):
        m = _StreamMetrics("sid", True, True, None, 100)
        time.sleep(0.01)  # 10ms
        snap = m._snapshot("success")
        assert snap["latency_ms"] >= 10  # 至少 10ms

    def test_snapshot_error_fields(self):
        m = _StreamMetrics("sid", True, True, None, 100)
        m.error_code = "STREAM_ERROR"
        m.error_message = "boom"
        snap = m._snapshot("error")
        assert snap["status"] == "error"
        assert snap["error_code"] == "STREAM_ERROR"
        assert snap["error_message"] == "boom"
        assert snap["tool_count"] == 0


class TestStreamMetricsLogSuccess:
    """log_success: 一行 JSON 进 logger.info (行为验证: 可 grep)"""

    def test_log_success_emits_metrics_tag(self, caplog):
        m = _StreamMetrics("sid-ok", True, True, None, 100)
        m.tool_count = 3
        with caplog.at_level(logging.INFO, logger="app.api.stream"):
            m.log_success()
        # 必须有 [METRICS] 前缀 + 一行 JSON
        metrics_logs = [r for r in caplog.records if "[METRICS]" in r.message]
        assert len(metrics_logs) == 1
        body = metrics_logs[0].message.split("[METRICS] ", 1)[1]
        data = json.loads(body)
        assert data["status"] == "success"
        assert data["tool_count"] == 3
        assert data["session_id"] == "sid-ok"
        assert data["error_code"] is None

    def test_log_success_emits_at_info_level(self, caplog):
        """成功是 INFO, 失败是 WARNING (按 log_level 区分)"""
        m = _StreamMetrics("sid", True, True, None, 100)
        with caplog.at_level(logging.DEBUG, logger="app.api.stream"):
            m.log_success()
        records = [r for r in caplog.records if "[METRICS]" in r.message]
        assert records[0].levelname == "INFO"


class TestStreamMetricsLogError:
    """log_error: warning 级别, 截断 message 避免日志爆"""

    def test_log_error_truncates_long_message(self, caplog):
        m = _StreamMetrics("sid", True, True, None, 100)
        long_msg = "x" * 1000
        with caplog.at_level(logging.WARNING, logger="app.api.stream"):
            m.log_error("STREAM_ERROR", long_msg)
        records = [r for r in caplog.records if "[METRICS]" in r.message]
        body = records[0].message.split("[METRICS] ", 1)[1]
        data = json.loads(body)
        # 200 字符截断
        assert len(data["error_message"]) == 200
        assert data["error_code"] == "STREAM_ERROR"
        assert data["status"] == "error"

    def test_log_error_emits_at_warning_level(self, caplog):
        m = _StreamMetrics("sid", True, True, None, 100)
        with caplog.at_level(logging.DEBUG, logger="app.api.stream"):
            m.log_error("INTERNAL_ERROR", "boom")
        records = [r for r in caplog.records if "[METRICS]" in r.message]
        assert records[0].levelname == "WARNING"

    def test_log_error_preserves_short_message(self, caplog):
        """短消息不截断"""
        m = _StreamMetrics("sid", True, True, None, 100)
        with caplog.at_level(logging.WARNING, logger="app.api.stream"):
            m.log_error("STREAM_ERROR", "oops")
        records = [r for r in caplog.records if "[METRICS]" in r.message]
        body = records[0].message.split("[METRICS] ", 1)[1]
        data = json.loads(body)
        assert data["error_message"] == "oops"


class TestStreamMetricsIntegration:
    """集成场景: 模拟一次完整调用的 metrics 演化"""

    def test_full_call_simulation(self, caplog):
        """模拟一次调用: 2 个 tool_start, 然后 log_success"""
        m = _StreamMetrics("sid-full", True, True, None, 100)
        m.tool_count += 1  # 第 1 个 tool
        m.tool_count += 1  # 第 2 个 tool
        with caplog.at_level(logging.INFO, logger="app.api.stream"):
            m.log_success()
        records = [r for r in caplog.records if "[METRICS]" in r.message]
        data = json.loads(records[0].message.split("[METRICS] ", 1)[1])
        assert data["tool_count"] == 2
        assert data["latency_ms"] >= 0
        assert data["status"] == "success"

    def test_error_call_simulation(self, caplog):
        """模拟一次失败: 1 个 tool, 然后 STREAM_ERROR"""
        m = _StreamMetrics("sid-err", True, True, None, 100)
        m.tool_count += 1
        with caplog.at_level(logging.WARNING, logger="app.api.stream"):
            m.log_error("STREAM_ERROR", "工具调用超时")
        records = [r for r in caplog.records if "[METRICS]" in r.message]
        data = json.loads(records[0].message.split("[METRICS] ", 1)[1])
        assert data["tool_count"] == 1
        assert data["error_code"] == "STREAM_ERROR"
        assert data["error_message"] == "工具调用超时"
        assert data["status"] == "error"
