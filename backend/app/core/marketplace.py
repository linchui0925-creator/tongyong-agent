"""
marketplace - Skill 市场后端

功能：
- 从用户配置的 GitHub 仓库列表（owner/repo）抓取所有 SKILL.md
- 用 frontmatter 解析补全元信息（description/category/version/tags）
- 复用 _SKILL_THREAT_PATTERNS 做安全扫描，过滤的项不入 registry
- 缓存到 backend/public/marketplace_registry.json（带 ETag / Last-Modified）
- 提供 install() 把远端 skill 落地到本地 hermes skills 目录
  （skill_type=external, quarantined=true，待用户在前端确认后激活）

数据源：用户在前端"+ 添加源"输入 owner/repo 写入 settings.marketplace_sources
"""

import json
import logging
import os
import re
import shutil
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.config import settings

logger = logging.getLogger(__name__)

# ── 路径 ──────────────────────────────────────────

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_PATH = _BACKEND_ROOT / "public" / "marketplace_registry.json"
_LOCAL_SKILLS_DIR = Path(settings.hermes_skills_dir)

# ── 安全规则（与 hermes/skill_file.py 保持一致） ────

_SKILL_THREAT_PATTERNS = [
    r"rm\s+-rf\s+/",
    r":(){:|:&};:",  # fork bomb
    r"sudo\s+",
    r"chmod\s+-R\s+777",
    r"curl\s+.*\|\s*(bash|sh)\b",
    r"wget\s+.*-O-\s+.*\|\s*(bash|sh)\b",
    r"base64\s+.*decode.*\|.*(bash|sh)\b",
    r"eval\s*\(",
    r"exec\s*\(",
    r"system\s*\(",
    r"DROP\s+(TABLE|DATABASE)",
    r"git\s+push\s+--force",
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"you\s+are\s+(not|no\s+longer)",
]

# GitHub raw 模板
_GH_RAW_TEMPLATE = "https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
_GH_TREE_API = "https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
_GH_FILE_API = "https://api.github.com/repos/{owner}/{repo}/contents/{path}"

# 无需 Cookie/API Key 的公开 Skill 社区源。用户仍可在界面添加其他 GitHub 仓库。
DEFAULT_PUBLIC_SKILL_SOURCES = (
    "anthropics/skills",
    "obra/superpowers",
)


# ── 缓存辅助 ──────────────────────────────────────

def _load_cache() -> Dict[str, Any]:
    """读取 marketplace_registry.json，文件不存在则返回空结构"""
    if not _REGISTRY_PATH.is_file():
        return {
            "version": 1,
            "updated_at": None,
            "etag": None,
            "sources": {},  # source_id -> {owner, repo, etag, last_fetch, skills: []}
        }
    try:
        with _REGISTRY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            # 兼容老格式
            if "sources" not in data:
                data["sources"] = {}
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"marketplace registry 损坏，重新初始化: {e}")
        return {"version": 1, "updated_at": None, "etag": None, "sources": {}}


def _save_cache(data: Dict[str, Any]) -> None:
    """写入 marketplace_registry.json（原子：先写 .tmp 再 rename）"""
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _REGISTRY_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(_REGISTRY_PATH)


def _is_cache_fresh(source_data: Dict[str, Any]) -> bool:
    """判断某个源是否还在 TTL 内"""
    ttl_seconds = settings.marketplace_cache_ttl_hours * 3600
    last = source_data.get("last_fetch")
    if not last:
        return False
    try:
        ts = datetime.fromisoformat(last).timestamp()
    except ValueError:
        return False
    return (time.time() - ts) < ttl_seconds


# ── 安全扫描 ──────────────────────────────────────

def _security_scan(content: str) -> Optional[str]:
    """复用 skill_file.py 的 14 条规则；返回第一个匹配 pattern 或 None"""
    content_lower = content.lower()
    for pattern in _SKILL_THREAT_PATTERNS:
        if re.search(pattern, content_lower):
            return pattern
    return None


# ── 描述补全（enrichment） ──────────────────────────

def _enrich_description(meta: Dict[str, str], body: str) -> str:
    """三层降级：frontmatter.description → 第一个 ## 标题 → "No description\""""
    desc = (meta.get("description") or "").strip()
    if desc:
        return desc[:200]
    # 取 body 第一个 ## 标题
    if body:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                title = stripped[3:].strip()
                if title:
                    return f"[no description] {title}"[:200]
    return "No description"


def _parse_skill_md(content: str) -> Tuple[Dict[str, Any], str]:
    """从 SKILL.md 提取 frontmatter + body"""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                if not isinstance(meta, dict):
                    meta = {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].strip()
    return {}, content.strip()


# ── GitHub 抓取 ────────────────────────────────────

# 瞬时网络错误重试次数 (GitHub raw/api 偶发 SSL UNEXPECTED_EOF)
_HTTP_MAX_RETRIES = 3
_HTTP_RETRY_BACKOFF = 0.8


def _build_ssl_context() -> "ssl.SSLContext":
    """优先用 certifi 的 CA bundle，没有就 unverified（仅 fallback）"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl._create_unverified_context()


def _http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], str]:
    """简易 HTTP GET，返回 (status, headers, body)

    macOS 系统的 Python 不带 system CA bundle，会报 CERTIFICATE_VERIFY_FAILED
    这里优先用 certifi 的 CA bundle（项目里应该装了），没有就回退到 unverified。
    对瞬时网络错误（SSL UNEXPECTED_EOF / URLError / timeout）做指数退避重试。
    """
    ssl_context = _build_ssl_context()

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "tongyong-agent-marketplace/1.0")
    req.add_header("Accept", "application/vnd.github.v3+json")
    if settings.marketplace_github_token:
        req.add_header("Authorization", f"token {settings.marketplace_github_token}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    last_err: Optional[Exception] = None
    for attempt in range(1, _HTTP_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=15, context=ssl_context) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # HTTP 层面的错误 (403/404/500) 不重试, 直接返回
            return e.code, dict(e.headers) if e.headers else {}, ""
        except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < _HTTP_MAX_RETRIES:
                time.sleep(_HTTP_RETRY_BACKOFF * attempt)
                continue
    logger.warning(f"GET {url} 失败 (重试 {_HTTP_MAX_RETRIES} 次): {type(last_err).__name__}: {last_err}")
    return 0, {}, ""


def _list_skill_files_in_repo(owner: str, repo: str) -> Dict[str, List[Dict[str, Any]]]:
    """递归列出仓库中所有 SKILL.md 的相对路径, 并附带每个 skill 目录下的所有文件

    返回: { skill_md_path: [{path, size, sha, type}, ...] }
        - skill_md_path: SKILL.md 的仓库内路径
        - files[i].path: 相对于仓库根的路径
        - 包含 SKILL.md 本体
    """
    url = _GH_TREE_API.format(owner=owner, repo=repo)
    status, headers, body = _http_get(url)
    if status != 200:
        logger.warning(f"列仓库 {owner}/{repo} 树失败: HTTP {status}")
        return {}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {}

    # 第一遍: 找所有 SKILL.md
    skill_md_paths: List[str] = []
    for item in data.get("tree", []):
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if path.endswith("SKILL.md") and not path.startswith("."):
            skill_md_paths.append(path)

    # 第二遍: 按 skill 目录归类文件
    result: Dict[str, List[Dict[str, Any]]] = {}
    for skill_md in skill_md_paths:
        skill_dir = str(Path(skill_md).parent)
        # SKILL.md 本身 + 同目录下所有文件
        files: List[Dict[str, Any]] = []
        for item in data.get("tree", []):
            if item.get("type") != "blob":
                continue
            ip = item.get("path", "")
            # 保留 Skill 目录下的完整递归结构（references/scripts/assets 等）。
            if ip == skill_md or ip.startswith(skill_dir.rstrip("/") + "/"):
                files.append({
                    "path": ip,
                    "size": int(item.get("size", 0) or 0),
                    "sha": item.get("sha", ""),
                    "type": item.get("type", "blob"),
                })
        result[skill_md] = sorted(files, key=lambda f: f["path"])

    return result


def _list_skill_paths_in_repo(owner: str, repo: str) -> List[str]:
    """递归列出仓库中所有 SKILL.md 的相对路径（兼容旧 API）"""
    files_map = _list_skill_files_in_repo(owner, repo)
    return sorted(files_map.keys())


def _safe_rel_path(rel_path: str) -> Optional[str]:
    """校验文件相对路径, 防止路径穿越 (../)

    返回清理后的路径, 如果不安全返回 None
    """
    # 禁止绝对路径
    if rel_path.startswith("/"):
        return None
    # 禁止 ..
    parts = Path(rel_path).parts
    if any(p == ".." for p in parts):
        return None
    # 禁止隐藏文件/目录
    if any(p.startswith(".") for p in parts):
        return None
    return rel_path


def _fetch_skill_content(owner: str, repo: str, path: str) -> Optional[str]:
    """拉取单个 SKILL.md 的 raw 内容"""
    url = _GH_RAW_TEMPLATE.format(owner=owner, repo=repo, path=path)
    status, _, body = _http_get(url)
    if status != 200 or not body:
        logger.warning(f"拉取 {owner}/{repo}/{path} 失败: HTTP {status}")
        return None
    return body


def _fetch_skill_bytes(owner: str, repo: str, path: str) -> Optional[bytes]:
    """按原始字节下载 Skill 配套文件。"""
    import ssl
    import urllib.error
    import urllib.request

    try:
        import certifi

        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_context = ssl._create_unverified_context()

    url = _GH_RAW_TEMPLATE.format(owner=owner, repo=repo, path=path)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "tongyong-agent-marketplace/1.0"},
    )
    if settings.marketplace_github_token:
        request.add_header("Authorization", f"token {settings.marketplace_github_token}")
    try:
        with urllib.request.urlopen(request, timeout=15, context=ssl_context) as response:
            if response.status != 200:
                return None
            return response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("拉取 %s/%s/%s 失败: %s", owner, repo, path, exc)
        return None


# ── 注册表管理 ────────────────────────────────────

def get_registry() -> Dict[str, Any]:
    """返回完整 registry（不触发网络）"""
    return _load_cache()


def list_marketplace_skills(
    category: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """从 registry 列出 skill（不刷新缓存）

    返回每条：{name, description, category, version, tags, source, source_url, content_preview}
    同名 skill 可能来自多个 source，因此这里按 (name, source_repo) 去重，
    避免前端出现重复 key，也避免同一仓库的重复条目被重复展示。
    """
    cache = _load_cache()
    results: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    search_lower = (search or "").lower().strip()

    for src_id, src in cache.get("sources", {}).items():
        if source and src_id != source:
            continue
        source_repo = f"{src.get('owner')}/{src.get('repo')}"
        for skill in src.get("skills", []):
            if skill.get("quarantined_reason"):
                continue
            cat = skill.get("category", "general")
            if category and cat != category:
                continue
            if search_lower:
                haystack = f"{skill.get('name', '')} {skill.get('description', '')}".lower()
                if search_lower not in haystack:
                    continue

            dedupe_key = (skill.get("name", ""), source_repo)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            files_meta = skill.get("files", [])
            extra_files = [f for f in files_meta if f.get("path") != skill.get("path")]
            extra_size = sum(int(f.get("size", 0) or 0) for f in extra_files)

            results.append({
                "name": skill["name"],
                "description": skill.get("description", ""),
                "category": cat,
                "version": skill.get("version", "0.0.0"),
                "tags": skill.get("tags", []),
                "source": src_id,
                "source_repo": source_repo,
                "source_path": skill.get("path"),
                "source_url": f"https://github.com/{src.get('owner')}/{src.get('repo')}/blob/HEAD/{skill.get('path')}",
                "size_bytes": skill.get("size_bytes", 0),
                "files": files_meta,
                "file_count": len(extra_files),
                "total_size_bytes": skill.get("size_bytes", 0) + extra_size,
            })
    return results


def list_marketplace_categories() -> List[Dict[str, Any]]:
    """从 registry 聚合所有分类及计数"""
    cache = _load_cache()
    counts: Dict[str, int] = {}
    for src in cache.get("sources", {}).values():
        for skill in src.get("skills", []):
            if skill.get("quarantined_reason"):
                continue
            cat = skill.get("category", "general")
            counts[cat] = counts.get(cat, 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items())]


def get_marketplace_skill(name: str, source: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """获取单个 skill 详情（含原始 raw content）"""
    cache = _load_cache()
    for src_id, src in cache.get("sources", {}).items():
        if source and src_id != source:
            continue
        for skill in src.get("skills", []):
            if skill["name"] == name:
                return {
                    **skill,
                    "source": src_id,
                    "source_repo": f"{src.get('owner')}/{src.get('repo')}",
                }
    return None


# ── 刷新：抓取并更新 registry ─────────────────────

def refresh_source(owner: str, repo: str, force: bool = False) -> Dict[str, Any]:
    """刷新单个仓库的 registry 条目

    流程：
    1. 检查缓存 TTL（force=True 跳过）
    2. 列仓库所有 SKILL.md
    3. 拉每个文件 → 解析 → 安全扫描
    4. 写入 marketplace_registry.json
    """
    source_id = f"{owner}/{repo}"
    cache = _load_cache()
    src = cache["sources"].get(source_id, {})

    if not force and _is_cache_fresh(src):
        return {"ok": True, "skipped": True, "reason": "cache_fresh", "count": len(src.get("skills", []))}

    files_map = _list_skill_files_in_repo(owner, repo)
    paths = sorted(files_map.keys())
    if not paths and not src:
        return {"ok": False, "error": "list_failed_or_empty_repo", "count": 0}

    skills: List[Dict[str, Any]] = []
    for path in paths:
        content = _fetch_skill_content(owner, repo, path)
        if not content:
            continue

        # 安全扫描
        threat = _security_scan(content)
        if threat:
            logger.warning(f"marketplace 跳过有毒 skill: {owner}/{repo}/{path} ({threat})")
            # 仍然记入 registry，但标 quarantined_reason，让 UI 知道
            skills.append({
                "name": Path(path).parent.name,
                "path": path,
                "category": "general",
                "description": f"[⚠️ 已过滤：匹配 {threat}]",
                "version": "0.0.0",
                "tags": ["quarantined"],
                "quarantined_reason": threat,
                "size_bytes": len(content),
                "files": files_map.get(path, []),
            })
            continue

        meta, body = _parse_skill_md(content)
        # 缺省 name
        name = meta.get("name") or Path(path).parent.name
        category = str(meta.get("category", "general")).strip().lower() or "general"
        # 防御：未知 category 落到 general
        if not re.match(r"^[a-z0-9_-]+$", category):
            category = "general"
        # tags 兼容 list / str
        tags_raw = meta.get("tags", [])
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        else:
            tags = []

        skills.append({
            "name": name,
            "path": path,
            "category": category,
            "description": _enrich_description(meta, body),
            "version": str(meta.get("version", "0.0.0")),
            "tags": tags,
            "quarantined_reason": None,
            "size_bytes": len(content),
            # 关联的配套文件列表（references/templates/scripts/README.md 等）
            "files": files_map.get(path, []),
            # 不缓存 content，下次 install 时再拉
        })

    cache["sources"][source_id] = {
        "owner": owner,
        "repo": repo,
        "last_fetch": datetime.now(timezone.utc).isoformat(),
        "skill_count": len(skills),
        "skills": skills,
    }
    cache["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_cache(cache)
    logger.info(f"marketplace 刷新: {source_id} → {len(skills)} skills")
    return {"ok": True, "count": len(skills), "filtered": sum(1 for s in skills if s.get("quarantined_reason"))}


def get_configured_sources() -> List[str]:
    """返回内置公开社区源与用户源的稳定去重集合。"""
    return list(dict.fromkeys([
        *DEFAULT_PUBLIC_SKILL_SOURCES,
        *(source.strip() for source in settings.marketplace_sources if source.strip()),
    ]))


def ensure_public_sources(force: bool = False) -> Dict[str, Any]:
    """首次打开市场时填充公开社区缓存；已有缓存时遵循 TTL。"""
    cache = _load_cache()
    results: Dict[str, Any] = {}
    for source in DEFAULT_PUBLIC_SKILL_SOURCES:
        if not force and source in cache.get("sources", {}) and _is_cache_fresh(cache["sources"][source]):
            continue
        owner, repo = source.split("/", 1)
        results[source] = refresh_source(owner, repo, force=force)
    return results


def refresh_all_sources(force: bool = False) -> Dict[str, Any]:
    """刷新所有内置公开社区源和用户源。"""
    results = {}
    for src in get_configured_sources():
        src = src.strip()
        if "/" not in src:
            continue
        owner, repo = src.split("/", 1)
        owner, repo = owner.strip(), repo.strip()
        if not owner or not repo:
            continue
        try:
            results[src] = refresh_source(owner, repo, force=force)
        except Exception as e:
            logger.exception(f"刷新 {src} 失败")
            results[src] = {"ok": False, "error": str(e)}
    return results


def add_source(owner_repo: str) -> Dict[str, Any]:
    """添加一个新的源到 settings.marketplace_sources，并立即刷新"""
    owner_repo = owner_repo.strip()
    if "/" not in owner_repo or " " in owner_repo:
        return {"ok": False, "error": "格式应为 owner/repo"}
    owner, repo = owner_repo.split("/", 1)
    owner, repo = owner.strip(), repo.strip()
    if not owner or not repo:
        return {"ok": False, "error": "owner 或 repo 为空"}

    sources = list(settings.marketplace_sources)
    source_id = f"{owner}/{repo}"
    if source_id not in sources:
        sources.append(source_id)
        # 直接修改 settings（内存），前端应通过另一个 PATCH /api/marketplace/sources 同步到 config.yaml
        settings.marketplace_sources = sources

    # 立即刷新
    result = refresh_source(owner, repo, force=True)
    return {"ok": True, "source": source_id, **result}


def remove_source(owner_repo: str) -> Dict[str, Any]:
    """从 sources 移除（不删 registry 缓存，下次 add 会刷新）"""
    owner_repo = owner_repo.strip()
    sources = [s for s in settings.marketplace_sources if s.strip() != owner_repo]
    settings.marketplace_sources = sources
    cache = _load_cache()
    cache["sources"].pop(owner_repo, None)
    _save_cache(cache)
    return {"ok": True, "removed": owner_repo}


# ── 安装（install）─────────────────────────────────

# 单 skill 配套文件总大小阈值（超过拒绝下载, 防止恶意大文件）
_MAX_SKILL_BUNDLE_BYTES = 5 * 1024 * 1024  # 5MB


def _resolve_skill_in_repo(owner: str, repo: str, skill_id: str) -> Dict[str, Any]:
    """单个 skill 精准解析 (只调一次 tree API, 不全仓库拉取 SKILL.md)

    skills.sh 的 skillId 与仓库目录名不一定一致, 依次尝试:
      1. skill 目录名 == skill_id
      2. SKILL.md frontmatter 的 name == skill_id
    命中后只解析该 skill 的 SKILL.md, 返回跟 get_marketplace_skill 兼容的 dict。
    找不到时返回 {ok: False, error, candidates}。
    """
    files_map = _list_skill_files_in_repo(owner, repo)
    if not files_map:
        return {"ok": False, "error": "list_failed_or_empty_repo", "candidates": []}

    source_id = f"{owner}/{repo}"
    candidates = sorted({str(PurePosixPath(md).parent.name) for md in files_map})

    # 1) 目录名精确匹配
    matched_md: Optional[str] = None
    for md in files_map:
        if str(PurePosixPath(md).parent.name) == skill_id:
            matched_md = md
            break

    # 2) frontmatter name 匹配 (逐个拉, 命中即停)
    content: Optional[str] = None
    if matched_md is None:
        for md in files_map:
            body = _fetch_skill_content(owner, repo, md)
            if not body:
                continue
            meta, _ = _parse_skill_md(body)
            if str(meta.get("name", "")).strip() == skill_id:
                matched_md = md
                content = body
                break

    if matched_md is None:
        return {
            "ok": False,
            "error": f"仓库 {source_id} 中找不到 skill '{skill_id}'. 可用: {', '.join(candidates) or '(空)'}",
            "candidates": candidates,
        }

    if content is None:
        content = _fetch_skill_content(owner, repo, matched_md)
    if not content:
        return {"ok": False, "error": "拉取远端内容失败", "candidates": candidates}

    threat = _security_scan(content)
    if threat:
        return {"ok": False, "error": f"skill 被安全扫描过滤: {threat}", "candidates": candidates}

    meta, _body = _parse_skill_md(content)
    category = str(meta.get("category", "general")).strip().lower() or "general"
    if not re.match(r"^[a-z0-9_-]+$", category):
        category = "general"

    return {
        "ok": True,
        "skill": {
            "name": skill_id,
            "path": matched_md,
            "category": category,
            "description": meta.get("description", ""),
            "version": str(meta.get("version", "0.0.0")),
            "quarantined_reason": None,
            "files": files_map.get(matched_md, []),
            "source": source_id,
            "source_repo": source_id,
            "source_url": f"https://github.com/{owner}/{repo}/blob/HEAD/{matched_md}",
        },
    }


def install_skill(name: str, source: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """把远端 skill 落地到本地 hermes skills 目录

    升级版（v2）:
    - 默认 skill_type=external、quarantined=true
    - 落地前再扫一次安全（防 ETag 缓存返回毒内容）
    - 配套下载 references/templates/scripts/README.md 等文件
    - 同名冲突时整目录备份为 <skill>.bak.<timestamp>/
    - profile 参数预留：多 profile 部署时切换 base_dir
    """
    owner, repo = source.split("/", 1)
    skill = get_marketplace_skill(name, source=source)
    if not skill:
        # 缓存未命中: 单次解析仓库树, 按 skill_id 精准定位 (不全仓库扫描)
        resolved = _resolve_skill_in_repo(owner, repo, name)
        if not resolved.get("ok"):
            return {"ok": False, "error": resolved.get("error", f"marketplace 中找不到 skill: {name}@{source}")}
        skill = resolved["skill"]
    if skill.get("quarantined_reason"):
        return {"ok": False, "error": f"skill 被安全扫描过滤: {skill['quarantined_reason']}"}

    content = _fetch_skill_content(owner, repo, skill["path"])
    if not content:
        return {"ok": False, "error": "拉取远端内容失败"}

    # 再扫一次
    threat = _security_scan(content)
    if threat:
        return {"ok": False, "error": f"安全扫描失败: {threat}"}

    # 解析后注入 skill_type / quarantined
    meta, body = _parse_skill_md(content)
    meta["skill_type"] = "external"
    meta["quarantined"] = True
    meta.setdefault("name", name)
    meta.setdefault("description", skill.get("description", ""))
    meta.setdefault("version", skill.get("version", "0.0.0"))
    meta["source"] = source
    meta["source_url"] = skill.get("source_url", "")
    new_content = f"---\n{yaml.dump(meta, allow_unicode=True, default_flow_style=False)}---\n\n{body}\n"

    # 准备目标目录
    category = skill.get("category", "general")
    target_dir = _LOCAL_SKILLS_DIR / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target_skill_dir = target_dir / name
    target_file = target_skill_dir / "SKILL.md"

    # 在同一文件系统的临时目录完整落盘，成功后再原子替换。
    staging_dir = target_dir / f".{name}.staging.{os.getpid()}.{time.time_ns()}"
    staging_file = staging_dir / "SKILL.md"
    files_meta = skill.get("files", [])
    skill_bytes = new_content.encode("utf-8")
    total_bytes = len(skill_bytes)
    downloaded: List[Dict[str, Any]] = []
    skill_path = PurePosixPath(str(skill["path"]))
    skill_dir_remote = skill_path.parent
    planned: List[Tuple[str, str, int]] = []
    seen_paths = {"SKILL.md"}

    try:
        for file_meta in files_meta:
            remote_path = str(file_meta.get("path", ""))
            if remote_path == str(skill_path):
                continue
            try:
                local_rel = str(PurePosixPath(remote_path).relative_to(skill_dir_remote))
            except ValueError:
                raise ValueError(f"unsafe or unrelated bundle path: {remote_path}")
            safe = _safe_rel_path(local_rel)
            if not safe or safe in seen_paths:
                raise ValueError(f"unsafe or duplicate bundle path: {remote_path}")
            seen_paths.add(safe)
            declared_size = int(file_meta.get("size", 0) or 0)
            if declared_size < 0:
                raise ValueError(f"unsafe bundle size: {remote_path}")
            total_bytes += declared_size
            if total_bytes > _MAX_SKILL_BUNDLE_BYTES:
                raise ValueError("bundle size exceeds 5 MiB limit")
            planned.append((remote_path, safe, declared_size))

        staging_dir.mkdir(parents=True, exist_ok=False)
        staging_file.write_bytes(skill_bytes)
        actual_total_bytes = len(skill_bytes)
        for remote_path, safe, _ in planned:
            payload = _fetch_skill_bytes(owner, repo, remote_path)
            if payload is None:
                raise OSError(f"failed to download bundle file: {remote_path}")
            actual_total_bytes += len(payload)
            if actual_total_bytes > _MAX_SKILL_BUNDLE_BYTES:
                raise ValueError("bundle size exceeds 5 MiB limit")
            local_path = staging_dir / safe
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(payload)
            downloaded.append({"path": safe, "size": len(payload)})

        backup: Optional[Path] = None
        if target_skill_dir.exists():
            backup = target_skill_dir.with_name(f"{name}.bak.{time.time_ns()}")
            target_skill_dir.replace(backup)
        try:
            staging_dir.replace(target_skill_dir)
        except Exception:
            if backup is not None and backup.exists() and not target_skill_dir.exists():
                backup.replace(target_skill_dir)
            raise
    except (OSError, ValueError) as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        return {"ok": False, "error": str(exc)}

    logger.info(
        "marketplace 完整安装: %s/%s → %s (%s files, %s bytes)",
        source,
        name,
        target_skill_dir,
        len(downloaded) + 1,
        actual_total_bytes,
    )

    # 用相对路径（或绝对路径）回传给前端，避免 relative_to 抛错
    try:
        rel_path = str(target_file.relative_to(_BACKEND_ROOT))
    except ValueError:
        rel_path = str(target_file)

    return {
        "ok": True,
        "path": rel_path,
        "abs_path": str(target_skill_dir),
        "quarantined": True,
        "skill_type": "external",
        "files": downloaded,
        "files_skipped": [],
        "files_failed": [],
        "total_files": len(downloaded) + 1,
        "total_bytes": actual_total_bytes,
        "complete": True,
        "package_type": "full_bundle" if files_meta else "skill_md",
        "preserved_original_package": True,
        "source_repo": source,
    }
