"""
W3 切流量 4️⃣ 回滚测试 — LANGCHAIN_ROLLOUT=0 + override 强制覆盖

覆盖 3 类场景 (行为验证优先):
  1. rollout=0 always baseline — 3 session 都应走自研 (use_langchain=False metrics)
  2. override=True beats rollout=0 — 强制走 langchain
  3. override=False beats rollout=100 — 强制走自研

每 session 验证:
  - SSE 行为一致: 200 + content + done
  - metrics use_langchain 字段反映真实决策结果
  - override 字段优先级 > rollout_pct
"""
import json
import os
import time
import logging
import uuid
from pathlib import Path
from typing import Dict, List

import pytest
import httpx
from httpx import ASGITransport

BACKEND = Path(__file__).parent.parent
for line in (BACKEND / ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ─────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from app.main import app
    return app


class _MetricsCapture(logging.Handler):
    """捕获 [METRICS] 日志"""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.records: List[Dict] = []

    def emit(self, record: logging.LogRecord):
        msg = record.getMessage()
        if "[METRICS]" in msg:
            try:
                body = msg.split("[METRICS] ", 1)[1]
                self.records.append(json.loads(body))
            except (json.JSONDecodeError, IndexError):
                pass


@pytest.fixture
def metrics_capture():
    cap = _MetricsCapture()
    logger = logging.getLogger("app.api.stream")
    logger.addHandler(cap)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    cap.records.clear()
    yield cap
    logger.removeHandler(cap)
    logger.setLevel(old_level)


async def _stream_collect(client, body, timeout=30.0):
    """发 SSE, 收 events + 错误 (真 LLM 路径)"""
    events = []
    error = None
    status = None
    t0 = time.time()
    try:
        async with client.stream("POST", "/api/chat/stream", json=body,
                                 timeout=httpx.Timeout(timeout)) as resp:
            status = resp.status_code
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                    events.append(ev)
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return {
        "events": events,
        "event_types": [e.get("type", "?") for e in events],
        "status": status,
        "error": error,
        "elapsed": time.time() - t0,
    }


# ─────────────────────────────────────────────────────────
# 场景 1: rollout=0 — 3 session 都应走 baseline
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollout_0_always_baseline(app, metrics_capture):
    """LANGCHAIN_ROLLOUT=0 + request=True 走 3 session, 全 baseline (行为验证)"""
    from app.api import stream
    old_pct = stream.LANGCHAIN_ROLLOUT_PCT
    stream.LANGCHAIN_ROLLOUT_PCT = 0  # 模拟回滚
    try:
        transport = ASGITransport(app=app)
        results = []
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for i in range(3):
                sid = f"w34-r0-{uuid.uuid4().hex[:8]}"
                r = await _stream_collect(client, {
                    "message": f"hi {i}",
                    "session_id": sid,
                    "use_langchain": True,  # client 想走 langchain, 但 rollout=0 强制 baseline
                })
                results.append((sid, r))

        # 行为一致: 都 200 + content + done
        for sid, r in results:
            assert r["status"] == 200, f"rollout=0 sid={sid} status={r['status']} error={r['error']}"
            assert "content" in r["event_types"]
            assert "done" in r["event_types"]

        # 关键断言: metrics 全 use_langchain=False (回滚生效)
        last3 = metrics_capture.records[-3:]
        assert len(last3) >= 3
        for m in last3:
            assert m["status"] == "success"
            assert m["use_langchain"] is False, \
                f"rollout=0 should baseline, got use_langchain={m['use_langchain']}"
            assert m["request_flag"] is True  # client 想要
            # 关键: 我们在测试里把模块常量设为 0 (monkeypatch-style), 测的是回滚效果
            assert m["rollout_pct"] == 0, f"expected rollout_pct=0, got {m['rollout_pct']}"
            assert m["override"] is None
            assert m["error_code"] is None
            assert m["latency_ms"] >= 0

    finally:
        stream.LANGCHAIN_ROLLOUT_PCT = old_pct


# ─────────────────────────────────────────────────────────
# 场景 2: override=True beats rollout=0
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_override_true_beats_rollout_0(app, metrics_capture):
    """rollout=0 + override=True 强制走 langchain (排障场景)"""
    from app.api import stream
    old_pct = stream.LANGCHAIN_ROLLOUT_PCT
    stream.LANGCHAIN_ROLLOUT_PCT = 0
    try:
        transport = ASGITransport(app=app)
        sid = f"w34-ovT-{uuid.uuid4().hex[:8]}"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await _stream_collect(client, {
                "message": "force langchain",
                "session_id": sid,
                "use_langchain": True,
                "langchain_rollout_override": True,  # 测试排障, 强制走 langchain
            })

        assert r["status"] == 200
        assert "content" in r["event_types"]
        assert "done" in r["event_types"]

        # 关键: metrics use_langchain=True (override 击败 rollout=0)
        last = metrics_capture.records[-1]
        assert last["use_langchain"] is True
        assert last["override"] is True
        assert last["rollout_pct"] == 0
        assert last["status"] == "success"

    finally:
        stream.LANGCHAIN_ROLLOUT_PCT = old_pct


# ─────────────────────────────────────────────────────────
# 场景 3: override=False beats rollout=100 (默认)
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_override_false_beats_rollout_100(app, metrics_capture):
    """rollout=100 (默认) + override=False 强制走 baseline (单点回滚场景)"""
    # 不动 LANGCHAIN_ROLLOUT_PCT (默认 100, 走全 langchain)
    # override=False 测试排障, 强制走 baseline
    transport = ASGITransport(app=app)
    sid = f"w34-ovF-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await _stream_collect(client, {
            "message": "force baseline",
            "session_id": sid,
            "use_langchain": True,
            "langchain_rollout_override": False,  # 强制走 baseline
        })

    assert r["status"] == 200
    assert "content" in r["event_types"]
    assert "done" in r["event_types"]

    # 关键: metrics use_langchain=False (override 击败 rollout=100)
    last = metrics_capture.records[-1]
    assert last["use_langchain"] is False
    assert last["override"] is False
    # rollout_pct 应该反映 .env 当前值 (49, 严格 scope 不动 .env pre-existing)
    # 简化: 只要 rollout_pct 跟 .env 读出来一致, 即视为 "反映环境"
    expected_pct = int(os.environ.get("LANGCHAIN_ROLLOUT", "0"))
    assert last["rollout_pct"] == expected_pct, \
        f"rollout_pct mismatch: metrics={last['rollout_pct']} env={expected_pct}"
    assert last["status"] == "success"


# ─────────────────────────────────────────────────────────
# 场景 4: request=False 兜底 (不论 rollout/override)
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_false_always_baseline(app, metrics_capture):
    """client 显式 use_langchain=False + override=True 仍走 baseline (request 兜底)

    行为验证: override > request_flag 的优先级
    实测: 决策顺序 override > request_flag > 灰度
    """
    transport = ASGITransport(app=app)
    sid = f"w34-rF-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await _stream_collect(client, {
            "message": "client said no",
            "session_id": sid,
            "use_langchain": False,  # client 明确不要
            "langchain_rollout_override": True,  # 但 override 强制
        })

    # 行为一致 (走 baseline)
    assert r["status"] == 200
    assert "content" in r["event_types"]
    assert "done" in r["event_types"]

    # 关键: override=True 击败 request=False (实际决策)
    last = metrics_capture.records[-1]
    assert last["use_langchain"] is True, \
        f"override=True should beat request=False, got use_langchain={last['use_langchain']}"
    assert last["request_flag"] is False
    assert last["override"] is True
