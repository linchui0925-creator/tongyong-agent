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
from fastapi.responses import FileResponse, PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

# 后端进程启动时的 cwd — bare filename 解析的锚点
_BACKEND_CWD = Path(os.getcwd()).resolve()

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
        Path("/tmp").resolve(),
        Path("/private/tmp").resolve(),
        Path("/var/folders").resolve(),
        Path("/private/var/folders").resolve(),
        home,
        home / "Documents",
        home / "Desktop",
    ]
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

    p = Path(path_str)
    if not p.is_absolute():
        # bare filename 或相对路径 → 锚定到 backend cwd
        p = (_BACKEND_CWD / p).resolve()
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
