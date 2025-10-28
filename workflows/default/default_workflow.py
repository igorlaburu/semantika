"""Default workflow implementation.

Standard processing pipeline for companies without custom workflows.
"""

from typing import Dict, Any
from sources.base_source import SourceContent
from workflows.base_workflow import BaseWorkflow
from utils.openrouter_client import get_openrouter_client


class DefaultWorkflow(BaseWorkflow):
    """Default content processing workflow."""

    async def generate_context_unit(self, source_content: SourceContent) -> Dict[str, Any]:
        """Generate context unit using standard LLM processing.
        
        Args:
            source_content: Raw content from source
            
        Returns:
            Standard context unit
        """
        # Get aggregated text from source content
        raw_content = source_content.raw_content
        
        # Combine all text content
        text_parts = []
        
        # Email body/text
        if "body" in raw_content:
            text_parts.append(raw_content["body"])
        
        # Transcriptions from audio
        if "transcriptions" in raw_content:
            for transcript in raw_content["transcriptions"]:
                text_parts.append(transcript.get("text", ""))
        
        # Attachment text
        if "attachments_text" in raw_content:
            for att_text in raw_content["attachments_text"]:
                text_parts.append(att_text)

        # Combine all text
        full_text = "\n\n".join(filter(None, text_parts))
        
        if not full_text.strip():
            self.logger.warn("no_text_content_found", source_id=source_content.source_id)
            return {
                "title": "Empty Content",
                "summary": "No text content found in source",
                "tags": [],
                "atomic_statements": [],
                "raw_text": ""
            }

        # Use OpenRouter client for LLM processing
        openrouter = get_openrouter_client()
        
        # Generate context unit with tracking
        # Note: organization_id and context_unit_id will be handled by universal_pipeline
        context_unit = await openrouter.generate_context_unit(
            text=full_text,
            organization_id=None,  # Will be set by pipeline
            context_unit_id=None,  # Will be set by pipeline
            client_id=None  # Email source, no specific client
        )
        
        # Add raw_text to context unit
        context_unit["raw_text"] = full_text
        
        self.logger.info(
            "context_unit_generated",
            company_code=self.company_code,
            title_length=len(context_unit.get("title", "")),
            statements_count=len(context_unit.get("atomic_statements", []))
        )

        return context_unit