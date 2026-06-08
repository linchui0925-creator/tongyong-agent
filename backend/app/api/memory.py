"""
Memory API - 会话 / 消息 / 记忆的 CRUD 路由。

挂载点：/api/memory/* (在 main.py 注册)
职责划分：
  - /sessions            会话管理（list / create / get / delete）
  - /sessions/{id}/messages  会话内消息（list / add）
  - /memories            全量记忆（search / add / update / delete）
  - /settings            用户级设置（key-value 存储）

所有 Pydantic Request model 定义在本文件顶部；操作逻辑直接走 MemoryStorage
（同步 API，路由用 sync 函数 + FastAPI 自动 run_in_threadpool）。
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from app.core.base import Memory, Session
from app.core.agent import AgentEngine
import logging
import time

router = APIRouter()
logger = logging.getLogger(__name__)

class CreateSessionRequest(BaseModel):
    """新建会话请求。"""
    name: str

class UpdateSessionRequest(BaseModel):
    """更新会话名请求。"""
    name: str

class SearchRequest(BaseModel):
    """向量记忆搜索请求。"""
    query: str
    k: int = 10
    session_id: Optional[str] = None

class AddMemoryRequest(BaseModel):
    """新增记忆请求。"""
    type: str
    content: str
    importance: int = 1
    session_id: Optional[str] = None

class UpdateMemoryRequest(BaseModel):
    """更新记忆内容请求。"""
    content: str
    importance: Optional[int] = None

class AddSettingRequest(BaseModel):
    key: str
    value: str
    type: str = "string"

class UpdateSettingRequest(BaseModel):
    value: str

def get_agent() -> AgentEngine:
    from app.main import agent_engine
    if agent_engine is None:
        raise HTTPException(status_code=503, detail="Agent引擎未初始化")
    return agent_engine

@router.post("/create")
async def create_session(request: CreateSessionRequest, engine: AgentEngine = Depends(get_agent)):
    session = await engine.create_session(request.name)
    return {"session": session.model_dump()}

@router.get("/sessions")
async def get_sessions(engine: AgentEngine = Depends(get_agent)):
    sessions = await engine.get_sessions()
    return {"sessions": [s.model_dump() for s in sessions]}

@router.put("/session/{session_id}")
async def update_session(session_id: str, request: UpdateSessionRequest, engine: AgentEngine = Depends(get_agent)):
    """更新会话名称
    
    Args:
        session_id: 会话ID
        request: 包含新名称
        
    Returns:
        dict: 更新后的会话
    """
    session = await engine.update_session(session_id, request.name)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session": session.model_dump()}

@router.get("/messages/{session_id}")
async def get_session_messages(session_id: str, engine: AgentEngine = Depends(get_agent)):
    """获取指定会话的所有消息
    
    Args:
        session_id: 会话ID
        
    Returns:
        dict: 包含消息列表
    """
    try:
        messages = await engine.get_conversation_history(session_id)
        return {
            "session_id": session_id,
            "messages": [
                {
                    "id": msg.id if hasattr(msg, 'id') else str(idx),
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at if hasattr(msg, 'created_at') else None
                }
                for idx, msg in enumerate(messages)
            ]
        }
    except Exception as e:
        logger.error(f"获取会话消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/message/previous/{session_id}/{current_sequence}")
async def get_previous_message(session_id: str, current_sequence: int, engine: AgentEngine = Depends(get_agent)):
    """获取指定消息的上一条消息
    
    Args:
        session_id: 会话ID
        current_sequence: 当前消息的序列号
        
    Returns:
        dict: 上一条消息
    """
    try:
        message = await engine.get_previous_message(session_id, current_sequence)
        if not message:
            raise HTTPException(status_code=404, detail="没有找到上一条消息")
        return message
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取上一条消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/message/last-user/{session_id}")
async def get_last_user_message(session_id: str, engine: AgentEngine = Depends(get_agent)):
    """获取会话的最后一条用户消息
    
    Args:
        session_id: 会话ID
        
    Returns:
        dict: 最后一条用户消息
    """
    try:
        message = await engine.get_last_user_message(session_id)
        if not message:
            raise HTTPException(status_code=404, detail="没有找到用户消息")
        return message
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取最后用户消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/message/by-sequence/{session_id}/{sequence}")
async def get_message_by_sequence(session_id: str, sequence: int, engine: AgentEngine = Depends(get_agent)):
    """根据序列号获取指定消息
    
    Args:
        session_id: 会话ID
        sequence: 消息序列号
        
    Returns:
        dict: 指定序列号的消息
    """
    try:
        message = await engine.get_message_by_sequence(session_id, sequence)
        if not message:
            raise HTTPException(status_code=404, detail="没有找到指定消息")
        return message
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"根据序列号获取消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/conversation/stats/{session_id}")
async def get_conversation_stats(session_id: str, engine: AgentEngine = Depends(get_agent)):
    """获取会话统计信息
    
    Args:
        session_id: 会话ID
        
    Returns:
        dict: 会话统计信息
    """
    try:
        stats = await engine.get_conversation_stats(session_id)
        return stats
    except Exception as e:
        logger.error(f"获取会话统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """健康检查端点"""
    try:
        from app.main import agent_engine
        sessions = await agent_engine.get_sessions()
        return {
            "status": "ok",
            "sessions_count": len(sessions),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, engine: AgentEngine = Depends(get_agent)):
    """删除会话（完整实现）
    
    Args:
        session_id: 会话ID
        
    Returns:
        dict: 删除结果
    """
    try:
        success = await engine.delete_session(session_id)
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        logger.info(f"删除会话成功: {session_id}")
        return {"success": True, "message": "会话已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}/messages")
async def clear_session_messages(session_id: str, engine: AgentEngine = Depends(get_agent)):
    """清空会话消息"""
    try:
        success = await engine.memory_storage.clear_messages(session_id)
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        logger.info(f"清空会话消息成功: {session_id}")
        return {"status": "ok", "message": "会话消息已清空"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清空会话消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{session_id}")
async def get_session_memories(session_id: str, engine: AgentEngine = Depends(get_agent)):
    memories = await engine.get_session_memories(session_id)
    return {"memories": [m.model_dump() for m in memories]}

@router.post("/search")
async def search_memories(request: SearchRequest, engine: AgentEngine = Depends(get_agent)):
    memories = await engine.search_memories(request.query, request.k, request.session_id)
    return {"results": [m.model_dump() for m in memories]}

@router.post("/add")
async def add_memory(request: AddMemoryRequest, engine: AgentEngine = Depends(get_agent)):
    memory = await engine.add_memory(request.type, request.content, request.importance, request.session_id)
    return {"memory": memory.model_dump()}

@router.put("/update/{memory_id}")
async def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    engine: AgentEngine = Depends(get_agent)
):
    updated_memory = await engine.update_memory(memory_id, request.content, request.importance)
    if not updated_memory:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"memory": updated_memory.model_dump()}

@router.delete("/delete/{memory_id}")
async def delete_memory(memory_id: str, engine: AgentEngine = Depends(get_agent)):
    success = await engine.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"success": success}

@router.get("/versions/{memory_id}")
async def get_memory_versions(memory_id: str, engine: AgentEngine = Depends(get_agent)):
    versions = await engine.get_memory_versions(memory_id)
    return {"versions": versions}

@router.get("/verify/{session_id}")
async def verify_memory_loading(session_id: str, engine: AgentEngine = Depends(get_agent)):
    verification = await engine.verify_memory_loading(session_id)
    return verification

@router.post("/settings/add")
async def add_setting(
    session_id: str,
    request: AddSettingRequest,
    engine: AgentEngine = Depends(get_agent)
):
    setting = await engine.add_setting(session_id, request.key, request.value, request.type)
    return {"setting": setting}

@router.get("/settings/{session_id}")
async def get_settings(session_id: str, engine: AgentEngine = Depends(get_agent)):
    settings = await engine.get_all_settings(session_id)
    return {"settings": settings}

@router.get("/settings/{session_id}/{key}")
async def get_setting(session_id: str, key: str, engine: AgentEngine = Depends(get_agent)):
    setting = await engine.get_setting(session_id, key)
    if not setting:
        raise HTTPException(status_code=404, detail="设定不存在")
    return {"setting": setting}

@router.put("/settings/{session_id}/{key}")
async def update_setting(
    session_id: str,
    key: str,
    request: UpdateSettingRequest,
    engine: AgentEngine = Depends(get_agent)
):
    setting = await engine.update_setting(session_id, key, request.value)
    if not setting:
        raise HTTPException(status_code=404, detail="设定不存在")
    return {"setting": setting}

@router.delete("/settings/{session_id}/{key}")
async def delete_setting(session_id: str, key: str, engine: AgentEngine = Depends(get_agent)):
    success = await engine.delete_setting(session_id, key)
    if not success:
        raise HTTPException(status_code=404, detail="设定不存在")
    return {"success": success}

@router.get("/")
async def root():
    return {"message": "Memory API"}
