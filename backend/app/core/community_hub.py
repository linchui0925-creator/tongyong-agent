"""
community_hub - W5-1 Skill Community Hub 核心层

职责（按 spec §5.3 §5.4 §5.6 拆分）:
- 持久化 backend/data/community_hub.json (W5-1 S1)
- HubScheduler 生命周期 (S2 — 当前 stub)
- 默认 whitelist (S3 — 当前 stub)
- marketplace install 联动 (S5 — 当前 stub)
- browse layer scrape (S6 — 当前 stub)
- catalog sync_all_sources (S3 — 实现)

铁律 (spec §0 §3 §7):
1. catalog 同步永远不 install
2. install 必须用户主动触发
3. browse layer 仅做 catalog; 挖出的 mapping 走 marketplace.install_skill

本文件只实现 S1 部分 + 占位 stub 供后续步骤填:
    - DEFAULT_HUB_REPOS
    - load_hub_config / save_hub_config
    - schema 常量
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 路径 ────────────────────────────────────────────────────────

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _BACKEND_ROOT / "data"
CONFIG_PATH = _DATA_DIR / "community_hub.json"
CONFIG_BACKUP_SUFFIX = ".corrupt"

SCHEMA_VERSION = 2

# ── 默认 whitelist (spec §5.2) ──────────────────────────────────
# 真伪待 user 验证; 不存在则从 whitelist 删除。
# 顺序 = 优先级 (小 -> 大)
DEFAULT_HUB_REPOS: List[Tuple[str, str, str]] = [
    ("anthropics",            "skills",                "Anthropic official skills"),
    ("ComposioHQ",            "awesome-claude-skills", "Composio curated"),
]

# ── 默认 browse layer (spec §5.6) ───────────────────────────────
# 默认 enabled=False, 用户 UI 显式 opt-in
DEFAULT_BROWSE_LAYERS: List[Dict[str, Any]] = [
    {
        "id": "skillhub_lol",
        "base_url": "https://skillhub.lol",
        "enabled": False,
        "user_enabled_at": None,
        "last_sync_at": None,
        "rate_limit_per_sec": 1.0,
        "scraped_count": 0,
    },
    {
        "id": "skillhub_cn",
        "base_url": "https://skillhub.cn",
        "enabled": False,
        "user_enabled_at": None,
        "last_sync_at": None,
        "rate_limit_per_sec": 1.0,
        "scraped_count": 0,
    },
]


# ── 默认结构 (spec §5.3) ─────────────────────────────────────────

def _empty_config() -> Dict[str, Any]:
    """全新配置 — 第一次加载或损坏回退时

    deep-copy DEFAULT_BROWSE_LAYERS / DEFAULT_HUB_REPOS 避免污染模块级默认
    (之前 list(DEFAULT_BROWSE_LAYERS) 只浅 copy, dict 还是共享引用 → 测试间污染)
    """
    return {
        "schema": SCHEMA_VERSION,
        "updated_at": None,
        "github_sources": [
            {"owner": o, "repo": r, "description": desc, "kind": "default", "enabled": True,
             "added_at": datetime.now(timezone.utc).isoformat(),
             "added_by": "default", "scraped_from": None}
            for o, r, desc in DEFAULT_HUB_REPOS
        ],
        "browse_layers": copy.deepcopy(DEFAULT_BROWSE_LAYERS),
        "slug_mappings": {},
    }


def _validate(raw: Any) -> Tuple[bool, str]:
    """轻量校验 — schema 版本 + 必填字段类型; 通过返回 (True, ''), 否则 (False, reason)"""
    if not isinstance(raw, dict):
        return False, "not_dict"
    schema = raw.get("schema")
    if schema != SCHEMA_VERSION:
        return False, f"schema_mismatch (got {schema}, want {SCHEMA_VERSION})"
    if not isinstance(raw.get("github_sources"), list):
        return False, "github_sources_not_list"
    if not isinstance(raw.get("browse_layers"), list):
        return False, "browse_layers_not_list"
    if not isinstance(raw.get("slug_mappings"), dict):
        return False, "slug_mappings_not_dict"
    return True, ""


# ── 持久化 (S1 核心) ─────────────────────────────────────────────

def load_hub_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取社区 hub 配置

    - 文件不存在 → 写默认到磁盘并返回 (let-it-boot)
    - schema 不匹配 / JSON 损坏 → 备份 .corrupt.<ts> + 返回默认值 (不抛)
    - 通过校验 → 原样返回
    """
    p = Path(path) if path else CONFIG_PATH
    if not p.is_file():
        cfg = _empty_config()
        try:
            save_hub_config(cfg, path=p)
        except Exception as e:
            logger.warning(f"写入默认 community_hub.json 失败 (无害): {e}")
        return cfg
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"community_hub.json 损坏, 回退默认: {e}")
        _backup_corrupt(p)
        cfg = _empty_config()
        try:
            save_hub_config(cfg, path=p)
        except Exception:
            pass
        return cfg
    ok, reason = _validate(raw)
    if not ok:
        logger.warning(f"community_hub.json schema 校验失败 ({reason}), 回退默认")
        _backup_corrupt(p)
        cfg = _empty_config()
        try:
            save_hub_config(cfg, path=p)
        except Exception:
            pass
        return cfg
    return raw


def save_hub_config(cfg: Dict[str, Any], path: Optional[Path] = None) -> None:
    """原子写: 先写 .tmp 再 rename

    自动更新 schema 版本与 updated_at 时间戳
    """
    p = Path(path) if path else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    out = dict(cfg)
    out["schema"] = SCHEMA_VERSION
    out["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


def _backup_corrupt(p: Path) -> None:
    """把损坏的 config 文件备份加 .corrupt.<ts> 后缀"""
    try:
        ts = int(time.time())
        target = p.with_name(f"{p.name}{CONFIG_BACKUP_SUFFIX}.{ts}")
        shutil.copy2(p, target)
        logger.info(f"备份损坏配置到 {target}")
    except Exception as e:
        logger.warning(f"备份损坏配置失败: {e}")


# ── S2: HubScheduler ─────────────────────────────────────────────

import asyncio


class HubScheduler:
    """社区 hub 后台调度器 (spec §5.4 §7)

    职责:
    - 启动时跑一次 fire-and-forget sync
    - 后台循环每 N 小时跑一次
    - 提供 sync_now() 手动触发 (与 background 串行化)
    - 关闭时干净 cancel 后台 loop task

    铁律 (spec §0 §3 §7): sync 永远只动 catalog, 不 install。

    S2 实装 scheduler 骨架; sync_body 由调用方注入, S3 起会替换为真的 catalog sync。
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        interval_seconds: float = 6 * 3600.0,
        sync_on_start: bool = True,
        sync_body=None,
    ):
        self._config_path = Path(config_path) if config_path else CONFIG_PATH
        self._interval = float(interval_seconds)
        self._sync_on_start = sync_on_start
        self._sync_body = sync_body  # async callable, optional (S3 will inject)
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._lock = asyncio.Lock()
        # 监控指标 (供 /api/hub/info 暴露)
        self.last_sync_at: Optional[str] = None
        self.last_sync_status: Optional[str] = None  # "ok" | "error"
        self.last_sync_error: Optional[str] = None
        self.last_sync_count: Optional[int] = None
        self.sync_count: int = 0

    def install_sync_body(self, body) -> None:
        """S3 之后由调用方注入真正的 sync 实现 (sync catalog, 不 install)"""
        self._sync_body = body

    async def start(self) -> None:
        """启动后台 loop + 一次 fire-and-forget 启动 sync"""
        if self._task is not None:
            return  # idempotent
        self._stop_event = asyncio.Event()
        # 启动 sync (可选)
        if self._sync_on_start and self._sync_body is not None:
            asyncio.create_task(self.sync_now())
        # 启动 loop task
        self._task = asyncio.create_task(self._loop(), name="community-hub-loop")

    async def stop(self) -> None:
        """Cancel 后台 loop; running sync 等它自然完成 (锁机制保证)"""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        """后台循环: 等 stop 或 interval, 然后 sync"""
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._interval
                )
                break  # 收到 stop
            except asyncio.TimeoutError:
                # 到点, 跑一次 sync
                try:
                    await self.sync_now()
                except Exception as e:
                    logger.warning(f"background sync error: {e}")

    async def sync_now(self) -> Dict[str, Any]:
        """立即同步 — 被串行化 (asyncio.Lock) 让 background + manual 不撞车

        返回 dict 给 API 暴露状态
        """
        async with self._lock:
            return await self._sync_locked()

    async def _sync_locked(self) -> Dict[str, Any]:
        if self._sync_body is None:
            return {"ok": True, "skipped": True, "reason": "no_sync_body"}
        try:
            result = await self._sync_body()
            self.last_sync_at = datetime.now(timezone.utc).isoformat()
            self.last_sync_status = "ok"
            self.last_sync_error = None
            self.last_sync_count = (
                result.get("count") if isinstance(result, dict) else None
            )
            self.sync_count += 1
            return result
        except Exception as e:
            self.last_sync_at = datetime.now(timezone.utc).isoformat()
            self.last_sync_status = "error"
            self.last_sync_error = str(e)
            logger.warning(f"sync failed: {e}")
            return {"ok": False, "error": str(e)}


# ── S5/S6 占位 ──────────────────────────────────────────────────


# ── S6: browse layer scrape (spec §5.6) ────────────────────────
import re as _re
import urllib.request as _ur
import urllib.error as _ue
import ssl as _ssl

_SLUG_RE = _re.compile(r"/skills/([A-Za-z0-9_\-\.]+)")
_GH_REPO_RE = _re.compile(r"https?://github\.com/([A-Za-z0-9_\-\.]+)/([A-Za-z0-9_\-\.]+)")

# 用于测试注入的 http fetcher override (spec §9 acceptance #6)
_HTTP_FETCHER = None  # callable(url) -> (status, body_str)


def set_http_fetcher_for_tests(fetcher):
    """测试 hook: 让 scrape_skillhub_lol 用注入的 fetcher 拉 HTML

    fetcher 签名: (url: str) -> (status: int, body: str)
    """
    global _HTTP_FETCHER
    _HTTP_FETCHER = fetcher


def _http_get_simple(url: str) -> tuple:
    """跟 marketplace 同款: 用 urllib + certifi CA bundle"""
    ssl_context = None
    try:
        import certifi
        ssl_context = _ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_context = _ssl._create_unverified_context()
    req = _ur.Request(url)
    req.add_header("User-Agent", "tongyong-hub/1.0 (learn-slug)")
    req.add_header("Accept", "text/html,application/xhtml+xml")
    try:
        with _ur.urlopen(req, timeout=10, context=ssl_context) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except _ue.HTTPError as e:
        return e.code, ""
    except (_ue.URLError, TimeoutError, OSError) as e:
        return 0, ""


def _extract_skill_slugs(html: str) -> List[str]:
    """从索引页 HTML 抽 skill slug (形如 /skills/seo-audit)"""
    seen = set()
    out = []
    for m in _SLUG_RE.finditer(html):
        slug = m.group(1).strip()
        if not slug or slug in seen:
            continue
        # 排除明显是路径段的 (不要 .html / 太长)
        if len(slug) > 64 or "/" in slug:
            continue
        seen.add(slug)
        out.append(slug)
    return out


def _extract_github_repo_from_detail(html: str) -> Optional[Tuple[str, str]]:
    """从详情页 HTML 抽首个 github.com/owner/repo URL"""
    m = _GH_REPO_RE.search(html)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    # 防御: 排除明显非 repo 的 (e.g. owner=sponsors)
    if owner.lower() in {"sponsors", "orgs", "settings", "marketplace"}:
        return None
    return owner, repo


def scrape_skillhub_lol(
    base_url: str = "https://skillhub.lol",
    max_slugs: int = 50,
    config_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """同步 scrape skillhub.lol (spec §5.6)

    1. GET {base_url}/skills → 抽 slug 列表
    2. 对每个 slug, GET {base_url}/skills/{slug} → 抽 github URL
    3. 写 slug_mappings[slug] + 动态加 github_sources (kind="scraped")

    返回: {ok, slugs_seen, mappings_written, sources_added, errors: [..]}

    铁律:
    - ❌ 不 install
    - ❌ 不写本地 hermes
    - ✅ 仅动 community_hub.json (mapping + scraped sources)
    - ✅ rate-limit 1 req/sec (sleep)
    - ✅ 抓不到的 slug 跳过, 不阻断其他
    """
    fetcher = _HTTP_FETCHER or _http_get_simple
    out: Dict[str, Any] = {
        "ok": True,
        "base_url": base_url,
        "slugs_seen": 0,
        "mappings_written": 0,
        "sources_added": 0,
        "errors": [],
    }
    try:
        status, idx_html = fetcher(f"{base_url}/skills")
    except Exception as e:
        return {"ok": False, "error": f"index_fetch_failed: {e}"}
    if status != 200 or not idx_html:
        return {"ok": False, "error": f"index_http_{status}", "skipped": True}
    slugs = _extract_skill_slugs(idx_html)[:max_slugs]
    out["slugs_seen"] = len(slugs)

    cfg = load_hub_config(config_path)
    mappings: Dict[str, Any] = cfg.setdefault("slug_mappings", {})
    sources: List[Dict[str, Any]] = cfg.setdefault("github_sources", [])
    existing_source_ids = {s.get("owner", "") + "/" + s.get("repo", "") for s in sources}
    now_iso = datetime.now(timezone.utc).isoformat()
    rate_per_sec = float(cfg.get("rate_limit_per_sec", 1.0)) if isinstance(cfg.get("rate_limit_per_sec"), (int, float)) else 1.0
    rate_per_sec = max(rate_per_sec, 0.1)  # 不要比 100ms 更猛

    for slug in slugs:
        try:
            time.sleep(1.0 / rate_per_sec)  # rate-limit
            status, html = fetcher(f"{base_url}/skills/{slug}")
        except Exception as e:
            out["errors"].append(f"{slug}: fetch_failed: {e}")
            continue
        if status != 200 or not html:
            out["errors"].append(f"{slug}: http_{status}")
            continue
        gh = _extract_github_repo_from_detail(html)
        if not gh:
            # 详情页没 GitHub URL → 跳过, 卡片降级 ↗ View
            continue
        owner, repo = gh
        source_id = f"{owner}/{repo}"
        # 写 mapping
        existed = slug in mappings
        mappings[slug] = {
            "source": source_id,
            "path": "SKILL.md",
            "scraped_from": base_url,
            "scraped_at": now_iso,
            "confidence": "high",
        }
        if not existed:
            out["mappings_written"] += 1
        # 动态加 scraped source (如果还没有)
        if source_id not in existing_source_ids:
            sources.append({
                "owner": owner, "repo": repo,
                "kind": "scraped", "enabled": True,
                "added_at": now_iso,
                "added_by": "scraper",
                "scraped_from": base_url,
            })
            existing_source_ids.add(source_id)
            out["sources_added"] += 1

    cfg["slug_mappings"] = mappings
    cfg["github_sources"] = sources
    try:
        save_hub_config(cfg, config_path)
    except Exception as e:
        out["errors"].append(f"save_failed: {e}")
        out["ok"] = False
    return out


async def scrape_browse_layers(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """异步调度 — 扫所有 enabled browse layer (spec §5.4 §7)"""
    cfg = load_hub_config(config_path)
    layers = [bl for bl in cfg.get("browse_layers", []) if bl.get("enabled")]
    per_layer: Dict[str, Any] = {}
    errors: List[str] = []
    loop = asyncio.get_running_loop()
    for bl in layers:
        bl_id = bl.get("id")
        base_url = bl.get("base_url")
        if not bl_id or not base_url:
            continue
        try:
            # 当前只实装 .lol, .cn 调同一个函数 (base_url 不同)
            result = await loop.run_in_executor(
                None, scrape_skillhub_lol, base_url, 50, config_path,
            )
            per_layer[bl_id] = result
            bl["last_sync_at"] = datetime.now(timezone.utc).isoformat()
            if not result.get("ok"):
                errors.append(f"{bl_id}: " + str(result.get("error", "unknown")))
        except Exception as e:
            errors.append(f"{bl_id}: {e}")
            per_layer[bl_id] = {"ok": False, "error": str(e)}
    cfg["browse_layers"] = [
        bl if bl.get("id") in {k for k in per_layer} else bl
        for bl in cfg.get("browse_layers", [])
    ]
    try:
        save_hub_config(cfg, config_path)
    except Exception as e:
        errors.append(f"save_failed: {e}")
    return {
        "ok": len(errors) == 0,
        "per_layer": per_layer,
        "errors": errors,
    }




# ── S3: catalog sync (sync 永远不动本地) ────────────────────────


async def _refresh_one_source(owner: str, repo: str, force: bool = False) -> Dict[str, Any]:
    """单源 refresh — 同步包装 mp.refresh_source

    故意做成 run_in_executor, 因为 mp.refresh_source 是同步阻塞 IO;
    在 hub 的 asyncio loop 里跑会卡整 loop。We keep it thread-safe.
    """
    from app.core import marketplace as mp
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, mp.refresh_source, owner, repo, force)


async def sync_all_sources(force: bool = False, config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Catalog sync — 拉 enabled GitHub sources 的 SKILL.md tree, 写 registry

    铁律: ❌ 不 install, ❌ 不写本地 hermes skills
    仅写 marketplace_registry.json (catalog cache) + community_hub.json 状态

    Returns: {ok, sources_synced, total_skills, per_source: {...}, errors: [...]}
    """
    cfg = load_hub_config(config_path)
    sources = [s for s in cfg.get("github_sources", []) if s.get("enabled", True)]

    per_source: Dict[str, Any] = {}
    errors: List[str] = []
    total_skills = 0

    for src in sources:
        source_id = f"{src['owner']}/{src['repo']}"
        try:
            result = await _refresh_one_source(src["owner"], src["repo"], force=force)
            count = result.get("count", 0) if isinstance(result, dict) else 0
            per_source[source_id] = {"ok": result.get("ok", True), "count": count, "skipped": result.get("skipped", False)}
            total_skills += count
            # 记每源同步时间
            src["last_sync_at"] = datetime.now(timezone.utc).isoformat()
            src["last_sync_status"] = "ok" if result.get("ok") else "error"
        except Exception as e:
            errors.append(f"{source_id}: {e}")
            per_source[source_id] = {"ok": False, "error": str(e)}
            src["last_sync_at"] = datetime.now(timezone.utc).isoformat()
            src["last_sync_status"] = "error"
            logger.warning(f"refresh {source_id} failed: {e}")

    # 持久化 (sources 状态 / errors 不写, errors 仅 return)
    cfg["github_sources"] = sources
    try:
        save_hub_config(cfg, config_path)
    except Exception as e:
        logger.warning(f"save_hub_config failed (无害): {e}")

    return {
        "ok": len(errors) == 0,
        "sources_synced": len(sources),
        "count": total_skills,
        "total_skills": total_skills,
        "per_source": per_source,
        "errors": errors,
    }


async def install_from_slug(
    slug: str,
    config_path: Optional[Path] = None,
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    """用户主动 install 路径 (spec §7)

    流程 (spec §7 install flow):
    1. 查 slug_mappings[slug] — 若无映射 → 抛 NoMappingError
    2. 拿 mapping → 调 marketplace.install_skill(name=slug, source=source)
    3. 返回 {ok, path, abs_path, quarantined, skill_type, slug, source}

    铁律: 这条路径是唯一 install 入口, 后端不验证"用户已确认", 那是前端 UX 增强.
    """
    if not slug or not isinstance(slug, str):
        return {"ok": False, "error": "slug 必填 (string)"}
    slug = slug.strip()
    if not slug:
        return {"ok": False, "error": "slug 不能为空"}

    cfg = load_hub_config(config_path)
    mappings = cfg.get("slug_mappings", {})
    mapping = mappings.get(slug)
    if not mapping:
        return {
            "ok": False,
            "error": "no_source_mapping",
            "slug": slug,
            "view_url": f"https://skillhub.lol/skills/{slug}",  # best-effort 引导
        }

    source = mapping.get("source")
    if not source or "/" not in source:
        return {
            "ok": False,
            "error": f"mapping['source'] 非法: {source!r}",
            "slug": slug,
        }

    # 调 marketplace 真正的 install (同步 IO, 走 executor 不卡 loop)
    from app.core import marketplace as mp
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, mp.install_skill, slug, source, profile
    )
    # 补字段给前端
    if result.get("ok"):
        result["slug"] = slug
        result["source"] = source
        result["instructions"] = "去 Local Tab 解 quarantine 激活"
    else:
        result["slug"] = slug
        result["source"] = source
    return result


def add_user_mapping(
    slug: str,
    source: str,
    path: str,
    config_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """用户补 mapping (spec §5.9 POST /api/hub/slug-mapping)

    - slug: 唯一 key (e.g. 'seo-audit')
    - source: 'owner/repo' 格式
    - path: 在 repo 内相对路径, 通常 'SKILL.md'
    """
    if not slug or not isinstance(slug, str):
        return {"ok": False, "error": "slug 必填"}
    slug = slug.strip()
    # source 必须是 owner/repo: 含恰好一个 '/', 不含空格, 两侧非空
    if " " in source or source.count("/") != 1:
        return {"ok": False, "error": f"source 格式应为 owner/repo, 收到 {source!r}"}
    owner, repo = source.split("/", 1)
    if not owner.strip() or not repo.strip():
        return {"ok": False, "error": f"source 的 owner/repo 不能为空"}
    if not path or not isinstance(path, str):
        return {"ok": False, "error": "path 必填"}
    if path.startswith("/") or ".." in Path(path).parts:
        return {"ok": False, "error": f"path 不安全: {path!r}"}

    cfg = load_hub_config(config_path)
    mappings = cfg.setdefault("slug_mappings", {})
    now_iso = datetime.now(timezone.utc).isoformat()
    existed = slug in mappings
    mappings[slug] = {
        "source": f"{owner.strip()}/{repo.strip()}",
        "path": path.strip(),
        "scraped_from": "user_api",
        "scraped_at": now_iso,
        "confidence": "user_supplied",
    }
    save_hub_config(cfg, config_path)
    return {
        "ok": True,
        "slug": slug,
        "mapping": mappings[slug],
        "updated": existed,
    }
