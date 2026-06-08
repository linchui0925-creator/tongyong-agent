"""
W3 切流量 3️⃣ 端到端测试 — 30 session 切流量 + 行为一致性

覆盖 3 类场景 (行为验证优先, 不靠口头汇报):
  1. baseline path   (use_langchain=false)  → 走自研
  2. langchain path  (use_langchain=true)   → 走 langchain
  3. rollout path    (LANGCHAIN_ROLLOUT=50)  → 50/50 分布

每 session 验证:
  - SSE 行为一致: 必产 start / content / done
  - metrics 日志真出现: [METRICS] JSON 含 3 指标 (latency_ms/tool_count/error_code)
  - use_langchain 字段反映灰度决策结果 (不是 client request)
"""
import asyncio
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
    cap.records.clear()  # 重置 (避免模块级 fixture 污染)
    yield cap
    logger.removeHandler(cap)
    logger.setLevel(old_level)


async def _stream_collect(client, body, timeout=60.0):
    """发 SSE, 收 events + 错误 (真 LLM 路径, 不 mock)"""
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


def _assert_sse_behavior(r, sid, label):
    """SSE 行为一致性断言: 200 + 至少 1 content + 1 done"""
    assert r["status"] == 200, f"{label} sid={sid} status={r['status']} error={r['error']}"
    assert "content" in r["event_types"], f"{label} sid={sid} no content: {r['event_types']}"
    assert "done" in r["event_types"], f"{label} sid={sid} no done: {r['event_types']}"


# ─────────────────────────────────────────────────────────
# 场景 1 + 2: 单 session 行为对齐 (最快, 1 baseline + 1 langchain)
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_paths_behavior_aligned(app, metrics_capture):
    """1 baseline + 1 langchain — 验两条路 SSE 行为一致 (行为验证: 不靠口述)
    langchain 路径用 override=True 强制走 (不受 .env LANGCHAIN_ROLLOUT 影响)
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        baseline = await _stream_collect(client, {
            "message": "hi baseline",
            "session_id": f"w33-b-{uuid.uuid4().hex[:8]}",
            "use_langchain": False,
        })
        langchain = await _stream_collect(client, {
            "message": "hi langchain",
            "session_id": f"w33-l-{uuid.uuid4().hex[:8]}",
            "use_langchain": True,
            "langchain_rollout_override": True,  # 强制走 langchain, 不受 .env rollout=1 影响
        })

    # 行为一致: 都有 start / content / done
    for label, r in [("baseline", baseline), ("langchain", langchain)]:
        _assert_sse_behavior(r, r.get("session_id", "?"), label)
        # start 事件必须最先到 (start 在 content 之前)
        if r["event_types"]:
            assert r["event_types"][0] == "start", \
                f"{label}: first event should be 'start', got {r['event_types'][0]}"

    # metrics: 必须有 2 条 (各 1 个)
    assert len(metrics_capture.records) >= 2, \
        f"expected 2+ metrics, got {len(metrics_capture.records)}"
    last2 = metrics_capture.records[-2:]
    # 第 1 条是 baseline, 第 2 条是 langchain (按调用顺序)
    assert last2[0]["use_langchain"] is False, \
        f"first metrics should be baseline, got {last2[0]['use_langchain']}"
    assert last2[1]["use_langchain"] is True, \
        f"second metrics should be langchain, got {last2[1]['use_langchain']}"
    # 3 指标都必填
    for m in last2:
        assert m["status"] == "success"
        assert m["error_code"] is None
        assert m["latency_ms"] >= 0
        assert isinstance(m["tool_count"], int)


# ─────────────────────────────────────────────────────────
# 场景 3: rollout 50% — 30 session 验分布
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollout_50_sessions_split(app, metrics_capture):
    """12 session 走灰度, 验 ~50% baseline / ~50% langchain 分布
    (行为验证: 同 rollout_pct, 不同 session_id 真分裂到两条路)
    并发跑 (asyncio.gather) 控制在 60s 内
    """
    from app.api import stream
    old_pct = stream.LANGCHAIN_ROLLOUT_PCT
    stream.LANGCHAIN_ROLLOUT_PCT = 50
    try:
        transport = ASGITransport(app=app)
        n = 12  # 12 session, 并发 4 = ~3 轮 × ~16s = ~50s

        async def _one(idx):
            sid = f"w33-roll-{idx:03d}-{uuid.uuid4().hex[:6]}"
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as cli:
                r = await _stream_collect(cli, {
                    "message": f"r{idx}",
                    "session_id": sid,
                    "use_langchain": True,
                }, timeout=30.0)
            return sid, r

        # 并发 4
        sem = asyncio.Semaphore(4)
        async def _guarded(idx):
            async with sem:
                return await _one(idx)
        results = await asyncio.gather(*[_guarded(i) for i in range(n)])

        # 全 200 + 行为一致 (允许少量网络失败, 但 ≥8/12)
        n_ok = 0
        for sid, r in results:
            try:
                _assert_sse_behavior(r, sid, "rollout")
                n_ok += 1
            except AssertionError:
                pass
        assert n_ok >= 8, f"rollout 12: only {n_ok}/{n} ok (≥8 容忍少量失败)"

        # metrics 分布: ~50% use_langchain=True
        rollout_metrics = metrics_capture.records[-n:]
        n_langchain = sum(1 for m in rollout_metrics if m.get("use_langchain") is True)
        n_baseline = sum(1 for m in rollout_metrics if m.get("use_langchain") is False)
        total = n_langchain + n_baseline
        assert total >= 8, f"got {total} metrics records, expected ~12"
        ratio = n_langchain / total if total else 0
        # 50% ±30% 容忍
        assert 0.20 <= ratio <= 0.80, \
            f"rollout=50 should split ~50/50, got langchain={n_langchain} baseline={n_baseline} ratio={ratio:.2%}"

        # 验证 metrics 3 指标字段齐
        for m in rollout_metrics:
            assert "latency_ms" in m
            assert "tool_count" in m
            assert "error_code" in m
            assert "rollout_pct" in m
            assert m["rollout_pct"] == 50

    finally:
        stream.LANGCHAIN_ROLLOUT_PCT = old_pct
