"""
Q3-A 验证：use_langchain=true 工具调用路径 — 修必修 1 后的回归

测什么：
  问 "现在几点了" → 期望 LLM 调 terminal 工具（time 命令）→ 工具返回时间 → LLM 答
  验证 SSE 5 类事件齐全: start / content / tool_start / tool_complete / done

对比：跟 q1_test.py 同样 ASGI in-process 方式
"""
import asyncio
import sys
import os
import json
from pathlib import Path

BACKEND = Path(__file__).parent
sys.path.insert(0, str(BACKEND))

for line in (BACKEND / ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def test(use_langchain: bool, message: str, label: str):
    import httpx
    from app.main import app

    print(f"\n{'='*60}")
    print(f"[{label}] use_langchain={use_langchain}")
    print(f"  message: {message!r}")
    print("=" * 60)

    body = {
        "session_id": None,
        "message": message,
        "use_memory": False,
        "use_langchain": use_langchain,
    }

    seen = {}
    first_content = []
    first_tool = None
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
                if not line or not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                ev_type = ev.get("type", "unknown")
                seen[ev_type] = seen.get(ev_type, 0) + 1
                if ev_type == "content" and len(first_content) < 3:
                    first_content.append(ev.get("content", "")[:80])
                if ev_type == "tool_start" and first_tool is None:
                    first_tool = ev
                if ev_type == "error":
                    print(f"  ERROR event: {ev.get('content', ev)[:300]}")

    elapsed = time.time() - t0
    print(f"\n--- 事件统计（{elapsed:.1f}s）---")
    for k, v in seen.items():
        if v:
            print(f"  {k:20s} = {v}")
    if first_content:
        print(f"\n  First 3 content chunks: {first_content}")
    if first_tool:
        print(f"\n  First tool_start: name={first_tool.get('tool_name')!r} args={first_tool.get('arguments')!r} emoji={first_tool.get('emoji')!r}")


async def main():
    # 跑两轮
    await test(use_langchain=False, message="现在几点了？只调工具，不准自己编时间",
               label="BASELINE 自研 工具调用")
    await test(use_langchain=True,  message="现在几点了？只调工具，不准自己编时间",
               label="USE_LANGCHAIN 实验 工具调用")


if __name__ == "__main__":
    asyncio.run(main())
