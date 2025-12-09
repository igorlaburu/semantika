"""UNIFIED CONTEXT INGESTER - Guardado final de context units con embeddings y deduplicación.

¿QUÉ HACE?
-----------
Punto final de convergencia para TODOS los flujos. Acepta contenido enriquecido
(o raw) y lo guarda en press_context_units con embeddings y deduplicación semántica.

¿QUÉ ACEPTA?
------------
Combinaciones flexibles:
- raw_text + url
- title + summary + tags (pre-generado)
- raw_text solo (genera metadata con LLM)
- title + raw_text (genera resto con LLM)

¿QUÉ GENERA?
------------
- Embeddings: FastEmbed multilingual 768d
- Campos faltantes: Via GPT-4o-mini si needed
- Normalización: atomic_statements en formato estándar
- Deduplicación: Búsqueda semántica threshold 0.98

¿CUÁNDO SE USA?
---------------
- Scraping: Después de parse + enrich
- Perplexity: Después de fetch + enrich
- Email: Después de combine + enrich
- Manual: Después de validación

¿POR QUÉ CENTRALIZADO?
----------------------
- ✅ Un solo lugar para guardar context units
- ✅ Deduplicación semántica consistente
- ✅ Embedding generation centralizado
- ✅ Normalización de atomic_statements
- ✅ Todos los flujos convergen aquí

EJEMPLO DE USO:
---------------
result = await ingest_context_unit(
    title="Título ya enriquecido",
    summary="Resumen...",
    raw_text="Texto completo...",
    tags=["política", "bilbao"],
    category="política",
    atomic_statements=[...],
    company_id="uuid-123",
    source_type="scraping",
    source_id="uuid-456",
    generate_embedding_flag=True,
    check_duplicates=True
)
# Returns: {success, context_unit_id, duplicate, generated_fields, ...}
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

from .llm_client import LLMClient
from .embedding_generator import generate_embedding
from .supabase_client import get_supabase_client
from .logger import get_logger

logger = get_logger("unified_context_ingester")

# Duplicate detection thresholds
DUPLICATE_THRESHOLD_CLIENT = 0.98  # Regular clients: very strict (avoid duplicating own content)
DUPLICATE_THRESHOLD_POOL = 0.92    # Pool: more sensitive (aggregate from multiple sources)


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

        # QUALITY GATE: Reject if insufficient content
        statement_count = len(atomic_statements) if atomic_statements else 0
        
        # Check for "sin contenido noticioso" in title or summary
        has_no_content_marker = (
            (title and "sin contenido noticioso" in title.lower()) or
            (summary and "sin contenido noticioso" in summary.lower())
        )
        
        if statement_count < 2 or has_no_content_marker:
            logger.info("context_unit_rejected_quality",
                title=title[:50] if title else "No title",
                statement_count=statement_count,
                has_no_content_marker=has_no_content_marker,
                reason="insufficient_statements" if statement_count < 2 else "no_news_content"
            )
            return {
                "success": False,
                "context_unit_id": None,
                "duplicate": False,
                "rejected": True,
                "reason": "insufficient_statements" if statement_count < 2 else "no_news_content",
                "statement_count": statement_count,
                "error": f"Context unit rejected: {statement_count} statements (minimum 2 required)" if statement_count < 2 else "Content marked as 'sin contenido noticioso'"
            }

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
                
                # Select threshold based on company type
                # Pool uses lower threshold (0.92) to catch more duplicates from multiple sources
                # Clients use higher threshold (0.98) to avoid false positives
                is_pool = company_id == "99999999-9999-9999-9999-999999999999"
                threshold = DUPLICATE_THRESHOLD_POOL if is_pool else DUPLICATE_THRESHOLD_CLIENT

                # Use search RPC function for duplicate detection
                embedding_str = '[' + ','.join(map(str, embedding)) + ']'

                result = supabase.client.rpc(
                    'search_context_units_by_vector',
                    {
                        'p_company_id': company_id,
                        'p_query_embedding': embedding_str,
                        'p_threshold': threshold,
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


async def ingest_web_context_unit(
    # Flexible content inputs
    raw_text: str,
    
    # Pre-generated fields (optional - LLM will generate if missing)
    title: Optional[str] = None,
    summary: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category: Optional[str] = None,
    atomic_statements: Optional[List[Any]] = None,
    
    # Required metadata
    company_id: str = None,
    source_type: str = None,
    source_id: str = None,
    
    # Optional metadata
    source_metadata: Optional[Dict[str, Any]] = None,
    
    # Control flags
    force_save: bool = False,
    check_duplicates: bool = True,
    generate_embedding_flag: bool = True,
    replace_previous: bool = True  # Replace previous version
) -> Dict[str, Any]:
    """
    Ingest context unit into web_context_units table.
    
    Similar to ingest_context_unit() but for web monitoring (subsidies, forms, etc.)
    
    Key differences:
    - Saves to web_context_units (not press_context_units)
    - Supports versioning (replace_previous flag)
    - Uses content_hash and simhash for change tracking
    
    Args:
        raw_text: Full content text (Markdown report)
        title, summary, tags, category, atomic_statements: Pre-generated or LLM-generated
        company_id, source_type, source_id: Required metadata
        source_metadata: Additional metadata
        generate_embedding_flag: Whether to generate embedding
        check_duplicates: Whether to check for duplicates
        replace_previous: If True, UPDATE existing; if False, INSERT new version
        
    Returns:
        Dict with success, context_unit_id, duplicate info, etc.
    """
    try:
        logger.info("ingesting_web_context_unit",
            company_id=company_id,
            source_id=source_id,
            source_type=source_type,
            replace_previous=replace_previous
        )
        
        # Use same logic as ingest_context_unit for LLM generation
        generated_fields = []
        
        # Generate missing fields with LLM
        if not all([title, summary, tags, category, atomic_statements]):
            llm_result = await _generate_missing_fields_with_llm(
                raw_text=raw_text,
                existing_title=title,
                existing_summary=summary,
                existing_tags=tags,
                existing_category=category,
                existing_atomic_statements=atomic_statements
            )
            
            if not title:
                title = llm_result.get("title", "Sin título")
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
        
        # Normalize atomic_statements
        atomic_statements = normalize_atomic_statements(atomic_statements)
        
        # Generate embedding
        embedding = None
        if generate_embedding_flag:
            try:
                embedding = await generate_embedding(
                    title=title,
                    summary=summary,
                    company_id=company_id
                )
            except Exception as e:
                logger.error("web_embedding_generation_failed",
                    error=str(e)
                )
        
        # Generate content_hash and simhash
        from utils.content_hasher import compute_content_hashes
        content_hash, simhash = compute_content_hashes(text=raw_text)
        
        # Check duplicates (optional)
        if check_duplicates and embedding and not replace_previous:
            # TODO: Implement semantic duplicate detection for web_context_units
            # For now, skip (replacement logic handles this)
            pass
        
        # Save to database
        supabase = get_supabase_client()
        
        context_unit_id = str(uuid.uuid4())
        
        context_unit_data = {
            "id": context_unit_id,
            "company_id": company_id,
            "source_type": source_type,
            "source_id": source_id,
            "title": title,
            "summary": summary,
            "raw_text": raw_text,
            "tags": tags,
            "category": category,
            "atomic_statements": atomic_statements,
            "source_metadata": source_metadata or {},
            "embedding": embedding,
            "content_hash": content_hash,
            "simhash": simhash,
            "is_latest": True,
            "version": 1,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if replace_previous:
            # Check if exists
            existing = supabase.client.table("web_context_units")\
                .select("id, version")\
                .eq("source_id", source_id)\
                .eq("company_id", company_id)\
                .eq("is_latest", True)\
                .maybe_single()\
                .execute()
            
            if existing and existing.data:
                # UPDATE existing record
                context_unit_data["id"] = existing.data["id"]
                context_unit_data["version"] = existing.data["version"] + 1
                context_unit_data.pop("created_at")  # Don't update created_at
                
                result = supabase.client.table("web_context_units")\
                    .update(context_unit_data)\
                    .eq("id", existing.data["id"])\
                    .execute()
                
                context_unit_id = existing.data["id"]
                
                logger.info("web_context_unit_updated",
                    context_unit_id=context_unit_id,
                    version=context_unit_data["version"]
                )
            else:
                # INSERT new record
                result = supabase.client.table("web_context_units")\
                    .insert(context_unit_data)\
                    .execute()
                
                if not result or not result.data:
                    logger.error("web_context_unit_insert_failed",
                        context_unit_id=context_unit_id,
                        error="No data returned from insert"
                    )
                    raise Exception("Failed to insert web_context_unit")
                
                logger.info("web_context_unit_inserted",
                    context_unit_id=context_unit_id
                )
        else:
            # Always INSERT (create new version)
            result = supabase.client.table("web_context_units")\
                .insert(context_unit_data)\
                .execute()
            
            if not result or not result.data:
                logger.error("web_context_unit_insert_failed",
                    context_unit_id=context_unit_id,
                    error="No data returned from insert"
                )
                raise Exception("Failed to insert web_context_unit")
            
            logger.info("web_context_unit_inserted_new_version",
                context_unit_id=context_unit_id
            )
        
        return {
            "success": True,
            "context_unit_id": context_unit_id,
            "duplicate": False,
            "generated_fields": generated_fields
        }
    
    except Exception as e:
        logger.error("ingest_web_context_unit_error",
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


async def _generate_missing_fields_with_llm(
    raw_text: str,
    existing_title: Optional[str] = None,
    existing_summary: Optional[str] = None,
    existing_tags: Optional[List[str]] = None,
    existing_category: Optional[str] = None,
    existing_atomic_statements: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    Generate missing fields using LLM.
    
    Helper function used by both ingest_context_unit and ingest_web_context_unit.
    """
    llm_client = LLMClient()
    
    # Build prompt for missing fields
    fields_to_generate = []
    if not existing_title:
        fields_to_generate.append("title")
    if not existing_summary:
        fields_to_generate.append("summary")
    if not existing_tags:
        fields_to_generate.append("tags")
    if not existing_category:
        fields_to_generate.append("category")
    if not existing_atomic_statements:
        fields_to_generate.append("atomic_statements")
    
    prompt = f"""Analiza el siguiente contenido y genera los campos faltantes en formato JSON.

Contenido:
{raw_text[:10000]}

Campos a generar: {", ".join(fields_to_generate)}

Responde SOLO con JSON válido con esta estructura:
{{
  "title": "Título claro y descriptivo (máx 100 caracteres)",
  "summary": "Resumen ejecutivo del contenido (2-3 líneas)",
  "tags": ["tag1", "tag2", "tag3"],
  "category": "categoría general",
  "atomic_statements": [
    {{"type": "fact", "text": "Hecho verificable 1", "order": 1}},
    {{"type": "fact", "text": "Hecho verificable 2", "order": 2}}
  ]
}}

JSON:"""
    
    try:
        # TODO: Fix this to use proper LLM interface
        # For now, skip auto-generation if not provided
        logger.warn("llm_field_generation_skipped", reason="generate() method not available")
        return {
            "title": existing_title or "Sin título",
            "summary": existing_summary or "",
            "tags": existing_tags or [],
            "category": existing_category or None,
            "atomic_statements": existing_atomic_statements or []
        }
        
        # response = await llm_client.generate(
        #     prompt=prompt,
        #     system_prompt="...",
        #     model="openrouter/openai/gpt-4o-mini",
        #     temperature=0.3,
        #     max_tokens=1000
        # )
        
        # Parse JSON
        import json
        cleaned_response = response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()
        
        llm_result = json.loads(cleaned_response)
        
        # Use existing values if provided
        if existing_title:
            llm_result["title"] = existing_title
        if existing_summary:
            llm_result["summary"] = existing_summary
        if existing_tags:
            llm_result["tags"] = existing_tags
        if existing_category:
            llm_result["category"] = existing_category
        if existing_atomic_statements:
            llm_result["atomic_statements"] = existing_atomic_statements
        
        return llm_result
    
    except Exception as e:
        logger.error("llm_field_generation_error", error=str(e))
        # Return minimal defaults
        return {
            "title": existing_title or "Sin título",
            "summary": existing_summary or "",
            "tags": existing_tags or [],
            "category": existing_category or "general",
            "atomic_statements": existing_atomic_statements or []
        }
