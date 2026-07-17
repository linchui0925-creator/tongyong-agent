"""
hub API - W5-1 Community Hub HTTP 路由 (spec §5.9)

本文件只实装 S4 路由 (info / sources CRUD / sync); S5 install 在 /api/hub/install
S6 browse layer 在 /api/hub/browse-layers
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request

from app.core import community_hub as hub_mod
from app.core import skill_search
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hub", tags=["hub"])

# 接受 owner_repo 路径段 (含 /); FastAPI 默认 path 不能含 /, 用 :path 显式
_OWNER_REPO_REGEX = r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$"


# ── helpers ──────────────────────────────────────────────────────

def _hub_cfg_path() -> Path:
    return hub_mod.CONFIG_PATH


def _hub_cfg() -> Dict[str, Any]:
    return hub_mod.load_hub_config(_hub_cfg_path())


def _save_hub_cfg(cfg: Dict[str, Any]) -> None:
    hub_mod.save_hub_config(cfg, _hub_cfg_path())


def _scheduler(request: Request) -> Optional[hub_mod.HubScheduler]:
    """从 app.state.hub 拿 scheduler, 没启就 None"""
    return getattr(request.app.state, "hub", None)


def _validate_owner_repo(s: str) -> tuple:
    if not re.match(_OWNER_REPO_REGEX, s):
        raise HTTPException(status_code=400, detail="owner_repo 格式: owner/repo")
    owner, repo = s.split("/", 1)
    return owner.strip(), repo.strip()


# ── info ────────────────────────────────────────────────────────

@router.get("/search")
async def search_skills(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    """实时代理 skills.sh 搜索，不写入本地 catalog。"""
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="q 不能为空")
    try:
        skills = await asyncio.to_thread(skill_search.search_skills, query, limit)
    except skill_search.SkillSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "query": query, "skills": skills, "total": len(skills)}


@router.get("/info")
async def info(request: Request):
    """Hub 状态概览 — 给前端 Hub Status card"""
    cfg = _hub_cfg()
    sched = _scheduler(request)

    enabled_sources = [s for s in cfg.get("github_sources", []) if s.get("enabled", True)]
    return {
        "ok": True,
        "config_path": str(_hub_cfg_path()),
        "sources_total": len(cfg.get("github_sources", [])),
        "sources_enabled": len(enabled_sources),
        "browse_layers": [
            {"id": bl.get("id"), "enabled": bl.get("enabled", False),
             "last_sync_at": bl.get("last_sync_at"),
             "scraped_count": bl.get("scraped_count", 0)}
            for bl in cfg.get("browse_layers", [])
        ],
        "slug_mappings_count": len(cfg.get("slug_mappings", {})),
        "scheduler": {
            "running": sched is not None and sched._task is not None,
            "last_sync_at": sched.last_sync_at if sched else None,
            "last_sync_status": sched.last_sync_status if sched else None,
            "last_sync_count": sched.last_sync_count if sched else None,
            "last_sync_error": sched.last_sync_error if sched else None,
            "sync_count": sched.sync_count if sched else 0,
            "interval_seconds": sched._interval if sched else
                settings.community_hub_sync_interval_hours * 3600,
        },
        "schema": cfg.get("schema"),
        "updated_at": cfg.get("updated_at"),
    }


# ── sources CRUD ────────────────────────────────────────────────

@router.get("/sources")
async def list_sources():
    cfg = _hub_cfg()
    return {
        "sources": cfg.get("github_sources", []),
        "total": len(cfg.get("github_sources", [])),
    }


@router.post("/sources")
async def add_source(payload: Dict[str, Any] = Body(...)):
    """添加 user source — body: {owner_repo: 'x/y'}"""
    owner_repo = (payload.get("owner_repo") or "").strip()
    if not owner_repo:
        raise HTTPException(status_code=400, detail="owner_repo 必填")
    owner, repo = _validate_owner_repo(owner_repo)

    cfg = _hub_cfg()
    source_id = f"{owner}/{repo}"
    # 默认源保护 (在 duplicate 检查之前, 默认源 400 而非 409)
    default_ids = {f"{o}/{r}" for o, r, _ in hub_mod.DEFAULT_HUB_REPOS}
    if source_id in default_ids:
        raise HTTPException(status_code=400, detail="默认源不可手动添加 (已存在)")

    # 重复检测
    if any(f"{s['owner']}/{s['repo']}" == source_id for s in cfg.get("github_sources", [])):
        raise HTTPException(status_code=409, detail=f"source '{source_id}' 已存在")

    new_source = {
        "owner": owner, "repo": repo,
        "kind": "user", "enabled": True,
        "added_at": hub_mod.datetime.now(hub_mod.timezone.utc).isoformat(),
        "added_by": "user_api",
        "scraped_from": None,
    }
    cfg["github_sources"].append(new_source)
    _save_hub_cfg(cfg)
    return {"ok": True, "source": new_source, "source_id": source_id}


@router.delete("/sources/{owner_repo:path}")
async def remove_source(owner_repo: str):
    owner, repo = _validate_owner_repo(owner_repo)
    source_id = f"{owner}/{repo}"

    cfg = _hub_cfg()
    default_ids = {f"{o}/{r}" for o, r, _ in hub_mod.DEFAULT_HUB_REPOS}
    if source_id in default_ids:
        raise HTTPException(status_code=400, detail="默认源不可删除 (disable 即可)")

    before = len(cfg.get("github_sources", []))
    cfg["github_sources"] = [
        s for s in cfg.get("github_sources", [])
        if f"{s['owner']}/{s['repo']}" != source_id
    ]
    if len(cfg["github_sources"]) == before:
        raise HTTPException(status_code=404, detail=f"source '{source_id}' 不存在")
    # 删除关联 slug_mappings (那些 mapping 指向这源)
    cfg["slug_mappings"] = {
        k: v for k, v in cfg.get("slug_mappings", {}).items()
        if v.get("source") != source_id
    }
    _save_hub_cfg(cfg)
    return {"ok": True, "removed": source_id}


@router.post("/sources/{owner_repo:path}/toggle")
async def toggle_source(owner_repo: str):
    owner, repo = _validate_owner_repo(owner_repo)
    source_id = f"{owner}/{repo}"

    cfg = _hub_cfg()
    target = None
    for s in cfg.get("github_sources", []):
        if f"{s['owner']}/{s['repo']}" == source_id:
            target = s
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"source '{source_id}' 不存在")

    target["enabled"] = not target.get("enabled", True)
    _save_hub_cfg(cfg)
    return {"ok": True, "source_id": source_id, "enabled": target["enabled"]}


# ── sync 触发 ──────────────────────────────────────────────────

@router.post("/sync")
async def trigger_sync(request: Request, payload: Dict[str, Any] = Body(default_factory=dict)):
    """手动触发 catalog sync (background, 不阻塞响应)

    body: {force: bool} 默认 false
    """
    sched = _scheduler(request)
    if sched is None:
        raise HTTPException(status_code=503, detail="HubScheduler 未初始化")
    force = bool(payload.get("force", False))
    # 实际 sync 拉到 background, 立刻返回
    asyncio.create_task(sched.sync_now())
    return {
        "ok": True,
        "triggered": True,
        "force": force,
        "scheduler_running": sched._task is not None,
        "note": "后台运行, 通过 /api/hub/info 看进度",
    }


# ── diff ────────────────────────────────────────────────────────

@router.get("/diff")
async def diff(source: Optional[str] = Query(None)):
    """跨源聚合 catalog (基于 marketplace_registry) + 简单 diff (new/updated/removed)

    S4 阶段用 mp.list_marketplace_skills() 输出; 真正的 diff 自愈需要 S3 sync 跑过
    之后再加。这一步先返回 registry 全部 + status
    """
    from app.core import marketplace as mp
    skills = mp.list_marketplace_skills(source=source)
    return {
        "ok": True,
        "skills": skills,
        "total": len(skills),
        "source": source,
        "note": "diff 自愈逻辑在 S3 sync 跑过之后才能精确给出",
    }



# ── browse layers (spec §5.6 §5.9) ─────────────────────────

@router.get("/browse-layers")
async def list_browse_layers():
    """已配 browse layer 列表 — 给前端 Browse Layers panel"""
    cfg = _hub_cfg()
    return {
        "layers": cfg.get("browse_layers", []),
        "total": len(cfg.get("browse_layers", [])),
    }


@router.post("/browse-layers/{layer_id}/toggle")
async def toggle_browse_layer(layer_id: str, payload: Dict[str, Any] = Body(default_factory=dict)):
    """enable / disable 一个 browse layer

    body: {enabled: bool}  (省略则 toggle)
    """
    cfg = _hub_cfg()
    target = None
    for bl in cfg.get("browse_layers", []):
        if bl.get("id") == layer_id:
            target = bl
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"browse layer '{layer_id}' 不存在")

    if "enabled" in payload:
        target["enabled"] = bool(payload["enabled"])
    else:
        target["enabled"] = not target.get("enabled", False)

    if target["enabled"] and not target.get("user_enabled_at"):
        target["user_enabled_at"] = hub_mod.datetime.now(hub_mod.timezone.utc).isoformat()

    _save_hub_cfg(cfg)
    return {"ok": True, "layer_id": layer_id, "enabled": target["enabled"]}


# ── install — 唯一 install path (spec §7) ───────────────────

@router.post("/install")
async def install_skill(payload: Dict[str, Any] = Body(...)):
    """用户主动 install 入口 — body: {slug, source?, profile?}

    - 查 slug_mappings[slug] → 无映射返回 404 + view_url
    - 走 marketplace.install_skill (默认 quarantined=true, skill_type=external)
    - 不验证"用户已确认" — 那是前端 UX 增强
    """
    slug = (payload.get("slug") or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug 必填")
    profile = payload.get("profile")
    source = (payload.get("source") or "").strip()
    if source:
        _validate_owner_repo(source)
    result = await hub_mod.install_from_slug(slug, profile=profile, source=source or None)
    if not result.get("ok"):
        err = result.get("error", "install failed")
        if err == "no_source_mapping":
            raise HTTPException(
                status_code=404,
                detail={
                    "error": err,
                    "slug": slug,
                    "view_url": result.get("view_url"),
                    "message": "无 source repo 映射, 可通过 /api/hub/slug-mapping 补 mapping 或点 ↗ View",
                },
            )
        # 安全扫描失败
        if "安全扫描" in err or "安全" in err:
            raise HTTPException(
                status_code=403,
                detail={"error": err, "slug": slug, "source": result.get("source")},
            )
        # marketplace 找不到该 skill
        if "marketplace 中找不到" in err:
            raise HTTPException(status_code=404, detail={"error": err, "slug": slug})
        # 拉取失败 / 其他
        raise HTTPException(status_code=400, detail={"error": err, "slug": slug})
    return result


# ── slug mapping (spec §5.9) ───────────────────────────────

@router.get("/slug-mapping")
async def get_slug_mappings():
    """当前所有 slug → {source, path} 映射"""
    cfg = _hub_cfg()
    return {
        "mappings": cfg.get("slug_mappings", {}),
        "total": len(cfg.get("slug_mappings", {})),
    }


@router.post("/slug-mapping")
async def post_slug_mapping(payload: Dict[str, Any] = Body(...)):
    """用户补 mapping — body: {slug, source: 'owner/repo', path: 'SKILL.md'}

    用法:
    - browse layer 还没挖到的 slug, 用户手动指 source
    - scrape 挖错的 mapping, 用户覆盖

    注意: 只更新 mapping, 不立即 install (需再 POST /api/hub/install)
    """
    slug = (payload.get("slug") or "").strip()
    source = (payload.get("source") or "").strip()
    path = (payload.get("path") or "SKILL.md").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug 必填")
    if not source:
        raise HTTPException(status_code=400, detail="source 必填 (格式: owner/repo)")
    result = hub_mod.add_user_mapping(slug, source, path)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "add failed"))
    return result
