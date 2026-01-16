"""Context Units endpoints (enrichment, CRUD, search)."""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_company_id_from_auth, get_auth_context

logger = get_logger("api.context_units")
router = APIRouter(tags=["context-units"])

# Initialize supabase client
supabase_client = get_supabase_client()


# ============================================
# PYDANTIC MODELS
# ============================================

class EnrichContextUnitRequest(BaseModel):
    """Request model for context unit enrichment."""
    enrich_type: str  # "update" | "background" | "verify"


class SaveEnrichedStatementsRequest(BaseModel):
    """Request model for saving enriched statements."""
    statements: List[Dict[str, Any]]
    append: bool = True


class SemanticSearchRequest(BaseModel):
    """Request model for semantic search."""
    query: str = Field(..., description="Search query to vectorize and match")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of results")
    threshold: float = Field(default=0.18, ge=0.0, le=1.0, description="Minimum similarity score (0.0-1.0, default 0.18 for high recall)")
    max_days: Optional[int] = Field(default=None, ge=1, description="Maximum age of context units in days (e.g., 30 = last 30 days)")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Optional filters (category, source_type, etc.)")
    include_pool: bool = Field(default=False, description="Include pool content (company_id = 99999999-9999-9999-9999-999999999999)")


# ============================================
# ENRICHMENT ENDPOINTS
# ============================================

@router.post("/api/v1/context-units/{context_unit_id}/enrichment")
async def enrichment_context_unit(
    context_unit_id: str,
    request: EnrichContextUnitRequest,
    auth: Dict = Depends(get_auth_context)
):
    """
    Enrich context unit with real-time web search using EnrichmentService (NEW).

    This endpoint uses Groq Compound model with automatic web search to:
    - Find updates on news stories (enrich_type=update)
    - Discover historical context (enrich_type=background)
    - Verify information currency (enrich_type=verify)

    This is the new implementation using provider architecture with automatic
    usage tracking. Once validated, will replace /enrich endpoint.

    Args:
        context_unit_id: UUID of context unit to enrich
        request: Enrichment parameters
        client: Authenticated client data

    Returns:
        Enrichment results with suggestions and sources
    """
    try:
        logger.info(
            "enrichment_context_unit_request",
            context_unit_id=context_unit_id,
            enrich_type=request.enrich_type,
            client_id=auth["client_id"]
        )

        # Validate enrich_type
        if request.enrich_type not in ["update", "background", "verify"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid enrich_type. Must be: update, background, or verify"
            )

        # Get context unit from database
        # Allow access to both client's own units AND pool units
        pool_company_id = "99999999-9999-9999-9999-999999999999"

        result = supabase_client.client.table("press_context_units")\
            .select("*")\
            .eq("id", context_unit_id)\
            .or_(f"company_id.eq.{auth['company_id']},company_id.eq.{pool_company_id}")\
            .maybe_single()\
            .execute()

        if not result or not result.data:
            logger.warn(
                "context_unit_not_found",
                context_unit_id=context_unit_id,
                client_id=auth["client_id"]
            )
            raise HTTPException(status_code=404, detail="Context unit not found")

        context_unit = result.data

        # Calculate age - fix malformed Supabase timestamps
        created_at = context_unit.get("created_at", "")
        if created_at:
            try:
                created_at_clean = created_at.replace('Z', '+00:00')

                if '.' in created_at_clean and '+' in created_at_clean:
                    parts = created_at_clean.split('.')
                    if len(parts) == 2:
                        microseconds = parts[1].split('+')[0]
                        microseconds = microseconds.ljust(6, '0')
                        created_at_clean = f"{parts[0]}.{microseconds}+00:00"

                dt = datetime.fromisoformat(created_at_clean)
                age_days = (datetime.now(dt.tzinfo) - dt).days
            except Exception as e:
                logger.warn("timestamp_parse_failed",
                    created_at=created_at,
                    error=str(e)
                )
                age_days = 0
        else:
            age_days = 0

        # Enrich using EnrichmentService (NEW)
        from utils.enrichment_service import get_enrichment_service

        enrichment_service = get_enrichment_service()
        enrichment_result = await enrichment_service.enrich_context_unit(
            title=context_unit.get("title", ""),
            summary=context_unit.get("summary", ""),
            created_at=created_at,
            tags=context_unit.get("tags", []),
            enrich_type=request.enrich_type,
            organization_id=auth.get("organization_id", "00000000-0000-0000-0000-000000000001"),
            context_unit_id=context_unit_id,
            client_id=auth["client_id"]
        )

        # Detect empty results
        has_content = False
        if request.enrich_type == "update":
            has_content = enrichment_result.get("has_updates", False) and len(enrichment_result.get("new_developments", [])) > 0
        elif request.enrich_type == "background":
            has_content = len(enrichment_result.get("background_facts", [])) > 0
        elif request.enrich_type == "verify":
            has_content = len(enrichment_result.get("issues", [])) > 0 or enrichment_result.get("status") != "vigente"

        logger.info(
            "enrichment_context_unit_completed",
            context_unit_id=context_unit_id,
            enrich_type=request.enrich_type,
            has_error=bool(enrichment_result.get("error")),
            has_content=has_content
        )

        return {
            "success": not bool(enrichment_result.get("error")),
            "context_unit_id": context_unit_id,
            "context_unit_title": context_unit.get("title", ""),
            "enrich_type": request.enrich_type,
            "age_days": age_days,
            "has_content": has_content,  # NEW: Frontend can check this
            "result": enrichment_result,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "enrichment_context_unit_error",
            context_unit_id=context_unit_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/v1/context-units/{context_unit_id}/enriched-statements")
async def save_enriched_statements(
    context_unit_id: str,
    request: SaveEnrichedStatementsRequest,
    auth: Dict = Depends(get_auth_context)
):
    """
    Save user-selected enriched statements to context unit.

    This endpoint allows selective saving of enriched statements after
    user review. The web backend calls this after user selection.

    Args:
        context_unit_id: UUID of context unit
        request: Statements to save and append mode
        client: Authenticated client data

    Returns:
        Success status with count information
    """
    try:
        logger.info(
            "save_enriched_statements_request",
            context_unit_id=context_unit_id,
            statements_count=len(request.statements),
            append=request.append,
            client_id=auth["client_id"]
        )

        # Get context unit from database
        # Allow access to both client's own units AND pool units
        pool_company_id = "99999999-9999-9999-9999-999999999999"

        result = supabase_client.client.table("press_context_units")\
            .select("*")\
            .eq("id", context_unit_id)\
            .or_(f"company_id.eq.{auth['company_id']},company_id.eq.{pool_company_id}")\
            .maybe_single()\
            .execute()

        if not result or not result.data:
            logger.warn(
                "context_unit_not_found",
                context_unit_id=context_unit_id,
                client_id=auth["client_id"]
            )
            raise HTTPException(status_code=404, detail="Context unit not found")

        context_unit = result.data
        is_pool_unit = context_unit.get("company_id") == pool_company_id
        base_id = context_unit.get("base_id", context_unit_id)

        # Get current atomic_statements to calculate next order number
        atomic_statements = context_unit.get("atomic_statements", [])
        existing_enriched = context_unit.get("enriched_statements", [])

        max_order = 0

        # Find max order from atomic_statements
        if atomic_statements:
            for stmt in atomic_statements:
                if isinstance(stmt, dict):
                    stmt_order = stmt.get("order", 0)
                    if stmt_order > max_order:
                        max_order = stmt_order

        # Find max order from existing enriched_statements
        if existing_enriched and request.append:
            for stmt in existing_enriched:
                if isinstance(stmt, dict):
                    stmt_order = stmt.get("order", 0)
                    if stmt_order > max_order:
                        max_order = stmt_order

        # Add order and speaker to new statements
        next_order = max_order + 1
        new_statements = []

        for stmt in request.statements:
            if not isinstance(stmt, dict) or not stmt.get("text"):
                continue

            new_stmt = {
                "text": stmt.get("text"),
                "type": stmt.get("type", "fact"),
                "order": next_order,
                "speaker": stmt.get("speaker", None)
            }
            new_statements.append(new_stmt)
            next_order += 1

        # Prepare final enriched_statements array
        if request.append:
            # Normalize existing enriched to JSONB format
            normalized_existing = []
            if existing_enriched:
                for item in existing_enriched:
                    if isinstance(item, dict):
                        normalized_existing.append(item)
                    elif isinstance(item, str) and item:
                        # Legacy string format - convert
                        normalized_existing.append({
                            "text": item,
                            "type": "fact",
                            "order": 9999,
                            "speaker": None
                        })

            final_statements = normalized_existing + new_statements
        else:
            # Replace all
            final_statements = new_statements

        # DECISION: Pool unit → create enrichment child, Own unit → update directly
        if is_pool_unit:
            # Check if enrichment child already exists for this user
            enrichment_check = supabase_client.client.table("press_context_units")\
                .select("id, enriched_statements")\
                .eq("base_id", base_id)\
                .eq("company_id", auth["company_id"])\
                .maybe_single()\
                .execute()

            if enrichment_check.data:
                # Update existing enrichment
                existing_enriched_statements = enrichment_check.data.get("enriched_statements", [])
                if request.append:
                    final_statements = existing_enriched_statements + new_statements

                update_result = supabase_client.client.table("press_context_units").update({
                    "enriched_statements": final_statements
                }).eq("id", enrichment_check.data["id"]).execute()

                enrichment_id = enrichment_check.data["id"]
                logger.info("enrichment_child_updated",
                    base_id=base_id,
                    enrichment_id=enrichment_id,
                    company_id=auth["company_id"]
                )
            else:
                # Create new enrichment child
                import uuid
                enrichment_id = str(uuid.uuid4())

                insert_result = supabase_client.client.table("press_context_units").insert({
                    "id": enrichment_id,
                    "base_id": base_id,
                    "company_id": auth["company_id"],
                    "client_id": auth["client_id"],
                    "source_id": None,
                    "title": None,  # Inherit from base
                    "summary": None,  # Inherit from base
                    "category": None,  # Inherit from base
                    "tags": [],
                    "atomic_statements": [],
                    "enriched_statements": final_statements,
                    "embedding": None,
                    "created_at": datetime.utcnow().isoformat()
                }).execute()

                update_result = insert_result
                logger.info("enrichment_child_created",
                    base_id=base_id,
                    enrichment_id=enrichment_id,
                    company_id=auth["company_id"]
                )
        else:
            # Own unit - update directly
            update_result = supabase_client.client.table("press_context_units").update({
                "enriched_statements": final_statements
            }).eq("id", context_unit_id).execute()

        if not update_result.data:
            logger.error(
                "enriched_statements_save_failed",
                context_unit_id=context_unit_id
            )
            raise HTTPException(status_code=500, detail="Failed to save enriched statements")

        logger.info(
            "enriched_statements_saved",
            context_unit_id=context_unit_id,
            statements_added=len(new_statements),
            total_enriched=len(final_statements),
            append=request.append
        )

        return {
            "success": True,
            "context_unit_id": context_unit_id,
            "statements_added": len(new_statements),
            "total_enriched": len(final_statements)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "save_enriched_statements_error",
            context_unit_id=context_unit_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# DATA ACCESS ENDPOINTS
# ============================================

@router.get("/api/v1/context-units")
async def list_context_units(
    company_id: str = Depends(get_company_id_from_auth),
    limit: int = 20,
    offset: int = 0,
    timePeriod: str = "24h",
    source: str = "all",
    topic: str = "all",
    category: str = "all",
    starred: bool = False,
    include_pool: bool = False
) -> Dict:
    """
    Get filtered and paginated list of context units.

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)

    Filters by company_id from authentication.
    Optionally includes pool content (company_id = 99999999-9999-9999-9999-999999999999) when include_pool=true.
    """
    try:
        # Validate limit
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")
        supabase = get_supabase_client()

        # Build query with pool inclusion
        pool_uuid = "99999999-9999-9999-9999-999999999999"

        if include_pool:
            # Include own company AND pool content
            query = supabase.client.table("press_context_units")\
                .select("*", count="exact")\
                .in_("company_id", [company_id, pool_uuid])
        else:
            # Only own company content
            query = supabase.client.table("press_context_units")\
                .select("*", count="exact")\
                .eq("company_id", company_id)

        # Time period filter
        if timePeriod != "all":
            now = datetime.utcnow()
            if timePeriod == "24h":
                cutoff = now - timedelta(hours=24)
            elif timePeriod == "week":
                cutoff = now - timedelta(days=7)
            elif timePeriod == "month":
                cutoff = now - timedelta(days=30)
            else:
                raise HTTPException(status_code=400, detail="Invalid timePeriod. Use: 24h, week, month, all")

            query = query.gte("created_at", cutoff.isoformat())

        # Source filter
        if source != "all":
            query = query.eq("source_type", source)

        # Topic filter (tag in array)
        if topic != "all":
            query = query.contains("tags", [topic])

        # Category filter
        if category != "all":
            query = query.eq("category", category)

        # Starred filter
        if starred:
            query = query.eq("is_starred", True)

        # Order and paginate
        result = query.order("created_at", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()

        total = result.count if hasattr(result, 'count') else 0
        items = result.data or []

        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("list_context_units_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch context units: {str(e)}")


@router.get("/api/v1/context-units/filter-options")
async def get_filter_options(
    auth: Dict = Depends(get_auth_context)
) -> Dict:
    """
    Get available filter options (sources, topics, and categories) for context units.

    Returns unique source_types, tags, and categories with counts.
    """
    try:
        company_id = auth["company_id"]
        supabase = get_supabase_client()

        # Query all units and aggregate manually (simple and reliable)
        all_units = supabase.client.table("press_context_units")\
            .select("source_type, tags, category")\
            .eq("company_id", company_id)\
            .execute()

        # Manual aggregation
        sources_map = {}
        topics_map = {}
        categories_map = {}

        for unit in all_units.data or []:
            source_type = unit.get("source_type")
            if source_type:
                sources_map[source_type] = sources_map.get(source_type, 0) + 1

            for tag in unit.get("tags") or []:
                topics_map[tag] = topics_map.get(tag, 0) + 1

            category = unit.get("category")
            if category:
                categories_map[category] = categories_map.get(category, 0) + 1

        sources = [{"value": k, "label": k, "count": v} for k, v in sources_map.items()]
        topics = [{"value": k, "label": k, "count": v} for k, v in topics_map.items()]
        categories = [{"value": k, "label": k, "count": v} for k, v in categories_map.items()]

        sources.sort(key=lambda x: x["count"], reverse=True)
        topics.sort(key=lambda x: x["count"], reverse=True)
        categories.sort(key=lambda x: x["count"], reverse=True)

        return {"sources": sources, "topics": topics, "categories": categories}

    except Exception as e:
        logger.error("get_filter_options_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch filter options")


@router.get("/api/v1/context-units/{context_unit_id}")
async def get_context_unit(
    context_unit_id: str,
    auth: Dict = Depends(get_auth_context)
) -> Dict:
    """
    Get a single context unit by ID.

    Returns context unit merged with user's enrichments if available.
    Supports both base units and enrichment children.
    """
    try:
        company_id = auth["company_id"]
        pool_company_id = "99999999-9999-9999-9999-999999999999"
        supabase = get_supabase_client()

        # First, get the requested unit to determine its base_id
        initial_result = supabase.client.table("press_context_units")\
            .select("*")\
            .eq("id", context_unit_id)\
            .single()\
            .execute()

        if not initial_result.data:
            raise HTTPException(status_code=404, detail="Context unit not found or access denied")

        initial_unit = initial_result.data
        base_id = initial_unit.get("base_id", context_unit_id)

        # Fetch base + user's enrichment (if exists)
        all_units_result = supabase.client.table("press_context_units")\
            .select("*")\
            .eq("base_id", base_id)\
            .in_("company_id", [pool_company_id, company_id])\
            .execute()

        units = all_units_result.data or [initial_unit]

        # Separate base and enrichment
        base_unit = None
        enrichment_unit = None

        for unit in units:
            if unit["id"] == unit.get("base_id"):
                # This is the base unit
                base_unit = unit
            elif unit.get("company_id") == company_id:
                # This is user's enrichment
                enrichment_unit = unit

        # Fallback if no base found (shouldn't happen)
        if not base_unit:
            base_unit = initial_unit

        # Merge enrichment into base
        merged = dict(base_unit)

        if enrichment_unit:
            # Merge enriched_statements
            base_enriched = base_unit.get("enriched_statements", [])
            user_enriched = enrichment_unit.get("enriched_statements", [])
            merged["enriched_statements"] = base_enriched + user_enriched

            # Add metadata about enrichment
            merged["has_user_enrichment"] = True
            merged["enrichment_id"] = enrichment_unit["id"]
        else:
            merged["has_user_enrichment"] = False

        return merged

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_context_unit_error", error=str(e), context_unit_id=context_unit_id)
        raise HTTPException(status_code=500, detail="Failed to fetch context unit")


# ============================================
# SEARCH ENDPOINT
# ============================================

@router.post("/api/v1/context-units/search-vector")
async def hybrid_semantic_search(
    request: SemanticSearchRequest,
    company_id: str = Depends(get_company_id_from_auth)
):
    """
    Hybrid search: Semantic (pgvector) + Keyword (full-text) with query expansion.

    Combines three techniques:
    1. Query expansion (cache + local synonyms + LLM if needed)
    2. Semantic search (pgvector cosine similarity)
    3. Keyword search (PostgreSQL full-text search)

    Results are merged and re-ranked by combined score (70% semantic + 30% keyword).

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)

    Args:
        request: Search parameters (query, limit, threshold, filters)
        company_id: Company ID from authentication (JWT or API Key)

    Returns:
        List of matching context units with similarity scores and query expansion info
    """
    try:
        start_time = datetime.utcnow()

        logger.info("hybrid_search_start",
            company_id=company_id,
            query=request.query[:100],
            limit=request.limit,
            threshold=request.threshold,
            max_days=request.max_days
        )

        # Step 1: Query expansion (cache + local synonyms + LLM)
        from utils.query_expander import get_query_expander

        expander = get_query_expander()
        expanded_terms = await expander.expand(request.query, use_llm=True)

        # Combine expanded terms for keyword search
        query_text_expanded = " ".join(expanded_terms)

        logger.debug("query_expanded",
            original=request.query[:50],
            expanded=query_text_expanded[:100],
            terms_count=len(expanded_terms)
        )

        # Step 2: Generate embedding for ORIGINAL query (not expanded)
        # Reason: Semantic search works better with original intent
        from utils.embedding_generator import generate_embedding_fastembed

        query_embedding = await generate_embedding_fastembed(request.query)

        logger.debug("query_embedding_generated",
            company_id=company_id,
            embedding_dim=len(query_embedding)
        )

        # Convert embedding to string format for pgvector
        embedding_str = f"[{','.join(map(str, query_embedding))}]"

        # Step 3: Build RPC parameters for hybrid search
        rpc_params = {
            'p_company_id': company_id,
            'p_query_text': query_text_expanded,  # Expanded for keyword search
            'p_query_embedding': embedding_str,    # Original for semantic search
            'p_semantic_threshold': request.threshold,
            'p_limit': request.limit,
            'p_max_days': request.max_days,
            'p_category': request.filters.get('category') if request.filters else None,
            'p_source_type': request.filters.get('source_type') if request.filters else None,
            'p_include_pool': request.include_pool
        }

        # Step 4: Execute hybrid search via new RPC function
        result = supabase_client.client.rpc('hybrid_search_context_units', rpc_params).execute()

        results = result.data or []

        query_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        logger.info("hybrid_search_completed",
            company_id=company_id,
            query=request.query[:50],
            expanded_terms_count=len(expanded_terms),
            results_count=len(results),
            threshold=request.threshold,
            query_time_ms=round(query_time_ms, 2)
        )

        response = {
            "query": request.query,
            "results": results,
            "count": len(results),
            "threshold_used": request.threshold,
            "max_results": request.limit,
            "query_expansion": {
                "original": request.query,
                "expanded_terms": expanded_terms,
                "terms_count": len(expanded_terms),
                "expanded_query": query_text_expanded
            },
            "search_method": "hybrid_semantic_keyword",
            "query_time_ms": round(query_time_ms, 2)
        }

        # Add max_days to response if filter was used
        if request.max_days:
            response["max_days_filter"] = request.max_days

        return response

    except Exception as e:
        logger.error("hybrid_search_error",
            company_id=company_id,
            query=request.query[:50],
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Hybrid search failed: {str(e)}")
