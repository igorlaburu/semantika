"""Universal context unit saver with embedding generation and duplicate detection.

Normalizes saving across all source types:
- scraping (via url_content_units)
- email
- perplexity
- api
- manual

All sources generate embeddings and check for duplicates before saving.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

from .supabase_client import get_supabase_client
from .embedding_generator import generate_embedding, cosine_similarity
from .logger import get_logger
from .source_metadata_schema import normalize_source_metadata

logger = get_logger("context_unit_saver")

# Duplicate detection threshold
DUPLICATE_THRESHOLD = 0.95


async def check_for_duplicates(
    embedding: List[float],
    company_id: str,
    title: str,
    threshold: float = DUPLICATE_THRESHOLD
) -> Optional[Dict[str, Any]]:
    """Check if similar context unit already exists using pgvector similarity.
    
    Args:
        embedding: Embedding vector to check
        company_id: Company UUID
        title: Title for logging
        threshold: Similarity threshold (default 0.95)
        
    Returns:
        Dict with duplicate info if found, None otherwise
    """
    try:
        supabase = get_supabase_client()
        
        # Use pgvector similarity function
        # Note: Supabase Python client doesn't support RPC with vector params directly
        # We need to use raw SQL
        from supabase import Client
        
        # Convert embedding to Postgres array format
        embedding_str = '[' + ','.join(map(str, embedding)) + ']'
        
        result = supabase.client.rpc(
            'match_context_units',
            {
                'query_embedding': embedding_str,
                'company_id_filter': company_id,
                'match_threshold': threshold,
                'match_count': 1
            }
        ).execute()
        
        if result.data and len(result.data) > 0:
            duplicate = result.data[0]
            logger.info("duplicate_detected",
                title=title,
                duplicate_id=duplicate['id'],
                duplicate_title=duplicate.get('title', '')[:50],
                similarity=duplicate['similarity']
            )
            return duplicate
        
        logger.debug("no_duplicates_found", title=title)
        return None
        
    except Exception as e:
        logger.error("duplicate_check_error", error=str(e), title=title)
        # On error, assume no duplicates (safer to have duplicates than miss content)
        return None


async def save_context_unit(
    company_id: str,
    source_id: str,
    title: str,
    summary: Optional[str] = None,
    content: Optional[str] = None,
    tags: Optional[List[str]] = None,
    atomic_statements: Optional[List[Dict[str, Any]]] = None,
    source_type: str = "manual",
    source_metadata: Optional[Dict[str, Any]] = None,
    url_content_unit_id: Optional[str] = None,
    category: Optional[str] = None,
    special_info: bool = False,
    force_save: bool = False,
    check_duplicates: bool = True,
    generate_embedding_flag: bool = True
) -> Dict[str, Any]:
    """Universal function to save context unit with embedding and duplicate detection.
    
    Args:
        company_id: Company UUID
        source_id: Source UUID
        title: Content title
        summary: Content summary
        content: Full content text
        tags: List of tags
        atomic_statements: List of atomic statement dicts
        source_type: Type of source (scraping/email/perplexity/api/manual)
        source_metadata: Additional metadata (URL, email headers, etc.)
        url_content_unit_id: Reference to url_content_unit (for scraping sources)
        special_info: Is this special info (no TTL)
        force_save: Save even if duplicate found
        check_duplicates: Check for duplicates before saving
        generate_embedding_flag: Generate embedding for duplicate detection
        
    Returns:
        Dict with:
        - success: bool
        - context_unit_id: UUID if saved
        - duplicate: bool
        - duplicate_id: UUID if duplicate found
        - error: str if failed
    """
    logger.debug("save_context_unit_start",
        company_id=company_id,
        source_id=source_id,
        title=title[:50],
        source_type=source_type
    )
    
    try:
        supabase = get_supabase_client()
        
        # Generate embedding for duplicate detection and semantic search
        embedding = None
        if generate_embedding_flag:
            try:
                embedding = await generate_embedding(
                    title=title,
                    summary=summary,
                    company_id=company_id
                )
                logger.debug("embedding_generated", title=title[:50])
            except Exception as e:
                logger.error("embedding_generation_failed", 
                    title=title[:50], 
                    error=str(e)
                )
                # Continue without embedding if generation fails
        
        # Check for duplicates if enabled
        if check_duplicates and embedding:
            duplicate = await check_for_duplicates(
                embedding=embedding,
                company_id=company_id,
                title=title
            )
            
            if duplicate and not force_save:
                logger.warn("duplicate_found_skipping_save",
                    title=title[:50],
                    duplicate_id=duplicate['id'],
                    similarity=duplicate['similarity']
                )
                return {
                    "success": False,
                    "context_unit_id": None,
                    "duplicate": True,
                    "duplicate_id": duplicate['id'],
                    "duplicate_title": duplicate.get('title'),
                    "similarity": duplicate['similarity']
                }
        
        # Prepare context unit data
        context_unit_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        context_unit_data = {
            "id": context_unit_id,
            "base_id": context_unit_id,  # Self-reference for base context units
            "company_id": company_id,
            "source_id": source_id,
            "title": title,
            "summary": summary,
            "raw_text": content,
            "tags": tags or [],
            "atomic_statements": atomic_statements or [],
            "source_type": source_type,
            "source_metadata": source_metadata or {},
            "category": category,
            "status": "pending",
            "created_at": now
        }
        
        # Add embedding if generated
        if embedding:
            # Convert to Postgres array format
            context_unit_data["embedding"] = embedding
        
        # Add url_content_unit_id reference if provided (scraping sources)
        if url_content_unit_id:
            context_unit_data["url_content_unit_id"] = url_content_unit_id
        
        # Insert into press_context_units
        result = supabase.client.table("press_context_units").insert(
            context_unit_data
        ).execute()
        
        if result.data and len(result.data) > 0:
            logger.info("context_unit_saved",
                context_unit_id=context_unit_id,
                company_id=company_id,
                source_id=source_id,
                title=title[:50],
                source_type=source_type,
                has_embedding=bool(embedding)
            )
            
            return {
                "success": True,
                "context_unit_id": context_unit_id,
                "duplicate": False,
                "duplicate_id": None
            }
        else:
            logger.error("context_unit_save_failed_no_data",
                title=title[:50]
            )
            return {
                "success": False,
                "context_unit_id": None,
                "duplicate": False,
                "error": "No data returned from insert"
            }
        
    except Exception as e:
        logger.error("context_unit_save_error",
            title=title[:50],
            error=str(e)
        )
        return {
            "success": False,
            "context_unit_id": None,
            "duplicate": False,
            "error": str(e)
        }


async def save_context_units_batch(
    context_units: List[Dict[str, Any]],
    company_id: str,
    source_id: str,
    source_type: str = "manual",
    check_duplicates: bool = True
) -> Dict[str, Any]:
    """Save multiple context units in batch.
    
    Args:
        context_units: List of context unit dicts (title, summary, content, etc.)
        company_id: Company UUID
        source_id: Source UUID
        source_type: Type of source
        check_duplicates: Check for duplicates
        
    Returns:
        Dict with:
        - total: int
        - saved: int
        - duplicates: int
        - errors: int
        - context_unit_ids: List[str]
    """
    logger.info("save_context_units_batch_start",
        company_id=company_id,
        source_id=source_id,
        count=len(context_units)
    )
    
    total = len(context_units)
    saved = 0
    duplicates = 0
    errors = 0
    context_unit_ids = []
    
    # Process each context unit
    for i, cu in enumerate(context_units):
        result = await save_context_unit(
            company_id=company_id,
            source_id=source_id,
            title=cu.get("title", f"Untitled {i+1}"),
            summary=cu.get("summary"),
            content=cu.get("content"),
            tags=cu.get("tags"),
            atomic_statements=cu.get("atomic_statements"),
            source_type=source_type,
            source_metadata=cu.get("source_metadata"),
            special_info=cu.get("special_info", False),
            check_duplicates=check_duplicates
        )
        
        if result["success"]:
            saved += 1
            context_unit_ids.append(result["context_unit_id"])
        elif result["duplicate"]:
            duplicates += 1
        else:
            errors += 1
    
    logger.info("save_context_units_batch_completed",
        company_id=company_id,
        total=total,
        saved=saved,
        duplicates=duplicates,
        errors=errors
    )
    
    return {
        "total": total,
        "saved": saved,
        "duplicates": duplicates,
        "errors": errors,
        "context_unit_ids": context_unit_ids
    }


async def update_context_unit_embedding(
    context_unit_id: str,
    company_id: str
) -> Dict[str, Any]:
    """Update embedding for existing context unit (backfill).
    
    Args:
        context_unit_id: Context unit UUID
        company_id: Company UUID
        
    Returns:
        Dict with success status
    """
    try:
        supabase = get_supabase_client()
        
        # Fetch context unit
        result = supabase.client.table("press_context_units").select(
            "id, title, summary, embedding"
        ).eq("id", context_unit_id).eq("company_id", company_id).execute()
        
        if not result.data or len(result.data) == 0:
            logger.error("context_unit_not_found", context_unit_id=context_unit_id)
            return {"success": False, "error": "Context unit not found"}
        
        cu = result.data[0]
        
        # Check if already has embedding
        if cu.get("embedding"):
            logger.debug("context_unit_already_has_embedding", 
                context_unit_id=context_unit_id
            )
            return {"success": True, "skipped": True}
        
        # Generate embedding
        embedding = await generate_embedding(
            title=cu["title"],
            summary=cu.get("summary"),
            company_id=company_id,
            context_unit_id=context_unit_id
        )
        
        # Update context unit
        update_result = supabase.client.table("press_context_units").update({
            "embedding": embedding
        }).eq("id", context_unit_id).execute()
        
        if update_result.data:
            logger.info("context_unit_embedding_updated",
                context_unit_id=context_unit_id
            )
            return {"success": True, "skipped": False}
        else:
            logger.error("context_unit_embedding_update_failed",
                context_unit_id=context_unit_id
            )
            return {"success": False, "error": "Update failed"}
        
    except Exception as e:
        logger.error("update_context_unit_embedding_error",
            context_unit_id=context_unit_id,
            error=str(e)
        )
        return {"success": False, "error": str(e)}


async def backfill_embeddings(
    company_id: str,
    limit: int = 100
) -> Dict[str, Any]:
    """Backfill embeddings for context units without embeddings.
    
    Args:
        company_id: Company UUID
        limit: Maximum number to backfill
        
    Returns:
        Dict with stats
    """
    logger.info("backfill_embeddings_start", company_id=company_id, limit=limit)
    
    try:
        supabase = get_supabase_client()
        
        # Find context units without embeddings
        result = supabase.client.table("press_context_units").select(
            "id, title, summary"
        ).eq("company_id", company_id).is_(
            "embedding", "null"
        ).limit(limit).execute()
        
        if not result.data:
            logger.info("no_context_units_need_embeddings", company_id=company_id)
            return {"total": 0, "updated": 0, "errors": 0}
        
        total = len(result.data)
        updated = 0
        errors = 0
        
        for cu in result.data:
            result = await update_context_unit_embedding(
                context_unit_id=cu["id"],
                company_id=company_id
            )
            
            if result["success"] and not result.get("skipped"):
                updated += 1
            elif not result["success"]:
                errors += 1
        
        logger.info("backfill_embeddings_completed",
            company_id=company_id,
            total=total,
            updated=updated,
            errors=errors
        )
        
        return {
            "total": total,
            "updated": updated,
            "errors": errors
        }
        
    except Exception as e:
        logger.error("backfill_embeddings_error",
            company_id=company_id,
            error=str(e)
        )
        return {"total": 0, "updated": 0, "errors": 0, "error": str(e)}


# Convenience functions for specific source types

async def save_from_email(
    company_id: str,
    source_id: str,
    email_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Save context unit from email source.
    
    Args:
        company_id: Company UUID
        source_id: Source UUID
        email_data: Dict with email content (subject, body, attachments, etc.)
        
    Returns:
        Save result
    """
    return await save_context_unit(
        company_id=company_id,
        source_id=source_id,
        title=email_data.get("subject", "Email sin asunto"),
        summary=email_data.get("body_preview"),
        content=email_data.get("body"),
        source_type="email",
        source_metadata={
            "from": email_data.get("from"),
            "to": email_data.get("to"),
            "date": email_data.get("date"),
            "has_attachments": bool(email_data.get("attachments"))
        }
    )


async def save_from_perplexity(
    company_id: str,
    source_id: str,
    perplexity_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Save context unit from Perplexity source.
    
    Args:
        company_id: Company UUID
        source_id: Source UUID
        perplexity_data: Dict with Perplexity response
        
    Returns:
        Save result
    """
    return await save_context_unit(
        company_id=company_id,
        source_id=source_id,
        title=perplexity_data.get("title", "Perplexity News"),
        summary=perplexity_data.get("summary"),
        content=perplexity_data.get("content"),
        tags=perplexity_data.get("tags"),
        source_type="perplexity",
        source_metadata={
            "query": perplexity_data.get("query"),
            "sources": perplexity_data.get("sources", [])
        }
    )


async def save_from_scraping(
    company_id: str,
    source_id: str,
    url_content_unit_id: str,
    scraping_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Save context unit from scraping source.

    Args:
        company_id: Company UUID
        source_id: Source UUID
        url_content_unit_id: URL content unit UUID (for traceability)
        scraping_data: Dict with scraped content

    Returns:
        Save result
    """
    # Extract source_name from URL
    source_name = None
    url = scraping_data.get("url")
    if url:
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            source_name = domain.replace("www.", "").split(".")[0].upper()
        except:
            pass
    
    # Normalize metadata to standard schema
    metadata = normalize_source_metadata(
        url=url,
        source_name=source_name,
        published_at=scraping_data.get("published_at"),
        scraped_at=scraping_data.get("scraped_at"),
        connector_type="scraping",
        featured_image=scraping_data.get("featured_image"),
        connector_specific={}
    )
    
    return await save_context_unit(
        company_id=company_id,
        source_id=source_id,
        title=scraping_data.get("title", "Untitled"),
        summary=scraping_data.get("summary"),
        content=scraping_data.get("content"),
        tags=scraping_data.get("tags"),
        atomic_statements=scraping_data.get("atomic_statements"),
        category=scraping_data.get("category"),
        source_type="scraping",
        source_metadata=metadata,
        url_content_unit_id=url_content_unit_id
    )
