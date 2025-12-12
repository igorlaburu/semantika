"""Base LLM Provider interface for extensible LLM integration.

This module provides:
- Abstract base class for all LLM providers
- Consistent interface across OpenRouter, Groq, and future providers
- Automatic usage tracking with cost calculation
- Model pricing from database
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.usage_tracker import get_usage_tracker

logger = get_logger("llm_provider")


@dataclass
class ModelInfo:
    """Model information and pricing."""
    provider: str
    model_name: str
    model_alias: str
    price_input_per_mtok: float
    price_output_per_mtok: float
    context_window: int
    max_output_tokens: int
    pricing_id: str


@dataclass
class UsageInfo:
    """Token usage information from LLM response."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


class LLMProvider(ABC):
    """Base class for all LLM providers.
    
    Implements:
    - Consistent interface across providers
    - Automatic usage tracking
    - Cost calculation from database pricing
    - Error handling
    
    Usage:
        provider = SomeProvider(model_name="...", model_alias="...")
        response = await provider.ainvoke(
            messages,
            config={'tracking': {'organization_id': '...', 'operation': '...'}}
        )
    """
    
    def __init__(self, model_name: str, model_alias: str):
        """Initialize provider.
        
        Args:
            model_name: Full model identifier (e.g., 'mixtral-8x7b-32768')
            model_alias: Friendly alias (e.g., 'groq_fast')
        """
        self.model_name = model_name
        self.model_alias = model_alias
        self._model_info: Optional[ModelInfo] = None
        self._client = None  # LangChain client instance
    
    async def _load_model_info(self) -> ModelInfo:
        """Load model pricing from database.
        
        Returns:
            ModelInfo with pricing data
            
        Raises:
            ValueError: If pricing not found in database
        """
        if self._model_info:
            return self._model_info
        
        supabase = get_supabase_client()
        
        # Get active pricing for this model
        response = supabase.client.table("llm_model_pricing")\
            .select("*")\
            .eq("provider", self.get_provider_name())\
            .eq("model_name", self.model_name)\
            .eq("is_active", True)\
            .is_("effective_until", "null")\
            .limit(1)\
            .execute()
        
        if not response.data:
            logger.error("model_pricing_not_found_using_defaults",
                provider=self.get_provider_name(),
                model=self.model_name,
                message="Pricing not found in DB, using default values (cost tracking disabled)"
            )
            
            # Use default pricing instead of failing
            # Cost tracking will be disabled but LLM will work
            self._model_info = ModelInfo(
                provider=self.get_provider_name(),
                model_name=self.model_name,
                model_alias=self.model_alias or "Unknown",
                price_input_per_mtok=0.0,  # Default: free (no tracking)
                price_output_per_mtok=0.0,  # Default: free (no tracking)
                context_window=0,
                max_output_tokens=0,
                pricing_id=None
            )
        else:
            pricing = response.data[0]
            
            self._model_info = ModelInfo(
                provider=pricing['provider'],
                model_name=pricing['model_name'],
                model_alias=pricing['model_alias'] or self.model_alias,
                price_input_per_mtok=float(pricing['price_input_per_mtok']),
                price_output_per_mtok=float(pricing['price_output_per_mtok']),
                context_window=pricing['context_window'] or 0,
                max_output_tokens=pricing['max_output_tokens'] or 0,
                pricing_id=pricing['id']
            )
        
        logger.debug("model_info_loaded",
            model=self.model_name,
            alias=self.model_alias,
            input_price=self._model_info.price_input_per_mtok,
            output_price=self._model_info.price_output_per_mtok
        )
        
        return self._model_info
    
    def _calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost in USD for token usage.
        
        Args:
            prompt_tokens: Number of input tokens
            completion_tokens: Number of output tokens
            
        Returns:
            Total cost in USD
        """
        if not self._model_info:
            return 0.0
        
        input_cost = (prompt_tokens / 1_000_000) * self._model_info.price_input_per_mtok
        output_cost = (completion_tokens / 1_000_000) * self._model_info.price_output_per_mtok
        
        return round(input_cost + output_cost, 6)
    
    async def _track_usage(
        self,
        usage: UsageInfo,
        tracking_config: Dict[str, Any]
    ):
        """Track usage in database.
        
        Args:
            usage: UsageInfo with token counts and cost
            tracking_config: Dict with company_id or organization_id, operation, etc.
        """
        # Support both company_id (new) and organization_id (legacy)
        company_id = tracking_config.get('company_id') or tracking_config.get('organization_id')
        
        if not company_id:
            logger.warn("no_company_for_tracking", 
                model=self.model_name,
                tracking_config=tracking_config
            )
            return
        
        tracker = get_usage_tracker()
        
        # Build metadata with cost and pricing info
        metadata = {
            'provider': self.get_provider_name(),
            'model_alias': self.model_alias,
            'cost_usd': usage.cost_usd,
            'pricing_id': self._model_info.pricing_id if self._model_info else None
        }
        
        await tracker.track(
            company_id=company_id,
            model=f"{self.get_provider_name()}/{self.model_name}",
            operation=tracking_config.get('operation', 'unknown'),
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            client_id=tracking_config.get('client_id'),
            context_unit_id=tracking_config.get('context_unit_id'),
            metadata=metadata
        )
        
        logger.debug("usage_tracked",
            model=self.model_name,
            provider=self.get_provider_name(),
            tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
            company_id=company_id
        )
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Return provider name (e.g., 'openrouter', 'groq').
        
        Returns:
            Provider identifier string
        """
        pass
    
    @abstractmethod
    async def ainvoke(self, messages, config: Optional[Dict] = None):
        """Invoke LLM with messages.
        
        Args:
            messages: LangChain messages or prompt
            config: Optional config dict with 'tracking' key
            
        Returns:
            LLM response
        """
        pass
    
    @abstractmethod
    def _extract_usage(self, response) -> Optional[UsageInfo]:
        """Extract token usage from provider-specific response.
        
        Args:
            response: LLM response object
            
        Returns:
            UsageInfo if extraction successful, None otherwise
        """
        pass
