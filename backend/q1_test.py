"""
Q1 验证：use_langchain=true 真对话 — 不起 server，直接 ASGI in-process

为什么不起 server：
  hermes 沙箱会在 ~30s SIGTERM 后台子进程（dev-up.sh 启的 uvicorn）。
  改用 httpx + ASGITransport 直接调 FastAPI app —— 一次 Python 调用闭环。

测什么：
  POST /api/chat/stream  body={"message":"你好", "use_langchain":true}
  验证 SSE 4 类事件齐全: start / content / tool_* / done
"""
import asyncio
import sys
import os
import json
from pathlib import Path

BACKEND = Path(__file__).parent
sys.path.insert(0, str(BACKEND))

# 手动 source .env 防止 pydantic_settings 漏
for line in (BACKEND / ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def test(use_langchain: bool, label: str):
    import httpx
    from app.main import app

    print(f"\n{'='*60}")
    print(f"[{label}] use_langchain={use_langchain}")
    print("=" * 60)

    body = {
        "session_id": None,  # 新 session
        "message": "你好，1+1等于几？只回数字",
        "use_memory": False,
        "use_langchain": use_langchain,
    }

    seen = {"start": 0, "content": 0, "tool_start": 0, "tool_complete": 0,
            "tool_error": 0, "progress": 0, "done": 0, "error": 0,
            "events_total": 0}
    first_content = []
    last_event_type = None
    elapsed = 0.0

    import time
    t0 = time.time()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST", "/api/chat/stream", json=body, timeout=httpx.Timeout(60.0)
        ) as resp:
            print(f"HTTP status: {resp.status_code}")
            if resp.status_code != 200:
                body_text = (await resp.aread()).decode()[:500]
                print(f"Response body: {body_text}")
                return

            async for line in resp.aiter_lines():
                seen["events_total"] += 1
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                try:
                    ev = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                ev_type = ev.get("type", "unknown")
                seen[ev_type] = seen.get(ev_type, 0) + 1
                last_event_type = ev_type
                if ev_type == "content" and len(first_content) < 3:
                    first_content.append(ev.get("content", "")[:80])
                if ev_type == "error":
                    print(f"  ERROR event: {ev.get('content', ev)[:200]}")

    elapsed = time.time() - t0

    print(f"\n--- Event summary (用时 {elapsed:.1f}s, 总 events={seen['events_total']}) ---")
    for k, v in seen.items():
        if v and k != "events_total":
            print(f"  {k:15s} = {v}")
    if first_content:
        print(f"\n  First 3 content chunks: {first_content}")
    print(f"  Last event: {last_event_type}")


async def main():
    # 跑两轮：先 false (baseline)，再 true (验证)
    await test(use_langchain=False, label="BASELINE 自研")
    await test(use_langchain=True, label="USE_LANGCHAIN 实验")


if __name__ == "__main__":
    asyncio.run(main())
