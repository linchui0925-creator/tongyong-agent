#!/usr/bin/env python3
"""Custom image generation wrapper for minimax image_generation endpoint."""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

DEFAULT_MODEL = "image-01"
ENDPOINT = "https://api.minimaxi.com/v1/image_generation"


def _die(msg, code=1):
    print(f"Error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _read_prompt(prompt, prompt_file):
    if prompt and prompt_file:
        _die("Use --prompt or --prompt-file, not both.")
    if prompt_file:
        return Path(prompt_file).read_text(encoding="utf-8").strip()
    if prompt:
        return prompt.strip()
    _die("Missing prompt.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prompt")
    p.add_argument("--prompt-file")
    p.add_argument("--out", required=True)
    p.add_argument("--size", default="1024x1024")
    p.add_argument("--n", type=int, default=1)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    out = Path(args.out)
    if out.exists() and not args.force:
        _die(f"Output already exists: {out}. Use --force to overwrite.")

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY")
    if not api_key:
        _die("OPENAI_API_KEY (or MINIMAX_API_KEY) not set")

    prompt = _read_prompt(args.prompt, args.prompt_file)
    payload = {
        "model": args.model,
        "prompt": prompt,
        "n": args.n,
        "size": args.size,
        "response_format": "url",
    }
    if args.seed is not None:
        payload["seed"] = args.seed

    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            print(f"Attempt {attempt+1} failed: {e}", file=sys.stderr)
            time.sleep(2 + attempt * 2)
    else:
        _die(f"API request failed after 3 attempts: {last_err}")

    if body.get("base_resp", {}).get("status_code", 0) != 0:
        _die(f"API error: {body.get('base_resp')}")

    urls = body.get("data", {}).get("image_urls") or []
    if not urls:
        _die(f"No image URLs in response: {body}")

    out.parent.mkdir(parents=True, exist_ok=True)
    url = urls[0]
    with urllib.request.urlopen(url, timeout=60) as resp:
        out.write_bytes(resp.read())
    print(f"Wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
