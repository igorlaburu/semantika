"""Context Unit Generator.

Generates structured context units from any source content using LLM.
"""

from typing import Dict, Any
from sources.base_source import SourceContent
from utils.openrouter_client import get_openrouter_client
from utils.logger import get_logger

logger = get_logger("context_unit_generator")


class ContextUnitGenerator:
    """Generates structured context units from source content."""

    def __init__(self):
        """Initialize generator with OpenRouter client."""
        self.openrouter = get_openrouter_client()
        logger.debug("context_unit_generator_initialized")

    async def generate(self, source_content: SourceContent) -> Dict[str, Any]:
        """
        Generate context unit from source content.

        Args:
            source_content: Unified content from any source

        Returns:
            Dict with title, summary, tags, atomic_statements
        """
        logger.info(
            "generate_context_unit_start",
            org=source_content.organization_slug,
            source_type=source_content.source_type
        )

        try:
            # 1. Build unified text from raw_content
            prompt_text = self._build_prompt_text(source_content.raw_content)

            logger.debug("prompt_built", text_length=len(prompt_text))

            # 2. Call LLM to generate context unit
            result = await self.openrouter.generate_context_unit(prompt_text)

            logger.info(
                "context_unit_generated",
                org=source_content.organization_slug,
                statements_count=len(result.get("atomic_statements", []))
            )

            return result

        except Exception as e:
            logger.error("context_unit_generation_error", error=str(e))
            raise

    def _build_prompt_text(self, raw_content: Dict[str, Any]) -> str:
        """
        Build unified text input for LLM from raw content.

        Aggregates:
        - Subject (if email)
        - Body text
        - Audio transcriptions (if any)
        - Text attachments (if any)

        Args:
            raw_content: Dictionary with content parts

        Returns:
            Formatted text for LLM
        """
        parts = []

        # Subject (emails)
        if raw_content.get("subject"):
            parts.append(f"ASUNTO: {raw_content['subject']}")

        # Body text
        if raw_content.get("body"):
            parts.append(f"CUERPO:\n{raw_content['body']}")

        # Attachments
        for attachment in raw_content.get("attachments", []):
            att_type = attachment.get("type")
            filename = attachment.get("filename", "unknown")

            if att_type == "audio" and attachment.get("transcription"):
                parts.append(
                    f"AUDIO ({filename}):\n{attachment['transcription']}"
                )
            elif att_type == "text" and attachment.get("text"):
                parts.append(
                    f"ADJUNTO ({filename}):\n{attachment['text']}"
                )

        # Join all parts with double newline
        return "\n\n".join(parts)
