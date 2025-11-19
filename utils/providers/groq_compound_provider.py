"""Groq Compound provider for web search-enabled LLM calls.

Groq Compound is a special model that automatically performs web searches
when needed, using Tavily search API. It's billed separately:
- Base model tokens (Llama 3.3 70B or similar)
- Web search requests ($0.005-$0.008 per request)
"""

from typing import Optional, Dict
from groq import AsyncGroq

from utils.llm_provider import LLMProvider, UsageInfo
from utils.config import settings
from utils.logger import get_logger

logger = get_logger("groq_compound_provider")


class GroqCompoundProvider(LLMProvider):
    """Groq Compound provider using AsyncGroq for web search."""

    def __init__(self, model_name: str = "groq/compound", model_alias: str = "groq_compound"):
        """Initialize Groq Compound provider.

        Args:
            model_name: Full model name (default: 'groq/compound')
            model_alias: Friendly alias (default: 'groq_compound')
        """
        super().__init__(model_name, model_alias)

        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY not configured")

        # Use AsyncGroq (native Groq client, not LangChain)
        # No timeout - let Groq take as long as needed for web search
        # (web searches can take longer than 60s)
        self._client = AsyncGroq(
            api_key=settings.groq_api_key
        )

        logger.debug("groq_compound_provider_initialized",
            model=model_name,
            alias=model_alias,
            timeout=60.0
        )

    def get_provider_name(self) -> str:
        """Return provider name."""
        return "groq"

    def get_runnable(self):
        """Get underlying client.

        Note: Groq Compound uses AsyncGroq, not LangChain runnable.
        This method is here for interface compatibility but shouldn't
        be used in chains.

        Returns:
            AsyncGroq instance
        """
        logger.warn("groq_compound_get_runnable_called",
            message="Groq Compound cannot be used in LangChain chains"
        )
        return self._client

    async def ainvoke(self, messages, config: Optional[Dict] = None):
        """Invoke Groq Compound LLM with web search.

        Args:
            messages: List of message dicts [{"role": "system", "content": "..."}, ...]
            config: Optional config with 'tracking' key

        Returns:
            Groq API response object
        """
        config = config or {}
        tracking_config = config.pop('tracking', None)

        # Load model info for cost calculation
        await self._load_model_info()

        # Call Groq Compound
        # Web search is automatic - no tools array needed
        response = await self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=config.get('temperature', 0.0)
        )

        # Extract and track usage
        if tracking_config:
            usage = self._extract_usage(response)
            if usage:
                # Web search cost: average between basic ($0.005) and advanced ($0.008)
                search_cost = tracking_config.get('web_search_cost', 0.0065)

                # Calculate total cost (model tokens + web search)
                actual_total = usage.cost_usd + search_cost

                # Track search cost separately in metadata
                tracking_config.setdefault('metadata', {})
                tracking_config['metadata']['web_search_cost'] = search_cost
                tracking_config['metadata']['model_tokens_cost'] = usage.cost_usd
                tracking_config['metadata']['total_cost_with_search'] = actual_total

                await self._track_usage(usage, tracking_config)

        return response

    def _extract_usage(self, response) -> Optional[UsageInfo]:
        """Extract token usage from Groq response.

        Args:
            response: Groq API response object

        Returns:
            UsageInfo if extraction successful, None otherwise
        """
        if not hasattr(response, 'usage') or not response.usage:
            logger.warn("no_usage_in_response",
                model=self.model_name
            )
            return None

        usage = response.usage

        # Groq native API uses prompt_tokens, completion_tokens
        prompt_tokens = getattr(usage, 'prompt_tokens', 0)
        completion_tokens = getattr(usage, 'completion_tokens', 0)
        total_tokens = getattr(usage, 'total_tokens', prompt_tokens + completion_tokens)

        # Calculate cost (model tokens only, web search cost tracked separately)
        cost_usd = self._calculate_cost(prompt_tokens, completion_tokens)

        return UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd
        )
