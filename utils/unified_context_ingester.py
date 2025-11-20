"""Unified context unit ingester - flexible mega-ingester for all sources.

Phase 2: Generate and save context unit with maximum flexibility.

Accepts ANY combination of inputs:
- raw_text + url
- pre-generated title + raw_text
- title + summary + tags (pre-generated)
- url only (fetch and process)
- etc.

Always generates:
- Embeddings (768d multilingual)
- Semantic deduplication check
- Complete context unit in press_context_units
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

from .llm_client import LLMClient
from .embedding_generator import generate_embedding
from .supabase_client import get_supabase_client
from .logger import get_logger

logger = get_logger("unified_context_ingester")

# Duplicate detection threshold
DUPLICATE_THRESHOLD = 0.98


def normalize_atomic_statements(
    atomic_statements: Optional[List[Any]]
) -> List[Dict[str, Any]]:
    """Normalize atomic_statements to standardized format.

    Handles conversion from:
    - Groq format: ["fact 1", "fact 2", ...]  (simple string array)
    - GPT-4o-mini format: [{"type": "fact", "text": "...", "order": 1}, ...]  (structured objects)

    Args:
        atomic_statements: Input in any format (or None)

    Returns:
        List of dicts with structure: {"type": "fact", "text": "...", "order": N}
    """
    if not atomic_statements:
        return []

    normalized = []

    for i, statement in enumerate(atomic_statements):
        if isinstance(statement, dict):
            # Already structured (GPT-4o-mini format)
            # Ensure all required fields exist
            normalized.append({
                "type": statement.get("type", "fact"),
                "text": statement.get("text", ""),
                "order": statement.get("order", i + 1),
                "speaker": statement.get("speaker"),  # Optional
                "timestamp": statement.get("timestamp")  # Optional
            })
        elif isinstance(statement, str):
            # Simple string (Groq format) - convert to structured format
            normalized.append({
                "type": "fact",
                "text": statement,
                "order": i + 1,
                "speaker": None,
                "timestamp": None
            })
        else:
            logger.warn("unknown_atomic_statement_format",
                statement_type=type(statement).__name__,
                index=i
            )
            # Skip unknown formats
            continue

    return normalized


async def ingest_context_unit(
    # Flexible content inputs (provide at least ONE)
    raw_text: Optional[str] = None,
    url: Optional[str] = None,

    # Pre-generated fields (optional - LLM will generate if missing)
    title: Optional[str] = None,
    summary: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category: Optional[str] = None,
    atomic_statements: Optional[List[Any]] = None,  # Can be string array or dict array

    # Required metadata
    company_id: str = None,
    source_type: str = None,
    source_id: str = None,

    # Optional metadata
    source_metadata: Optional[Dict[str, Any]] = None,
    url_content_unit_id: Optional[str] = None,

    # Control flags
    force_save: bool = False,
    check_duplicates: bool = True,
    generate_embedding_flag: bool = True
) -> Dict[str, Any]:
    """Universal mega-ingester: accepts any combination of inputs.

    FLEXIBLE INPUTS - provide at least ONE of:
    - raw_text: Full content text
    - url: URL to fetch (NOT YET IMPLEMENTED - future feature)

    PRE-GENERATED FIELDS (optional):
    - title: Pre-generated title (LLM generates if missing)
    - summary: Pre-generated summary (LLM generates if missing)
    - tags: Pre-generated tags (LLM generates if missing)
    - category: Pre-generated category (LLM generates if missing)
    - atomic_statements: Pre-generated statements in ANY format (LLM generates if missing)

    REQUIRED METADATA:
    - company_id: Company UUID
    - source_type: scraping/email/perplexity/api/manual
    - source_id: Source UUID

    USE CASES:
    1. Email with audio:
       raw_text = f"Subject: {subject}\\nBody: {body}\\n--- Audio ---\\n{transcription}"
       title = subject  (pre-generated)
       # LLM generates: summary, tags, category, atomic_statements

    2. Perplexity with pre-generated title:
       raw_text = news_item["texto"]
       title = news_item["titulo"]  (pre-generated from Perplexity)
       # LLM generates: summary, tags, category, atomic_statements

    3. API endpoint with full text only:
       raw_text = request_body["text"]
       # LLM generates: title, summary, tags, category, atomic_statements

    4. Manual entry with complete data:
       title = "User title"
       summary = "User summary"
       raw_text = "Full text..."
       tags = ["tag1", "tag2"]
       # LLM only generates: category, atomic_statements (if missing)

    Returns:
        Dict with:
        - success: bool
        - context_unit_id: UUID if saved
        - duplicate: bool
        - duplicate_id: UUID if duplicate found
        - generated_fields: List[str] (fields generated by LLM)
        - error: str if failed
    """
    logger.debug("ingest_context_unit_start",
        company_id=company_id,
        source_id=source_id,
        source_type=source_type,
        has_raw_text=bool(raw_text),
        has_url=bool(url),
        has_title=bool(title),
        has_summary=bool(summary)
    )

    # Validation: At least ONE content input required
    if not raw_text and not url:
        logger.error("no_content_provided",
            company_id=company_id,
            source_id=source_id
        )
        return {
            "success": False,
            "context_unit_id": None,
            "duplicate": False,
            "error": "Either raw_text or url must be provided"
        }

    # Validation: Required metadata
    if not company_id or not source_type or not source_id:
        logger.error("missing_required_metadata",
            has_company_id=bool(company_id),
            has_source_type=bool(source_type),
            has_source_id=bool(source_id)
        )
        return {
            "success": False,
            "context_unit_id": None,
            "duplicate": False,
            "error": "company_id, source_type, and source_id are required"
        }

    try:
        # Step 1: Fetch URL if provided (NOT YET IMPLEMENTED)
        if url and not raw_text:
            logger.error("url_fetch_not_implemented", url=url)
            return {
                "success": False,
                "context_unit_id": None,
                "duplicate": False,
                "error": "URL fetching not yet implemented - provide raw_text"
            }

        # Step 2: Generate missing fields using LLM (GPT-4o-mini)
        generated_fields = []
        llm_client = None

        # Determine what needs to be generated
        needs_generation = (
            not title or
            not summary or
            not tags or
            not category or
            not atomic_statements
        )

        if needs_generation:
            logger.debug("generating_missing_fields",
                needs_title=not title,
                needs_summary=not summary,
                needs_tags=not tags,
                needs_category=not category,
                needs_atomic_statements=not atomic_statements
            )

            # Initialize LLM client (GPT-4o-mini via OpenRouter)
            llm_client = LLMClient()

            # Call generate_context_unit to get ALL fields at once
            # (More efficient than multiple LLM calls)
            llm_result = await llm_client.generate_context_unit(
                text=raw_text,
                organization_id=company_id,
                client_id=company_id
            )

            # Use LLM-generated fields for missing values
            if not title:
                title = llm_result.get("title", "Untitled")
                generated_fields.append("title")

            if not summary:
                summary = llm_result.get("summary", "")
                generated_fields.append("summary")

            if not tags:
                tags = llm_result.get("tags", [])
                generated_fields.append("tags")

            if not category:
                category = llm_result.get("category", "general")
                generated_fields.append("category")

            if not atomic_statements:
                atomic_statements = llm_result.get("atomic_statements", [])
                generated_fields.append("atomic_statements")

            logger.info("llm_fields_generated",
                title=title[:50],
                generated_fields=generated_fields
            )

        # Step 3: Normalize atomic_statements format
        atomic_statements = normalize_atomic_statements(atomic_statements)

        # Step 4: Generate embedding for duplicate detection and search
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

        # Step 5: Check for semantic duplicates using embedding similarity
        if check_duplicates and embedding:
            try:
                supabase = get_supabase_client()

                # Use search RPC function for duplicate detection
                # (cosine similarity > 0.98)
                embedding_str = '[' + ','.join(map(str, embedding)) + ']'

                result = supabase.client.rpc(
                    'search_context_units_by_vector',
                    {
                        'p_company_id': company_id,
                        'p_query_embedding': embedding_str,
                        'p_threshold': DUPLICATE_THRESHOLD,
                        'p_limit': 1
                    }
                ).execute()

                if result.data and len(result.data) > 0:
                    duplicate = result.data[0]

                    if not force_save:
                        logger.warn("duplicate_found_skipping_save",
                            title=title[:50],
                            duplicate_id=duplicate['id'],
                            similarity=duplicate.get('similarity')
                        )
                        return {
                            "success": False,
                            "context_unit_id": None,
                            "duplicate": True,
                            "duplicate_id": duplicate['id'],
                            "duplicate_title": duplicate.get('title'),
                            "similarity": duplicate.get('similarity'),
                            "generated_fields": generated_fields
                        }

            except Exception as e:
                logger.error("duplicate_check_error",
                    title=title[:50],
                    error=str(e)
                )
                # Continue - safer to have duplicates than miss content

        # Step 6: Save to press_context_units
        try:
            supabase = get_supabase_client()

            context_unit_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat()

            context_unit_data = {
                "id": context_unit_id,
                "company_id": company_id,
                "source_id": source_id,
                "title": title,
                "summary": summary,
                "raw_text": raw_text,
                "tags": tags or [],
                "atomic_statements": atomic_statements,
                "category": category,
                "source_type": source_type,
                "source_metadata": source_metadata or {},
                "status": "completed",
                "created_at": now
            }

            # Add embedding if generated
            if embedding:
                context_unit_data["embedding"] = embedding

            # Add url_content_unit_id if provided (scraping sources)
            if url_content_unit_id:
                context_unit_data["url_content_unit_id"] = url_content_unit_id

            # Insert
            result = supabase.client.table("press_context_units").insert(
                context_unit_data
            ).execute()

            if result.data and len(result.data) > 0:
                logger.info("context_unit_saved",
                    context_unit_id=context_unit_id,
                    company_id=company_id,
                    source_id=source_id,
                    source_type=source_type,
                    title=title[:50],
                    category=category,
                    has_embedding=bool(embedding),
                    generated_fields=generated_fields
                )

                return {
                    "success": True,
                    "context_unit_id": context_unit_id,
                    "duplicate": False,
                    "duplicate_id": None,
                    "generated_fields": generated_fields
                }
            else:
                logger.error("context_unit_save_failed_no_data",
                    title=title[:50]
                )
                return {
                    "success": False,
                    "context_unit_id": None,
                    "duplicate": False,
                    "error": "No data returned from insert",
                    "generated_fields": generated_fields
                }

        except Exception as e:
            logger.error("context_unit_save_error",
                title=title[:50] if title else "No title",
                error=str(e)
            )
            return {
                "success": False,
                "context_unit_id": None,
                "duplicate": False,
                "error": str(e),
                "generated_fields": generated_fields
            }

    except Exception as e:
        logger.error("ingest_context_unit_error",
            company_id=company_id,
            source_id=source_id,
            error=str(e)
        )
        return {
            "success": False,
            "context_unit_id": None,
            "duplicate": False,
            "error": str(e),
            "generated_fields": []
        }
