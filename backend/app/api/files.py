"""
W4-45: 本地文件 HTTP serve 端点

让前端 FilePathLink 点击直接打开网页 (http://127.0.0.1:8000/api/files/serve?path=...)
解决 Chrome 静默 block file:// 链接的问题.

安全策略:
- 只允许白名单目录 (backend cwd, /tmp, /var/folders, 用户 home)
- 拒绝 ../ 路径穿越
- 拒绝 /etc /private/etc /System 等系统目录
- 拒绝 符号链接逃逸
"""
import logging
import mimetypes
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

# 后端进程启动时的 cwd — bare filename 解析的锚点
_BACKEND_CWD = Path(os.getcwd()).resolve()

# 相对/裸文件名的解析锚点: 与 file_tools._resolve_path 保持一致 (写入落在项目根),
# 否则点击链接 (path=index.html) 会锚到 backend/ 找不到文件, 预览空白。
_REPO_ROOT = _BACKEND_CWD.parent if _BACKEND_CWD.name == "backend" else _BACKEND_CWD


def _workspace_roots() -> list:
    """会话隔离工作区根 (workspace_* 工具写入处), 供裸文件名兜底查找。"""
    roots = []
    try:
        from app.paths import data_path
        base = Path(os.getenv("TONGYONG_WORKSPACE_ROOT", data_path("workspaces"))).resolve()
        if base.exists():
            roots.append(base)
    except Exception:
        pass
    return roots

# 允许的目录白名单 (前缀匹配, 已 resolve)
def _allowed_dirs() -> list:
    """运行时构建白名单 (用户 home 可能不固定)"""
    cwd = _BACKEND_CWD
    parts = list(cwd.parents)
    # 找到 home (e.g. /Users/linc)
    home = Path.home().resolve()
    allowed = [
        cwd,  # backend cwd
        cwd.parent,  # 项目根
        _REPO_ROOT,
        Path("/tmp").resolve(),
        Path("/private/tmp").resolve(),
        Path("/var/folders").resolve(),
        Path("/private/var/folders").resolve(),
        home,
        home / "Documents",
        home / "Desktop",
    ] + _workspace_roots()
    return [p for p in allowed if p.exists()]

# 拒绝的目录 (前缀匹配)
_BLOCKED_PREFIXES = [
    "/etc", "/private/etc",
    "/System", "/private/var/db",
    "/usr", "/bin", "/sbin",
    "/var/log", "/var/db", "/var/audit",
    "/Library/Keychains",
    "/.ssh", "/.aws", "/.gnupg",
    "/proc", "/sys",
    "/private/var/root",
]


def _is_blocked(p: Path) -> bool:
    """系统敏感目录检查"""
    s = str(p)
    for prefix in _BLOCKED_PREFIXES:
        if s == prefix or s.startswith(prefix + "/") or s.startswith(prefix):
            return True
    return False


def _resolve_path(path_str: str) -> Path:
    """解析路径 + 安全检查.

    - bare filename → backend cwd
    - 相对路径 → backend cwd
    - 绝对路径 → 直接用
    - 检查是否在白名单, 拒绝系统目录
    """
    if not path_str or not path_str.strip():
        raise HTTPException(400, "path 不能为空")

    path_str = path_str.strip()
    # 路径穿越
    if "\x00" in path_str:
        raise HTTPException(400, "path 含非法字符")

    if path_str.startswith(("http://", "https://", "file://", "//")):
        raise HTTPException(
            400,
            f"请直接打开远程链接，不要通过文件预览代理: {path_str}",
        )

    p = Path(path_str).expanduser()
    if not p.is_absolute():
        # 裸文件名 / 相对路径 → 与 file_tools 一致锚到项目根;
        # 若项目根不存在, 再依次尝试 backend cwd 和会话工作区。
        candidates = [(_REPO_ROOT / p).resolve(), (_BACKEND_CWD / p).resolve()]
        for root in _workspace_roots():
            candidates.append((root / p).resolve())
            matches = sorted(root.rglob(p.name)) if not p.parts[:-1] else []
            candidates.extend(m.resolve() for m in matches if m.is_file())
        p = next((c for c in candidates if c.exists()), candidates[0])
    else:
        p = p.resolve()

    # 系统目录黑名单
    if _is_blocked(p):
        raise HTTPException(403, f"禁止访问系统目录: {p}")

    # 白名单检查
    allowed = _allowed_dirs()
    in_allowed = False
    for d in allowed:
        try:
            p.relative_to(d)
            in_allowed = True
            break
        except ValueError:
            continue
    if not in_allowed:
        raise HTTPException(403, f"路径不在白名单内: {p}")

    if not p.exists():
        raise HTTPException(404, f"文件不存在: {p}")
    if not p.is_file():
        raise HTTPException(400, f"不是文件: {p}")

    return p



@router.get("/serve")
async def serve_file(path: str = Query(..., description="本地文件路径")):
    """serve 本地文件, 让前端 FilePathLink 可以直接打开.

    支持:
    - 绝对路径: /Users/linc/hello.html
    - 相对路径: ./hello.html (相对 backend cwd)
    - bare filename: hello.html (相对 backend cwd)
    """
    p = _resolve_path(path)

    # MIME 推断
    mime, _ = mimetypes.guess_type(str(p))
    if mime is None:
        # 默认二进制下载
        mime = "application/octet-stream"

    logger.info(f"[files.serve] {p}  (mime={mime})")
    return FileResponse(
        path=str(p),
        media_type=mime,
        filename=p.name,
        headers={
            "Cache-Control": "no-cache",
            "X-Served-From": str(p),
        },
    )


@router.get("/preview", response_class=HTMLResponse)
async def preview_file(path: str = Query(..., description="本地 HTML/图片/SVG 文件路径")):
    """把本地网页/图片包装成安全预览页, 供聊天窗口 iframe 内嵌渲染。"""
    p = _resolve_path(path)
    ext = p.suffix.lower()
    if ext not in {".html", ".htm", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        raise HTTPException(400, f"不支持预览该类型: {ext or 'unknown'}")

    import html
    from urllib.parse import quote

    src = "/api/files/serve?path=" + quote(str(p), safe="")
    title = html.escape(p.name)
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        body = f'<img src="{src}" alt="{title}" />'
    else:
        body = f'<iframe src="{src}" sandbox="allow-scripts allow-forms allow-pointer-lock allow-popups allow-modals"></iframe>'

    return HTMLResponse(f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    html, body {{ margin: 0; width: 100%; height: 100%; background: #0f1115; overflow: hidden; }}
    iframe {{ width: 100%; height: 100%; border: 0; background: white; }}
    img {{ width: 100%; height: 100%; object-fit: contain; display: block; }}
  </style>
</head>
<body>{body}</body>
</html>""")


@router.get("/info")
async def file_info(path: str = Query(...)):
    """查询文件元信息 (不下载内容)"""
    p = _resolve_path(path)
    stat = p.stat()
    return {
        "path": str(p),
        "name": p.name,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "exists": True,
    }
