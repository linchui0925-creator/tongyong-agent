"""Hermes 功能 API 路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.hermes import MemoryFileManager, SkillFileManager

router = APIRouter(prefix="/api/hermes", tags=["hermes"])

# 全局实例 (由 main.py 初始化时注入)
memory_manager: Optional[MemoryFileManager] = None
skill_manager: Optional[SkillFileManager] = None


def ensure_initialized():
    if memory_manager is None or skill_manager is None:
        raise HTTPException(status_code=503, detail="Hermes 模块未初始化")


class MemoryWriteRequest(BaseModel):
    content: str


class EntryRequest(BaseModel):
    entry: str


class ReplaceEntryRequest(BaseModel):
    old: str
    new: str


class SkillCreateRequest(BaseModel):
    name: str
    description: str
    steps: List[str]
    pitfalls: Optional[List[str]] = None
    category: str = "general"
    platforms: Optional[List[str]] = None


class SkillEditRequest(BaseModel):
    content: str


class SkillPatchRequest(BaseModel):
    old: str
    new: str


# ── MEMORY.md ──────────────────────────────────

@router.get("/memory")
async def get_memory():
    ensure_initialized()
    raw = memory_manager.get_stats()
    return {
        "content": memory_manager.read_memory(),
        "stats": {
            "entry_count": raw["memory_entries"],
            "char_count": raw["memory_chars"],
            "max_chars": raw["memory_limit"],
            "file_path": memory_manager.memory_path,
        },
    }


@router.post("/memory")
async def write_memory(req: MemoryWriteRequest):
    ensure_initialized()
    ok, msg = memory_manager.write_memory(req.content)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.get("/memory/entries")
async def list_memory_entries():
    ensure_initialized()
    return {"entries": memory_manager.list_entries("memory")}


@router.post("/memory/entries")
async def add_memory_entry(req: EntryRequest):
    ensure_initialized()
    ok, msg = memory_manager.add_entry("memory", req.entry)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.put("/memory/entries")
async def replace_memory_entry(req: ReplaceEntryRequest):
    ensure_initialized()
    ok, msg = memory_manager.replace_entry("memory", req.old, req.new)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.delete("/memory/entries")
async def remove_memory_entry(old: str):
    ensure_initialized()
    ok, msg = memory_manager.remove_entry("memory", old)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


# ── USER.md ────────────────────────────────────

@router.get("/user")
async def get_user():
    ensure_initialized()
    raw = memory_manager.get_stats()
    return {
        "content": memory_manager.read_user(),
        "stats": {
            "entry_count": raw["user_entries"],
            "char_count": raw["user_chars"],
            "max_chars": raw["user_limit"],
            "file_path": memory_manager.user_path,
        },
    }


@router.post("/user")
async def write_user(req: MemoryWriteRequest):
    ensure_initialized()
    ok, msg = memory_manager.write_user(req.content)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.get("/user/entries")
async def list_user_entries():
    ensure_initialized()
    return {"entries": memory_manager.list_entries("user")}


@router.post("/user/entries")
async def add_user_entry(req: EntryRequest):
    ensure_initialized()
    ok, msg = memory_manager.add_entry("user", req.entry)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}

@router.put("/user/entries")
async def replace_user_entry(req: ReplaceEntryRequest):
    ensure_initialized()
    ok, msg = memory_manager.replace_entry("user", req.old, req.new)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}

@router.delete("/user/entries")
async def remove_user_entry(old: str):
    ensure_initialized()
    ok, msg = memory_manager.remove_entry("user", old)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


# ── Skills ────────────────────────────────────

@router.get("/skills")
async def list_skills():
    ensure_initialized()
    return {"skills": skill_manager.list_skills(), "stats": skill_manager.get_stats()}


@router.get("/skills/{name}")
async def view_skill(name: str):
    ensure_initialized()
    skill = skill_manager.view_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"技能 '{name}' 未找到")
    return skill


@router.post("/skills/{name}")
async def create_skill(name: str, req: SkillCreateRequest):
    ensure_initialized()
    ok, msg = skill_manager.create_skill(
        name=req.name,
        description=req.description,
        steps=req.steps,
        pitfalls=req.pitfalls,
        category=req.category,
        platforms=req.platforms,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.put("/skills/{name}")
async def edit_skill(name: str, req: SkillEditRequest):
    ensure_initialized()
    ok, msg = skill_manager.edit_skill(name, req.content)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.patch("/skills/{name}")
async def patch_skill(name: str, req: SkillPatchRequest):
    ensure_initialized()
    ok, msg = skill_manager.patch_skill(name, req.old, req.new)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.delete("/skills/{name}")
async def delete_skill(name: str):
    ensure_initialized()
    ok, msg = skill_manager.delete_skill(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.get("/skills/{name}/files/{file_path:path}")
async def view_skill_file(name: str, file_path: str):
    ensure_initialized()
    content = skill_manager.view_file(name, file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="文件未找到")
    return {"content": content}


@router.get("/stats")
async def get_hermes_stats():
    ensure_initialized()
    raw = memory_manager.get_stats()
    return {
        "memory": {
            "entry_count": raw["memory_entries"],
            "char_count": raw["memory_chars"],
            "max_chars": raw["memory_limit"],
        },
        "user": {
            "entry_count": raw["user_entries"],
            "char_count": raw["user_chars"],
            "max_chars": raw["user_limit"],
        },
    }
