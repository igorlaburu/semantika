"""Discovery search providers: Groq Compound vs Tavily + OpenAI o1-mini.

Providers:
1. groq_compound: Uses Groq's Compound model with integrated web search (free but rate limited)
2. tavily_openai: Uses Tavily Search API + OpenAI o1-mini for analysis (paid but reliable)

Switch between providers via DISCOVERY_SEARCH_PROVIDER env var.
"""

from typing import Dict, Any, Optional, List
from utils.logger import get_logger
from utils.config import settings

logger = get_logger("discovery_search")


async def search_original_source_groq(headline: str, snippet: str) -> Optional[str]:
    """Search for original news source using Groq Compound (legacy).
    
    Args:
        headline: News headline
        snippet: News snippet/description
        
    Returns:
        Original source URL or None
    """
    from groq import AsyncGroq
    
    client = AsyncGroq(api_key=settings.groq_api_key)
    
    prompt = f"""Busca la fuente original de esta noticia:

Titular: {headline}
Resumen: {snippet}

Encuentra el sitio web institucional o medio local que publicó originalmente esta noticia.
Devuelve SOLO la URL del sitio raíz (ejemplo: https://ayuntamiento.vitoria.es o https://elnortedecastilla.es).
Si no encuentras fuente, responde "NO_ENCONTRADO"."""

    try:
        response = await client.chat.completions.create(
            model="llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200
        )
        
        result = response.choices[0].message.content.strip()
        
        if "NO_ENCONTRADO" in result or not result.startswith("http"):
            return None
            
        return result
        
    except Exception as e:
        logger.error("groq_compound_error", 
            headline=headline[:100], 
            error_type=type(e).__name__,
            error=str(e)
        )
        return None


async def search_original_source_tavily(headline: str, snippet: str) -> Optional[str]:
    """Search for original news source using Tavily + OpenAI o1-mini.
    
    Args:
        headline: News headline
        snippet: News snippet/description
        
    Returns:
        Original source URL or None
    """
    import httpx
    import json
    from openai import AsyncOpenAI
    
    # Step 1: Search with Tavily
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": f"{headline} {snippet}",
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_domains": [],
                    "exclude_domains": ["google.com", "facebook.com", "twitter.com", "youtube.com"]
                },
                timeout=10.0
            )
            response.raise_for_status()
            search_results = response.json()
            
        results = search_results.get("results", [])
        
        if not results:
            logger.debug("tavily_no_results", headline=headline[:100])
            return None
            
        logger.debug("tavily_search_success", 
            headline=headline[:100],
            results_count=len(results)
        )
        
    except Exception as e:
        logger.error("tavily_search_error",
            headline=headline[:100],
            error=str(e)
        )
        return None
    
    # Step 2: Analyze with OpenAI o1-mini
    try:
        openai_client = AsyncOpenAI(api_key=settings.openrouter_api_key,
                                     base_url="https://openrouter.ai/api/v1")
        
        # Format search results for LLM
        formatted_results = "\n\n".join([
            f"URL: {r['url']}\nTítulo: {r.get('title', '')}\nContenido: {r.get('content', '')[:200]}"
            for r in results[:5]
        ])
        
        analysis_prompt = f"""Analiza estos resultados de búsqueda y determina la fuente original de la noticia.

NOTICIA BUSCADA:
Titular: {headline}
Resumen: {snippet}

RESULTADOS DE BÚSQUEDA:
{formatted_results}

TAREA:
Identifica el sitio web institucional o medio local que publicó originalmente esta noticia.
Devuelve SOLO la URL del sitio raíz (ejemplo: https://ayuntamiento.vitoria.es).
Si ningún resultado parece la fuente original, responde "NO_ENCONTRADO".

Formato de respuesta: Solo la URL o "NO_ENCONTRADO", nada más."""

        response = await openai_client.chat.completions.create(
            model="openai/o1-mini",
            messages=[{"role": "user", "content": analysis_prompt}],
            max_completion_tokens=200
        )
        
        result = response.choices[0].message.content.strip()
        
        if "NO_ENCONTRADO" in result or not result.startswith("http"):
            logger.debug("o1mini_no_source_found", headline=headline[:100])
            return None
        
        # Extract first URL if there are multiple lines
        url = result.split("\n")[0].strip()
        
        logger.info("tavily_openai_source_found",
            headline=headline[:100],
            source_url=url
        )
        
        return url
        
    except Exception as e:
        logger.error("o1mini_analysis_error",
            headline=headline[:100],
            error=str(e)
        )
        return None


async def search_original_source(headline: str, snippet: str = "") -> Optional[str]:
    """Search for original news source using configured provider.
    
    Routes to either Groq Compound or Tavily + OpenAI based on config.
    
    Args:
        headline: News headline
        snippet: News snippet/description
        
    Returns:
        Original source URL or None
    """
    provider = settings.discovery_search_provider
    
    logger.debug("discovery_search_start",
        provider=provider,
        headline=headline[:100]
    )
    
    if provider == "tavily_openai":
        return await search_original_source_tavily(headline, snippet)
    elif provider == "groq_compound":
        return await search_original_source_groq(headline, snippet)
    else:
        logger.error("unknown_discovery_provider", provider=provider)
        # Fallback to Groq
        return await search_original_source_groq(headline, snippet)
