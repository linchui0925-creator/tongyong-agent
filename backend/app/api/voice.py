"""
语音 API 路由模块
提供语音转文字（ASR）与文字转语音（TTS）能力。
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.services.llm_manager import get_llm_manager

router = APIRouter()
logger = logging.getLogger(__name__)

VOICE_OUTPUT_DIR = Path(os.getenv("VOICE_OUTPUT_DIR", "/tmp/tongyong-agent-voice"))
VOICE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=12000)
    voice: Optional[str] = Field(None, description="OpenAI TTS voice")
    format: str = Field("mp3", description="mp3 / wav / opus / aac / flac")
    model_id: Optional[str] = Field(None, description="Selected model ID from LLM manager")


def _resolve_voice_llm(model_id: Optional[str] = None):
    """Resolve LLM for voice from the same runtime source as chat.

    Priority:
    1) explicit saved model_id
    2) current engine.llm / llm_manager current runtime
    3) rebuild from current provider/model if needed
    """
    from app.main import app
    llm_manager = get_llm_manager()
    agent_engine = getattr(app, "extra", {}).get("agent_engine") if hasattr(app, "extra") else None
    if agent_engine is None:
        # main.py may keep agent_engine as module global
        try:
            from app import main as main_mod
            agent_engine = getattr(main_mod, "agent_engine", None)
        except Exception:
            agent_engine = None

    llm = None
    if model_id:
        model = llm_manager.get_saved_model_by_id(model_id)
        if model:
            llm = llm_manager.get_llm(
                provider=model.get("provider"),
                api_key=model.get("api_key"),
                model=model.get("model"),
                api_endpoint=model.get("api_endpoint"),
            )
    if llm is None:
        llm = llm_manager.get_current_llm() or (getattr(agent_engine, "llm", None) if agent_engine else None)
    if llm is None:
        # rebuild from current runtime config
        provider = llm_manager.get_current_provider()
        model = llm_manager.get_current_model()
        runtime = llm_manager.build_runtime_config(provider=provider, model=model)
        llm = llm_manager._llm_from_runtime_config(runtime)

    # Prefer OpenAI-compatible voice client when possible
    if llm is not None and not hasattr(llm, "_get_client"):
        from app.llm.openai import OpenAILLM
        from app.llm.openai_compatible import OpenAICompatibleLLM
        if isinstance(llm, OpenAICompatibleLLM) or hasattr(llm, "api_base"):
            voice_llm = OpenAILLM(api_key=getattr(llm, "api_key", None) or "", model=getattr(llm, "model", None))
            if getattr(llm, "api_base", None):
                voice_llm.api_base = llm.api_base
            llm = voice_llm
    return llm


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...), model_id: Optional[str] = None):
    """将上传的音频转成文字。"""
    try:
        llm = _resolve_voice_llm(model_id)
        if llm is None:
            return JSONResponse(status_code=503, content={"success": False, "error": "LLM 未初始化"})
        if not getattr(llm, "api_key", None):
            return JSONResponse(status_code=400, content={"success": False, "error": "当前模型 API 密钥未设置，无法语音识别"})
        if not hasattr(llm, "_get_client"):
            return JSONResponse(status_code=501, content={"success": False, "error": "当前模型不支持语音识别（需要 OpenAI 兼容 audio API）"})

        suffix = Path(file.filename or "audio.webm").suffix or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(await file.read())

        try:
            client = llm._get_client()  # noqa: SLF001 - reuse provider client
            with tmp_path.open("rb") as audio_fp:
                transcript = await client.audio.transcriptions.create(
                    model=os.getenv("VOICE_ASR_MODEL", "whisper-1"),
                    file=audio_fp,
                    language=os.getenv("VOICE_ASR_LANGUAGE", "zh"),
                )
            text = getattr(transcript, "text", "") or ""
            return {"success": True, "text": text}
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception as exc:
        logger.error("语音转写失败: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/speak")
async def speak_text(request: TTSRequest):
    """将文本合成为语音文件并返回下载地址。"""
    try:
        llm = _resolve_voice_llm(request.model_id)
        if llm is None:
            return JSONResponse(status_code=503, content={"success": False, "error": "LLM 未初始化"})
        if not getattr(llm, "api_key", None):
            return JSONResponse(status_code=400, content={"success": False, "error": "当前模型 API 密钥未设置，无法语音合成"})
        if not hasattr(llm, "_get_client"):
            return JSONResponse(status_code=501, content={"success": False, "error": "当前模型不支持语音合成（需要 OpenAI 兼容 audio API）"})

        client = llm._get_client()  # noqa: SLF001 - reuse provider client
        voice = request.voice or os.getenv("VOICE_TTS_VOICE", "alloy")
        response = await client.audio.speech.create(
            model=os.getenv("VOICE_TTS_MODEL", "tts-1"),
            voice=voice,
            input=request.text,
            response_format=request.format,
        )

        out_name = f"tts_{uuid.uuid4().hex}.{request.format}"
        out_path = VOICE_OUTPUT_DIR / out_name
        data = response.read() if hasattr(response, "read") else response.content
        if hasattr(data, "__await__"):
            data = await data
        out_path.write_bytes(data)
        return {
            "success": True,
            "audio_url": f"/api/voice/audio/{out_name}",
            "format": request.format,
            "voice": voice,
        }
    except Exception as exc:
        logger.error("语音合成失败: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.get("/audio/{filename}")
def get_audio(filename: str):
    path = VOICE_OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="音频文件不存在")
    return FileResponse(path)
