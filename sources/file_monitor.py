"""File monitor for semantika.

Monitors a directory for new files (text and audio) and ingests them automatically.
"""

import os
import time
from pathlib import Path
from typing import Set, Optional
import asyncio

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from .audio_transcriber import AudioTranscriber

logger = get_logger("file_monitor")


class FileMonitor:
    """Monitor directory for new files and ingest them."""

    # Supported file extensions
    TEXT_EXTENSIONS = {".txt", ".md", ".pdf", ".doc", ".docx"}
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

    def __init__(
        self,
        watch_dir: str,
        processed_dir: str,
        check_interval: int = 30
    ):
        """
        Initialize file monitor.

        Args:
            watch_dir: Directory to monitor
            processed_dir: Directory to move processed files
            check_interval: Check interval in seconds
        """
        self.watch_dir = Path(watch_dir)
        self.processed_dir = Path(processed_dir)
        self.check_interval = check_interval
        self.processed_files: Set[str] = set()

        # Create directories if they don't exist
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        # Initialize audio transcriber
        self.transcriber = AudioTranscriber(model_name="base")

        logger.info(
            "file_monitor_initialized",
            watch_dir=str(self.watch_dir),
            processed_dir=str(self.processed_dir),
            check_interval=check_interval
        )

    def _get_client_from_filename(self, filename: str) -> Optional[str]:
        """
        Extract client_id from filename.

        Expected format: {client_id}_{anything}.ext
        Example: 28d8c40a-c661-4b74-b4ea-7ed075339e9d_report.txt

        Args:
            filename: Filename

        Returns:
            Client ID or None
        """
        try:
            parts = filename.split("_", 1)
            if len(parts) >= 2:
                potential_id = parts[0]
                # Basic UUID format check
                if len(potential_id) == 36 and potential_id.count("-") == 4:
                    return potential_id
        except Exception as e:
            logger.debug("client_extraction_failed", filename=filename, error=str(e))

        return None

    async def _process_text_file(self, file_path: Path, client_id: str):
        """
        Process text file.

        Args:
            file_path: Path to text file
            client_id: Client UUID
        """
        from core_ingest import IngestPipeline

        try:
            logger.info("processing_text_file", file=str(file_path))

            # Read file
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()

            # Ingest
            pipeline = IngestPipeline(client_id=client_id)

            result = await pipeline.ingest_text(
                text=text,
                title=file_path.stem,
                metadata={
                    "source": "file_monitor",
                    "original_file": file_path.name
                },
                skip_guardrails=False
            )

            logger.info(
                "text_file_processed",
                file=str(file_path),
                documents_added=result["documents_added"]
            )

        except Exception as e:
            logger.error("text_file_processing_error", file=str(file_path), error=str(e))
            raise

    async def _process_audio_file(self, file_path: Path, client_id: str):
        """
        Process audio file.

        Args:
            file_path: Path to audio file
            client_id: Client UUID
        """
        try:
            logger.info("processing_audio_file", file=str(file_path))

            result = await self.transcriber.transcribe_and_ingest(
                file_path=str(file_path),
                client_id=client_id,
                title=file_path.stem,
                language=None,  # Auto-detect
                skip_guardrails=False
            )

            logger.info(
                "audio_file_processed",
                file=str(file_path),
                documents_added=result["documents_added"],
                language=result.get("language")
            )

        except Exception as e:
            logger.error("audio_file_processing_error", file=str(file_path), error=str(e))
            raise

    async def _process_file(self, file_path: Path):
        """
        Process a single file.

        Args:
            file_path: Path to file
        """
        try:
            # Extract client_id from filename
            client_id = self._get_client_from_filename(file_path.name)

            if not client_id:
                logger.warn(
                    "invalid_filename_format",
                    file=str(file_path),
                    expected_format="{client_id}_{name}.ext"
                )
                # Move to processed anyway to avoid reprocessing
                target = self.processed_dir / f"error_{file_path.name}"
                file_path.rename(target)
                return

            # Verify client exists
            supabase = get_supabase_client()
            client = await supabase.get_client_by_id(client_id)

            if not client:
                logger.warn("client_not_found", client_id=client_id, file=str(file_path))
                target = self.processed_dir / f"error_{file_path.name}"
                file_path.rename(target)
                return

            # Process based on file type
            extension = file_path.suffix.lower()

            if extension in self.TEXT_EXTENSIONS:
                await self._process_text_file(file_path, client_id)
            elif extension in self.AUDIO_EXTENSIONS:
                await self._process_audio_file(file_path, client_id)
            else:
                logger.warn("unsupported_file_type", file=str(file_path), extension=extension)

            # Move to processed
            target = self.processed_dir / file_path.name
            file_path.rename(target)

            logger.info("file_moved_to_processed", file=str(file_path))

        except Exception as e:
            logger.error("file_processing_error", file=str(file_path), error=str(e))
            # Move to processed with error prefix
            target = self.processed_dir / f"error_{file_path.name}"
            file_path.rename(target)

    async def scan_directory(self):
        """Scan directory for new files and process them."""
        try:
            logger.debug("scanning_directory", dir=str(self.watch_dir))

            files = list(self.watch_dir.glob("*"))

            for file_path in files:
                # Skip directories and hidden files
                if file_path.is_dir() or file_path.name.startswith("."):
                    continue

                # Skip if already processed
                if str(file_path) in self.processed_files:
                    continue

                # Process file
                await self._process_file(file_path)
                self.processed_files.add(str(file_path))

        except Exception as e:
            logger.error("directory_scan_error", error=str(e))

    async def start(self):
        """Start monitoring directory."""
        logger.info("file_monitor_started", watch_dir=str(self.watch_dir))

        while True:
            try:
                await self.scan_directory()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error("monitor_loop_error", error=str(e))
                await asyncio.sleep(self.check_interval)
