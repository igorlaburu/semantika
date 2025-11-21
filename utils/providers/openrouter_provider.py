"""OpenRouter LLM provider implementation."""

from typing import Optional, Dict
from langchain_openai import ChatOpenAI

from utils.llm_provider import LLMProvider, UsageInfo
from utils.config import settings
from utils.logger import get_logger

logger = get_logger("openrouter_provider")


class OpenRouterProvider(LLMProvider):
    """OpenRouter provider using ChatOpenAI."""
    
    def __init__(self, model_name: str, model_alias: str, temperature: float = 0.0):
        """Initialize OpenRouter provider.
        
        Args:
            model_name: Full model name (e.g., 'anthropic/claude-3.5-sonnet-20241022')
            model_alias: Friendly alias (e.g., 'sonnet_premium')
            temperature: Model temperature (default: 0.0)
        """
        super().__init__(model_name, model_alias)
        
        self._client = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            max_tokens=8192,  # Limit output tokens to avoid credit exhaustion
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/semantika",
                "X-Title": "semantika"
            }
        )
        
        logger.debug("openrouter_provider_initialized",
            model=model_name,
            alias=model_alias,
            temperature=temperature
        )
    
    def get_provider_name(self) -> str:
        """Return provider name."""
        return "openrouter"
    
    def get_runnable(self):
        """Get underlying LangChain runnable for use in chains.
        
        Returns:
            ChatOpenAI instance that can be used in RunnableSequence
        """
        return self._client
    
    async def ainvoke(self, messages, config: Optional[Dict] = None):
        """Invoke OpenRouter LLM.
        
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
        """Extract token usage from OpenRouter response.
        
        Args:
            response: LLM response object
            
        Returns:
            UsageInfo if extraction successful, None otherwise
        """
        usage = None
        
        # Try usage_metadata (LangChain v0.1+)
        if hasattr(response, 'usage_metadata'):
            usage_meta = response.usage_metadata
            
            # Dict format
            if isinstance(usage_meta, dict) and 'input_tokens' in usage_meta:
                usage = {
                    'prompt_tokens': usage_meta['input_tokens'],
                    'completion_tokens': usage_meta['output_tokens'],
                    'total_tokens': usage_meta['total_tokens']
                }
            # Object format
            elif hasattr(usage_meta, 'input_tokens'):
                usage = {
                    'prompt_tokens': usage_meta.input_tokens,
                    'completion_tokens': usage_meta.output_tokens,
                    'total_tokens': usage_meta.total_tokens
                }
        
        # Try response_metadata
        elif hasattr(response, 'response_metadata'):
            response_meta = response.response_metadata
            for key in ['token_usage', 'usage', 'token_count', 'tokens']:
                if key in response_meta:
                    usage = response_meta[key]
                    break
        
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
