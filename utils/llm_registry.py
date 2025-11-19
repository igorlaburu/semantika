"""Central registry for all LLM providers and models."""

from typing import Dict, Optional
from utils.providers.openrouter_provider import OpenRouterProvider
from utils.providers.groq_provider import GroqProvider
from utils.providers.groq_compound_provider import GroqCompoundProvider
from utils.config import settings
from utils.logger import get_logger

logger = get_logger("llm_registry")


class LLMRegistry:
    """Registry for managing all LLM instances."""
    
    def __init__(self):
        """Initialize registry with all configured models."""
        self._providers: Dict[str, any] = {}
        self._initialize_providers()
    
    def _initialize_providers(self):
        """Initialize all LLM providers."""
        
        # OpenRouter models
        self._providers['sonnet_premium'] = OpenRouterProvider(
            model_name='anthropic/claude-sonnet-4.5',
            model_alias='sonnet_premium',
            temperature=0.0
        )
        
        self._providers['fast'] = OpenRouterProvider(
            model_name='openai/gpt-4o-mini',
            model_alias='fast',
            temperature=0.0
        )
        
        # Groq models
        if settings.groq_api_key:
            self._providers['groq_fast'] = GroqProvider(
                model_name='llama-3.3-70b-versatile',
                model_alias='groq_fast',
                temperature=0.1
            )

            self._providers['groq_writer'] = GroqProvider(
                model_name='openai/gpt-oss-20b',
                model_alias='groq_writer',
                temperature=0.0
            )

            self._providers['groq_compound'] = GroqCompoundProvider(
                model_name='groq/compound',
                model_alias='groq_compound'
            )

        logger.info("llm_registry_initialized",
            models=list(self._providers.keys())
        )
    
    def get(self, alias: str):
        """Get LLM provider by alias.
        
        Args:
            alias: Model alias (e.g., 'sonnet_premium', 'groq_fast')
            
        Returns:
            LLM provider instance
            
        Raises:
            ValueError: If alias not found
        """
        if alias not in self._providers:
            logger.error("model_not_found", alias=alias, available=list(self._providers.keys()))
            raise ValueError(
                f"Model '{alias}' not found. Available: {list(self._providers.keys())}"
            )
        
        return self._providers[alias]
    
    def list_models(self) -> list:
        """List all available model aliases.
        
        Returns:
            List of model aliases
        """
        return list(self._providers.keys())


# Global registry instance
_registry: Optional[LLMRegistry] = None


def get_llm_registry() -> LLMRegistry:
    """Get global LLM registry instance.
    
    Returns:
        LLMRegistry singleton
    """
    global _registry
    if _registry is None:
        _registry = LLMRegistry()
    return _registry
