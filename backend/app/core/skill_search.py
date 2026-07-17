from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://skills.sh/api/search"
_HTTP_FETCHER: Optional[Callable[[str], Tuple[int, str]]] = None


class SkillSearchError(RuntimeError):
    pass


def set_http_fetcher_for_tests(
    fetcher: Optional[Callable[[str], Tuple[int, str]]],
) -> None:
    global _HTTP_FETCHER
    _HTTP_FETCHER = fetcher


def _http_get(url: str) -> Tuple[int, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(
            request, timeout=10, context=ssl.create_default_context()
        ) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("skills.sh search failed: %s", exc)
        return 0, ""


def search_skills(query: Optional[str], limit: int = 10) -> List[Dict[str, Any]]:
    normalized = (query or "").strip()
    if not normalized:
        return []

    bounded_limit = max(1, min(int(limit), 50))
    url = f"{_SEARCH_URL}?{urlencode({'q': normalized, 'limit': bounded_limit})}"
    status, body = (_HTTP_FETCHER or _http_get)(url)
    if status != 200:
        raise SkillSearchError(f"skills.sh returned HTTP {status}")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SkillSearchError("skills.sh returned invalid JSON") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("skills"), list):
        raise SkillSearchError("skills.sh returned an invalid response")

    results: List[Dict[str, Any]] = []
    for item in payload["skills"]:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        skill_id = item.get("skillId")
        if not isinstance(source, str) or not isinstance(skill_id, str):
            continue
        results.append(
            {
                "id": str(item.get("id") or f"{source}/{skill_id}"),
                "skill_id": skill_id,
                "name": str(item.get("name") or skill_id),
                "source": source,
                "installs": int(item.get("installs") or 0),
            }
        )
    return results
