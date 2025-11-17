"""FastAPI server for semantika API.

Handles all HTTP requests for document ingestion, search, and aggregation.

Version: 2025-10-28
"""

from datetime import datetime
from typing import Dict, Optional, Any, List
import subprocess
import io

from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client
from utils.usage_tracker import get_usage_tracker
from core_ingest import IngestPipeline

# Initialize logger
logger = get_logger("api")

# Initialize Supabase client
supabase_client = get_supabase_client()

# Initialize FastAPI app
app = FastAPI(
    title="semantika API",
    description="Semantic data pipeline with multi-tenant support and task scheduling",
    version="0.1.2",
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


# ============================================
# AUTHENTICATION ENDPOINTS (Supabase Auth)
# ============================================

class LoginRequest(BaseModel):
    """Request model for login."""
    email: str
    password: str


class RefreshTokenRequest(BaseModel):
    """Request model for token refresh."""
    refresh_token: str


@app.post("/auth/login")
async def auth_login(request: LoginRequest) -> Dict:
    """
    Login with email and password using Supabase Auth.

    Returns JWT access token and refresh token.

    Body:
        - email: User email
        - password: User password

    Returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600,
            "user": {...}
        }
    """
    try:
        # Use Supabase auth to login
        from gotrue import SyncGoTrueClient

        auth_client = SyncGoTrueClient(
            url=f"{settings.supabase_url}/auth/v1",
            headers={
                "apikey": settings.supabase_key,
                "Authorization": f"Bearer {settings.supabase_key}"
            }
        )

        response = auth_client.sign_in_with_password({
            "email": request.email,
            "password": request.password
        })

        if not response.session:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        logger.info("user_logged_in",
            email=request.email,
            user_id=response.user.id
        )

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in,
            "user": {
                "id": response.user.id,
                "email": response.user.email,
                "created_at": response.user.created_at
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("login_error", error=str(e))
        raise HTTPException(status_code=500, detail="Login failed")


@app.post("/auth/refresh")
async def auth_refresh(request: RefreshTokenRequest) -> Dict:
    """
    Refresh access token using refresh token.

    Body:
        - refresh_token: Valid refresh token

    Returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600
        }
    """
    try:
        from gotrue import SyncGoTrueClient

        auth_client = SyncGoTrueClient(
            url=f"{settings.supabase_url}/auth/v1",
            headers={
                "apikey": settings.supabase_key,
                "Authorization": f"Bearer {settings.supabase_key}"
            }
        )

        response = auth_client.refresh_session(request.refresh_token)

        if not response.session:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("refresh_token_error", error=str(e))
        raise HTTPException(status_code=500, detail="Token refresh failed")


@app.post("/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(None)) -> Dict:
    """
    Logout current user (invalidate token).

    Requires: Authorization header with Bearer token

    Returns:
        {"success": true}
    """
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header required")

        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization header")

        token = parts[1]

        from gotrue import SyncGoTrueClient

        auth_client = SyncGoTrueClient(
            url=f"{settings.supabase_url}/auth/v1",
            headers={
                "apikey": settings.supabase_key,
                "Authorization": f"Bearer {token}"
            }
        )

        auth_client.sign_out()

        logger.info("user_logged_out")

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("logout_error", error=str(e))
        raise HTTPException(status_code=500, detail="Logout failed")


@app.get("/auth/user")
async def auth_get_user() -> Dict:
    """
    Get current authenticated user info (from JWT).

    Requires: Authorization header with Bearer token

    Returns:
        User information including company_id, role, etc.
    """
    from utils.supabase_auth import get_current_user_from_jwt

    user = await get_current_user_from_jwt()

    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name"),
        "company_id": user["company_id"],
        "organization_id": user.get("organization_id"),
        "role": user.get("role"),
        "is_active": user["is_active"]
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


class MicroEditRequest(BaseModel):
    """Request model for micro-editing."""
    text: str
    command: str
    context: Optional[str] = None
    params: Optional[Dict[str, Any]] = {}


class RedactNewsRichRequest(BaseModel):
    """Request model for rich news redaction from context units."""
    context_unit_ids: List[str]
    title: Optional[str] = None
    instructions: Optional[str] = None
    style_guide: Optional[str] = None
    language: str = "es"


class CreateContextUnitRequest(BaseModel):
    """Request model for creating context unit from text."""
    text: str
    title: Optional[str] = None


class CreateContextUnitFromURLRequest(BaseModel):
    """Request model for creating context unit from URL."""
    url: str
    title: Optional[str] = None


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
            company_id=client["company_id"],
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
        tasks = await supabase_client.get_tasks_by_client(client["client_id"], client["company_id"])
        return tasks

    except Exception as e:
        logger.error("list_tasks_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/executions")
async def get_executions(
    client: Dict = Depends(get_current_client),
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
            .eq("client_id", client["client_id"])\
            .order("timestamp", desc=True)\
            .limit(limit)\
            .offset(offset)\
            .execute()
        
        return result.data
        
    except Exception as e:
        logger.error("get_executions_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sources")
async def get_sources(
    client: Dict = Depends(get_current_client),
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
        sources = await supabase.get_sources_by_client(client["client_id"], source_type)
        return sources
        
    except Exception as e:
        logger.error("get_sources_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sources")
async def create_source(
    request: Dict[str, Any],
    client: Dict = Depends(get_current_client)
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
            "client_id": client["client_id"],
            "company_id": client.get("company_id"),
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


@app.put("/sources/{source_id}")
async def update_source(
    source_id: str,
    request: Dict[str, Any],
    client: Dict = Depends(get_current_client)
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
            .eq("client_id", client["client_id"])\
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
            .eq("client_id", client["client_id"])\
            .execute()
        
        if result.data and len(result.data) > 0:
            logger.info("source_updated", 
                source_id=source_id,
                client_id=client["client_id"],
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


@app.get("/context-units")
async def get_context_units(
    limit: int = 20,
    offset: int = 0,
    client: Dict = Depends(get_current_client)
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
            .eq("company_id", client["company_id"])\
            .order("created_at", desc=True)\
            .limit(limit)\
            .offset(offset)\
            .execute()
        
        return result.data or []
        
    except Exception as e:
        logger.error("get_context_units_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/context-units")
async def create_context_unit(
    request: CreateContextUnitRequest,
    client: Dict = Depends(get_current_client)
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
            client_id=client["client_id"],
            text_length=len(request.text),
            has_title=bool(request.title)
        )
        
        # Get company and organization
        supabase = get_supabase_client()
        
        company_result = supabase.client.table("companies")\
            .select("*")\
            .eq("id", client["company_id"])\
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
        context_unit_id = str(uuid.uuid4())
        source_content = SourceContent(
            source_type="manual",
            source_id=f"manual_{context_unit_id[:8]}",
            organization_slug=organization["slug"],
            text_content=request.text,
            metadata={
                "manual_entry": True,
                "client_id": client["client_id"],
                "company_id": company["id"]
            },
            title=request.title or None
        )
        # Set ID manually after creation
        source_content.id = context_unit_id
        
        # Get workflow and process
        workflow = get_workflow("default", company.get("settings", {}))
        result = await workflow.process_content(source_content)
        
        # Extract context unit
        context_unit = result.get("context_unit", {})
        if not context_unit:
            raise HTTPException(status_code=500, detail="Failed to generate context unit")
        
        # Save to database
        context_unit_data = {
            "id": context_unit.get("id"),
            "organization_id": organization["id"],
            "company_id": company["id"],
            "source_type": "manual",
            "source_id": source_content.source_id,
            "source_metadata": {
                "manual_entry": True,
                "client_id": client["client_id"],
                "created_via": "api",
                "has_custom_title": bool(request.title)
            },
            "title": context_unit.get("title"),
            "summary": context_unit.get("summary"),
            "tags": context_unit.get("tags", []),
            "atomic_statements": context_unit.get("atomic_statements", []),
            "raw_text": request.text,
            "status": "completed",
            "processed_at": "now()"
        }
        
        db_result = supabase.client.table("press_context_units")\
            .insert(context_unit_data)\
            .execute()
        
        if not db_result.data:
            raise HTTPException(status_code=500, detail="Failed to save context unit")
        
        created_unit = db_result.data[0]
        
        logger.info(
            "manual_context_unit_created",
            client_id=client["client_id"],
            context_unit_id=created_unit["id"],
            title=created_unit.get("title", "")
        )
        
        # Log execution
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        await supabase.log_execution(
            client_id=client["client_id"],
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
            "context_unit": created_unit
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_context_unit_error", error=str(e), client_id=client["client_id"])
        
        # Log failed execution
        try:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            await supabase.log_execution(
                client_id=client["client_id"],
                company_id=client["company_id"],
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


@app.post("/context-units/from-url")
async def create_context_unit_from_url(
    request: CreateContextUnitFromURLRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Create a context unit from a URL (web scraping).
    
    Use this endpoint to automatically scrape and process web content:
    - News articles
    - Blog posts
    - Press releases
    - Any public web page
    
    Workflow:
    1. Receives URL (and optional title)
    2. Scrapes web page content using BeautifulSoup/LLM
    3. Processes through default workflow (generates context unit)
    4. Saves to press_context_units table with source_type="scraping"
    5. Returns created context unit
    
    Requires: X-API-Key header
    
    Body:
        - url: URL to scrape (required)
        - title: Optional title override (if not provided, extracted from page)
    
    Returns:
        Created context unit with id, title, summary, tags, atomic_statements
    """
    start_time = datetime.utcnow()
    
    try:
        from sources.web_scraper import WebScraper
        from workflows.workflow_factory import get_workflow
        from core.source_content import SourceContent
        import uuid
        
        logger.info(
            "url_context_unit_request",
            client_id=client["client_id"],
            url=request.url,
            has_title=bool(request.title)
        )
        
        # Get company and organization
        supabase = get_supabase_client()
        
        company_result = supabase.client.table("companies")\
            .select("*")\
            .eq("id", client["company_id"])\
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
        
        # Scrape URL
        scraper = WebScraper()
        scrape_results = await scraper.scrape_url(request.url, extract_multiple=False)
        
        if not scrape_results or len(scrape_results) == 0:
            raise HTTPException(status_code=400, detail="Failed to scrape URL or no content found")
        
        # Get first result (single article mode)
        scraped_data = scrape_results[0]
        scraped_text = scraped_data.get("text", "")
        scraped_title = scraped_data.get("title", "")
        
        if not scraped_text:
            raise HTTPException(status_code=400, detail="No content extracted from URL")
        
        # Use provided title or scraped title
        final_title = request.title or scraped_title or None
        
        # Create SourceContent
        context_unit_id = str(uuid.uuid4())
        source_content = SourceContent(
            source_type="scraping",
            source_id=f"scraping_{context_unit_id[:8]}",
            organization_slug=organization["slug"],
            text_content=scraped_text,
            metadata={
                "url": request.url,
                "scraped_title": scraped_title,
                "client_id": client["client_id"],
                "company_id": company["id"],
                "manual_scraping": True
            },
            title=final_title
        )
        # Set ID manually after creation
        source_content.id = context_unit_id
        
        # Get workflow and process
        workflow = get_workflow("default", company.get("settings", {}))
        result = await workflow.process_content(source_content)
        
        # Extract context unit
        context_unit = result.get("context_unit", {})
        if not context_unit:
            raise HTTPException(status_code=500, detail="Failed to generate context unit")
        
        # Save to database
        context_unit_data = {
            "id": context_unit.get("id"),
            "organization_id": organization["id"],
            "company_id": company["id"],
            "source_type": "scraping",
            "source_id": source_content.source_id,
            "source_metadata": {
                "url": request.url,
                "scraped_title": scraped_title,
                "client_id": client["client_id"],
                "created_via": "api",
                "manual_scraping": True,
                "has_custom_title": bool(request.title)
            },
            "title": context_unit.get("title"),
            "summary": context_unit.get("summary"),
            "tags": context_unit.get("tags", []),
            "atomic_statements": context_unit.get("atomic_statements", []),
            "raw_text": scraped_text,
            "status": "completed",
            "processed_at": "now()"
        }
        
        db_result = supabase.client.table("press_context_units")\
            .insert(context_unit_data)\
            .execute()
        
        if not db_result.data:
            raise HTTPException(status_code=500, detail="Failed to save context unit")
        
        created_unit = db_result.data[0]
        
        logger.info(
            "url_context_unit_created",
            client_id=client["client_id"],
            context_unit_id=created_unit["id"],
            url=request.url,
            title=created_unit.get("title", "")
        )
        
        # Log execution
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        await supabase.log_execution(
            client_id=client["client_id"],
            company_id=company["id"],
            source_name="Manual URL Scraping",
            source_type="scraping",
            items_count=1,
            status_code=200,
            status="success",
            details=f"URL scraped and context unit created: {created_unit.get('title', 'Untitled')}",
            metadata={
                "context_unit_id": created_unit["id"],
                "url": request.url,
                "scraped_title": scraped_title,
                "text_length": len(scraped_text),
                "has_custom_title": bool(request.title),
                "created_via": "api"
            },
            duration_ms=duration_ms,
            workflow_code="default"
        )
        
        return {
            "success": True,
            "context_unit": created_unit,
            "scraped_url": request.url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_context_unit_from_url_error", error=str(e), client_id=client["client_id"], url=request.url)
        
        # Log failed execution
        try:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            await supabase.log_execution(
                client_id=client["client_id"],
                company_id=client["company_id"],
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
        # Verify task belongs to client and company (automatic filtering)
        task = await supabase_client.get_task_by_id(task_id, client["company_id"])
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if task["client_id"] != client["client_id"]:
            raise HTTPException(status_code=403, detail="Not authorized to delete this task")

        await supabase_client.delete_task(task_id, client["company_id"])

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
    Analyze text and extract: title, summary, tags with usage control.

    Requires: X-API-Key header

    Body:
        - text: Text to analyze (required)
        - action: Must be "analyze"
        - params: Optional parameters (not used)

    Returns:
        Analysis result with title, summary, tags
    """
    try:
        from utils.workflow_endpoints import execute_analyze

        result = await execute_analyze(
            client=client,
            text=request.text,
            params=request.params
        )

        # Handle workflow result format
        if result.get("success", True):
            data = result.get("data", result)
            return {
                "status": "ok",
                "action": "analyze",
                "result": data,
                "text_length": len(request.text)
            }
        else:
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429, 
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_analyze_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process/analyze-atomic")
async def process_analyze_atomic(
    request: ProcessTextRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Analyze text and extract: title, summary, tags, atomic facts with usage control.

    Requires: X-API-Key header

    Body:
        - text: Text to analyze (required)
        - action: Must be "analyze_atomic"
        - params: Optional parameters (not used)

    Returns:
        Analysis result with title, summary, tags, atomic_facts
    """
    try:
        from utils.workflow_endpoints import execute_analyze_atomic

        result = await execute_analyze_atomic(
            client=client,
            text=request.text,
            params=request.params
        )

        # Handle workflow result format
        if result.get("success", True):
            data = result.get("data", result)
            return {
                "status": "ok",
                "action": "analyze_atomic",
                "result": data,
                "text_length": len(request.text)
            }
        else:
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429, 
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_analyze_atomic_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process/redact-news")
async def process_redact_news(
    request: ProcessTextRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Generate news article from text/facts with specific style and usage control.

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
        from utils.workflow_endpoints import execute_redact_news

        result = await execute_redact_news(
            client=client,
            text=request.text,
            params=request.params
        )

        # Handle workflow result format
        if result.get("success", True):
            data = result.get("data", result)
            return {
                "status": "ok",
                "action": "redact_news",
                "result": data,
                "text_length": len(request.text)
            }
        else:
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429, 
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
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


@app.post("/process/redact-news-rich")
async def process_redact_news_rich(
    request: RedactNewsRichRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Generate rich news article from multiple context units with custom instructions.

    Requires: X-API-Key header

    Body:
        - context_unit_ids: List of context unit UUIDs (required)
        - title: Optional title suggestion (if empty, LLM generates it)
        - instructions: Optional writing instructions (if empty, ignored)
        - style_guide: Optional markdown style guide (string)
        - language: Target language (default: "es")

    Returns:
        Generated article with title, summary, tags, and sources
    """
    try:
        from utils.workflow_endpoints import execute_redact_news_rich

        result = await execute_redact_news_rich(
            client=client,
            context_unit_ids=request.context_unit_ids,
            title=request.title,
            instructions=request.instructions,
            style_guide=request.style_guide,
            language=request.language
        )

        if result.get("success", True):
            data = result.get("data", result)
            return {
                "status": "ok",
                "action": "redact_news_rich",
                "result": data
            }
        else:
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429, 
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_redact_news_rich_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/test/perplexity")
async def test_perplexity_execution(
    x_api_key: str = Header(..., alias="x-api-key")
):
    """Execute Perplexity news task manually for testing."""
    try:
        # Validate API key
        client = await get_current_client(x_api_key)
        
        # Get Perplexity source
        supabase = get_supabase_client()
        result = supabase.client.table("sources")\
            .select("*")\
            .eq("source_name", "Medios Generalistas")\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Perplexity source not found")
        
        source = result.data[0]
        
        # Execute task
        from sources.perplexity_news_connector import execute_perplexity_news_task
        result = await execute_perplexity_news_task(source)
        
        return {
            "success": True,
            "message": "Perplexity task executed",
            "result": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("test_perplexity_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@app.post("/process/micro-edit")
async def micro_edit(
    request: MicroEditRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """
    Perform micro-editing on text using LLM with usage control.

    Requires: X-API-Key header

    Args:
        request: Micro-edit request data
        client: Authenticated client

    Returns:
        Dict with original_text, edited_text, explanation, word_count_change
    """
    try:
        logger.info(
            "micro_edit_request",
            client_id=client["client_id"],
            text_length=len(request.text),
            command=request.command[:100]
        )

        # Use workflow-enabled function
        from utils.workflow_endpoints import execute_micro_edit
        
        result = await execute_micro_edit(
            client=client,
            text=request.text,
            command=request.command,
            context=request.context,
            params=request.params
        )

        # Handle workflow result format
        if result.get("success", True):
            data = result.get("data", result)
            logger.info(
                "micro_edit_completed",
                client_id=client["client_id"],
                word_count_change=data.get("word_count_change", 0)
            )
            return {
                "success": True,
                "data": data
            }
        else:
            # Usage limit exceeded or other workflow error
            logger.warn(
                "micro_edit_workflow_failed",
                client_id=client["client_id"],
                error=result.get("error"),
                details=result.get("details")
            )
            
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429, 
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("micro_edit_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CONTEXT UNIT ENRICHMENT
# ============================================

class EnrichContextUnitRequest(BaseModel):
    """Request model for context unit enrichment."""
    enrich_type: str  # "update" | "background" | "verify"


@app.post("/api/v1/context-units/{context_unit_id}/enrichment")
async def enrichment_context_unit(
    context_unit_id: str,
    request: EnrichContextUnitRequest,
    client: Dict = Depends(get_current_client)
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
            client_id=client["client_id"]
        )

        # Validate enrich_type
        if request.enrich_type not in ["update", "background", "verify"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid enrich_type. Must be: update, background, or verify"
            )

        # Get context unit from database
        result = supabase_client.client.table("press_context_units")\
            .select("*")\
            .eq("id", context_unit_id)\
            .eq("company_id", client["company_id"])\
            .maybe_single()\
            .execute()

        if not result.data:
            logger.warn(
                "context_unit_not_found",
                context_unit_id=context_unit_id,
                client_id=client["client_id"]
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
            organization_id=client.get("organization_id", "00000000-0000-0000-0000-000000000001"),
            context_unit_id=context_unit_id,
            client_id=client["client_id"]
        )

        logger.info(
            "enrichment_context_unit_completed",
            context_unit_id=context_unit_id,
            enrich_type=request.enrich_type,
            has_error=bool(enrichment_result.get("error"))
        )

        return {
            "success": not bool(enrichment_result.get("error")),
            "context_unit_id": context_unit_id,
            "context_unit_title": context_unit.get("title", ""),
            "enrich_type": request.enrich_type,
            "age_days": age_days,
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


class SaveEnrichedStatementsRequest(BaseModel):
    """Request model for saving enriched statements."""
    statements: List[Dict[str, Any]]
    append: bool = True


@app.patch("/api/v1/context-units/{context_unit_id}/enriched-statements")
async def save_enriched_statements(
    context_unit_id: str,
    request: SaveEnrichedStatementsRequest,
    client: Dict = Depends(get_current_client)
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
            client_id=client["client_id"]
        )

        # Get context unit from database
        result = supabase_client.client.table("press_context_units")\
            .select("*")\
            .eq("id", context_unit_id)\
            .eq("company_id", client["company_id"])\
            .maybe_single()\
            .execute()

        if not result.data:
            logger.warn(
                "context_unit_not_found",
                context_unit_id=context_unit_id,
                client_id=client["client_id"]
            )
            raise HTTPException(status_code=404, detail="Context unit not found")

        context_unit = result.data

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

        # Update database
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
# TTS ENDPOINTS (Piper TTS)
# ============================================

class TTSRequest(BaseModel):
    """Request model for TTS synthesis."""
    text: str = Field(..., min_length=1, max_length=3000, description="Text to synthesize (max 3000 chars for speed)")
    rate: float = Field(1.3, ge=0.5, le=2.0, description="Speech rate (0.5=slow, 2.0=fast)")


@app.get("/tts/health")
async def tts_health(client: Dict = Depends(get_current_client)):
    """TTS service health check (requires authentication).

    Args:
        client: Authenticated client from API key

    Returns:
        Health status of TTS service
    """
    return {
        "status": "ok",
        "service": "semantika-tts",
        "version": "1.0.0",
        "model": "es_ES-carlfm-x_low",
        "quality": "x_low (3-4x faster, 28MB)",
        "integrated": True,
        "client_id": client["client_id"]
    }


@app.post("/tts/synthesize")
async def tts_synthesize(
    request: TTSRequest,
    client: Dict = Depends(get_current_client)
):
    """Synthesize speech from text using Piper TTS.

    Args:
        request: TTSRequest with text and rate

    Returns:
        WAV audio stream

    Raises:
        HTTPException: If synthesis fails
    """
    try:
        logger.info(
            "tts_request",
            client_id=client["client_id"],
            text_length=len(request.text),
            rate=request.rate,
            text_preview=request.text[:50]
        )

        # Warn if text is long (may take >10s)
        if len(request.text) > 2000:
            logger.warn(
                "tts_long_text",
                client_id=client["client_id"],
                text_length=len(request.text),
                estimated_duration_seconds=len(request.text) // 200  # ~200 chars/sec
            )

        # Convert rate to length_scale (inverse)
        # rate 1.3 = 30% faster = length_scale 0.77
        length_scale = 1.0 / request.rate

        # Call Piper binary with X_LOW quality model (3-4x faster, carlfm voice)
        # Output to stdout as WAV format
        process = subprocess.Popen(
            [
                '/app/piper/piper',
                '--model', '/app/models/es_ES-carlfm-x_low.onnx',
                '--length_scale', str(length_scale),
                '--output_file', '-'  # Output WAV to stdout
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        audio_data, error = process.communicate(
            input=request.text.encode('utf-8'),
            timeout=15  # 15s timeout for better UX (fallback to browser TTS)
        )

        if process.returncode != 0:
            error_msg = error.decode('utf-8', errors='ignore')
            logger.error(
                "piper_tts_error",
                returncode=process.returncode,
                error=error_msg[:200]
            )
            raise HTTPException(
                status_code=500,
                detail=f"TTS synthesis failed: {error_msg[:100]}"
            )

        audio_size = len(audio_data)
        estimated_duration = audio_size // 32000  # Rough estimate

        logger.info(
            "tts_success",
            client_id=client["client_id"],
            audio_size=audio_size,
            estimated_duration_seconds=estimated_duration,
            text_length=len(request.text),
            rate=request.rate
        )

        # Track usage as simple operation (microedición)
        tracker = get_usage_tracker()
        await tracker.track(
            organization_id=client.get("organization_id", "00000000-0000-0000-0000-000000000001"),
            model="piper/es_ES-carlfm-x_low",
            operation="tts_synthesize",
            input_tokens=0,
            output_tokens=0,
            client_id=client["client_id"],
            metadata={
                "text_length": len(request.text),
                "audio_size": audio_size,
                "rate": request.rate,
                "duration_seconds": estimated_duration,
                "usage_type": "simple"  # Microedición
            }
        )

        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=speech.wav",
                "Content-Length": str(audio_size),
                "Cache-Control": "public, max-age=3600"
            }
        )

    except subprocess.TimeoutExpired:
        logger.error(
            "tts_timeout",
            client_id=client["client_id"],
            text_length=len(request.text)
        )
        raise HTTPException(
            status_code=504,
            detail=f"TTS timeout (>15s) - texto demasiado largo ({len(request.text)} caracteres). Usa menos de 2000 caracteres para síntesis rápida."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "tts_error",
            client_id=client["client_id"],
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"TTS error: {str(e)}"
        )


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
