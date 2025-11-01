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
        from utils.openrouter_client import get_openrouter_client
        
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
        
        # Get OpenRouter client and perform micro-edit
        openrouter = get_openrouter_client()
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
        logger.error("redact_news_workflow_error", error=str(e))
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
        from utils.openrouter_client import get_openrouter_client
        
        supabase_client = get_supabase_client()
        organization_id = client.get("organization_id", "00000000-0000-0000-0000-000000000001")
        
        context_units = []
        for cu_id in context_unit_ids:
            result = supabase_client.client.table("press_context_units")\
                .select("*")\
                .eq("id", cu_id)\
                .eq("company_id", client["company_id"])\
                .maybe_single()\
                .execute()
            
            if result.data:
                context_units.append(result.data)
        
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
        for cu in context_units:
            cu_title = cu.get("title", "Sin título")
            cu_summary = cu.get("summary", "")
            statements = cu.get("atomic_statements", [])
            
            source_text_parts.append(f"## {cu_title}")
            if cu_summary:
                source_text_parts.append(f"Resumen: {cu_summary}")
            
            if statements:
                source_text_parts.append("Hechos atómicos:")
                for stmt in statements:
                    stmt_text = stmt.get("text", "") if isinstance(stmt, dict) else str(stmt)
                    source_text_parts.append(f"- {stmt_text}")
            
            source_text_parts.append("")
        
        source_text = "\n".join(source_text_parts)
        
        openrouter = get_openrouter_client()
        result = await openrouter.redact_news_rich(
            source_text=source_text,
            title_suggestion=title or "",
            instructions=instructions or "",
            style_guide=style_guide,
            language=language,
            organization_id=organization_id,
            client_id=client["client_id"]
        )
        
        result["sources"] = [
            {
                "id": cu["id"],
                "title": cu.get("title", ""),
                "summary": cu.get("summary", ""),
                "created_at": cu.get("created_at", "")
            }
            for cu in context_units
        ]
        result["statements_count"] = len(all_statements)
        
        return result
        
    except Exception as e:
        logger.error("redact_news_rich_workflow_error", error=str(e))
        raise