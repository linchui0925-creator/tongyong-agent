"""MCP Server 运行状态与连接管理 API。"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.paths import data_path

from app.services.mcp_registry import search_registry
from app.tools.mcp_client import get_mcp_start_error, get_mcp_status, restart_mcp_server

router = APIRouter(prefix="/api/mcp", tags=["mcp"])
_CONFIG_PATH = Path(data_path("mcp_servers.json"))


class InstallRequest(BaseModel):
    server_id: str
    package: Optional[Dict[str, Any]] = None
    remote: Optional[Dict[str, Any]] = None
    env: Dict[str, str] = {}


def _runtime_argument_values(arguments: List[Dict[str, Any]]) -> List[str]:
    values: List[str] = []
    for argument in arguments:
        name = str(argument.get("name") or "").strip()
        value = str(argument.get("value") or "").strip()
        if name:
            values.append(name)
        if value:
            values.append(value)
    return values


def _build_launch_config(
    package: Optional[Dict[str, Any]],
    remote: Optional[Dict[str, Any]],
    env: Dict[str, str],
) -> Dict[str, Any]:
    if package:
        registry_type = str(package.get("registryType") or "").lower()
        identifier = str(package.get("identifier") or "").strip()
        if not identifier:
            raise HTTPException(status_code=400, detail="MCP package 缺少 identifier")
        runtime_hint = str(package.get("runtimeHint") or "").strip()
        if registry_type == "npm":
            command = runtime_hint or "npx"
            args = ["-y", identifier]
        elif registry_type in {"pypi", "python"}:
            command = runtime_hint or "uvx"
            args = [identifier]
        else:
            raise HTTPException(status_code=400, detail=f"暂不支持自动安装 {registry_type or '未知'} 包")
        args.extend(_runtime_argument_values(package.get("runtimeArguments") or []))
        return {"command": command, "args": args, "env": env, "transport": "stdio"}

    if remote:
        url = str(remote.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="远程 MCP Server URL 无效")
        transport = str(remote.get("type") or "streamable-http").lower()
        return {"url": url, "transport": transport, "headers": env}

    raise HTTPException(status_code=400, detail="该条目没有可安装包或远程连接地址")


def _load_configs() -> Dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8")) if _CONFIG_PATH.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


@router.get("/marketplace")
async def marketplace(
    search: str = Query(""),
    limit: int = Query(24, ge=1, le=100),
    cursor: Optional[str] = Query(None),
):
    try:
        return await search_registry(search=search, limit=limit, cursor=cursor)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"官方 MCP Registry 暂不可用: {exc}") from exc


@router.post("/servers/install")
async def install_server(req: InstallRequest):
    server_id = re.sub(r"[^a-zA-Z0-9_-]", "_", req.server_id).strip("_").lower()
    if not server_id:
        raise HTTPException(status_code=400, detail="Server ID 不能为空")
    launch_config = _build_launch_config(req.package, req.remote, req.env)
    configs = _load_configs()
    previous = configs.get(server_id)
    configs[server_id] = launch_config
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")
    if not await restart_mcp_server(server_id):
        if previous is None:
            configs.pop(server_id, None)
        else:
            configs[server_id] = previous
        _CONFIG_PATH.write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")
        raise HTTPException(status_code=400, detail={
            "message": "MCP Server 启动失败，配置未保存",
            "reason": get_mcp_start_error(server_id) or "未知启动错误",
            "server_id": server_id,
            "config": launch_config,
        })
    return {"success": True, "server": next((s for s in get_mcp_status() if s["id"] == server_id), None)}


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str):
    configs = _load_configs()
    if server_id not in configs:
        raise HTTPException(status_code=404, detail="MCP Server 不存在或由环境变量管理")
    configs.pop(server_id)
    _CONFIG_PATH.write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"success": True}


@router.get("/servers")
async def list_servers():
    servers = get_mcp_status()
    return {"servers": servers, "total": len(servers)}


@router.post("/servers/{server_id}/restart")
async def restart_server(server_id: str):
    if not await restart_mcp_server(server_id):
        raise HTTPException(status_code=404, detail="MCP Server 不存在或启动失败")
    server = next((item for item in get_mcp_status() if item["id"] == server_id), None)
    return {"success": True, "server": server}
