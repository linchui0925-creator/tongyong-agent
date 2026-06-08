"""
领域基础数据模型 - Message / Session / Memory / ToolResult。

被 agent / memory / api 等多模块引用，**禁止改字段名**（会破 SQLite schema 迁移）。
新增字段时：Optional 字段 + 默认值，向后兼容。
"""
from pydantic import BaseModel
from typing import Optional, Any

class Message(BaseModel):
    """消息模型 - 包含完整的上下文追踪信息"""
    id: Optional[int] = None  # 自增序列号，确保消息顺序
    session_id: Optional[str] = None  # 会话ID
    role: str  # 角色：user/assistant
    content: str  # 消息内容
    created_at: Optional[str] = None  # 创建时间
    sequence: Optional[int] = None  # 序列号，用于精确排序

class Session(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str

class Memory(BaseModel):
    id: str
    type: str
    content: str
    importance: int = 1
    session_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    vector_id: Optional[str] = None
    version: int = 1

class ToolResult(BaseModel):
    tool: str
    success: bool
    result: Any = None
    error: Optional[str] = None