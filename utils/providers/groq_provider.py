"""Groq LLM provider implementation."""

from typing import Optional, Dict
from langchain_groq import ChatGroq

from utils.llm_provider import LLMProvider, UsageInfo
from utils.config import settings
from utils.logger import get_logger

logger = get_logger("groq_provider")


class GroqProvider(LLMProvider):
    """Groq provider using ChatGroq."""
    
    def __init__(self, model_name: str, model_alias: str, temperature: float = 0.0):
        """Initialize Groq provider.
        
        Args:
            model_name: Full model name (e.g., 'mixtral-8x7b-32768')
            model_alias: Friendly alias (e.g., 'groq_fast')
            temperature: Model temperature (default: 0.0)
        """
        super().__init__(model_name, model_alias)
        
        self._client = ChatGroq(
            model=model_name,
            temperature=temperature,
            groq_api_key=settings.groq_api_key
        )
        
        logger.debug("groq_provider_initialized",
            model=model_name,
            alias=model_alias,
            temperature=temperature
        )
    
    def get_provider_name(self) -> str:
        """Return provider name."""
        return "groq"
    
    def get_runnable(self):
        """Get underlying LangChain runnable for use in chains.
        
        Returns:
            ChatGroq instance that can be used in RunnableSequence
        """
        return self._client
    
    async def ainvoke(self, messages, config: Optional[Dict] = None):
        """Invoke Groq LLM.
        
        Args:
            messages: LangChain messages
            config: Optional config with 'tracking' key
            
        Returns:
            LLM response
        """
        config = config or {}
        tracking_config = config.pop('tracking', None)
        
        # Load model info for cost calculation
        await self._load_model_info()
        
        # Call LLM
        response = await self._client.ainvoke(messages, config)
        
        # Extract and track usage
        if tracking_config:
            usage = self._extract_usage(response)
            if usage:
                await self._track_usage(usage, tracking_config)
        
        return response
    
    def _extract_usage(self, response) -> Optional[UsageInfo]:
        """Extract token usage from Groq response.
        
        Args:
            response: LLM response object
            
        Returns:
            UsageInfo if extraction successful, None otherwise
        """
        usage = None
        
        # Groq uses usage_metadata
        if hasattr(response, 'usage_metadata'):
            usage_meta = response.usage_metadata
            
            # Dict format
            if isinstance(usage_meta, dict):
                usage = {
                    'prompt_tokens': usage_meta.get('input_tokens', 0),
                    'completion_tokens': usage_meta.get('output_tokens', 0),
                    'total_tokens': usage_meta.get('total_tokens', 0)
                }
            # Object format
            elif hasattr(usage_meta, 'input_tokens'):
                usage = {
                    'prompt_tokens': usage_meta.input_tokens,
                    'completion_tokens': usage_meta.output_tokens,
                    'total_tokens': usage_meta.total_tokens
                }
        
        # Try response_metadata as fallback
        elif hasattr(response, 'response_metadata'):
            response_meta = response.response_metadata
            if 'usage' in response_meta:
                usage_dict = response_meta['usage']
                usage = {
                    'prompt_tokens': usage_dict.get('prompt_tokens', 0),
                    'completion_tokens': usage_dict.get('completion_tokens', 0),
                    'total_tokens': usage_dict.get('total_tokens', 0)
                }
        
        if not usage:
            logger.warn("no_usage_found", 
                model=self.model_name,
                response_type=type(response).__name__
            )
            return None
        
        # Calculate cost
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', prompt_tokens + completion_tokens)
        
        cost_usd = self._calculate_cost(prompt_tokens, completion_tokens)
        
        return UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd
        )
