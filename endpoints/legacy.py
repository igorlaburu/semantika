"""Legacy endpoints (ingestion, search, aggregate, tasks, sources, context-units).

These endpoints are maintained for backwards compatibility.
Prefer using the newer /api/v1/* endpoints for new integrations.
"""

from datetime import datetime
from typing import Dict, Optional, Any, List
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_auth_context
from utils.unified_context_ingester import ingest_context_unit
from core_ingest import IngestPipeline

logger = get_logger("api.legacy")
router = APIRouter(tags=["legacy"])

# Get global supabase client for some endpoints
supabase_client = get_supabase_client()


# ============================================
# PYDANTIC MODELS
# ============================================

class IngestTextRequest(BaseModel):
    """Request model for text ingestion."""
    text: str
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    skip_guardrails: bool = False


class IngestURLRequest(BaseModel):
    """Request model for URL ingestion."""
    url: str
    extract_multiple: bool = False
    skip_guardrails: bool = False


class CreateTaskRequest(BaseModel):
    """Request model for creating a task."""
    source_type: str
    target: str
    frequency_min: int
    config: Optional[Dict[str, Any]] = None


class CreateContextUnitRequest(BaseModel):
    """Request model for creating context unit from text."""
    text: str
    title: Optional[str] = None
    images: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Array of images with base64 data and filename",
        example=[
            {
                "base64": "data:image/jpeg;base64,/9j/4AAQ...",
                "filename": "imagen1.jpg"
            }
        ]
    )


class CreateContextUnitFromURLRequest(BaseModel):
    """Request model for creating context unit from URL."""
    url: str
    title: Optional[str] = None


# ============================================
# INGESTION ENDPOINTS
# ============================================

@router.post("/ingest/text")
async def ingest_text(
    request: IngestTextRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Ingest text document (LEGACY - use POST /context-units instead).

    Requires: X-API-Key header

    Body:
        - text: Document text (required)
        - title: Document title (optional)
        - metadata: Custom metadata (optional)
        - skip_guardrails: Skip PII/Copyright checks (default: false)

    Returns:
        Ingestion result with stats
    """
    try:
        supabase = get_supabase_client()

        # Get company for client
        company_result = supabase.client.table("companies")\
            .select("*")\
            .eq("id", auth["company_id"])\
            .maybe_single()\
            .execute()

        if not company_result.data:
            raise HTTPException(status_code=404, detail="Company not found")

        company = company_result.data

        # Use unified ingester
        ingest_result = await ingest_context_unit(
            # Input
            raw_text=request.text,
            title=request.title,

            # Required metadata
            company_id=company["id"],
            source_type="api",
            source_id=f"legacy_ingest_{auth['client_id'][:8]}",

            # Optional metadata
            source_metadata={
                "legacy_endpoint": "/ingest/text",
                "client_id": auth["client_id"],
                "custom_metadata": request.metadata or {},
                "skip_guardrails": request.skip_guardrails
            },

            # Control flags
            generate_embedding_flag=True,
            check_duplicates=True
        )

        if ingest_result["success"]:
            return {
                "success": True,
                "context_unit_id": ingest_result["context_unit_id"],
                "generated_fields": ingest_result.get("generated_fields", []),
                "message": "Text ingested successfully"
            }
        elif ingest_result.get("duplicate"):
            return {
                "success": False,
                "duplicate": True,
                "duplicate_id": ingest_result.get("duplicate_id"),
                "similarity": ingest_result.get("similarity"),
                "message": "Duplicate content detected"
            }
        else:
            raise HTTPException(status_code=500, detail=ingest_result.get("error", "Unknown error"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("ingest_text_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/url")
async def ingest_url(
    request: IngestURLRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Scrape URL and ingest content (LEGACY - use POST /context-units/from-url instead).

    Requires: X-API-Key header

    Body:
        - url: URL to scrape (required)
        - extract_multiple: Extract multiple articles from page (default: false)
        - skip_guardrails: Skip PII/Copyright checks (default: false)

    Returns:
        Scraping and ingestion results
    """
    try:
        from sources.web_scraper import WebScraper

        supabase = get_supabase_client()

        # Get company for client
        company_result = supabase.client.table("companies")\
            .select("*")\
            .eq("id", auth["company_id"])\
            .maybe_single()\
            .execute()

        if not company_result.data:
            raise HTTPException(status_code=404, detail="Company not found")

        company = company_result.data

        # Scrape URL
        scraper = WebScraper()
        scrape_results = await scraper.scrape_url(
            request.url,
            extract_multiple=request.extract_multiple
        )

        if not scrape_results or len(scrape_results) == 0:
            raise HTTPException(status_code=400, detail="Failed to scrape URL or no content found")

        # Ingest all scraped results
        ingested_units = []
        duplicates = []
        errors = []

        for i, scraped_data in enumerate(scrape_results):
            scraped_text = scraped_data.get("text", "")
            scraped_title = scraped_data.get("title", "")

            if not scraped_text:
                errors.append({
                    "index": i,
                    "error": "No content extracted"
                })
                continue

            # Use unified ingester
            ingest_result = await ingest_context_unit(
                # Input
                raw_text=scraped_text,
                title=scraped_title,

                # Required metadata
                company_id=company["id"],
                source_type="api",
                source_id=f"legacy_url_{auth['client_id'][:8]}_{i}",

                # Optional metadata
                source_metadata={
                    "legacy_endpoint": "/ingest/url",
                    "client_id": auth["client_id"],
                    "url": request.url,
                    "extract_multiple": request.extract_multiple,
                    "skip_guardrails": request.skip_guardrails,
                    "article_index": i
                },

                # Control flags
                generate_embedding_flag=True,
                check_duplicates=True
            )

            if ingest_result["success"]:
                ingested_units.append({
                    "context_unit_id": ingest_result["context_unit_id"],
                    "title": scraped_title,
                    "generated_fields": ingest_result.get("generated_fields", [])
                })
            elif ingest_result.get("duplicate"):
                duplicates.append({
                    "index": i,
                    "duplicate_id": ingest_result.get("duplicate_id"),
                    "similarity": ingest_result.get("similarity"),
                    "title": scraped_title
                })
            else:
                errors.append({
                    "index": i,
                    "error": ingest_result.get("error", "Unknown error"),
                    "title": scraped_title
                })

        return {
            "success": True,
            "url": request.url,
            "total_scraped": len(scrape_results),
            "ingested": len(ingested_units),
            "duplicates": len(duplicates),
            "errors": len(errors),
            "units": ingested_units,
            "duplicate_details": duplicates,
            "error_details": errors
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("ingest_url_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# SEARCH ENDPOINTS
# ============================================

@router.get("/search")
async def search(
    query: str,
    limit: int = 5,
    source: Optional[str] = None,
    auth: Dict = Depends(get_auth_context)
) -> List[Dict[str, Any]]:
    """
    Semantic search in documents.

    Requires: X-API-Key header

    Query params:
        - query: Search query (required)
        - limit: Maximum results (default: 5)
        - source: Filter by source (optional)

    Returns:
        List of matching documents with scores
    """
    try:
        pipeline = IngestPipeline(client_id=auth["client_id"])

        filters = {}
        if source:
            filters["source"] = source

        results = await pipeline.search(
            query=query,
            limit=limit,
            filters=filters if filters else None
        )

        return results

    except Exception as e:
        logger.error("search_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aggregate")
async def aggregate(
    query: str,
    limit: int = 10,
    threshold: float = 0.7,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Search and aggregate documents with LLM summary.

    Requires: X-API-Key header

    Query params:
        - query: Search query (required)
        - limit: Maximum documents to retrieve (default: 10)
        - threshold: Minimum similarity score (default: 0.7)

    Returns:
        Summary and source documents
    """
    try:
        pipeline = IngestPipeline(client_id=auth["client_id"])

        result = await pipeline.aggregate(
            query=query,
            limit=limit,
            threshold=threshold
        )

        return result

    except Exception as e:
        logger.error("aggregate_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# TASK MANAGEMENT ENDPOINTS
# ============================================

@router.post("/tasks")
async def create_task(
    request: CreateTaskRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Create a new scheduled task.

    Requires: X-API-Key header

    Body:
        - source_type: Type of source (web_llm, twitter, api_efe, etc.)
        - target: URL, query, or endpoint to scrape
        - frequency_min: Frequency in minutes
        - config: Optional configuration (optional)

    Returns:
        Created task information
    """
    try:
        task = await supabase_client.create_task(
            client_id=auth["client_id"],
            company_id=auth["company_id"],
            source_type=request.source_type,
            target=request.target,
            frequency_min=request.frequency_min,
            config=request.config
        )

        return {
            "status": "ok",
            "task_id": task["task_id"],
            "source_type": task["source_type"],
            "target": task["target"],
            "frequency_min": task["frequency_min"],
            "is_active": task["is_active"],
            "created_at": task["created_at"]
        }

    except Exception as e:
        logger.error("create_task_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def list_tasks(
    auth: Dict = Depends(get_auth_context)
) -> List[Dict[str, Any]]:
    """
    List all tasks for authenticated client.

    Requires: X-API-Key header

    Returns:
        List of tasks
    """
    try:
        tasks = await supabase_client.get_tasks_by_client(auth["client_id"], auth["company_id"])
        return tasks

    except Exception as e:
        logger.error("list_tasks_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executions")
async def get_executions(
    auth: Dict = Depends(get_auth_context),
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Get execution logs for authenticated client.

    Requires: X-API-Key header

    Query params:
        - limit: Maximum results (default: 100)
        - offset: Offset for pagination (default: 0)

    Returns:
        List of executions
    """
    try:
        supabase = get_supabase_client()

        # Get executions for this client
        result = supabase.client.table("executions")\
            .select("*")\
            .eq("client_id", auth["client_id"])\
            .order("timestamp", desc=True)\
            .limit(limit)\
            .offset(offset)\
            .execute()

        return result.data

    except Exception as e:
        logger.error("get_executions_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, str]:
    """
    Delete a task.

    Requires: X-API-Key header

    Path params:
        - task_id: UUID of the task to delete

    Returns:
        Status message
    """
    try:
        # Verify task belongs to client and company (automatic filtering)
        task = await supabase_client.get_task_by_id(task_id, auth["company_id"])
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if task["client_id"] != auth["client_id"]:
            raise HTTPException(status_code=403, detail="Not authorized to delete this task")

        await supabase_client.delete_task(task_id, auth["company_id"])

        return {
            "status": "ok",
            "message": "Task deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_task_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# SOURCE MANAGEMENT ENDPOINTS
# ============================================

@router.get("/sources")
async def get_sources(
    auth: Dict = Depends(get_auth_context),
    source_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get all information sources for authenticated client.

    Requires: X-API-Key header

    Query params:
        - source_type: Filter by source type (email, scraping, webhook, etc.)

    Returns:
        List of sources with configuration
    """
    try:
        supabase = get_supabase_client()
        sources = await supabase.get_sources_by_client(auth["client_id"], source_type)
        return sources

    except Exception as e:
        logger.error("get_sources_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources")
async def create_source(
    request: Dict[str, Any],
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Create a new information source.

    Requires: X-API-Key header

    Body:
        - source_code: Unique code for this client
        - source_name: Display name
        - source_type: Type (email, scraping, webhook, etc.)
        - config: Source-specific configuration
        - workflow_code: Optional workflow to use
        - schedule_config: Optional scheduling configuration

    Returns:
        Created source
    """
    try:
        supabase = get_supabase_client()

        source_data = {
            "client_id": auth["client_id"],
            "company_id": auth.get("company_id"),
            "source_code": request["source_code"],
            "source_name": request["source_name"],
            "source_type": request["source_type"],
            "config": request.get("config", {}),
            "workflow_code": request.get("workflow_code"),
            "schedule_config": request.get("schedule_config"),
            "description": request.get("description"),
            "is_active": request.get("is_active", True)
        }

        result = supabase.client.table("sources").insert(source_data).execute()

        if result.data and len(result.data) > 0:
            return result.data[0]
        else:
            raise HTTPException(status_code=400, detail="Failed to create source")

    except Exception as e:
        logger.error("create_source_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/sources/{source_id}")
async def update_source(
    source_id: str,
    request: Dict[str, Any],
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Update an existing information source.

    Requires: X-API-Key header

    Path params:
        - source_id: UUID of the source to update

    Body (all optional):
        - source_name: Display name
        - config: Source-specific configuration
        - workflow_code: Workflow to use
        - schedule_config: Scheduling configuration
        - description: Source description
        - is_active: Enable/disable source

    Returns:
        Updated source
    """
    try:
        supabase = get_supabase_client()

        # Verify source belongs to client
        existing_source = supabase.client.table("sources")\
            .select("*")\
            .eq("source_id", source_id)\
            .eq("client_id", auth["client_id"])\
            .maybe_single()\
            .execute()

        if not existing_source.data:
            raise HTTPException(status_code=404, detail="Source not found")

        # Prepare update data (only include provided fields)
        update_data = {}
        for field in ["source_name", "config", "workflow_code", "schedule_config", "description", "is_active"]:
            if field in request:
                update_data[field] = request[field]

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Update source
        result = supabase.client.table("sources")\
            .update(update_data)\
            .eq("source_id", source_id)\
            .eq("client_id", auth["client_id"])\
            .execute()

        if result.data and len(result.data) > 0:
            logger.info("source_updated",
                source_id=source_id,
                client_id=auth["client_id"],
                updated_fields=list(update_data.keys())
            )
            return result.data[0]
        else:
            raise HTTPException(status_code=400, detail="Failed to update source")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_source_error", source_id=source_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CONTEXT UNIT ENDPOINTS (OLD API)
# ============================================

@router.get("/context-units")
async def get_context_units(
    limit: int = 20,
    offset: int = 0,
    auth: Dict = Depends(get_auth_context)
) -> List[Dict[str, Any]]:
    """
    Get context units for authenticated client.

    Requires: X-API-Key header

    Query params:
        - limit: Maximum results (default: 20)
        - offset: Offset for pagination (default: 0)

    Returns:
        List of context units
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table("press_context_units")\
            .select("*")\
            .eq("company_id", auth["company_id"])\
            .order("created_at", desc=True)\
            .limit(limit)\
            .offset(offset)\
            .execute()

        return result.data or []

    except Exception as e:
        logger.error("get_context_units_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context-units")
async def create_context_unit(
    request: CreateContextUnitRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Create a context unit from plain text (manual entry).

    Use this endpoint to manually add context from:
    - Pasted text from clipboard
    - Dragged/uploaded text files
    - Manual text entry in UI
    - Any plain text source

    Workflow:
    1. Receives plain text (and optional title)
    2. Processes through default workflow (generates context unit with LLM)
    3. Saves to press_context_units table with source_type="manual"
    4. Returns created context unit

    Requires: X-API-Key header

    Body:
        - text: Plain text content (required)
        - title: Optional title suggestion (if not provided, LLM generates it)

    Returns:
        Created context unit with id, title, summary, tags, atomic_statements
    """
    start_time = datetime.utcnow()

    try:
        from workflows.workflow_factory import get_workflow
        from core.source_content import SourceContent
        import uuid

        logger.info(
            "manual_context_unit_request",
            client_id=auth["client_id"],
            text_length=len(request.text),
            has_title=bool(request.title)
        )

        # Get company and organization
        supabase = get_supabase_client()

        company_result = supabase.client.table("companies")\
            .select("*")\
            .eq("id", auth["company_id"])\
            .maybe_single()\
            .execute()

        if not company_result.data:
            raise HTTPException(status_code=404, detail="Company not found")

        company = company_result.data

        org_result = supabase.client.table("organizations")\
            .select("*")\
            .eq("company_id", company["id"])\
            .eq("is_active", True)\
            .limit(1)\
            .execute()

        if not org_result.data:
            raise HTTPException(status_code=404, detail="No active organization found")

        organization = org_result.data[0]

        # Create SourceContent
        # Use company_id as source_id (Manual source always has source.id = company.id)
        context_unit_id = str(uuid.uuid4())
        source_content = SourceContent(
            source_type="manual",
            source_id=company["id"],  # KEY: Manual source.id = company.id
            organization_slug=organization["slug"],
            text_content=request.text,
            metadata={
                "manual_entry": True,
                "client_id": auth["client_id"],
                "company_id": company["id"]
            },
            title=request.title or None
        )
        # Set ID manually after creation
        source_content.id = context_unit_id

        # Use unified ingester (API endpoints skip novelty verification)
        ingest_result = await ingest_context_unit(
            # Input
            raw_text=request.text,
            title=request.title,  # Pre-generated title (optional)

            # LLM will generate: summary, tags, category, atomic_statements (if needed)

            # Required metadata
            company_id=company["id"],
            source_type="manual",
            source_id=company["id"],  # KEY: Manual source.id = company.id

            # Optional metadata
            source_metadata={
                "manual_entry": True,
                "client_id": auth["client_id"],
                "created_via": "api",
                "has_custom_title": bool(request.title),
                "organization_id": organization["id"]
            },

            # Control flags
            generate_embedding_flag=True,
            check_duplicates=True  # Semantic dedup even for manual
        )

        if not ingest_result["success"]:
            error_msg = ingest_result.get("error", "Unknown error")
            if ingest_result.get("duplicate"):
                logger.warn(
                    "manual_context_unit_duplicate",
                    client_id=auth["client_id"],
                    duplicate_id=ingest_result.get("duplicate_id"),
                    similarity=ingest_result.get("similarity")
                )
                # Return existing unit
                existing_result = supabase.client.table("press_context_units")\
                    .select("*")\
                    .eq("id", ingest_result["duplicate_id"])\
                    .single()\
                    .execute()
                created_unit = existing_result.data if existing_result.data else {}
            else:
                raise HTTPException(status_code=500, detail=f"Failed to create context unit: {error_msg}")
        else:
            # Fetch created unit
            created_result = supabase.client.table("press_context_units")\
                .select("*")\
                .eq("id", ingest_result["context_unit_id"])\
                .single()\
                .execute()
            created_unit = created_result.data if created_result.data else {}

        logger.info(
            "manual_context_unit_created",
            client_id=auth["client_id"],
            context_unit_id=created_unit["id"],
            title=created_unit.get("title", "")
        )

        # Process images if provided
        images_saved = []
        if request.images:
            try:
                from utils.context_unit_images import ContextUnitImageProcessor

                logger.info("processing_context_unit_images",
                    context_unit_id=created_unit["id"],
                    image_count=len(request.images)
                )

                images_saved = await ContextUnitImageProcessor.save_context_unit_images(
                    context_unit_id=created_unit["id"],
                    images=request.images
                )

                # Update context unit metadata with image info
                if images_saved:
                    image_metadata = {
                        "has_manual_images": True,
                        "image_count": len(images_saved),
                        "image_sources": ["user_upload"] * len(images_saved),
                        "cached_images": [Path(p).stem for p in images_saved]  # Remove extension, keep only filename
                    }

                    # Update source_metadata
                    current_metadata = created_unit.get("source_metadata", {})
                    current_metadata.update(image_metadata)

                    supabase.client.table("press_context_units")\
                        .update({"source_metadata": current_metadata})\
                        .eq("id", created_unit["id"])\
                        .execute()

                    created_unit["source_metadata"] = current_metadata

                    logger.info("context_unit_images_metadata_updated",
                        context_unit_id=created_unit["id"],
                        images_saved=len(images_saved)
                    )

            except Exception as e:
                logger.error("process_context_unit_images_error",
                    context_unit_id=created_unit["id"],
                    error=str(e)
                )
                # Don't fail the whole request if image processing fails

        # Log execution
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        await supabase.log_execution(
            client_id=auth["client_id"],
            company_id=company["id"],
            source_name="Manual Text Entry",
            source_type="manual",
            items_count=1,
            status_code=200,
            status="success",
            details=f"Context unit created: {created_unit.get('title', 'Untitled')}",
            metadata={
                "context_unit_id": created_unit["id"],
                "text_length": len(request.text),
                "has_custom_title": bool(request.title),
                "created_via": "api"
            },
            duration_ms=duration_ms,
            workflow_code="default"
        )

        return {
            "success": True,
            "context_unit": created_unit,
            "images_saved": len(images_saved),
            "image_paths": images_saved if images_saved else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_context_unit_error", error=str(e), client_id=auth["client_id"])

        # Log failed execution
        try:
            supabase = get_supabase_client()
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            await supabase.log_execution(
                client_id=auth["client_id"],
                company_id=auth["company_id"],
                source_name="Manual Text Entry",
                source_type="manual",
                items_count=0,
                status_code=500,
                status="error",
                details=f"Failed to create context unit: {str(e)}",
                error_message=str(e),
                metadata={
                    "text_length": len(request.text),
                    "has_custom_title": bool(request.title),
                    "error_type": type(e).__name__
                },
                duration_ms=duration_ms,
                workflow_code="default"
            )
        except:
            pass

        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context-units/from-url")
async def create_context_unit_from_url(
    request: CreateContextUnitFromURLRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Create a context unit from a URL (intelligent web scraping).

    Use this endpoint to automatically scrape and process web content:
    - News articles
    - Blog posts
    - Press releases
    - Any public web page

    Workflow (LangGraph scraper_workflow):
    1. Fetch URL with aiohttp
    2. Parse content (title, summary, text)
    3. Multi-tier change detection (hash → simhash → embeddings)
    4. Multi-source date extraction (meta tags, JSON-LD, URL, LLM)
    5. Filter content (decide if should ingest)
    6. Save to monitored_urls (tracking)
    7. Save to url_content_units (content)
    8. Create press_context_unit (with embeddings + category)

    Features:
    - Intelligent change detection
    - Multi-noticia support (one URL, multiple news items)
    - Automatic duplicate prevention
    - Publication date extraction
    - Category classification

    Requires: X-API-Key header

    Body:
        - url: URL to scrape (required)
        - title: Optional title override (currently ignored by workflow)

    Returns:
        Created context unit with id, title, summary, tags, atomic_statements
        Plus workflow_metadata with change detection info
    """
    start_time = datetime.utcnow()

    try:
        from sources.scraper_workflow import scrape_url
        import uuid

        logger.info(
            "url_context_unit_request",
            client_id=auth["client_id"],
            url=request.url,
            has_title=bool(request.title)
        )

        # Get company
        supabase = get_supabase_client()

        company_result = supabase.client.table("companies")\
            .select("*")\
            .eq("id", auth["company_id"])\
            .maybe_single()\
            .execute()

        if not company_result.data:
            raise HTTPException(status_code=404, detail="Company not found")

        company = company_result.data

        # Use new LangGraph scraper workflow
        # Use company_id as source_id (Manual source always has source.id = company.id)
        source_id = company["id"]
        workflow_result = await scrape_url(
            company_id=company["id"],
            source_id=source_id,
            url=request.url,
            url_type="article"
        )

        # Check for workflow errors
        if workflow_result.get("error"):
            logger.error("scraper_workflow_error",
                url=request.url,
                error=workflow_result["error"]
            )
            raise HTTPException(
                status_code=400,
                detail=f"Failed to scrape URL: {workflow_result['error']}"
            )

        # Check if context units were created
        context_unit_ids = workflow_result.get("context_unit_ids", [])
        if not context_unit_ids:
            change_type = workflow_result.get("change_info", {}).get("change_type", "unknown")
            logger.warn("no_context_units_created",
                url=request.url,
                change_type=change_type
            )
            raise HTTPException(
                status_code=400,
                detail=f"No content extracted from URL (change_type: {change_type})"
            )

        # Get first context unit ID (workflow can create multiple for multi-noticia)
        context_unit_id = context_unit_ids[0]

        # Fetch created context unit
        created_result = supabase.client.table("press_context_units")\
            .select("*")\
            .eq("id", context_unit_id)\
            .single()\
            .execute()

        if not created_result.data:
            raise HTTPException(status_code=500, detail="Context unit was created but not found in database")

        created_unit = created_result.data

        logger.info(
            "url_context_unit_created",
            client_id=auth["client_id"],
            context_unit_id=created_unit["id"],
            url=request.url,
            title=created_unit.get("title", ""),
            workflow_used="scraper_workflow"
        )

        # Log execution
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        await supabase.log_execution(
            client_id=auth["client_id"],
            company_id=company["id"],
            source_name="Manual URL Scraping",
            source_type="scraping",
            items_count=len(context_unit_ids),
            status_code=200,
            status="success",
            details=f"URL scraped via intelligent workflow: {created_unit.get('title', 'Untitled')}",
            metadata={
                "context_unit_id": created_unit["id"],
                "url": request.url,
                "context_units_created": len(context_unit_ids),
                "change_type": workflow_result.get("change_info", {}).get("change_type"),
                "monitored_url_id": workflow_result.get("monitored_url_id"),
                "has_custom_title": bool(request.title),
                "created_via": "api",
                "workflow": "scraper_workflow"
            },
            duration_ms=duration_ms,
            workflow_code="scraper_workflow"
        )

        return {
            "success": True,
            "context_unit": created_unit,
            "scraped_url": request.url,
            "workflow_metadata": {
                "context_units_created": len(context_unit_ids),
                "change_type": workflow_result.get("change_info", {}).get("change_type"),
                "monitored_url_id": workflow_result.get("monitored_url_id")
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_context_unit_from_url_error", error=str(e), client_id=auth["client_id"], url=request.url)

        # Log failed execution
        try:
            supabase = get_supabase_client()
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            await supabase.log_execution(
                client_id=auth["client_id"],
                company_id=auth["company_id"],
                source_name="Manual URL Scraping",
                source_type="scraping",
                items_count=0,
                status_code=500,
                status="error",
                details=f"Failed to scrape URL and create context unit: {str(e)}",
                error_message=str(e),
                metadata={
                    "url": request.url,
                    "has_custom_title": bool(request.title),
                    "error_type": type(e).__name__
                },
                duration_ms=duration_ms,
                workflow_code="default"
            )
        except:
            pass

        raise HTTPException(status_code=500, detail=str(e))
