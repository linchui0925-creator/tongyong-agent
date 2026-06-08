"""
Skill 市场 API（/api/marketplace/*）

跟 multi_agent 的 /api/multi_agent/marketplace/* 区分开
（那个是 Agent 模板市场；本路由管 SKILL.md 资源）

接口：
- GET  /api/marketplace/skills              列表（支持 category/search/source 过滤）
- GET  /api/marketplace/skills/{name}       详情
- GET  /api/marketplace/categories          分类聚合
- GET  /api/marketplace/sources             当前已配置的仓库源
- POST /api/marketplace/sources             body: {owner_repo: "x/y"} 添加并刷新
- DELETE /api/marketplace/sources/{owner_repo} 移除（不删 registry 缓存）
- POST /api/marketplace/refresh             body: {owner_repo?: str, force?: bool} 刷新
- POST /api/marketplace/skills/{name}/install  body: {source, profile?} 安装到本地
"""

import logging
from datetime import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException, Body, Query

from app.config import settings
from app.core import marketplace as mp

# 本地 hermes skills 根目录（settings.hermes_skills_dir 已含 /skills 后缀）
_LOCAL_SKILLS_DIR = Path(settings.hermes_skills_dir)


def _resolve_local_skill_path(name: str) -> Optional[Path]:
    """在所有 category 目录里找名为 <name> 的 SKILL.md"""
    if not _LOCAL_SKILLS_DIR.is_dir():
        return None
    for cat_dir in _LOCAL_SKILLS_DIR.iterdir():
        candidate = cat_dir / name / "SKILL.md"
        if candidate.is_file():
            return candidate
    return None


def _resolve_local_skill_dir(name: str) -> Optional[Path]:
    """在所有 category 目录里找名为 <name> 的 skill 目录"""
    if not _LOCAL_SKILLS_DIR.is_dir():
        return None
    for cat_dir in _LOCAL_SKILLS_DIR.iterdir():
        candidate = cat_dir / name
        if candidate.is_dir():
            return candidate
    return None


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


# ── 列表 / 详情 / 分类 ───────────────────────────────

@router.get("/skills")
async def list_skills(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """列出 marketplace 中的 skill（不刷新缓存）"""
    all_skills = mp.list_marketplace_skills(
        category=category, search=search, source=source,
    )
    total = len(all_skills)
    start = (page - 1) * page_size
    page_skills = all_skills[start:start + page_size]

    # Phase 4+: 给每条 skill 补本地是否已装 + 装时的版本/时间
    # 扫本地 _LOCAL_SKILLS_DIR 下所有 SKILL.md，frontmatter 里有 source_repo/source 字段
    # 即为"已装来自市场"
    installed_index = _build_local_installed_index()
    for s in page_skills:
        local = installed_index.get(s["name"])
        s["installed"] = local is not None
        if local:
            s["local_quarantined"] = local.get("quarantined", False)
            s["local_skill_type"] = local.get("skill_type", "external")
        else:
            s["local_quarantined"] = None
            s["local_skill_type"] = None

    return {
        "skills": page_skills,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _build_local_installed_index() -> Dict[str, Dict[str, Any]]:
    """扫本地 _LOCAL_SKILLS_DIR，按 frontmatter.source_repo 区分市场来源

    返回 {name: {source_repo, quarantined, skill_type, version, installed_at}} 字典
    """
    index: Dict[str, Dict[str, Any]] = {}
    if not _LOCAL_SKILLS_DIR.exists():
        return index
    import yaml as _yaml
    for skill_dir in _LOCAL_SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue
        # 抽 frontmatter
        meta: Dict[str, Any] = {}
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = _yaml.safe_load(parts[1]) or {}
                except Exception:
                    meta = {}
        # 只索引来自市场的（source_repo 字段存在）
        source_repo = meta.get("source_repo")
        if not source_repo:
            continue
        try:
            stat = skill_md.stat()
            import datetime as _dt
            installed_at = _dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        except Exception:
            installed_at = None
        index[skill_dir.name] = {
            "source_repo": source_repo,
            "quarantined": bool(meta.get("quarantined", True)),
            "skill_type": meta.get("skill_type", "external"),
            "auto_load": bool(meta.get("auto_load", False)),
            "version": meta.get("version", 1),
            "installed_at": installed_at,
        }
    return index


@router.get("/skills/{name}")
async def get_skill(name: str, source: Optional[str] = Query(None)):
    """获取单个 skill 详情（不含原始 content；content 在 install 时再拉）"""
    skill = mp.get_marketplace_skill(name, source=source)
    if not skill:
        raise HTTPException(status_code=404, detail=f"marketplace skill '{name}' not found")
    # 不返回内部字段
    return {k: v for k, v in skill.items() if k != "size_bytes"}


@router.get("/categories")
async def list_categories():
    """分类聚合（带计数）"""
    return {"categories": mp.list_marketplace_categories()}


# ── 源管理 ─────────────────────────────────────────

@router.get("/sources")
async def list_sources():
    """当前已配置的 GitHub 源

    优先返回 settings.marketplace_sources（用户主动添加的源），
    并合并 registry 里的源（避免 reload 后 settings 内存清空导致 UI 看不到）.
    """
    cache = mp._load_cache()
    registry_sources = list(cache.get("sources", {}).keys())
    settings_sources = list(settings.marketplace_sources)
    # 合并去重, settings 优先
    seen = set()
    merged = []
    for s in settings_sources + registry_sources:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            merged.append(s)
    return {"sources": merged}


@router.post("/sources")
async def add_source(payload: Dict[str, Any] = Body(...)):
    """添加一个 GitHub 源（owner/repo），立即刷新"""
    owner_repo = payload.get("owner_repo")
    if not owner_repo or not isinstance(owner_repo, str):
        raise HTTPException(status_code=400, detail="owner_repo 必填，格式: owner/repo")
    result = mp.add_source(owner_repo)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "add failed"))
    return result


@router.delete("/sources/{owner_repo:path}")
async def remove_source(owner_repo: str):
    """移除一个源（注意：path 参数允许 owner_repo 含 /）"""
    return mp.remove_source(owner_repo)


# ── 刷新 ───────────────────────────────────────────

@router.post("/refresh")
async def refresh(payload: Dict[str, Any] = Body(default_factory=dict)):
    """刷新 registry。body: {owner_repo?: "x/y", force?: bool}"""
    owner_repo = payload.get("owner_repo")
    force = bool(payload.get("force", False))
    if owner_repo:
        if "/" not in owner_repo:
            raise HTTPException(status_code=400, detail="owner_repo 格式: owner/repo")
        owner, repo = owner_repo.split("/", 1)
        return mp.refresh_source(owner.strip(), repo.strip(), force=force)
    return mp.refresh_all_sources(force=force)


# ── 安装 ───────────────────────────────────────────

@router.post("/skills/{name}/install")
async def install(name: str, payload: Dict[str, Any] = Body(default_factory=dict)):
    """把 marketplace skill 落地到本地 hermes skills 目录

    body: {source: "owner/repo", profile?: "linc"}
    返回：{ok, path, abs_path, quarantined: true, skill_type: "external"}

    注意：默认 quarantined=true，不出现在 agent 索引里
    """
    source = payload.get("source")
    if not source:
        raise HTTPException(status_code=400, detail="source 必填")
    profile = payload.get("profile")
    result = mp.install_skill(name, source, profile=profile)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "install failed"))
    return result


@router.post("/skills/{name}/reinstall")
async def reinstall(name: str, payload: Dict[str, Any] = Body(default_factory=dict)):
    """重装已存在的 marketplace skill（强制覆盖，保留 quarantined 状态）

    语义:
    - 必须已存在(否则 404)
    - 走 install_skill 全链路(含配套文件下载 + 整目录备份)
    - 重装后恢复原 quarantined / skill_type 状态(因为 install_skill 会强制 quarantined=true)
    - 重新走安全扫描
    - 触发 skills_index 缓存刷新

    body: {source: "owner/repo"}  ← source 用于定位抓取源
    返回: install_skill 的返回(ok, path, files 列表等)
    """
    source = payload.get("source")
    if not source:
        raise HTTPException(status_code=400, detail="source 必填")

    # 1. 找本地目标目录
    target_dir = _resolve_local_skill_dir(name)
    if not target_dir or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"本地未找到 skill '{name}'，无法重装")

    # 2. 记录原 quarantined / skill_type, 重装后恢复
    original_meta_path = target_dir / "SKILL.md"
    original_quarantined = None
    original_skill_type = None
    if original_meta_path.is_file():
        try:
            _content = original_meta_path.read_text(encoding="utf-8")
            _meta, _ = mp._parse_skill_md(_content)
            original_quarantined = _meta.get("quarantined")
            original_skill_type = _meta.get("skill_type")
        except Exception:
            pass

    # 3. 复用 install_skill (含配套文件下载)
    result = mp.install_skill(name, source)
    if not result.get("ok"):
        # 特殊处理 404 (没找到)
        if "找不到" in (result.get("error") or ""):
            raise HTTPException(status_code=404, detail=result.get("error"))
        raise HTTPException(status_code=400, detail=result.get("error", "reinstall failed"))

    # 4. 恢复原 quarantined / skill_type (install_skill 会强制 quarantined=True, 改回去)
    if original_quarantined is not None and original_meta_path.is_file():
        try:
            _content = original_meta_path.read_text(encoding="utf-8")
            _meta, _body = mp._parse_skill_md(_content)
            _meta["quarantined"] = original_quarantined
            if original_skill_type is not None:
                _meta["skill_type"] = original_skill_type
            new_content = f"---\n{yaml.dump(_meta, allow_unicode=True, default_flow_style=False)}---\n\n{_body}\n"
            original_meta_path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"恢复 quarantined 状态失败: {e}")

    # 5. 刷新索引
    try:
        from app.core.skills_index import refresh as refresh_skills_index
        refresh_skills_index()
    except Exception as e:
        logger.warning(f"刷新 skill 索引失败: {e}")

    # 6. 加个 backup 字段让前端能展示
    # install_skill 已经备份到 <name>.bak.<ts>/ 形式, 找一下
    backups = sorted(
        target_dir.parent.glob(f"{name}.bak.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result["backup"] = str(backups[0]) if backups else None
    result["refreshed_at"] = _dt.now().isoformat(timespec="seconds")
    return result
