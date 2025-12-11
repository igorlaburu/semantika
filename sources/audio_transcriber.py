"""Audio transcription with Whisper for semantika.

Transcribes audio files to text using OpenAI Whisper.
"""

import os
from typing import Dict, Optional
import tempfile

import whisper

from utils.logger import get_logger

logger = get_logger("audio_transcriber")


class AudioTranscriber:
    """Audio transcriber using Whisper."""

    def __init__(self, model_name: str = "base"):
        """
        Initialize audio transcriber.

        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
        """
        try:
            import os
            logger.info("loading_whisper_model", model=model_name)
            download_root = os.getenv("WHISPER_CACHE_DIR", None)
            self.model = whisper.load_model(model_name, download_root=download_root)
            logger.info("whisper_model_loaded", model=model_name)
        except Exception as e:
            logger.error("whisper_model_load_failed", error=str(e))
            raise

    def transcribe_file(
        self,
        file_path: str,
        language: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Transcribe audio file.

        Args:
            file_path: Path to audio file
            language: Language code (e.g., 'es', 'en') or None for auto-detect

        Returns:
            Dict with transcription and detected language
        """
        try:
            logger.info("transcription_start", file=file_path, language=language)

            # Transcribe
            result = self.model.transcribe(
                file_path,
                language=language,
                fp16=False  # Disable FP16 for CPU compatibility
            )

            transcription = result["text"].strip()
            detected_language = result.get("language", "unknown")

            logger.info(
                "transcription_completed",
                file=file_path,
                text_length=len(transcription),
                detected_language=detected_language
            )

            return {
                "text": transcription,
                "language": detected_language
            }

        except Exception as e:
            logger.error("transcription_error", file=file_path, error=str(e))
            raise

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        filename: str = "audio.mp3",
        language: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Transcribe audio from bytes.

        Args:
            audio_bytes: Audio file bytes
            filename: Original filename (for extension detection)
            language: Language code or None

        Returns:
            Dict with transcription and language
        """
        try:
            # Save to temporary file
            suffix = os.path.splitext(filename)[1] or ".mp3"

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                # Transcribe
                result = self.transcribe_file(tmp_path, language=language)
                return result
            finally:
                # Clean up
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        except Exception as e:
            logger.error("transcribe_bytes_error", error=str(e))
            raise

    async def transcribe_and_ingest(
        self,
        file_path: str,
        client_id: str,
        title: Optional[str] = None,
        language: Optional[str] = None,
        skip_guardrails: bool = False
    ) -> Dict[str, any]:
        """
        Transcribe audio and ingest to vector store.

        Args:
            file_path: Path to audio file
            client_id: Client UUID
            title: Document title (defaults to filename)
            language: Language code
            skip_guardrails: Skip PII/Copyright checks

        Returns:
            Dict with transcription and ingestion results
        """
        from core_ingest import IngestPipeline

        try:
            # Transcribe
            transcription = self.transcribe_file(file_path, language=language)

            # Ingest
            pipeline = IngestPipeline(client_id=client_id)

            result = await pipeline.ingest_text(
                text=transcription["text"],
                title=title or os.path.basename(file_path),
                metadata={
                    "source": "audio",
                    "language": transcription["language"],
                    "original_file": os.path.basename(file_path)
                },
                skip_guardrails=skip_guardrails
            )

            logger.info(
                "transcribe_and_ingest_completed",
                file=file_path,
                documents_added=result["documents_added"]
            )

            return {
                "transcription": transcription["text"],
                "language": transcription["language"],
                **result
            }

        except Exception as e:
            logger.error("transcribe_and_ingest_error", file=file_path, error=str(e))
            raise
