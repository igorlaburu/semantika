"""Workflow-enabled endpoint functions with backward compatibility.

These functions replace the existing endpoint logic with workflow-wrapped versions
while maintaining 100% backward compatibility.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from .workflow_manager import workflow_wrapper
from .logger import get_logger
from .supabase_client import get_supabase_client

logger = get_logger("workflow_endpoints")


@workflow_wrapper("micro_edit")
async def execute_micro_edit(
    client: Dict[str, Any],
    text: str,
    command: str,
    context: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute micro-edit workflow with usage tracking.
    
    Args:
        client: Authenticated client data
        text: Text to edit
        command: Edit command
        context: Optional context
        params: Optional parameters
        
    Returns:
        Micro-edit result
    """
    try:
        # Import here to avoid circular imports
        from utils.llm_client import get_llm_client
        
        # Get organization_id from client
        organization_id = client.get("organization_id")
        if not organization_id:
            # Fallback for demo user
            organization_id = "00000000-0000-0000-0000-000000000001"
        
        # Extract parameters
        params = params or {}
        language = params.get("language", "es")
        preserve_meaning = params.get("preserve_meaning", True)
        style_guide_id = params.get("style_guide_id")
        max_length = params.get("max_length")
        
        # Get style guide if provided
        style_guide = None
        if style_guide_id:
            try:
                supabase_client = get_supabase_client()
                style_result = supabase_client.client.table("press_styles") \
                    .select("style_guide_markdown") \
                    .eq("id", style_guide_id) \
                    .eq("is_active", True) \
                    .single() \
                    .execute()
                
                if style_result.data:
                    style_guide = style_result.data["style_guide_markdown"]
            except Exception as e:
                logger.warn("style_guide_not_found", style_guide_id=style_guide_id, error=str(e))
        
        # Get LLM client and perform micro-edit
        openrouter = get_llm_client()
        result = await openrouter.micro_edit(
            text=text,
            command=command,
            context=context,
            language=language,
            preserve_meaning=preserve_meaning,
            style_guide=style_guide,
            max_length=max_length,
            organization_id=organization_id,
            client_id=client["client_id"]
        )
        
        return result
        
    except Exception as e:
        logger.error("micro_edit_workflow_error", error=str(e))
        raise


@workflow_wrapper("analyze")
async def execute_analyze(
    client: Dict[str, Any],
    text: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute text analysis workflow with usage tracking.
    
    Args:
        client: Authenticated client data
        text: Text to analyze
        params: Optional parameters
        
    Returns:
        Analysis result
    """
    try:
        from core_stateless import StatelessPipeline
        
        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id', "00000000-0000-0000-0000-000000000001"),
            client_id=client['client_id']
        )
        
        result = await pipeline.analyze(text)
        return result
        
    except Exception as e:
        logger.error("analyze_workflow_error", error=str(e))
        raise


@workflow_wrapper("analyze_atomic")
async def execute_analyze_atomic(
    client: Dict[str, Any],
    text: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute atomic analysis workflow with usage tracking.
    
    Args:
        client: Authenticated client data
        text: Text to analyze
        params: Optional parameters
        
    Returns:
        Atomic analysis result
    """
    try:
        from core_stateless import StatelessPipeline
        
        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id', "00000000-0000-0000-0000-000000000001"),
            client_id=client['client_id']
        )
        
        result = await pipeline.analyze_atomic(text)
        return result
        
    except Exception as e:
        logger.error("analyze_atomic_workflow_error", error=str(e))
        raise


@workflow_wrapper("redact_news")
async def execute_redact_news(
    client: Dict[str, Any],
    text: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute news generation workflow with usage tracking.
    
    Args:
        client: Authenticated client data
        text: Source text or facts
        params: Optional parameters
        
    Returns:
        Generated news article
    """
    try:
        from core_stateless import StatelessPipeline
        
        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id', "00000000-0000-0000-0000-000000000001"),
            client_id=client['client_id']
        )
        
        params = params or {}
        style_guide = params.get("style_guide")
        language = params.get("language", "es")
        
        result = await pipeline.redact_news(
            text=text,
            style_guide=style_guide,
            language=language
        )
        return result
        
    except Exception as e:
        import traceback
        logger.error("redact_news_workflow_error", error=str(e), traceback=traceback.format_exc())
        raise


@workflow_wrapper("style_generation")
async def execute_style_generation(
    client: Dict[str, Any],
    urls: list,
    style_name: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute style guide generation workflow with usage tracking.
    
    Args:
        client: Authenticated client data
        urls: URLs to analyze for style
        style_name: Name for the style guide
        params: Optional parameters
        
    Returns:
        Generated style guide
    """
    try:
        from core_stateless import StatelessPipeline
        
        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id', "00000000-0000-0000-0000-000000000001"),
            client_id=client['client_id']
        )
        
        result = await pipeline.generate_style_guide(
            urls=urls,
            style_name=style_name
        )
        
        result["generated_at"] = datetime.utcnow().isoformat() + "Z"
        return result
        
    except Exception as e:
        logger.error("style_generation_workflow_error", error=str(e))
        raise


@workflow_wrapper("url_processing")
async def execute_url_processing(
    client: Dict[str, Any],
    url: str,
    action: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute URL processing workflow with usage tracking.
    
    Args:
        client: Authenticated client data
        url: URL to process
        action: Processing action
        params: Optional parameters
        
    Returns:
        Processing result
    """
    try:
        from core_stateless import StatelessPipeline
        
        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id', "00000000-0000-0000-0000-000000000001"),
            client_id=client['client_id']
        )
        
        result = await pipeline.process_url(
            url=url,
            action=action,
            params=params
        )
        return result
        
    except Exception as e:
        logger.error("url_processing_workflow_error", error=str(e))
        raise


@workflow_wrapper("redact_news_rich")
async def execute_redact_news_rich(
    client: Dict[str, Any],
    context_unit_ids: list,
    title: Optional[str] = None,
    instructions: Optional[str] = None,
    style_guide: Optional[str] = None,
    language: str = "es"
) -> Dict[str, Any]:
    """
    Execute rich news redaction from multiple context units.
    
    Args:
        client: Authenticated client data
        context_unit_ids: List of context unit UUIDs
        title: Optional title suggestion
        instructions: Optional writing instructions
        style_guide: Optional markdown style guide
        language: Target language
        
    Returns:
        Generated news article with sources
    """
    try:
        from utils.llm_client import get_llm_client
        
        supabase_client = get_supabase_client()
        organization_id = client.get("organization_id", "00000000-0000-0000-0000-000000000001")
        
        context_units = []
        for cu_id in context_unit_ids:
            # Fetch context unit
            result = supabase_client.client.table("press_context_units")\
                .select("*")\
                .eq("id", cu_id)\
                .eq("company_id", client["company_id"])\
                .maybe_single()\
                .execute()

            if result.data:
                cu_data = result.data

                # Try to fetch source information if source_id is a valid UUID
                source_id = cu_data.get("source_id")
                if source_id:
                    try:
                        # Try to parse as UUID and fetch from sources table
                        import uuid
                        uuid.UUID(source_id)  # Validate UUID format

                        source_result = supabase_client.client.table("sources")\
                            .select("source_name, description, tags")\
                            .eq("source_id", source_id)\
                            .maybe_single()\
                            .execute()

                        if source_result.data:
                            cu_data["sources"] = source_result.data
                    except (ValueError, Exception):
                        # source_id is not a valid UUID, skip source lookup
                        pass

                context_units.append(cu_data)
        
        if not context_units:
            raise ValueError("No context units found for provided IDs")
        
        logger.info(
            "context_units_retrieved",
            count=len(context_units),
            client_id=client["client_id"]
        )
        
        all_statements = []
        for cu in context_units:
            atomic_statements = cu.get("atomic_statements", [])
            if isinstance(atomic_statements, list):
                for stmt in atomic_statements:
                    all_statements.append({
                        "context_unit_id": cu["id"],
                        "context_unit_title": cu.get("title", ""),
                        "statement": stmt
                    })
        
        all_statements.sort(key=lambda x: x.get("statement", {}).get("order", 0) if isinstance(x.get("statement"), dict) else 0)
        
        source_text_parts = []
        # Keep mapping of context_unit_id to title for statements_used processing
        cu_id_to_title = {}

        for cu in context_units:
            cu_id = cu.get("id")
            cu_title = cu.get("title", "Sin título")
            cu_summary = cu.get("summary", "")

            # Store mapping for later
            cu_id_to_title[cu_id] = cu_title

            # Handle NULL values from DB (use 'or []' to convert None to [])
            atomic_statements = cu.get("atomic_statements") or []
            enriched_statements = cu.get("enriched_statements") or []

            source_text_parts.append(f"## {cu_title} [CU:{cu_id}]")

            # Add source information (name and tags from sources table)
            sources_data = cu.get("sources")
            if sources_data:
                source_name = sources_data.get("source_name", "")
                source_tags = sources_data.get("tags", [])

                if source_name:
                    source_text_parts.append(f"Fuente: {source_name}")

                if source_tags:
                    # Filter out technical tags (scraping, api, webhook, index)
                    relevant_tags = [t for t in source_tags if t not in ["scraping", "api", "webhook", "index"]]
                    if relevant_tags:
                        tags_str = ", ".join(relevant_tags)
                        source_text_parts.append(f"Etiquetas de fuente: {tags_str}")

            if cu_summary:
                source_text_parts.append(f"Resumen: {cu_summary}")

            # Combine atomic statements + enriched statements (both JSONB format)
            all_statements = []

            # Extract atomic_statements (JSONB format with order)
            if atomic_statements:
                for stmt in atomic_statements:
                    if isinstance(stmt, dict):
                        all_statements.append(stmt)
                    elif isinstance(stmt, str) and stmt:
                        # Legacy string format - convert to JSONB
                        all_statements.append({
                            "text": stmt,
                            "type": "fact",
                            "order": 0,
                            "speaker": None
                        })

            # Extract enriched_statements (NEW: JSONB format, LEGACY: strings)
            if enriched_statements:
                for enriched in enriched_statements:
                    if isinstance(enriched, dict):
                        # New JSONB format
                        all_statements.append(enriched)
                    elif isinstance(enriched, str) and enriched:
                        # Legacy string format - convert to JSONB
                        all_statements.append({
                            "text": enriched,
                            "type": "fact",
                            "order": 9999,  # Put enriched at end by default
                            "speaker": None
                        })

            # Sort by order first
            all_statements.sort(key=lambda x: x.get("order", 9999))

            # CRITICAL: Renumber sequentially to avoid duplicate orders
            # This ensures atomic statements [0,1,2...] and enriched statements continue [N, N+1, N+2...]
            for idx, stmt in enumerate(all_statements):
                stmt["order"] = idx

            if all_statements:
                source_text_parts.append("Hechos verificados:")
                for stmt in all_statements:
                    stmt_text = stmt.get("text", "")
                    stmt_order = stmt.get("order", 0)
                    if stmt_text:
                        # Include order number for LLM tracking
                        source_text_parts.append(f"- [{stmt_order}] {stmt_text}")

            source_text_parts.append("")
        
        source_text = "\n".join(source_text_parts)

        # Count total statements (atomic + enriched)
        # Handle NULL values from DB (use 'or []' to convert None to [])
        total_atomic = sum(len(cu.get("atomic_statements") or []) for cu in context_units)
        total_enriched = sum(len(cu.get("enriched_statements") or []) for cu in context_units)

        # Log source text construction for debugging multi-source fusion
        logger.info(
            "source_text_constructed",
            context_units_count=len(context_units),
            atomic_statements_count=total_atomic,
            enriched_statements_count=total_enriched,
            total_statements=total_atomic + total_enriched,
            source_text_length=len(source_text),
            source_text_preview=source_text[:500]
        )
        
        openrouter = get_llm_client()
        result = await openrouter.redact_news_rich(
            source_text=source_text,
            title_suggestion=title or "",
            instructions=instructions or "",
            style_guide=style_guide,
            language=language,
            organization_id=organization_id,
            client_id=client["client_id"]
        )
        
        result["sources"] = []
        for cu in context_units:
            source_metadata = cu.get("source_metadata") or {}
            result["sources"].append({
                "id": cu["id"],
                "title": cu.get("title", ""),
                "summary": cu.get("summary", ""),
                "url": source_metadata.get("url", ""),
                "source_name": source_metadata.get("scraped_title", cu.get("title", "")),
                "source_type": cu.get("source_type", ""),
                "created_at": cu.get("created_at", "")
            })
        result["statements_count"] = len(all_statements)

        # Extract and normalize statements_used tracking
        statements_used_raw = result.get("statements_used", {})
        statements_used_normalized = {}

        if statements_used_raw:
            # Create reverse mapping: title -> cu_id for fallback
            title_to_cu_id = {v: k for k, v in cu_id_to_title.items()}

            for key, order_numbers in statements_used_raw.items():
                # Check if key is already a UUID (context_unit_id)
                if key in cu_id_to_title:
                    # Key is already a valid context_unit_id
                    statements_used_normalized[key] = order_numbers
                elif key in title_to_cu_id:
                    # Key is a title, map to context_unit_id
                    cu_id = title_to_cu_id[key]
                    statements_used_normalized[cu_id] = order_numbers
                else:
                    # Try to extract CU ID from format like "CU:uuid" or similar
                    if ":" in key:
                        potential_uuid = key.split(":")[-1].strip()
                        if potential_uuid in cu_id_to_title:
                            statements_used_normalized[potential_uuid] = order_numbers
                        else:
                            logger.warn(
                                "statements_used_key_not_mapped",
                                key=key,
                                available_cu_ids=list(cu_id_to_title.keys())
                            )
                    else:
                        logger.warn(
                            "statements_used_key_unknown_format",
                            key=key
                        )

            result["statements_used"] = statements_used_normalized

            logger.info(
                "statements_tracking_processed",
                raw_keys=list(statements_used_raw.keys()),
                normalized_count=len(statements_used_normalized),
                total_statements_tracked=sum(len(v) for v in statements_used_normalized.values())
            )
        else:
            result["statements_used"] = {}
            logger.warn("statements_used_not_returned_by_llm")

        # CATEGORY INHERITANCE LOGIC
        # Determine category from context unit with most statements used
        category = None
        if statements_used_normalized:
            # Find context_unit with most statements used
            max_statements = 0
            max_cu_id = None
            max_cu_created_at = None

            for cu_id, statement_orders in statements_used_normalized.items():
                count = len(statement_orders)
                # Get created_at for tie-breaking (use most recent)
                cu_created_at = next((cu.get("created_at") for cu in context_units if cu["id"] == cu_id), None)

                # If more statements, or same count but more recent, use this one
                if count > max_statements or (count == max_statements and cu_created_at and cu_created_at > max_cu_created_at):
                    max_statements = count
                    max_cu_id = cu_id
                    max_cu_created_at = cu_created_at

            # Get category from selected context unit
            if max_cu_id:
                selected_cu = next((cu for cu in context_units if cu["id"] == max_cu_id), None)
                if selected_cu:
                    category = selected_cu.get("category")
                    logger.info(
                        "article_category_inherited",
                        category=category,
                        from_context_unit=max_cu_id,
                        statements_count=max_statements
                    )

        # Fallback: if no category determined, use first context unit's category
        if not category and context_units:
            category = context_units[0].get("category")
            logger.info(
                "article_category_fallback",
                category=category,
                from_context_unit=context_units[0]["id"]
            )

        result["category"] = category

        return result
        
    except Exception as e:
        logger.error("redact_news_rich_workflow_error", error=str(e))
        raise