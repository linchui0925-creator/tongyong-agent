"""Official Model Context Protocol Registry client and local catalog helpers."""

from typing import Any, Dict, Optional, Tuple
import time

import httpx

REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1"
_CACHE: Dict[Tuple[str, int, Optional[str]], Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 300


async def search_registry(search: str = "", limit: int = 24, cursor: Optional[str] = None) -> Dict[str, Any]:
    cache_key = (search.strip().lower(), min(max(limit, 1), 100), cursor)
    cached = _CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        payload = cached[1]
    else:
        params: Dict[str, Any] = {"limit": cache_key[1]}
        if search.strip():
            params["search"] = search.strip()
        if cursor:
            params["cursor"] = cursor
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(f"{REGISTRY_BASE_URL}/servers", params=params)
            response.raise_for_status()
            payload = response.json()
        _CACHE[cache_key] = (now, payload)

    latest: Dict[str, Dict[str, Any]] = {}
    for record in payload.get("servers", []):
        server = record.get("server") or {}
        meta = (record.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {})
        name = server.get("name")
        if not name or meta.get("status") != "active":
            continue
        existing = latest.get(name)
        if meta.get("isLatest") or existing is None:
            latest[name] = {
                "id": name,
                "name": server.get("title") or name,
                "description": server.get("description", ""),
                "version": server.get("version", ""),
                "repository": server.get("repository"),
                "website_url": server.get("websiteUrl"),
                "packages": server.get("packages", []),
                "remotes": server.get("remotes", []),
                "published_at": meta.get("publishedAt"),
                "updated_at": meta.get("updatedAt"),
                "is_latest": bool(meta.get("isLatest")),
            }
    return {
        "servers": list(latest.values()),
        "next_cursor": (payload.get("metadata") or {}).get("nextCursor"),
        "registry": REGISTRY_BASE_URL,
        "cached": bool(cached),
    }
