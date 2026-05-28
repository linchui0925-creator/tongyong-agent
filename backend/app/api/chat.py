"""
聊天API路由模块
提供对话功能，支持会话管理和记忆检索
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from app.llm.base import LLMError
import logging
import time

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str = Field(..., min_length=1, max_length=10000, description="消息内容")
    session_id: Optional[str] = Field(None, description="会话ID")
    use_memory: bool = Field(True, description="是否使用记忆功能")
    
    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """验证消息内容"""
        if not v or not v.strip():
            raise ValueError('消息内容不能为空')
        return v.strip()


class ChatResponse(BaseModel):
    """聊天响应模型"""
    reply: str
    session_id: str
    memory_added: List[dict] = Field(default_factory=list)
    memory_verification: Optional[dict] = None
    tools_used: List[str] = Field(default_factory=list)
    commands_executed: List[str] = Field(default_factory=list, description="实际执行的命令列表")
    processing_time: Optional[float] = None


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str
    code: str
    details: Optional[str] = None
    timestamp: str


def get_agent():
    """获取Agent引擎实例"""
    from app.main import agent_engine
    if agent_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Agent引擎未初始化"
        )
    return agent_engine


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, engine = Depends(get_agent)):
    """
    发送聊天消息
    
    Args:
        request: 聊天请求参数
        engine: Agent引擎依赖
        
    Returns:
        ChatResponse: 聊天响应
        
    Raises:
        HTTPException: 请求失败时抛出
    """
    start_time = time.time()
    
    try:
        logger.info(f"收到聊天请求: session={request.session_id}, memory={request.use_memory}")
        
        # 调用Agent引擎处理
        result = await engine.chat(
            session_id=request.session_id,
            message=request.message,
            use_memory=request.use_memory
        )
        
        # 计算处理时间
        processing_time = time.time() - start_time
        
        logger.info(f"聊天请求处理完成，耗时: {processing_time:.2f}s")
        
        return ChatResponse(
            reply=result.get("reply", ""),
            session_id=result.get("session_id", ""),
            memory_added=result.get("memory_added", []),
            memory_verification=result.get("memory_verification"),
            tools_used=result.get("tools_used", []),
            commands_executed=result.get("commands_executed", []),
            processing_time=processing_time
        )
        
    except LLMError as e:
        # LLM相关错误
        logger.error(f"LLM错误: {e.code} - {e.message}", exc_info=True)
        
        return JSONResponse(
            status_code=502,
            content={
                "error": f"AI服务错误: {e.message}",
                "code": e.code,
                "details": str(e.details) if e.details else None,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        )
        
    except HTTPException:
        # 重新抛出HTTP异常
        raise
        
    except ValueError as e:
        # 参数验证错误
        logger.warning(f"参数验证错误: {e}")
        
        return JSONResponse(
            status_code=400,
            content={
                "error": "请求参数错误",
                "code": "VALIDATION_ERROR",
                "details": str(e),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        )
        
    except Exception as e:
        # 通用错误处理
        logger.error(f"聊天请求处理失败: {e}", exc_info=True)
        
        return JSONResponse(
            status_code=500,
            content={
                "error": "服务器内部错误",
                "code": "INTERNAL_ERROR",
                "details": str(e) if logger.level <= logging.DEBUG else None,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        )


@router.get("/")
async def root():
    """API根路径"""
    return {"message": "Chat API", "version": "1.0.0"}


@router.get("/health")
async def health_check(engine = Depends(get_agent)):
    """
    健康检查端点
    
    Returns:
        dict: 健康状态信息
    """
    return {
        "status": "ok",
        "llm_initialized": engine.llm is not None,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
