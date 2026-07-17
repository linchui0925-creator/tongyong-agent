"""
扣子(Coze)技能市场服务 - 优化版
✅ 首屏秒开：内置精选零延迟直接返回，不卡加载
✅ 按需加载：社区/官方技能用户主动选择才加载，不自动后台爬取
✅ 技能完整：所有来源技能自动补全角色、规则、输出要求，不会只有一句话描述
"""
import httpx
import re
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from app.paths import data_path

COZE_API_BASE = "https://www.coze.cn"
SKILLS_DIR = Path(data_path("hermes", "skills"))
SKILLS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = Path(data_path("coze_config.json"))
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
# live sync 结果 cache 落盘 (三源合并里的 live 层)
COZE_CACHE_PATH = Path(data_path("coze_live_cache.json"))

# live 同步节流窗口 (秒): 窗口内不重复打网, 复用上次结果
LIVE_SYNC_THROTTLE_SEC = 30

# Coze 官网公开技能列表候选端点 (真机可达; 沙箱外网不通, 测试用 _HTTP_FETCHER 注入)
COZE_LIVE_ENDPOINTS = [
    "https://www.coze.cn/api/marketplace/skill/list?page_size=50&sort=hot",
    "https://www.coze.cn/api/skill/v1/skills/hot?page_size=50",
]

cache = {
    "community_skills": [],
    "community_loaded": False,
    "community_loading": False,
}

# live sync 运行状态 (供节流 + UI 展示)
_state = {
    "last_live_sync_ts": 0.0,
    "last_live_synced": False,
    "last_live_at": None,
    "last_live_count": 0,
    "last_live_error": None,
}


def _default_http_fetcher(url: str):
    """默认实时抓取器: 返回 (status_code, text)。

    真机可达 coze; 沙箱外网不通会抛异常, 由调用方降级。
    测试通过 monkeypatch 替换 _HTTP_FETCHER 注入 fake, 不打真实网络。
    """
    try:
        with httpx.Client(timeout=6, follow_redirects=True) as client:
            r = client.get(url, headers=_get_headers())
            return r.status_code, r.text
    except Exception:
        return 0, ""


# 可注入的抓取器 (测试替换此符号)
_HTTP_FETCHER = _default_http_fetcher


class CozeSkill(BaseModel):
    id: str
    name: str
    description: str
    icon: Optional[str] = None
    author: Optional[str] = None
    usage_count: Optional[int] = 0
    installed: bool = False
    prompt: Optional[str] = None
    trigger_words: Optional[List[str]] = []
    dependencies: Optional[List[str]] = []
    has_platform_dependency: bool = False
    category: Optional[str] = "通用"
    source: str = "builtin"
    package_type: str = "prompt_template"
    file_count: int = 1


def _load_config() -> Dict:
    if CONFIG_PATH.exists():
        try: return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception: pass
    return {"coze_cookie": "", "enable_community": False}  # 默认关闭社区自动加载，不卡首屏


def _save_config(cfg: Dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_headers(cookie: str = "") -> Dict:
    h = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json", "Referer": "https://www.coze.cn/skills", "Content-Type": "application/json"
    }
    if cookie: h["Cookie"] = cookie
    return h


def _is_installed(skill_id: str) -> bool:
    skill_dir_name = f"coze_{skill_id}"
    if not SKILLS_DIR.exists(): return False
    for cat_dir in SKILLS_DIR.iterdir():
        if not cat_dir.is_dir(): continue
        p = cat_dir / skill_dir_name
        if p.exists() and (p / "SKILL.md").exists(): return True
    return False


def _complete_skill_prompt(skill: Dict) -> str:
    """自动补全技能prompt，确保是完整可运行的，不会只有一句话描述"""
    existing_prompt = skill.get("prompt", "").strip()
    name = skill["name"]
    desc = skill["description"]
    
    # 如果已有prompt长度超过200字并且包含规则/角色说明，直接用
    if len(existing_prompt) > 200 and ("角色" in existing_prompt or "规则" in existing_prompt or "工作流程" in existing_prompt):
        return existing_prompt
    
    # 否则自动补全成完整技能
    return f"""# {name}

## 角色设定
你现在是专业的{name}，在{desc.split('，')[0].split('。')[0]}领域拥有丰富的专业经验和实操经验。

## 核心能力
{desc}

## 工作规则
1. 准确理解用户需求，给出专业、可落地的回答，不要空泛套话
2. 输出结构清晰，分点说明，易于理解和执行
3. 如果用户提供的信息不足，主动询问澄清，不要瞎编
4. 遇到超出本技能范围的问题，明确告知用户
5. 所有建议符合该领域的专业规范和最佳实践

## 输出要求
- 优先给出可直接执行的方案和步骤
- 复杂问题分步骤说明，必要时举例
- 语言通俗易懂，避免堆砌不必要的专业术语
{existing_prompt}
"""


from app.services.coze_skills_builtin import FULL_SKILLS as BUILTIN_SKILLS
for s in BUILTIN_SKILLS:
    s["source"] = "builtin"
    s["prompt"] = _complete_skill_prompt(s)
    s["installed"] = _is_installed(s["id"])


async def load_community_skills(force: bool = False) -> List[Dict]:
    """用户主动触发才加载社区技能，不自动跑"""
    if cache["community_loading"]:
        return cache["community_skills"]
    if cache["community_loaded"] and not force:
        return cache["community_skills"]
    
    cache["community_loading"] = True
    skills = []
    
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get("https://skillhub.lol/skills", headers={"User-Agent": "Mozilla/5.0 Chrome/125.0.0.0"})
            if resp.status_code == 200:
                html = resp.text
                cards = re.findall(r'<a[^>]+href="/skills/([^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>.*?<p[^>]*>(.*?)</p>', html, re.DOTALL)
                for slug, name, desc in cards[:150]:
                    try:
                        slug = slug.strip()
                        name = re.sub(r'<[^>]+>', '', name).strip()
                        desc = re.sub(r'<[^>]+>', '', desc).strip()
                        if not name or not slug: continue
                        prompt = f"# {name}\n\n{desc}"
                        # 简单尝试拿详情，失败就用补全版
                        try:
                            d_resp = await client.get(f"https://skillhub.lol/skills/{slug}", timeout=6)
                            if d_resp.status_code == 200:
                                pm = re.search(r'<pre[^>]*>(.*?)</pre>', d_resp.text, re.DOTALL)
                                if pm: prompt = re.sub(r'<[^>]+>', '', pm.group(1)).strip()
                        except Exception: pass
                        
                        skills.append({
                            "id": f"hub_{slug}", "name": name, "description": desc,
                            "icon": "🌐", "author": "SkillHub社区", "usage_count": 0,
                            "category": "社区技能", "trigger_words": [name],
                            "prompt": prompt, "has_platform_dependency": False,
                            "dependencies": [], "source": "community"
                        })
                    except Exception: continue
    except Exception as e:
        logger.warning(f"加载社区技能失败: {e}")
    
    for s in skills:
        s["prompt"] = _complete_skill_prompt(s)
        s["installed"] = _is_installed(s["id"])
    
    cache["community_skills"] = skills
    cache["community_loaded"] = True
    cache["community_loading"] = False
    logger.info(f"社区技能加载完成，共{len(skills)}个")
    return skills


async def _search_official_skills(keyword: str, cookie: str, page: int = 1, page_size: int = 20) -> List[Dict]:
    if not cookie.strip() or not keyword.strip(): return []
    skills = []
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"{COZE_API_BASE}/api/skill/v1/skills/search",
                headers=_get_headers(cookie),
                json={"keyword": keyword, "page": page, "page_size": page_size, "tab": "all"}
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    for item in data.get("data", {}).get("list", []):
                        try:
                            prompt = item.get("prompt", item.get("description", ""))
                            sid = item.get("skill_id")
                            if sid:
                                try:
                                    d_resp = await client.get(f"{COZE_API_BASE}/api/skill/v1/skills/{sid}", headers=_get_headers(cookie), timeout=5)
                                    if d_resp.status_code == 200:
                                        dd = d_resp.json()
                                        if dd.get("code") == 0:
                                            prompt = dd["data"].get("prompt", prompt)
                                except Exception: pass
                            skills.append({
                                "id": f"official_{sid}", "name": item.get("name", ""),
                                "description": item.get("description", ""), "icon": item.get("icon", "🏛️"),
                                "author": item.get("author_name", "扣子官方"), "usage_count": int(item.get("use_count", 0)),
                                "category": item.get("category_name", "官方市场"),
                                "trigger_words": item.get("trigger_words", [item.get("name", "")]),
                                "prompt": prompt, "has_platform_dependency": bool(item.get("platform_dependency", False)),
                                "dependencies": [], "source": "official"
                            })
                        except Exception: continue
    except Exception as e:
        logger.warning(f"官方搜索失败: {e}")
    for s in skills:
        s["prompt"] = _complete_skill_prompt(s)
        s["installed"] = _is_installed(s["id"])
    return skills


def _score(skill: Dict, kw: str) -> int:
    score = 0
    kwl = kw.lower()
    n = skill["name"].lower()
    d = skill["description"].lower()
    ts = [t.lower() for t in skill.get("trigger_words", [])]
    if kwl == n: score += 100
    elif kwl in n: score += 60
    elif any(kwl == t for t in ts): score += 50
    elif kwl in d: score += 20
    if skill["source"] == "official": score += 20
    elif skill["source"] == "builtin": score += 10
    score += min(skill.get("usage_count", 0) // 100000, 15)
    return score


# ── live + cache 三源合并层 ──────────────────────────────

def _load_live_cache() -> List[Dict]:
    """读上一次 live sync 落盘的技能 (live 不可用时兜底)。"""
    try:
        if COZE_CACHE_PATH.exists():
            data = json.loads(COZE_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"读取 live cache 失败: {e}")
    return []


def _save_live_cache(skills: List[Dict]):
    try:
        COZE_CACHE_PATH.write_text(
            json.dumps(skills, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"写入 live cache 失败: {e}")


def _parse_live_payload(text: str) -> List[Dict]:
    """把 live 端点返回的 JSON 解析成统一 skill dict 列表。

    容忍多种结构: {data:[...]} / {data:{list:[...]}} / [...]。
    """
    try:
        payload = json.loads(text)
    except Exception:
        return []
    raw = []
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict) and isinstance(data.get("list"), list):
            raw = data["list"]
    skills = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sid = item.get("id") or item.get("skill_id")
        name = item.get("name", "")
        if not sid or not name:
            continue
        skills.append({
            "id": str(sid),
            "name": name,
            "description": item.get("description", ""),
            "icon": item.get("icon", "🌐"),
            "author": item.get("author_name") or item.get("author", "Coze市场"),
            "usage_count": int(item.get("use_count", item.get("usage_count", 0)) or 0),
            "category": item.get("category_name") or item.get("category", "Coze市场"),
            "trigger_words": item.get("trigger_words") or [name],
            "prompt": item.get("prompt", item.get("description", "")),
            "has_platform_dependency": bool(item.get("platform_dependency", False)),
            "dependencies": [],
            "source": "live",
        })
    return skills


def _live_sync(force: bool = False) -> List[Dict]:
    """实时抓取 coze 公开技能, 更新 _state 并落盘 cache。

    - 节流: LIVE_SYNC_THROTTLE_SEC 窗口内直接复用上次 cache, 不打网
    - 失败/超时/403: 静默降级, 记录 last_live_error, 返回上次 cache
    """
    import time
    now = time.time()
    # 节流: 窗口内不重新打网
    if not force and (now - _state["last_live_sync_ts"]) < LIVE_SYNC_THROTTLE_SEC:
        return _load_live_cache()

    _state["last_live_sync_ts"] = now
    last_error = None
    for url in COZE_LIVE_ENDPOINTS:
        try:
            status, text = _HTTP_FETCHER(url)
        except Exception as e:
            last_error = f"fetch 异常: {e}"
            continue
        if status == 200 and text:
            skills = _parse_live_payload(text)
            if skills:
                for sk in skills:
                    sk["prompt"] = _complete_skill_prompt(sk)
                _save_live_cache(skills)
                _state.update({
                    "last_live_synced": True,
                    "last_live_at": datetime.now().astimezone().isoformat(),
                    "last_live_count": len(skills),
                    "last_live_error": None,
                })
                return skills
            last_error = "live 返回空列表"
        elif status == 0:
            last_error = "网络错误/超时"
        else:
            last_error = f"HTTP {status}"

    # 全部端点失败 → 降级 cache
    _state.update({
        "last_live_synced": False,
        "last_live_at": _state.get("last_live_at"),
        "last_live_count": 0,
        "last_live_error": last_error or "live 不可用",
    })
    return _load_live_cache()



async def search_skills(
    keyword: str = "", page: int = 1, page_size: int = 24,
    category: str = None, sort_by: str = "hot", source_filter: str = "all",
    load_community: bool = False, sync: bool = False
) -> Dict[str, Any]:
    cfg = _load_config()
    all_skills = []
    seen_ids = set()

    def _add(items):
        for it in items:
            sid = it.get("id")
            if not sid or sid in seen_ids:
                continue
            seen_ids.add(sid)
            all_skills.append(it.copy())

    # 1. 永远先加内置精选，0延迟
    if source_filter in ["all", "builtin"]:
        _add(BUILTIN_SKILLS)

    # 1.5 live 层: sync=True 主动同步 coze 公开技能; 否则复用节流窗口内 cache。
    #     live 失败/超时/403 静默降级, 绝不 500 (见 _live_sync)。
    if source_filter in ["all", "live", "official"]:
        live_skills = _live_sync(force=sync)
        _add(live_skills)
    
    # 2. 社区技能：只有用户要求加载才去拿，不自动加载
    community_loading = False
    community_count = len(cache["community_skills"])
    if source_filter in ["all", "community"] and (cfg.get("enable_community") or load_community):
        if load_community or cache["community_loaded"]:
            community_skills = await load_community_skills()
            _add(community_skills)
            community_count = len(community_skills)
        else:
            community_loading = False  # 不自动加载，不卡
    
    # 3. 官方技能：有关键词+cookie才搜
    official_skills = []
    if source_filter in ["all", "official"] and cfg.get("coze_cookie") and keyword.strip():
        try:
            official_skills = await asyncio.wait_for(_search_official_skills(keyword, cfg["coze_cookie"]), timeout=5)
            _add(official_skills)
        except asyncio.TimeoutError:
            pass
    
    # 过滤分类
    if category and category != "全部":
        all_skills = [s for s in all_skills if s.get("category") == category]
    
    # 搜索排序
    if keyword.strip():
        kw = keyword.strip()
        scored = [(_score(s, kw), s) for s in all_skills if _score(s, kw) > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        all_skills = [s for _, s in scored]
    else:
        if sort_by == "hot":
            all_skills.sort(key=lambda x: x.get("usage_count", 0), reverse=True)
    
    for s in all_skills:
        s["installed"] = _is_installed(s["id"])
    
    total = len(all_skills)
    paginated = all_skills[(page-1)*page_size : page*page_size]
    
    cats = sorted({s.get("category", "通用") for s in BUILTIN_SKILLS})
    if cfg.get("enable_community"): cats.append("社区技能")
    if cfg.get("coze_cookie"): cats.append("官方市场")
    cats = ["全部"] + cats

    return {
        "success": True, "total": total, "page": page, "page_size": page_size,
        "categories": cats, "sort_by": sort_by, "source_filter": source_filter,
        "official_available": bool(cfg.get("coze_cookie")),
        "community_available": cfg.get("enable_community", False),
        "community_loaded": cache["community_loaded"],
        "community_loading": cache["community_loading"],
        "community_count": community_count,
        "live_synced": _state["last_live_synced"],
        "live_at": _state["last_live_at"],
        "live_count": _state["last_live_count"],
        "live_error": _state["last_live_error"],
        "cache_count": len(_load_live_cache()),
        "list": [CozeSkill(**s).model_dump() for s in paginated]
    }


async def get_skill_detail(skill_id: str) -> Dict[str, Any]:
    cfg = _load_config()
    for s in BUILTIN_SKILLS:
        if s["id"] == skill_id:
            s["installed"] = _is_installed(skill_id)
            return {"success": True, "skill": CozeSkill(**s).model_dump()}
    if skill_id.startswith("official_") and cfg.get("coze_cookie"):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                rid = skill_id.replace("official_", "")
                resp = await client.get(f"{COZE_API_BASE}/api/skill/v1/skills/{rid}", headers=_get_headers(cfg["coze_cookie"]))
                if resp.status_code == 200:
                    dd = resp.json()
                    if dd.get("code") == 0:
                        d = dd["data"]
                        s = {
                            "id": skill_id, "name": d.get("name", ""), "description": d.get("description", ""),
                            "icon": d.get("icon", "🏛️"), "author": d.get("author_name", "扣子官方"),
                            "usage_count": int(d.get("use_count", 0)), "category": d.get("category_name", "官方市场"),
                            "trigger_words": d.get("trigger_words", []), "prompt": d.get("prompt", d.get("description", "")),
                            "has_platform_dependency": bool(d.get("platform_dependency", False)),
                            "installed": _is_installed(skill_id), "source": "official"
                        }
                        s["prompt"] = _complete_skill_prompt(s)
                        return {"success": True, "skill": CozeSkill(**s).model_dump()}
        except Exception: pass
    if skill_id.startswith("hub_"):
        for s in cache["community_skills"]:
            if s["id"] == skill_id:
                s["installed"] = _is_installed(skill_id)
                return {"success": True, "skill": CozeSkill(**s).model_dump()}
    return {"success": False, "message": "技能不存在"}


async def translate_skill(skill_id: str, target_lang: str = "英文") -> Dict[str, Any]:
    try:
        dr = await get_skill_detail(skill_id)
        if not dr["success"]: return dr
        s = dr["skill"]
        from app.services.llm_manager import get_llm_manager
        llm = get_llm_manager().get_llm()
        async def _t(text: str) -> str:
            r = await llm.chat([
                {"role": "system", "content": f"翻译为{target_lang}，保持Markdown格式，直接返回结果。"},
                {"role": "user", "content": text}
            ])
            return r.content.strip()
        return {"success": True, "skill": {**s, "name": await _t(s["name"]), "description": await _t(s["description"]), "prompt": await _t(s["prompt"])}}
    except Exception as e:
        return {"success": False, "message": f"翻译失败: {str(e)}"}


async def install_skill(skill_id: str, translate_to_lang: Optional[str] = None) -> Dict[str, Any]:
    try:
        dr = await get_skill_detail(skill_id)
        if not dr["success"]: return dr
        s = dr["skill"]
        
        prompt = s.get("prompt", "")
        name = s["name"]
        desc = s["description"]
        if translate_to_lang:
            tr = await translate_skill(skill_id, translate_to_lang)
            if tr["success"]:
                prompt = tr["skill"]["prompt"]
                name = tr["skill"]["name"]
                desc = tr["skill"]["description"]
        
        # 确保prompt完整
        prompt = _complete_skill_prompt({**s, "name": name, "description": desc, "prompt": prompt})
        
        cat = s.get("category", "通用").replace('/', '_').replace(' ', '_')
        cat_dir = SKILLS_DIR / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        s_dir = cat_dir / f"coze_{skill_id}"
        s_dir.mkdir(parents=True, exist_ok=True)
        
        safe_name = name.replace('"', '\\"')
        safe_desc = desc.replace('"', '\\"')
        trigger_lines = '\n'.join([f'- {tw}' for tw in s.get('trigger_words', [name])])
        trigger_json = json.dumps(s.get('trigger_words', [name]), ensure_ascii=False)
        dep_warn = '⚠️ 本技能部分功能可能依赖Coze平台，使用时需要适配' if s.get('has_platform_dependency') else ''
        source_txt = 'Coze官方' if s['source']=='official' else 'SkillHub社区' if s['source']=='community' else '内置精选'
        
        content = f"""---
name: "{safe_name}"
description: "{safe_desc}"
author: "{s.get('author', '技能市场')}"
source: "{s['source']}"
source_id: "{skill_id}"
version: "1.0.0"
category: "{cat}"
trigger_words: {trigger_json}
skill_type: external
auto_load: false
quarantined: true
enabled: true
package_type: prompt_template
---
# {name}

## 描述
{desc}

## 元信息
- 来源：{source_txt}
- 作者：{s.get('author', '技能市场')}

## 触发方式
直接描述需求即可，或使用触发词：
{trigger_lines}

## 完整系统提示
{prompt}

## 输出要求
1. 严格按照角色设定回答，专业准确
2. 结构清晰，可落地执行
{dep_warn}
"""
        (s_dir / "SKILL.md").write_text(content, encoding="utf-8")
        
        try:
            from app.core.skills_index import refresh as refresh_skills_index
            refresh_skills_index()
            from app.tools.implementations import skill_tools
            skill_tools._skill_index_cache = {}
            skill_tools._skill_index_mtime = None
        except Exception as exc:
            logger.warning("Skill 安装后刷新索引失败: %s", exc)

        fpath = s_dir / "SKILL.md"
        if not fpath.is_file() or not prompt.strip():
            return {"success": False, "message": "安装失败，提示词模板为空"}

        installed_skill = {
            **s,
            "installed": True,
            "package_type": "prompt_template",
            "file_count": 1,
            "quarantined": True,
            "auto_load": False,
        }
        return {
            "success": True,
            "message": f"技能「{name}」已作为提示词模板安装，审核解除隔离后方可使用。",
            "skill": installed_skill,
            "install_report": {
                "package_type": "prompt_template",
                "files": ["SKILL.md"],
                "preserved_original_package": False,
                "warning": "来源未提供可下载的完整多文件 Skill 包。",
            },
        }
    except Exception as e:
        logger.error(f"安装失败: {e}", exc_info=True)
        return {"success": False, "message": f"安装失败: {str(e)}"}


async def save_coze_config(cookie: str, enable_community: bool = False) -> Dict[str, Any]:
    cfg = _load_config()
    cfg["coze_cookie"] = cookie.strip()
    cfg["enable_community"] = enable_community
    _save_config(cfg)
    cache["community_loaded"] = False
    cache["community_skills"] = []
    return {"success": True, "official_available": bool(cookie.strip())}


async def get_coze_config() -> Dict[str, Any]:
    cfg = _load_config()
    return {
        "success": True,
        "coze_cookie_set": bool(cfg.get("coze_cookie", "").strip()),
        "enable_community": cfg.get("enable_community", False),
        "official_available": bool(cfg.get("coze_cookie", "").strip())
    }
