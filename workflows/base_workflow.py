"""Base workflow class for processing content.

All company-specific workflows inherit from BaseWorkflow.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from core.source_content import SourceContent
from utils.logger import get_logger


class BaseWorkflow(ABC):
    """Base class for content processing workflows."""

    def __init__(self, company_code: str, company_settings: Optional[Dict[str, Any]] = None):
        """Initialize workflow.
        
        Args:
            company_code: Company identifier (e.g., "default", "acme")
            company_settings: Company settings from database
        """
        self.company_code = company_code
        self.company_settings = company_settings or {}
        self.logger = get_logger(f"workflow.{company_code}")

    async def process_content(self, source_content: SourceContent) -> Dict[str, Any]:
        """Main processing pipeline.
        
        Args:
            source_content: Content from any source
            
        Returns:
            Processed content with context unit and additional data
        """
        self.logger.info(
            "workflow_processing_start",
            company_code=self.company_code,
            source_type=source_content.source_type,
            source_id=source_content.source_id
        )

        try:
            # Step 1: Generate context unit (can be overridden)
            context_unit = await self.generate_context_unit(source_content)
            
            # Step 2: Additional analysis (can be overridden)
            analysis = await self.analyze_content(source_content, context_unit)
            
            # Step 3: Custom processing (implemented by subclasses)
            custom_data = await self.custom_processing(source_content, context_unit, analysis)

            result = {
                "context_unit": context_unit,
                "analysis": analysis,
                "custom_data": custom_data,
                "company_code": self.company_code
            }

            self.logger.info(
                "workflow_processing_completed",
                company_code=self.company_code,
                context_unit_id=context_unit.get("id")
            )

            return result

        except Exception as e:
            self.logger.error(
                "workflow_processing_error",
                company_code=self.company_code,
                error=str(e)
            )
            raise

    @abstractmethod
    async def generate_context_unit(self, source_content: SourceContent) -> Dict[str, Any]:
        """Generate context unit from source content.
        
        This is the core LLM operation that can be customized per company.
        
        Args:
            source_content: Raw content from source
            
        Returns:
            Context unit with title, summary, tags, atomic_statements
        """
        pass

    async def analyze_content(self, source_content: SourceContent, context_unit: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze content for additional insights.
        
        Override this for company-specific analysis (legal, financial, etc.)
        
        Args:
            source_content: Original content
            context_unit: Generated context unit
            
        Returns:
            Analysis results
        """
        # Default: No additional analysis
        return {
            "sentiment": "neutral",
            "confidence": 1.0,
            "flags": []
        }

    async def custom_processing(
        self, 
        source_content: SourceContent, 
        context_unit: Dict[str, Any], 
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Custom processing logic per company.
        
        Override this for company-specific workflows.
        
        Args:
            source_content: Original content
            context_unit: Generated context unit
            analysis: Analysis results
            
        Returns:
            Custom processing results
        """
        # Default: No custom processing
        return {}

    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration for this company.
        
        Returns:
            LLM settings (model, temperature, etc.)
        """
        return {
            "model": self.company_settings.get("llm_model", "openai/gpt-4o-mini"),
            "temperature": self.company_settings.get("llm_temperature", 0.0),
            "max_tokens": self.company_settings.get("llm_max_tokens", 4000)
        }

    def should_store_in_qdrant(self) -> bool:
        """Check if content should be stored in Qdrant."""
        return self.company_settings.get("store_in_qdrant", True)

    def get_data_ttl_days(self) -> int:
        """Get data TTL for this company."""
        return self.company_settings.get("data_ttl_days", 30)