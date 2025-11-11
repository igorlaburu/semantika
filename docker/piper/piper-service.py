"""Piper TTS Service for Semantika.

Provides text-to-speech synthesis using Piper TTS with Spanish voice.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import subprocess
import io
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","timestamp":"%(asctime)s","service":"piper-tts","action":"%(message)s"}'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Semantika TTS Service",
    description="Text-to-Speech service using Piper TTS",
    version="1.0.0"
)

# CORS configuration (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Text to synthesize")
    rate: float = Field(1.0, ge=0.5, le=2.0, description="Speech rate (0.5 = slow, 2.0 = fast)")


@app.post("/synthesize", response_class=StreamingResponse)
async def synthesize(request: TTSRequest):
    """Synthesize text to speech using Piper TTS.

    Args:
        request: TTSRequest with text and rate

    Returns:
        WAV audio stream
    """
    try:
        logger.info(f"tts_request text_length={len(request.text)} rate={request.rate}")

        # Convert rate to length_scale (inverse relationship)
        # rate 1.3 = 30% faster = length_scale 0.77
        length_scale = 1.0 / request.rate

        # Call Piper binary
        process = subprocess.Popen(
            [
                '/app/piper/piper',
                '--model', '/app/models/es_ES-davefx-medium.onnx',
                '--length_scale', str(length_scale),
                '--output-raw'
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        audio_data, error = process.communicate(
            input=request.text.encode('utf-8'),
            timeout=30
        )

        if process.returncode != 0:
            error_msg = error.decode('utf-8', errors='ignore')
            logger.error(f"piper_error returncode={process.returncode} error={error_msg}")
            raise HTTPException(
                status_code=500,
                detail=f"Piper TTS error: {error_msg}"
            )

        audio_size = len(audio_data)
        logger.info(f"tts_success audio_size={audio_size} estimated_duration={audio_size // 32000}s")

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
        logger.error("piper_timeout text_length=%d", len(request.text))
        raise HTTPException(status_code=504, detail="TTS generation timeout (30s)")

    except Exception as e:
        logger.error(f"tts_error error={str(e)}")
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "semantika-tts",
        "version": "1.0.0",
        "model": "es_ES-davefx-medium"
    }


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "Semantika TTS",
        "description": "Text-to-Speech service using Piper TTS",
        "endpoints": {
            "POST /synthesize": "Generate speech from text",
            "GET /health": "Health check",
            "GET /docs": "API documentation"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
