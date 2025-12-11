"""EMBEDDING GENERATOR - Generación de vectores 768d para búsqueda semántica.

¿QUÉ HACE?
-----------
Genera embeddings (vectores) de 768 dimensiones para contenido de texto usando
FastEmbed multilingual local. Si falla, usa OpenAI como fallback.

¿CÓMO FUNCIONA?
---------------
1. Primary: FastEmbed (local, gratis, 768d)
   - Modelo: paraphrase-multilingual-mpnet-base-v2
   - Idiomas: 50+ incluyendo español y euskera
   - Velocidad: ~100-200ms/embedding
   - Costo: $0.00

2. Fallback: OpenAI text-embedding-3-small (API, pago, 384d)
   - Solo si FastEmbed falla
   - Truncado de 1536d a 384d
   - Costo: ~$0.02 per 1M tokens

¿QUÉ SE EMBEDDEA?
-----------------
Combina title + summary en un solo texto:
  "Título del artículo. Resumen del contenido..."

¿CUÁNDO SE USA?
---------------
- En unified_context_ingester (al guardar context unit)
- En context_unit_saver (scraping workflow)
- En url_content_units (multi-noticia)
- Para deduplicación semántica (threshold 0.98)
- Para búsqueda por vector (/search endpoint)

¿POR QUÉ IMPORTANTE?
--------------------
- ✅ Búsqueda semántica precisa (entiende significado, no solo palabras)
- ✅ Deduplicación automática (detecta contenido similar)
- ✅ Gratis y local (FastEmbed sin API calls)
- ✅ Optimizado para español/euskera (multilingüe)

EJEMPLO DE USO:
---------------
embedding = await generate_embedding(
    title="Nuevo metro en Bilbao",
    summary="La Diputación aprueba fondos...",
    company_id="uuid-123"
)
# Returns: [0.123, -0.456, 0.789, ...] (768 floats)
"""

from typing import List, Optional, Dict, Any
import asyncio
from functools import lru_cache

from .config import settings
from .logger import get_logger

logger = get_logger("embedding_generator")

# Global FastEmbed model instance
_fastembed_model = None


def get_fastembed_model():
    """Get or initialize FastEmbed model (lazy loading)."""
    global _fastembed_model

    if _fastembed_model is None:
        try:
            from fastembed import TextEmbedding
            import os

            # Multilingual model for better Spanish/Basque support
            # sentence-transformers/paraphrase-multilingual-mpnet-base-v2
            # 768 dimensions - Optimized for 50+ languages
            cache_dir = os.getenv("FASTEMBED_CACHE_PATH", None)
            _fastembed_model = TextEmbedding(
                model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                cache_dir=cache_dir
            )

            logger.info("fastembed_initialized",
                model="paraphrase-multilingual-mpnet-base-v2",
                dimensions=768,
                languages="50+ (including Spanish and Basque)"
            )
        except Exception as e:
            logger.error("fastembed_initialization_failed", error=str(e))
            raise

    return _fastembed_model


async def generate_embedding_fastembed(text: str) -> List[float]:
    """Generate embedding using local FastEmbed.

    Args:
        text: Text to embed (title + summary recommended)

    Returns:
        768-dimensional embedding vector (multilingual model)

    Raises:
        Exception: If embedding generation fails
    """
    try:
        model = get_fastembed_model()
        
        # FastEmbed is sync, run in thread pool
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: list(model.embed([text[:512]]))  # Limit to 512 chars
        )
        
        embedding = embeddings[0].tolist()
        
        logger.debug("fastembed_embedding_generated", 
            text_length=len(text),
            embedding_dim=len(embedding)
        )
        
        return embedding
        
    except Exception as e:
        logger.error("fastembed_embedding_error", error=str(e), text_preview=text[:100])
        raise


async def generate_embedding_openai(text: str) -> List[float]:
    """Generate embedding using OpenAI API (legacy fallback - not recommended).
    
    Args:
        text: Text to embed
        
    Returns:
        384-dimensional embedding vector (truncated from 1536)
        
    Raises:
        Exception: If embedding generation fails
    """
    try:
        import openai
        
        if not settings.openrouter_api_key:
            raise ValueError("OpenRouter API key not configured")
        
        client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key
        )
        
        response = await client.embeddings.create(
            model="openai/text-embedding-3-small",  # 1536 dims, $0.02/1M tokens
            input=text[:8000]
        )
        
        # OpenAI returns 1536 dims, truncate to 384 for consistency
        full_embedding = response.data[0].embedding
        embedding = full_embedding[:384]
        
        logger.debug("openai_embedding_generated",
            text_length=len(text),
            embedding_dim=len(embedding),
            truncated_from=len(full_embedding)
        )
        
        return embedding
        
    except Exception as e:
        logger.error("openai_embedding_error", error=str(e), text_preview=text[:100])
        raise


async def generate_embedding(
    title: str,
    summary: Optional[str] = None,
    force_openai: bool = False,
    company_id: Optional[str] = None,
    context_unit_id: Optional[str] = None
) -> List[float]:
    """Generate embedding for content (title + summary).

    Strategy:
    1. Use FastEmbed multilingual model (local, free, optimized for Spanish/Basque)
    2. Fallback to OpenAI only if FastEmbed fails (rare)

    Args:
        title: Content title
        summary: Content summary (optional)
        force_openai: Force use of OpenAI API (not recommended)
        company_id: Company UUID for logging
        context_unit_id: Context unit UUID for logging

    Returns:
        768-dimensional embedding vector

    Raises:
        Exception: If all methods fail
    """
    # Combine title + summary (optimal balance)
    text_parts = [title]
    if summary:
        text_parts.append(summary)
    text = " | ".join(text_parts)
    
    logger.debug("generate_embedding_start",
        company_id=company_id,
        context_unit_id=context_unit_id,
        text_length=len(text),
        force_openai=force_openai
    )
    
    # Try OpenAI first if explicitly forced (not recommended)
    if force_openai:
        try:
            embedding = await generate_embedding_openai(text)
            logger.warn("openai_forced_used",
                company_id=company_id,
                context_unit_id=context_unit_id,
                dimensions=len(embedding),
                message="Using OpenAI instead of local multilingual model"
            )
            return embedding
        except Exception as e:
            logger.warn("openai_forced_but_failed", error=str(e))
            # Fall through to FastEmbed

    # Use FastEmbed multilingual model (primary method)
    try:
        embedding = await generate_embedding_fastembed(text)
        logger.info("embedding_generated",
            company_id=company_id,
            context_unit_id=context_unit_id,
            method="fastembed_multilingual",
            dimensions=len(embedding)
        )
        return embedding

    except Exception as fastembed_error:
        logger.error("fastembed_failed", error=str(fastembed_error))

        # Fallback to OpenAI via OpenRouter (rare, only if FastEmbed fails)
        if settings.openrouter_api_key:
            logger.warn("falling_back_to_openai",
                message="FastEmbed failed, using OpenAI fallback"
            )
            try:
                embedding = await generate_embedding_openai(text)
                logger.info("embedding_generated",
                    company_id=company_id,
                    context_unit_id=context_unit_id,
                    method="openai_fallback",
                    dimensions=len(embedding)
                )
                return embedding
            except Exception as openai_error:
                logger.error("all_embedding_methods_failed",
                    fastembed_error=str(fastembed_error),
                    openai_error=str(openai_error)
                )
                raise
        else:
            logger.error("fastembed_failed_no_openai_fallback", error=str(fastembed_error))
            raise


async def generate_embeddings_batch(
    items: List[Dict[str, str]],
    force_openai: bool = False
) -> List[List[float]]:
    """Generate embeddings for multiple items in batch.

    Args:
        items: List of dicts with 'title' and optional 'summary'
        force_openai: Force use of OpenAI API (not recommended)

    Returns:
        List of 768-dimensional embedding vectors
    """
    logger.debug("batch_embedding_start", count=len(items), force_openai=force_openai)
    
    # Generate embeddings concurrently
    tasks = [
        generate_embedding(
            title=item.get("title", ""),
            summary=item.get("summary"),
            force_openai=force_openai
        )
        for item in items
    ]
    
    embeddings = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out failed embeddings
    valid_embeddings = []
    failed_count = 0
    
    for i, emb in enumerate(embeddings):
        if isinstance(emb, Exception):
            logger.error("batch_embedding_item_failed", 
                index=i, 
                title=items[i].get("title", "")[:50],
                error=str(emb)
            )
            failed_count += 1
            valid_embeddings.append([0.0] * 768)  # Zero vector for failed items
        else:
            valid_embeddings.append(emb)
    
    logger.info("batch_embedding_completed",
        total=len(items),
        successful=len(items) - failed_count,
        failed=failed_count
    )
    
    return valid_embeddings


def cosine_similarity(embedding1: List[float], embedding2: List[float]) -> float:
    """Calculate cosine similarity between two embeddings.
    
    Args:
        embedding1: First embedding vector
        embedding2: Second embedding vector
        
    Returns:
        Similarity score (0.0 to 1.0)
    """
    import math
    
    # Dot product
    dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
    
    # Magnitudes
    magnitude1 = math.sqrt(sum(a * a for a in embedding1))
    magnitude2 = math.sqrt(sum(b * b for b in embedding2))
    
    # Cosine similarity
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    
    return dot_product / (magnitude1 * magnitude2)


async def find_similar_embeddings(
    query_embedding: List[float],
    candidate_embeddings: List[List[float]],
    threshold: float = 0.95
) -> List[int]:
    """Find indices of embeddings similar to query.
    
    Args:
        query_embedding: Query embedding vector
        candidate_embeddings: List of candidate embeddings
        threshold: Minimum similarity score (0.0-1.0)
        
    Returns:
        List of indices of similar embeddings
    """
    similar_indices = []
    
    for i, candidate in enumerate(candidate_embeddings):
        similarity = cosine_similarity(query_embedding, candidate)
        if similarity >= threshold:
            similar_indices.append(i)
            logger.debug("similar_embedding_found", 
                index=i, 
                similarity=round(similarity, 4)
            )
    
    logger.info("similarity_search_completed",
        candidates=len(candidate_embeddings),
        matches=len(similar_indices),
        threshold=threshold
    )
    
    return similar_indices


# Convenience functions for common use cases

async def generate_context_unit_embedding(
    context_unit: Dict[str, Any],
    force_openai: bool = False
) -> List[float]:
    """Generate embedding for a context unit.

    Args:
        context_unit: Dict with 'title', 'summary', 'id', 'company_id'
        force_openai: Force use of OpenAI API (not recommended)

    Returns:
        768-dimensional embedding vector
    """
    return await generate_embedding(
        title=context_unit.get("title", ""),
        summary=context_unit.get("summary"),
        force_openai=force_openai,
        company_id=context_unit.get("company_id"),
        context_unit_id=context_unit.get("id")
    )


async def generate_url_content_embedding(
    url_content: Dict[str, Any],
    force_openai: bool = False
) -> List[float]:
    """Generate embedding for a URL content unit.

    Args:
        url_content: Dict with 'title', 'summary', 'id', 'company_id'
        force_openai: Force use of OpenAI API (not recommended)

    Returns:
        768-dimensional embedding vector
    """
    return await generate_embedding(
        title=url_content.get("title", ""),
        summary=url_content.get("summary"),
        force_openai=force_openai,
        company_id=url_content.get("company_id"),
        context_unit_id=url_content.get("id")
    )
