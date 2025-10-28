"""FastAPI server for semantika API.

Handles all HTTP requests for document ingestion, search, and aggregation.
"""

from datetime import datetime
from typing import Dict, Optional, Any, List

from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client
from core_ingest import IngestPipeline

# Initialize logger
logger = get_logger("api")

# Initialize Supabase client
supabase_client = get_supabase_client()

# Initialize FastAPI app
app = FastAPI(
    title="semantika API",
    description="Semantic data pipeline with multi-tenant support and task scheduling",
    version="0.1.1",
    docs_url="/docs",
    redoc_url="/redoc"
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests."""
    start_time = datetime.utcnow()

    # Log request
    logger.info(
        "request_received",
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host if request.client else None
    )

    # Process request
    response = await call_next(request)

    # Calculate duration
    duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

    # Log response
    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2)
    )

    return response


# ============================================
# AUTHENTICATION
# ============================================

async def get_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """Extract API key from header."""
    if not x_api_key:
        logger.warn("missing_api_key")
        raise HTTPException(status_code=401, detail="Missing API Key")
    return x_api_key


async def get_current_client(api_key: str = Depends(get_api_key)) -> Dict:
    """
    Get current authenticated client from API key.

    Args:
        api_key: API key from header

    Returns:
        Client data

    Raises:
        HTTPException: If API key is invalid
    """
    client = await supabase_client.get_client_by_api_key(api_key)

    if not client:
        logger.warn("invalid_api_key", api_key_prefix=api_key[:10])
        raise HTTPException(status_code=403, detail="Invalid API Key")

    logger.debug("client_authenticated", client_id=client["client_id"])
    return client


# ============================================
# STARTUP/SHUTDOWN
# ============================================

@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    logger.info(
        "server_starting",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    logger.info("server_stopping")


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """
    Health check endpoint.

    Returns:
        Status and timestamp
    """
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": "semantika-api",
        "version": "0.1.0"
    }


@app.get("/")
async def root() -> Dict[str, str]:
    """
    Root endpoint with API information.

    Returns:
        API metadata
    """
    return {
        "name": "semantika API",
        "version": "0.1.0",
        "description": "Semantic data pipeline with multi-tenant support",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/me")
async def get_me(client: Dict = Depends(get_current_client)) -> Dict:
    """
    Get current authenticated client information.

    Requires: X-API-Key header

    Returns:
        Client information
    """
    return {
        "client_id": client["client_id"],
        "client_name": client["client_name"],
        "email": client.get("email"),
        "is_active": client["is_active"],
        "created_at": client["created_at"]
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to log all errors."""
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        method=request.method
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "path": request.url.path
        }
    )


# ============================================
# PYDANTIC MODELS
# ============================================

class IngestTextRequest(BaseModel):
    """Request model for text ingestion."""
    text: str
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    skip_guardrails: bool = False


class SearchRequest(BaseModel):
    """Request model for search."""
    query: str
    limit: int = 5
    filters: Optional[Dict[str, Any]] = None


class AggregateRequest(BaseModel):
    """Request model for aggregation."""
    query: str
    limit: int = 10
    threshold: float = 0.7


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


class ProcessTextRequest(BaseModel):
    """Request model for stateless text processing."""
    text: str
    action: str
    params: Optional[Dict[str, Any]] = None


class ProcessURLRequest(BaseModel):
    """Request model for stateless URL processing."""
    url: str
    action: str
    params: Optional[Dict[str, Any]] = None


class GenerateStyleRequest(BaseModel):
    """Request model for style guide generation."""
    style_name: str
    urls: List[str]


# ============================================
# INGESTION ENDPOINTS
# ============================================

@app.post("/ingest/text")
async def ingest_text(
    request: IngestTextRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Ingest text document.

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
        pipeline = IngestPipeline(client_id=client["client_id"])

        result = await pipeline.ingest_text(
            text=request.text,
            title=request.title,
            metadata=request.metadata,
            skip_guardrails=request.skip_guardrails
        )

        return result

    except Exception as e:
        logger.error("ingest_text_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/url")
async def ingest_url(
    request: IngestURLRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Scrape URL and ingest content.

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

        scraper = WebScraper()

        result = await scraper.scrape_and_ingest(
            url=request.url,
            client_id=client["client_id"],
            extract_multiple=request.extract_multiple,
            skip_guardrails=request.skip_guardrails
        )

        return result

    except Exception as e:
        logger.error("ingest_url_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# SEARCH ENDPOINTS
# ============================================

@app.get("/search")
async def search(
    query: str,
    limit: int = 5,
    source: Optional[str] = None,
    client: Dict = Depends(get_current_client)
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
        pipeline = IngestPipeline(client_id=client["client_id"])

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


@app.get("/aggregate")
async def aggregate(
    query: str,
    limit: int = 10,
    threshold: float = 0.7,
    client: Dict = Depends(get_current_client)
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
        pipeline = IngestPipeline(client_id=client["client_id"])

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

@app.post("/tasks")
async def create_task(
    request: CreateTaskRequest,
    client: Dict = Depends(get_current_client)
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
            client_id=client["client_id"],
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


@app.get("/tasks")
async def list_tasks(
    client: Dict = Depends(get_current_client)
) -> List[Dict[str, Any]]:
    """
    List all tasks for authenticated client.

    Requires: X-API-Key header

    Returns:
        List of tasks
    """
    try:
        tasks = await supabase_client.get_tasks_by_client(client["client_id"])
        return tasks

    except Exception as e:
        logger.error("list_tasks_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    client: Dict = Depends(get_current_client)
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
        # Verify task belongs to client
        task = await supabase_client.get_task_by_id(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if task["client_id"] != client["client_id"]:
            raise HTTPException(status_code=403, detail="Not authorized to delete this task")

        await supabase_client.delete_task(task_id)

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
# STATELESS PROCESSING ENDPOINTS
# ============================================

@app.post("/process/analyze")
async def process_analyze(
    request: ProcessTextRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Analyze text and extract: title, summary, tags.

    Requires: X-API-Key header

    Body:
        - text: Text to analyze (required)
        - action: Must be "analyze"
        - params: Optional parameters (not used)

    Returns:
        Analysis result with title, summary, tags
    """
    try:
        from core_stateless import StatelessPipeline

        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id'),
            client_id=client['client_id']
        )

        result = await pipeline.analyze(request.text)

        return {
            "status": "ok",
            "action": "analyze",
            "result": result,
            "text_length": len(request.text)
        }

    except Exception as e:
        logger.error("process_analyze_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process/analyze-atomic")
async def process_analyze_atomic(
    request: ProcessTextRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Analyze text and extract: title, summary, tags, atomic facts.

    Requires: X-API-Key header

    Body:
        - text: Text to analyze (required)
        - action: Must be "analyze_atomic"
        - params: Optional parameters (not used)

    Returns:
        Analysis result with title, summary, tags, atomic_facts
    """
    try:
        from core_stateless import StatelessPipeline

        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id'),
            client_id=client['client_id']
        )

        result = await pipeline.analyze_atomic(request.text)

        return {
            "status": "ok",
            "action": "analyze_atomic",
            "result": result,
            "text_length": len(request.text)
        }

    except Exception as e:
        logger.error("process_analyze_atomic_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process/redact-news")
async def process_redact_news(
    request: ProcessTextRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Generate news article from text/facts with specific style.

    Requires: X-API-Key header

    Body:
        - text: Source text or atomic facts (required)
        - action: Must be "redact_news"
        - params: Optional parameters
          - style_guide: Markdown style guide (string)
          - language: Target language (default: "es")

    Returns:
        Generated article with title, summary, tags
    """
    try:
        from core_stateless import StatelessPipeline

        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id'),
            client_id=client['client_id']
        )

        params = request.params or {}
        style_guide = params.get("style_guide")
        language = params.get("language", "es")

        result = await pipeline.redact_news(
            text=request.text,
            style_guide=style_guide,
            language=language
        )

        return {
            "status": "ok",
            "action": "redact_news",
            "result": result,
            "text_length": len(request.text)
        }

    except Exception as e:
        logger.error("process_redact_news_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process/url")
async def process_url(
    request: ProcessURLRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Scrape URL and process content (stateless, no storage).

    Requires: X-API-Key header

    Body:
        - url: URL to scrape (required)
        - action: Action to perform (analyze, analyze_atomic, redact_news)
        - params: Optional parameters for the action

    Returns:
        Processing result
    """
    try:
        from core_stateless import StatelessPipeline

        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id'),
            client_id=client['client_id']
        )

        result = await pipeline.process_url(
            url=request.url,
            action=request.action,
            params=request.params
        )

        return {
            "status": "ok",
            "url": request.url,
            "action": request.action,
            "result": result
        }

    except Exception as e:
        logger.error("process_url_error", error=str(e), url=request.url)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/styles/generate")
async def generate_style_guide(
    request: GenerateStyleRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Generate writing style guide from example articles.

    Requires: X-API-Key header

    Body:
        - style_name: Name for this style (required)
        - urls: List of URLs to analyze (3-20 articles recommended)

    Returns:
        Style guide in Markdown format with examples

    Note: This endpoint may take 1-3 minutes depending on number of URLs.
    """
    try:
        from core_stateless import StatelessPipeline
        from datetime import datetime

        if len(request.urls) < 1:
            raise HTTPException(
                status_code=400,
                detail="At least 1 URL required for style analysis"
            )

        if len(request.urls) > 10:
            raise HTTPException(
                status_code=400,
                detail="Maximum 10 URLs allowed"
            )

        pipeline = StatelessPipeline(
            organization_id=client.get('organization_id'),
            client_id=client['client_id']
        )

        result = await pipeline.generate_style_guide(
            urls=request.urls,
            style_name=request.style_name
        )

        result["generated_at"] = datetime.utcnow().isoformat() + "Z"

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("generate_style_guide_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    logger.info("starting_uvicorn", host=settings.api_host, port=settings.api_port)

    uvicorn.run(
        "server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level.lower()
    )
