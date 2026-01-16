"""TTS (Text-to-Speech) endpoints using Piper TTS."""

import io
import subprocess
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from utils.logger import get_logger
from utils.auth_dependencies import get_auth_context
from utils.usage_tracker import get_usage_tracker

logger = get_logger("api.tts")
router = APIRouter(prefix="/tts", tags=["tts"])


class TTSRequest(BaseModel):
    """Request model for TTS synthesis."""
    text: str = Field(..., min_length=1, max_length=3000, description="Text to synthesize (max 3000 chars for speed)")
    rate: float = Field(1.3, ge=0.5, le=2.0, description="Speech rate (0.5=slow, 2.0=fast)")


@router.get("/health")
async def tts_health(auth: Dict = Depends(get_auth_context)):
    """TTS service health check (requires authentication).

    Args:
        auth: Authenticated context from JWT or API key

    Returns:
        Health status of TTS service
    """
    return {
        "status": "ok",
        "service": "semantika-tts",
        "version": "1.0.0",
        "model": "es_ES-carlfm-x_low",
        "quality": "x_low (3-4x faster, 28MB)",
        "integrated": True,
        "client_id": auth["client_id"]
    }


@router.post("/synthesize")
async def tts_synthesize(
    request: TTSRequest,
    auth: Dict = Depends(get_auth_context)
):
    """Synthesize speech from text using Piper TTS.

    Args:
        request: TTSRequest with text and rate

    Returns:
        WAV audio stream

    Raises:
        HTTPException: If synthesis fails
    """
    try:
        logger.info(
            "tts_request",
            client_id=auth["client_id"],
            text_length=len(request.text),
            rate=request.rate,
            text_preview=request.text[:50]
        )

        # Warn if text is long (may take >10s)
        if len(request.text) > 2000:
            logger.warn(
                "tts_long_text",
                client_id=auth["client_id"],
                text_length=len(request.text),
                estimated_duration_seconds=len(request.text) // 200  # ~200 chars/sec
            )

        # Convert rate to length_scale (inverse)
        # rate 1.3 = 30% faster = length_scale 0.77
        length_scale = 1.0 / request.rate

        # Call Piper binary with X_LOW quality model (3-4x faster, carlfm voice)
        # Output to stdout as WAV format
        process = subprocess.Popen(
            [
                '/app/piper/piper',
                '--model', '/app/models/es_ES-carlfm-x_low.onnx',
                '--length_scale', str(length_scale),
                '--output_file', '-'  # Output WAV to stdout
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        audio_data, error = process.communicate(
            input=request.text.encode('utf-8'),
            timeout=15  # 15s timeout for better UX (fallback to browser TTS)
        )

        if process.returncode != 0:
            error_msg = error.decode('utf-8', errors='ignore')
            logger.error(
                "piper_tts_error",
                returncode=process.returncode,
                error=error_msg[:200]
            )
            raise HTTPException(
                status_code=500,
                detail=f"TTS synthesis failed: {error_msg[:100]}"
            )

        audio_size = len(audio_data)
        estimated_duration = audio_size // 32000  # Rough estimate

        logger.info(
            "tts_success",
            client_id=auth["client_id"],
            audio_size=audio_size,
            estimated_duration_seconds=estimated_duration,
            text_length=len(request.text),
            rate=request.rate
        )

        # Track usage as simple operation (microedicion)
        tracker = get_usage_tracker()
        await tracker.track(
            model="piper/es_ES-carlfm-x_low",
            operation="tts_synthesize",
            input_tokens=0,
            output_tokens=0,
            company_id=auth.get("company_id", "00000000-0000-0000-0000-000000000001"),
            client_id=auth["client_id"],
            metadata={
                "text_length": len(request.text),
                "audio_size": audio_size,
                "rate": request.rate,
                "duration_seconds": estimated_duration,
                "usage_type": "simple"
            }
        )

        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=speech.wav",
                "Content-Length": str(audio_size),
                "Cache-Control": "public, max-age=3600"
            }
        )

    except subprocess.TimeoutExpired:
        logger.error(
            "tts_timeout",
            client_id=auth["client_id"],
            text_length=len(request.text)
        )
        raise HTTPException(
            status_code=504,
            detail=f"TTS timeout (>15s) - texto demasiado largo ({len(request.text)} caracteres). Usa menos de 2000 caracteres para sintesis rapida."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "tts_error",
            client_id=auth["client_id"],
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"TTS error: {str(e)}"
        )
