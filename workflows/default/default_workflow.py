"""Default workflow implementation.

Standard processing pipeline for companies without custom workflows.
"""

from typing import Dict, Any
from core.source_content import SourceContent
from workflows.base_workflow import BaseWorkflow
from utils.openrouter_client import get_openrouter_client


class DefaultWorkflow(BaseWorkflow):
    """Default content processing workflow."""

    async def generate_context_unit(self, source_content: SourceContent) -> Dict[str, Any]:
        """Generate context unit using standard LLM processing.
        
        Args:
            source_content: SourceContent with text_content
            
        Returns:
            Standard context unit
        """
        # Use text_content from SourceContent
        full_text = source_content.text_content
        
        if not full_text.strip():
            self.logger.warn("no_text_content_found", source_id=source_content.source_id)
            return {
                "id": source_content.id,
                "title": source_content.get_display_title(),
                "summary": "No text content found in source",
                "tags": [],
                "atomic_statements": [],
                "raw_text": ""
            }

        # Use OpenRouter client for LLM processing
        openrouter = get_openrouter_client()
        
        # Generate context unit with new structured format
        try:
            # Use generate_context_unit for proper Spanish output and structured statements
            analysis_result = await openrouter.generate_context_unit(
                text=full_text,
                organization_id="00000000-0000-0000-0000-000000000001",
                context_unit_id=source_content.id,
                client_id=None
            )
            
            # Build context unit with structured atomic statements
            context_unit = {
                "id": source_content.id,
                "title": analysis_result.get("title", source_content.get_display_title()),
                "summary": analysis_result.get("summary", ""),
                "tags": analysis_result.get("tags", []),
                "atomic_statements": analysis_result.get("atomic_statements", []),
                "raw_text": full_text
            }
            
        except Exception as e:
            self.logger.warn("llm_analysis_failed", error=str(e))
            # Fallback to basic context unit
            context_unit = {
                "id": source_content.id,
                "title": source_content.get_display_title(),
                "summary": source_content.get_text_preview(300),
                "tags": [],
                "atomic_statements": [],
                "raw_text": full_text
            }
        
        self.logger.info(
            "context_unit_generated",
            company_code=self.company_code,
            title=context_unit.get("title", ""),
            summary_length=len(context_unit.get("summary", "")),
            word_count=source_content.get_word_count()
        )

        return context_unit