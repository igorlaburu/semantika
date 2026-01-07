"""FastAPI server for semantika API.

Handles all HTTP requests for document ingestion, search, and aggregation.

Version: 2025-10-28
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
import subprocess
import io
import re
from pathlib import Path

from fastapi import FastAPI, Request, Header, HTTPException, Depends, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field
import aiohttp

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client
from utils.supabase_auth import get_current_user_from_jwt
from utils.usage_tracker import get_usage_tracker
from utils.llm_registry import get_llm_registry
from utils.unified_context_ingester import ingest_context_unit
from core_ingest import IngestPipeline

# Initialize logger
logger = get_logger("api")

# Initialize Supabase client
supabase_client = get_supabase_client()

# Initialize FastAPI app
app = FastAPI(
    title="semantika API",
    description="Semantic data pipeline with multi-tenant support and task scheduling",
    version="0.1.4",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize FastEmbed model and geocoding cache on startup."""
    try:
        from utils.embedding_generator import get_fastembed_model
        logger.info("preloading_fastembed_model")
        model = get_fastembed_model()  # This will download and cache the model
        logger.info("fastembed_model_preloaded",
            model="paraphrase-multilingual-mpnet-base-v2",
            dimensions=768
        )
    except Exception as e:
        logger.error("fastembed_preload_failed", error=str(e))
        # Don't fail startup, let it try lazy-loading later
    
    try:
        from utils.geocoder import load_cache_from_db
        logger.info("loading_geocoding_cache")
        await load_cache_from_db()
        logger.info("geocoding_cache_loaded")
    except Exception as e:
        logger.error("geocoding_cache_load_failed", error=str(e))
        # Don't fail startup, geocoding will work without cache


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

async def get_api_key(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
) -> str:
    """Extract API key from X-API-Key or Authorization Bearer header."""
    if x_api_key:
        return x_api_key
    
    if authorization:
        if authorization.startswith("Bearer "):
            return authorization[7:]
        return authorization
    
    logger.warn("missing_api_key")
    raise HTTPException(status_code=401, detail="Missing API Key")


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


async def get_current_user_from_jwt_optional(authorization: Optional[str] = Header(None)) -> Optional[Dict]:
    """Optional version of get_current_user_from_jwt - returns None if no token."""
    if not authorization:
        return None
    try:
        return await get_current_user_from_jwt(authorization)
    except HTTPException:
        return None


async def get_current_client_optional(x_api_key: Optional[str] = Header(None)) -> Optional[Dict]:
    """Optional version of get_current_client - returns None if no API key."""
    if not x_api_key:
        return None
    try:
        client = await supabase_client.get_client_by_api_key(x_api_key)
        if client:
            logger.debug("client_authenticated", client_id=client["client_id"])
        return client
    except Exception:
        return None


async def get_company_id_from_auth(
    user: Optional[Dict] = Depends(get_current_user_from_jwt_optional),
    client: Optional[Dict] = Depends(get_current_client_optional)
) -> str:
    """
    Get company_id from either JWT or API Key (whichever is provided).
    
    Allows endpoints to accept both authentication methods.
    Useful for testing with API Key while frontend uses JWT.
    
    Args:
        user: User from JWT (optional)
        client: Client from API Key (optional)
        
    Returns:
        company_id string
        
    Raises:
        HTTPException: If neither auth method provided
    """
    if user:
        logger.debug("auth_via_jwt", user_id=user.get("sub"), company_id=user["company_id"])
        return user["company_id"]
    elif client:
        logger.debug("auth_via_api_key", client_id=client["client_id"], company_id=client["company_id"])
        return client["company_id"]
    else:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide either JWT token (Authorization: Bearer) or API Key (X-API-Key)"
        )


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
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint with memory stats.

    Returns:
        Status, timestamp, and memory usage
    """
    import gc
    import psutil
    import os
    
    # Force garbage collection to free memory
    gc.collect()
    
    # Get memory stats
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": "semantika-api",
        "version": "0.1.0",
        "memory": {
            "rss_mb": round(memory_info.rss / 1024 / 1024, 2),
            "vms_mb": round(memory_info.vms / 1024 / 1024, 2)
        }
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


class SignupRequest(BaseModel):
    """Request model for user signup."""
    email: str
    password: str
    company_name: str
    cif: str  # Company tax ID (CIF in Spain)
    tier: str = "starter"  # starter, pro, unlimited


@app.post("/auth/signup")
async def auth_signup(request: SignupRequest) -> Dict:
    """
    Sign up new user with a new company.

    Currently only allows creating new companies (1 user per company limit).

    Body:
        - email: User email
        - password: User password
        - company_name: Company name
        - cif: Company tax ID (CIF)
        - tier: Company tier (starter/pro/unlimited, default: starter)

    Returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "user": {...},
            "company": {...}
        }
    """
    try:
        # Validate tier
        valid_tiers = ["starter", "pro", "unlimited"]
        if request.tier not in valid_tiers:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier. Must be one of: {', '.join(valid_tiers)}"
            )

        # Normalize CIF (uppercase, remove spaces)
        cif_normalized = request.cif.upper().replace(" ", "")

        # Check if company with this CIF already exists
        supabase = get_supabase_client()
        existing_company = supabase.client.table("companies")\
            .select("id, company_code, company_name")\
            .eq("company_code", cif_normalized)\
            .maybe_single()\
            .execute()

        if existing_company and existing_company.data:
            logger.warn("signup_company_exists",
                cif=cif_normalized,
                company_name=existing_company.data["company_name"]
            )
            raise HTTPException(
                status_code=400,
                detail="Una empresa con este CIF ya está registrada. Por ahora solo permitimos nuevas empresas."
            )

        # Create company first
        logger.debug("creating_company", cif=cif_normalized, name=request.company_name)
        company_result = supabase.client.table("companies")\
            .insert({
                "company_code": cif_normalized,
                "company_name": request.company_name,
                "tier": request.tier,
                "is_active": True
            })\
            .execute()

        logger.debug("company_insert_result", result_type=str(type(company_result)), has_data=hasattr(company_result, 'data') if company_result else False)

        if not company_result or not company_result.data:
            logger.error("company_creation_failed", result=str(company_result))
            raise HTTPException(status_code=500, detail="Failed to create company")

        company = company_result.data[0]
        company_id = company["id"]

        logger.info("company_created",
            company_id=company_id,
            cif=cif_normalized,
            name=request.company_name
        )

        # Note: Manual source is created via CLI (python cli.py create-company)
        # NOT here, as signup is not used for production onboarding

        # Create user in Supabase Auth with company_id in metadata
        # Use supabase client's auth methods directly
        logger.debug("creating_auth_user", email=request.email, company_id=company_id)
        auth_response = supabase.client.auth.sign_up({
            "email": request.email,
            "password": request.password,
            "options": {
                "data": {
                    "company_id": company_id,
                    "name": request.email.split("@")[0]  # Default name from email
                }
            }
        })

        logger.debug("auth_signup_result", result_type=str(type(auth_response)), has_user=hasattr(auth_response, 'user') if auth_response else False)

        if not auth_response or not auth_response.user:
            # Rollback: delete company if user creation failed
            supabase.client.table("companies").delete().eq("id", company_id).execute()
            raise HTTPException(status_code=500, detail="Failed to create user")

        logger.info("user_created",
            email=request.email,
            user_id=auth_response.user.id,
            company_id=company_id
        )

        # Return JWT tokens
        return {
            "access_token": auth_response.session.access_token if auth_response.session else None,
            "refresh_token": auth_response.session.refresh_token if auth_response.session else None,
            "expires_in": auth_response.session.expires_in if auth_response.session else None,
            "user": {
                "id": auth_response.user.id,
                "email": auth_response.user.email,
                "created_at": auth_response.user.created_at
            },
            "company": {
                "id": company_id,
                "name": request.company_name,
                "cif": cif_normalized,
                "tier": request.tier
            },
            "message": "Usuario y empresa creados correctamente. Revisa tu email para confirmar la cuenta."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("signup_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")


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
        supabase = get_supabase_client()

        response = supabase.client.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password
        })

        if not response or not response.session:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Get user from database to get company_id
        user_result = supabase.client.table("users")\
            .select("id, email, name, company_id, role")\
            .eq("auth_user_id", response.user.id)\
            .single()\
            .execute()

        if not user_result or not user_result.data:
            raise HTTPException(status_code=404, detail="User not found in database")

        user_data = user_result.data
        company_id = user_data.get("company_id")

        if not company_id:
            raise HTTPException(status_code=403, detail="User must be assigned to a company")

        # Get company info
        company_result = supabase.client.table("companies")\
            .select("id, company_name, company_code, tier")\
            .eq("id", company_id)\
            .single()\
            .execute()

        if not company_result or not company_result.data:
            raise HTTPException(status_code=404, detail="Company not found")

        logger.info("user_logged_in",
            email=request.email,
            user_id=response.user.id,
            company_id=company_id
        )

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in,
            "user": {
                "id": user_data["id"],
                "email": user_data["email"],
                "name": user_data.get("name"),
                "role": user_data.get("role")
            },
            "company": {
                "id": company_result.data["id"],
                "name": company_result.data["company_name"],
                "cif": company_result.data["company_code"],
                "tier": company_result.data["tier"]
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
        supabase = get_supabase_client()

        response = supabase.client.auth.refresh_session(request.refresh_token)

        if not response or not response.session:
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

        supabase = get_supabase_client()
        supabase.client.auth.sign_out()

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


class SemanticSearchRequest(BaseModel):
    """Request model for semantic search."""
    query: str = Field(..., description="Search query to vectorize and match")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of results")
    threshold: float = Field(default=0.18, ge=0.0, le=1.0, description="Minimum similarity score (0.0-1.0, default 0.18 for high recall)")
    max_days: Optional[int] = Field(default=None, ge=1, description="Maximum age of context units in days (e.g., 30 = last 30 days)")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Optional filters (category, source_type, etc.)")
    include_pool: bool = Field(default=False, description="Include pool content (company_id = 99999999-9999-9999-9999-999999999999)")


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

@app.post("/ingest/text")
async def ingest_text(
    request: IngestTextRequest,
    client: Dict = Depends(get_current_client)
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
            .eq("id", client["company_id"])\
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
            source_id=f"legacy_ingest_{client['client_id'][:8]}",

            # Optional metadata
            source_metadata={
                "legacy_endpoint": "/ingest/text",
                "client_id": client["client_id"],
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


@app.post("/ingest/url")
async def ingest_url(
    request: IngestURLRequest,
    client: Dict = Depends(get_current_client)
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
            .eq("id", client["company_id"])\
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
                source_id=f"legacy_url_{client['client_id'][:8]}_{i}",

                # Optional metadata
                source_metadata={
                    "legacy_endpoint": "/ingest/url",
                    "client_id": client["client_id"],
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
        # Use company_id as source_id (Manual source always has source.id = company.id)
        context_unit_id = str(uuid.uuid4())
        source_content = SourceContent(
            source_type="manual",
            source_id=company["id"],  # KEY: Manual source.id = company.id
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
                "client_id": client["client_id"],
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
                    client_id=client["client_id"],
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
            client_id=client["client_id"],
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
            "context_unit": created_unit,
            "images_saved": len(images_saved),
            "image_paths": images_saved if images_saved else None
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
            client_id=client["client_id"],
            url=request.url,
            has_title=bool(request.title)
        )
        
        # Get company
        supabase = get_supabase_client()
        
        company_result = supabase.client.table("companies")\
            .select("*")\
            .eq("id", client["company_id"])\
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
            client_id=client["client_id"],
            context_unit_id=created_unit["id"],
            url=request.url,
            title=created_unit.get("title", ""),
            workflow_used="scraper_workflow"
        )
        
        # Log execution
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        await supabase.log_execution(
            client_id=client["client_id"],
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
        # Allow access to both client's own units AND pool units
        pool_company_id = "99999999-9999-9999-9999-999999999999"
        
        result = supabase_client.client.table("press_context_units")\
            .select("*")\
            .eq("id", context_unit_id)\
            .or_(f"company_id.eq.{client['company_id']},company_id.eq.{pool_company_id}")\
            .maybe_single()\
            .execute()

        if not result or not result.data:
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
        # Allow access to both client's own units AND pool units
        pool_company_id = "99999999-9999-9999-9999-999999999999"
        
        result = supabase_client.client.table("press_context_units")\
            .select("*")\
            .eq("id", context_unit_id)\
            .or_(f"company_id.eq.{client['company_id']},company_id.eq.{pool_company_id}")\
            .maybe_single()\
            .execute()

        if not result or not result.data:
            logger.warn(
                "context_unit_not_found",
                context_unit_id=context_unit_id,
                client_id=client["client_id"]
            )
            raise HTTPException(status_code=404, detail="Context unit not found")

        context_unit = result.data
        pool_company_id = "99999999-9999-9999-9999-999999999999"
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
                .eq("company_id", client["company_id"])\
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
                    company_id=client["company_id"]
                )
            else:
                # Create new enrichment child
                import uuid
                enrichment_id = str(uuid.uuid4())
                
                insert_result = supabase_client.client.table("press_context_units").insert({
                    "id": enrichment_id,
                    "base_id": base_id,
                    "company_id": client["company_id"],
                    "client_id": client["client_id"],
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
                    company_id=client["company_id"]
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
# IMAGE GENERATION AND RETRIEVAL
# ============================================

class GenerateImageRequest(BaseModel):
    image_prompt: str = Field(..., description="Image generation prompt in English")
    force_regenerate: bool = Field(default=False, description="Force regeneration even if cached")


@app.post("/api/v1/articles/{article_id}/generate-image")
async def generate_image_for_article(
    article_id: str,
    request: GenerateImageRequest,
    company_id: str = Depends(get_company_id_from_auth)
):
    """Generate photorealistic AI image for article from prompt.
    
    Uses Fal.ai FLUX.1 [schnell] model to generate conceptual, photorealistic
    images from a prompt provided by the frontend.
    
    Model specs:
    - Cost: $0.003/image
    - Speed: 1-2 seconds
    - Resolution: 1024x576 (landscape 16:9)
    - Quality: Excellent for simple photorealistic objects
    
    Generated images are:
    - Cached permanently in /app/cache/images/{article_id}.jpg
    - Served via GET /api/v1/images/{article_id} (unified endpoint)
    
    **Authentication**: Accepts JWT or API Key
    
    Args:
        article_id: Article UUID
        request.image_prompt: Image generation prompt (from frontend)
        request.force_regenerate: Force regeneration even if cached
        company_id: Company ID from auth
        
    Returns:
        Image generation result with URL and metadata
        
    Example:
        POST /api/v1/articles/uuid-123/generate-image
        Body: {
            "image_prompt": "A sleek medical device on sterile table...",
            "force_regenerate": false
        }
        Response: {
            "article_id": "uuid-123",
            "image_prompt": "A sleek medical device on sterile table...",
            "image_url": "/api/v1/articles/uuid-123/image",
            "status": "generated",
            "generated_at": "2025-12-18T14:30:00Z",
            "generation_time_ms": 1234.56
        }
    
    Raises:
        HTTPException: 404 if article not found
        HTTPException: 400 if image_prompt is empty
        HTTPException: 500 if image generation fails
    """
    try:
        logger.info("generate_image_request",
            article_id=article_id,
            company_id=company_id,
            force_regenerate=request.force_regenerate,
            prompt_preview=request.image_prompt[:100]
        )
        
        # Verify article exists and belongs to company
        result = supabase_client.client.table("press_articles").select(
            "id, company_id"
        ).eq("id", article_id).eq("company_id", company_id).maybe_single().execute()
        
        if not result.data:
            logger.warn("article_not_found_for_image_generation",
                article_id=article_id,
                company_id=company_id
            )
            raise HTTPException(status_code=404, detail="Article not found")
        
        # Validate image_prompt
        image_prompt = request.image_prompt.strip()
        if not image_prompt:
            logger.warn("empty_image_prompt",
                article_id=article_id
            )
            raise HTTPException(status_code=400, detail="image_prompt cannot be empty")
        
        # Generate image using Fal.ai with unique UUID
        import uuid
        from utils.image_generator import generate_image_from_prompt
        
        # Generate unique UUID for this image (allows multiple generations)
        image_uuid = str(uuid.uuid4())
        
        gen_result = await generate_image_from_prompt(
            context_unit_id=image_uuid,  # Use unique UUID as cache key
            image_prompt=image_prompt,
            force_regenerate=request.force_regenerate
        )
        
        if gen_result["success"]:
            logger.info("image_generation_success_endpoint",
                article_id=article_id,
                image_uuid=image_uuid,
                cached=gen_result["cached"],
                generation_time_ms=gen_result["generation_time_ms"]
            )
            
            # Return image UUID - frontend decides whether to assign it to article
            return {
                "article_id": article_id,
                "image_uuid": image_uuid,
                "image_url": f"/api/v1/images/{image_uuid}",
                "image_prompt": image_prompt,
                "status": "cached" if gen_result["cached"] else "generated",
                "generated_at": datetime.utcnow().isoformat(),
                "generation_time_ms": gen_result["generation_time_ms"]
            }
        else:
            logger.error("image_generation_failed_endpoint",
                article_id=article_id,
                error=gen_result.get("error")
            )
            raise HTTPException(
                status_code=500, 
                detail=f"Image generation failed: {gen_result.get('error', 'Unknown error')}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("generate_image_error",
            article_id=article_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/articles/{article_id}/image")
async def get_article_image(
    article_id: str,
    company_id: str = Depends(get_company_id_from_auth)
):
    """Get image for article with fallback to placeholder.
    
    Image priority:
    1. Cached image (from POST /generate-image) - X-Image-Source: "cached"
    2. Placeholder SVG - X-Image-Source: "placeholder"
    
    Images are cached in /app/cache/images/{article_id}.jpg
    
    Args:
        article_id: Article UUID
        company_id: Company ID from auth
        
    Returns:
        Image bytes (JPEG or SVG placeholder)
        
    Response Headers:
        - Content-Type: image/jpeg or image/svg+xml
        - Cache-Control: public, max-age=86400 (24 hours)
        - X-Image-Source: "cached" | "placeholder"
        
    Expected aspect ratio: 16:9 (1024x576) for generated
    
    Raises:
        HTTPException: 404 if article not found
    """
    from pathlib import Path
    
    try:
        # Check unified cache
        cache_dir = Path("/app/cache/images")
        cache_file = cache_dir / f"{article_id}.jpg"
        
        if cache_file.exists():
            logger.debug("article_image_cache_hit",
                article_id=article_id,
                cache_file=str(cache_file)
            )
            
            return Response(
                content=cache_file.read_bytes(),
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "X-Image-Source": "cached",
                    "X-Image-Cache": "hit"
                }
            )
        
        # Fallback: Return placeholder
        logger.debug("article_image_cache_miss", article_id=article_id)
        
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Image-Source": "placeholder"
            }
        )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("image_proxy_error", article_id=article_id, error=str(e))
        # Return placeholder on any error
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Image-Source": "placeholder"
            }
        )


@app.get("/api/v1/context-units/{context_unit_id}/image")
async def get_context_unit_image(
    context_unit_id: str,
    index: int = Query(0, ge=0, le=10, description="Image index (0 = first image)")
):
    """Get featured or manual image for context unit.
    
    Args:
        context_unit_id: UUID of context unit
        index: Image index (0 = first image, 1 = second, etc.)
        
    Returns:
        Image file or placeholder.
        
    Sources (in priority order):
        1. Manual uploaded images (index-based: {context_unit_id}_{index}.ext)
        2. Legacy format (backward compatibility: {context_unit_id}.ext - index=0 only)
        3. Featured images from scraping (index=0 only)
        4. Placeholder SVG
    """
    from pathlib import Path
    
    try:
        # Fetch context unit (allow pool access)
        pool_company_id = "99999999-9999-9999-9999-999999999999"
        
        result = supabase_client.client.table("press_context_units").select(
            "id, source_metadata, company_id"
        ).eq("id", context_unit_id).maybe_single().execute()
        
        if not result.data:
            logger.debug("context_unit_not_found_for_image", context_unit_id=context_unit_id)
            raise HTTPException(status_code=404, detail="Context unit not found")
        
        context_unit = result.data
        source_metadata = context_unit.get("source_metadata") or {}
        
        # Priority 1: Check for manual uploaded images (indexed)
        cache_dir = Path("/app/cache/images")
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Try manual images with index: {context_unit_id}_{index}.ext
        for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]:
            indexed_cache_file = cache_dir / f"{context_unit_id}_{index}{ext}"
            if indexed_cache_file.exists():
                # Determine media type from extension
                media_type_map = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", 
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                    ".bmp": "image/bmp"
                }
                media_type = media_type_map.get(ext, "image/jpeg")
                
                logger.debug("manual_image_cache_hit",
                    context_unit_id=context_unit_id,
                    index=index,
                    cache_file=str(indexed_cache_file)
                )
                
                return Response(
                    content=indexed_cache_file.read_bytes(),
                    media_type=media_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "X-Image-Source": "manual_upload",
                        "X-Image-Index": str(index)
                    }
                )
        
        # Priority 2: For index=0, try old format without index (backward compatibility)
        if index == 0:
            for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]:
                legacy_cache_file = cache_dir / f"{context_unit_id}{ext}"
                if legacy_cache_file.exists():
                    # Determine media type from extension
                    media_type_map = {
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".png": "image/png",
                        ".webp": "image/webp", 
                        ".gif": "image/gif",
                        ".bmp": "image/bmp"
                    }
                    media_type = media_type_map.get(ext, "image/jpeg")
                
                    logger.debug("legacy_image_cache_hit", 
                        context_unit_id=context_unit_id,
                        cache_file=str(legacy_cache_file),
                        extension=ext
                    )
                    return Response(
                        content=legacy_cache_file.read_bytes(),
                        media_type=media_type,
                        headers={
                            "Cache-Control": "public, max-age=86400",
                            "X-Image-Source": "legacy_format",
                            "X-Image-Cache": "hit"
                        }
                    )
        
        # Priority 3: For index=0, try featured image from scraping
        if index == 0:
            featured_image = source_metadata.get("featured_image")
            if featured_image and featured_image.get("url"):
                image_url = featured_image["url"]
                
                # Skip file:// URLs (should be cached already)
                if image_url.startswith("file://"):
                    logger.warn("file_url_without_cache", 
                        context_unit_id=context_unit_id, 
                        file_url=image_url
                    )
                    # Fall through to placeholder
                else:
                    # Try to fetch and cache featured image
                    try:
                        import ssl
                        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE
                        
                        connector = aiohttp.TCPConnector(ssl=ssl_context)
                        async with aiohttp.ClientSession(connector=connector) as session:
                            async with session.get(
                                image_url,
                                headers={
                                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                    'Accept': 'image/*',
                                    'Referer': source_metadata.get("url", "https://ekimen.ai")
                                },
                                timeout=aiohttp.ClientTimeout(total=10)
                            ) as response:
                                
                                if response.status == 200:
                                    image_bytes = await response.read()
                                    content_type = response.headers.get("Content-Type", "image/jpeg")
                                    
                                    # Try to cache to disk (optional - don't fail if this fails)
                                    try:
                                        # Determine extension from content type
                                        ext_map = {
                                            "image/jpeg": ".jpg",
                                            "image/png": ".png",
                                            "image/webp": ".webp",
                                            "image/gif": ".gif",
                                            "image/bmp": ".bmp"
                                        }
                                        ext = ext_map.get(content_type, ".jpg")
                                        cache_file = cache_dir / f"{context_unit_id}{ext}"
                                        
                                        cache_file.write_bytes(image_bytes)
                                        logger.info("featured_image_cached", 
                                            context_unit_id=context_unit_id,
                                            size_bytes=len(image_bytes),
                                            cache_path=str(cache_file)
                                        )
                                    except Exception as e:
                                        logger.warn("featured_image_cache_write_failed", 
                                            context_unit_id=context_unit_id,
                                            error=str(e)
                                        )
                                    
                                    return Response(
                                        content=image_bytes,
                                        media_type=content_type,
                                        headers={
                                            "Cache-Control": "public, max-age=86400",
                                            "X-Image-Source": "featured_image",
                                            "X-Image-Extraction": featured_image.get("source", "unknown")
                                        }
                                    )
                                else:
                                    logger.warn("featured_image_fetch_failed", 
                                        context_unit_id=context_unit_id,
                                        status=response.status,
                                        url=image_url
                                    )
                    except Exception as e:
                        logger.warn("featured_image_proxy_error", 
                            context_unit_id=context_unit_id, 
                            error=str(e),
                            url=image_url
                        )
        
        # Priority 4: Return placeholder
        logger.debug("image_not_found_using_placeholder", 
            context_unit_id=context_unit_id,
            index=index
        )
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Image-Source": "placeholder"
            }
        )
            
    except Exception as e:
        logger.error("get_context_unit_image_error", context_unit_id=context_unit_id, index=index, error=str(e))
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Image-Source": "placeholder"
            }
        )


def generate_placeholder_image() -> bytes:
    """Generate SVG placeholder image with 1.91:1 aspect ratio.
    
    Returns:
        SVG bytes for placeholder (600×314px, scales to any size)
    """
    svg = """<svg width="600" height="314" xmlns="http://www.w3.org/2000/svg">
  <rect width="600" height="314" fill="#f0f0f0"/>
  <text x="50%" y="50%" font-family="Arial, sans-serif" font-size="18" 
        fill="#999" text-anchor="middle" dominant-baseline="middle">
    Sin imagen
  </text>
</svg>"""
    return svg.encode('utf-8')


@app.get("/api/v1/context-units/{context_unit_id}/email-images")
async def get_context_unit_email_images(
    context_unit_id: str,
    company_id: str = Depends(get_company_id_from_auth)
):
    """Get cached email images for context unit."""
    try:
        # Get context unit with cached images metadata
        pool_company_id = "99999999-9999-9999-9999-999999999999"
        
        result = supabase_client.client.table("press_context_units").select(
            "id, source_metadata, source_type"
        ).eq("id", context_unit_id).in_("company_id", [company_id, pool_company_id]).maybe_single().execute()
        
        if not result.data or result.data.get("source_type") != "email":
            return {"images": []}
        
        cached_images = result.data.get("source_metadata", {}).get("connector_specific", {}).get("cached_images", [])
        
        # Filter existing images and add access URLs
        available_images = []
        for img in cached_images:
            cache_path = Path(img["cache_path"])
            if cache_path.exists():
                available_images.append({
                    "url": f"/api/v1/context-units/{context_unit_id}/email-image/{cache_path.name}",
                    "source": img["source"],
                    "filename": img.get("original_filename"),
                    "size_bytes": img.get("size_bytes")
                })
        
        return {"images": available_images}
        
    except Exception as e:
        logger.error("get_email_images_error", error=str(e))
        return {"images": []}


@app.get("/api/v1/context-units/{context_unit_id}/email-image/{image_filename}")
async def serve_cached_email_image(
    context_unit_id: str,
    image_filename: str,
    company_id: str = Depends(get_company_id_from_auth)
):
    """Serve cached email image."""
    try:
        # Security: validate filename format
        if not re.match(r'^[a-f0-9\-]+(\_img\_\d+)\.(jpg|png|webp|gif)$', image_filename):
            raise HTTPException(status_code=400, detail="Invalid image filename")
        
        # Verify context unit belongs to user
        pool_company_id = "99999999-9999-9999-9999-999999999999"
        result = supabase_client.client.table("press_context_units").select(
            "id"
        ).eq("id", context_unit_id).in_("company_id", [company_id, pool_company_id]).maybe_single().execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Context unit not found")
        
        # Serve image
        image_path = Path(f"/app/cache/email_images/{image_filename}")
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Determine content type
        ext = image_path.suffix.lower()
        content_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", 
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif"
        }
        content_type = content_type_map.get(ext, "image/jpeg")
        
        return Response(
            content=image_path.read_bytes(),
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=2592000",  # 30 days
                "X-Image-Source": "email_cache"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("serve_email_image_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to serve image")


# ============================================
# UNIFIED IMAGE ENDPOINT
# ============================================

@app.get("/api/v1/images/{image_id}")
async def get_image_unified(image_id: str):
    """Unified public image endpoint.
    
    Serves cached images from /app/cache/images/{uuid}.{ext}
    No authentication required - knowing the UUID is the protection.
    
    Images can be:
    1. AI-generated (from POST /articles/{id}/generate-image) - typically .jpg
    2. Featured images (cached from GET /context-units/{id}/image) - .jpg, .png, .gif, .webp, .bmp
    
    Args:
        image_id: UUID of article or context unit
        
    Returns:
        - Image if cached (JPEG/PNG/GIF/WebP/BMP) (X-Image-Source: "cached")
        - SVG placeholder if not found (X-Image-Source: "placeholder")
        
    Headers:
        - Cache-Control: public, max-age=86400 (24h)
        - X-Image-Source: "cached" | "placeholder"
    """
    from pathlib import Path
    
    try:
        cache_dir = Path("/app/cache/images")
        
        # Check for cached image with multiple extensions
        extensions = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]
        
        for ext in extensions:
            cache_file = cache_dir / f"{image_id}{ext}"
            if cache_file.exists():
                # Determine media type from extension
                media_type_map = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", 
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                    ".bmp": "image/bmp"
                }
                media_type = media_type_map.get(ext, "image/jpeg")
                
                logger.debug("unified_image_cache_hit", 
                    image_id=image_id,
                    extension=ext,
                    media_type=media_type
                )
                return Response(
                    content=cache_file.read_bytes(),
                    media_type=media_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "X-Image-Source": "cached"
                    }
                )
        
        # Not cached - return placeholder
        logger.debug("unified_image_not_found", image_id=image_id)
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Image-Source": "placeholder"
            }
        )
        
    except Exception as e:
        logger.error("unified_image_error", image_id=image_id, error=str(e))
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Image-Source": "placeholder"
            }
        )


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
            model="piper/es_ES-carlfm-x_low",
            operation="tts_synthesize",
            input_tokens=0,
            output_tokens=0,
            company_id=client.get("company_id", "00000000-0000-0000-0000-000000000001"),
            client_id=client["client_id"],
            metadata={
                "text_length": len(request.text),
                "audio_size": audio_size,
                "rate": request.rate,
                "duration_seconds": estimated_duration,
                "usage_type": "simple"
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


# ============================================
# DATA ACCESS ENDPOINTS (JWT Protected)
# ============================================

@app.get("/api/v1/context-units")
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


@app.get("/api/v1/context-units/filter-options")
async def get_filter_options(
    user: Dict = Depends(get_current_user_from_jwt)
) -> Dict:
    """
    Get available filter options (sources, topics, and categories) for context units.

    Returns unique source_types, tags, and categories with counts.
    """
    try:
        company_id = user["company_id"]
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


@app.get("/api/v1/context-units/{context_unit_id}")
async def get_context_unit(
    context_unit_id: str,
    user: Dict = Depends(get_current_user_from_jwt)
) -> Dict:
    """
    Get a single context unit by ID.
    
    Returns context unit merged with user's enrichments if available.
    Supports both base units and enrichment children.
    """
    try:
        company_id = user["company_id"]
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


@app.get("/api/v1/articles")
async def list_articles(
    company_id: str = Depends(get_company_id_from_auth),
    status: str = "all",
    category: str = "all",
    limit: int = 20,
    offset: int = 0
) -> Dict:
    """
    Get paginated list of articles (borradores or publicados).

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)
    
    Filters by company_id from authentication.
    """
    try:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")
        supabase = get_supabase_client()

        # Build query
        query = supabase.client.table("press_articles")\
            .select("*", count="exact")\
            .eq("company_id", company_id)

        # Status filter
        if status != "all":
            query = query.eq("estado", status)

        # Category filter
        if category != "all":
            query = query.eq("category", category)

        # Order and paginate
        result = query.order("updated_at", desc=True)\
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
        logger.error("list_articles_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch articles: {str(e)}")


@app.get("/api/v1/articles/by-slug/{slug}")
async def get_article_by_slug(
    slug: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Get a single article by slug.
    
    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table("press_articles")\
            .select("*")\
            .eq("slug", slug)\
            .eq("company_id", company_id)\
            .single()\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Article not found")

        return result.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_article_by_slug_error", error=str(e), slug=slug)
        raise HTTPException(status_code=500, detail="Failed to fetch article")


@app.post("/api/v1/articles")
async def create_or_update_article(
    article_data: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Create or update article (upsert inteligente).
    
    Si el artículo existe → UPDATE solo campos enviados
    Si no existe → INSERT con campos enviados
    
    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)
    
    **Body**: JSON with article fields
    """
    try:
        supabase = get_supabase_client()

        clean_data = {k: v for k, v in article_data.items() if v is not None}
        
        
        clean_data["company_id"] = company_id
        clean_data["updated_at"] = datetime.utcnow().isoformat()
        
        # If no style_id is provided, use default style for the company
        if "style_id" not in clean_data or clean_data["style_id"] is None:
            default_style = supabase.client.table("press_styles")\
                .select("id")\
                .eq("company_id", company_id)\
                .eq("predeterminado", True)\
                .maybe_single()\
                .execute()
            
            if default_style.data:
                clean_data["style_id"] = default_style.data["id"]
                logger.debug("using_default_style",
                    company_id=company_id,
                    style_id=default_style.data["id"]
                )
        
        # Log category inheritance for debugging
        if "category" in clean_data and "context_unit_ids" in clean_data:
            logger.info("article_with_category_and_context",
                category=clean_data["category"],
                context_unit_ids_count=len(clean_data.get("context_unit_ids", [])),
                article_id=clean_data.get("id")
            )
        
        article_id = clean_data.get("id")
        if not article_id:
            raise HTTPException(status_code=400, detail="Missing article id")

        # Check if exists
        existing = supabase.client.table("press_articles")\
            .select("id")\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .execute()

        if existing.data and len(existing.data) > 0:
            # EXISTS → UPDATE (acepta campos parciales)
            result = supabase.client.table("press_articles")\
                .update(clean_data)\
                .eq("id", article_id)\
                .eq("company_id", company_id)\
                .execute()
        else:
            # NO EXISTE → INSERT (requiere campos obligatorios)
            result = supabase.client.table("press_articles")\
                .insert(clean_data)\
                .execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to save article")

        logger.info(
            "article_saved",
            article_id=result.data[0].get("id"),
            company_id=company_id,
            titulo=clean_data.get("titulo", "")[:50]
        )

        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("save_article_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save article")


@app.get("/api/v1/articles/{article_id}")
async def get_article(
    article_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Get a single article by ID.
    
    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table("press_articles")\
            .select("*")\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .single()\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Article not found")

        return result.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_article_error", error=str(e), article_id=article_id)
        raise HTTPException(status_code=500, detail="Failed to fetch article")


@app.patch("/api/v1/articles/{article_id}")
async def update_article(
    article_id: str,
    updates: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Update article fields (partial update).
    
    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)
    
    **Body**: JSON object with fields to update, e.g.:
        {
            "estado": "publicado",
            "fecha_publicacion": "2025-11-23T10:00:00Z",
            "imagen_uuid": "a1b2c3d4-5678-90ab-cdef-1234567890ab"
        }
    
    **Note**: Use imagen_uuid (not imagen_url) for images. Frontend will construct URL.
    """
    try:
        supabase = get_supabase_client()

        # Clean None/undefined values
        clean_data = {k: v for k, v in updates.items() if v is not None}
        
        if not clean_data:
            raise HTTPException(status_code=400, detail="No valid fields")

        clean_data["updated_at"] = datetime.utcnow().isoformat()

        # Update only the provided fields
        result = supabase.client.table("press_articles")\
            .update(clean_data)\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .execute()

        if not result.data or len(result.data) == 0:
            raise HTTPException(status_code=404, detail="Article not found")

        logger.info(
            "article_updated",
            article_id=article_id,
            company_id=company_id,
            fields=list(clean_data.keys())
        )

        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_article_error", error=str(e), article_id=article_id)
        raise HTTPException(status_code=500, detail="Failed to update article")


async def publish_to_platforms(
    article: Dict[str, Any],
    company_id: str,
    target_ids: list
) -> Dict[str, Any]:
    """Publish article to specified platforms or default platforms."""
    from publishers.publisher_factory import PublisherFactory
    
    publication_results = {}
    supabase = get_supabase_client()
    
    try:
        # Get publication targets
        if target_ids:
            # Use specified targets
            targets_query = supabase.client.table("press_publication_targets")\
                .select("*")\
                .eq("company_id", company_id)\
                .eq("is_active", True)\
                .in_("id", target_ids)
            
            targets_result = targets_query.execute()
            targets = targets_result.data or []
        else:
            # First try default targets for each platform
            targets_query = supabase.client.table("press_publication_targets")\
                .select("*")\
                .eq("company_id", company_id)\
                .eq("is_active", True)\
                .eq("is_default", True)
            
            targets_result = targets_query.execute()
            targets = targets_result.data or []
            
            # If no default targets found, use the first available target
            if not targets:
                logger.info("no_default_targets_found_using_first_available", 
                    company_id=company_id
                )
                
                targets_query = supabase.client.table("press_publication_targets")\
                    .select("*")\
                    .eq("company_id", company_id)\
                    .eq("is_active", True)\
                    .order("created_at")\
                    .limit(1)
                
                targets_result = targets_query.execute()
                targets = targets_result.data or []
        
        if not targets:
            logger.warn("no_publication_targets_found", 
                company_id=company_id,
                specified_targets=target_ids
            )
            return {}
        
        # Update article with auto-assigned targets if needed
        if not target_ids:  # Only if no targets were specified (auto-assignment case)
            assigned_target_ids = [t['id'] for t in targets]
            try:
                supabase.client.table("press_articles")\
                    .update({"publication_targets": assigned_target_ids})\
                    .eq("id", article['id'])\
                    .eq("company_id", company_id)\
                    .execute()
                
                logger.info("publication_targets_auto_assigned",
                    article_id=article['id'],
                    target_ids=assigned_target_ids,
                    target_names=[t['name'] for t in targets]
                )
            except Exception as e:
                logger.warn("failed_to_update_article_targets",
                    article_id=article['id'],
                    error=str(e)
                )
        
        # Prepare article data for publication
        title = article.get('titulo', 'Untitled')
        content = article.get('contenido', '')
        excerpt = article.get('excerpt', '')
        tags = article.get('tags', [])
        category = article.get('category', None)
        
        # Use article slug (required field in press_articles)
        slug = article.get('slug')
        if not slug:
            logger.warn("article_missing_slug_field", 
                article_id=article.get('id'),
                title=title[:50]
            )
            # Fallback to generated slug if missing
            slug = _generate_slug_from_title(title)
        
        # Get image UUID for unified image endpoint
        imagen_uuid = article.get('imagen_uuid')
        temp_image_path = None
        
        # Transform image for publication if present
        if imagen_uuid:
            try:
                from utils.image_transformer import ImageTransformer
                import os
                
                # Read image from cache
                original_image_data = ImageTransformer.read_cached_image(imagen_uuid)
                
                if original_image_data:
                    # Transform image to temporary file with brand consistency and uniqueness
                    temp_image_path = ImageTransformer.transform_for_publication(
                        image_data=original_image_data,
                        platform="wordpress",  # TODO: Make dynamic per platform
                        image_uuid=imagen_uuid
                    )
                    
                    if temp_image_path:
                        temp_size_kb = round(os.path.getsize(temp_image_path) / 1024, 2)
                        logger.info("publication_image_transformed",
                            article_id=article.get('id'),
                            imagen_uuid=imagen_uuid,
                            temp_image_path=temp_image_path,
                            transformed_size_kb=temp_size_kb
                        )
                    else:
                        logger.error("publication_image_transformation_returned_none",
                            article_id=article.get('id'),
                            imagen_uuid=imagen_uuid
                        )
                else:
                    logger.warn("publication_image_not_found_in_cache",
                        article_id=article.get('id'),
                        imagen_uuid=imagen_uuid
                    )
            except Exception as e:
                logger.error("publication_image_transformation_failed",
                    article_id=article.get('id'),
                    imagen_uuid=imagen_uuid,
                    error=str(e)
                )
                # Continue without transformed image (fallback to UUID method)
        
        # Add references and image attribution footer
        content = await _add_article_footer(content, article.get('id'), company_id)
        
        # Publish to each target
        for target in targets:
            target_id = target['id']
            
            try:
                # Create publisher
                publisher = PublisherFactory.create_publisher(
                    target['platform_type'],
                    target['base_url'],
                    target['credentials_encrypted']
                )
                
                # Publish article with transformed image
                publish_kwargs = {
                    "title": title,
                    "content": content,
                    "excerpt": excerpt,
                    "tags": tags,
                    "category": category,
                    "status": "publish",
                    "slug": slug,
                    "fecha_publicacion": article.get('fecha_publicacion')
                }
                
                # Use temporary transformed image file if available, fallback to UUID method
                if temp_image_path:
                    publish_kwargs["temp_image_path"] = temp_image_path
                else:
                    publish_kwargs["imagen_uuid"] = imagen_uuid
                
                result = await publisher.publish_article(**publish_kwargs)
                
                publication_results[target_id] = {
                    "success": result.success,
                    "platform": target['platform_type'],
                    "target_name": target['name'],
                    "url": result.url,
                    "external_id": result.external_id,
                    "published_at": result.published_at,
                    "error": result.error,
                    "metadata": result.metadata
                }
                
                logger.info("article_published_to_platform",
                    article_id=article['id'],
                    target_id=target_id,
                    platform=target['platform_type'],
                    success=result.success,
                    url=result.url
                )
                
            except Exception as e:
                publication_results[target_id] = {
                    "success": False,
                    "platform": target['platform_type'],
                    "target_name": target['name'],
                    "error": f"Publication error: {str(e)}"
                }
                
                logger.error("platform_publication_failed",
                    article_id=article['id'],
                    target_id=target_id,
                    platform=target['platform_type'],
                    error=str(e)
                )
        
        # Clean up temporary image file if created
        if temp_image_path:
            try:
                import os
                os.unlink(temp_image_path)
                logger.info("temp_image_file_cleaned_up", 
                    temp_image_path=temp_image_path,
                    article_id=article['id']
                )
            except Exception as e:
                logger.warn("temp_image_file_cleanup_failed",
                    temp_image_path=temp_image_path,
                    article_id=article['id'],
                    error=str(e)
                )
        
        # Update article publication status
        if publication_results:
            supabase.client.table("press_articles")\
                .update({
                    "publication_targets": list(publication_results.keys()),
                    "publication_status": publication_results
                })\
                .eq("id", article['id'])\
                .execute()
        
    except Exception as e:
        logger.error("publish_to_platforms_error",
            article_id=article['id'],
            company_id=company_id,
            error=str(e)
        )
        # Return empty dict on error rather than failing the whole publication
    
    return publication_results


async def _add_article_footer(content: str, article_id: str, company_id: str) -> str:
    """Add references and image attribution footer to article content."""
    from urllib.parse import urlparse
    
    try:
        supabase = get_supabase_client()
        footer_parts = []
        
        # Get context units used in this article
        # Get article data to find context_unit_ids
        article_data = supabase.client.table("press_articles")\
            .select("context_unit_ids")\
            .eq("id", article_id)\
            .maybe_single()\
            .execute()
        
        context_units_result = {"data": []}
        
        if article_data.data and article_data.data.get("context_unit_ids"):
            # Use context units linked to this article
            context_unit_ids = article_data.data["context_unit_ids"]
            if context_unit_ids:
                context_units_result = supabase.client.table("press_context_units")\
                    .select("source_metadata, id")\
                    .in_("id", context_unit_ids)\
                    .execute()
        
        # If no context units found, use fallback to recent units from same company (no time limit)
        if not context_units_result.data:
            context_units_result = supabase.client.table("press_context_units")\
                .select("source_metadata, id")\
                .eq("company_id", company_id)\
                .is_not("source_metadata->url", "null")\
                .order("created_at", desc=True)\
                .limit(10)\
                .execute()
        
        context_units = context_units_result.data or []
        
        # Collect unique references (URLs)
        references = set()
        image_sources = []
        
        for unit in context_units:
            metadata = unit.get("source_metadata") or {}
            url = metadata.get("url")
            
            if url and url.startswith("http"):
                try:
                    parsed = urlparse(url)
                    domain = parsed.netloc
                    references.add((domain, url))
                except:
                    continue
            
            # Check for featured images
            featured_image = metadata.get("featured_image")
            if featured_image and featured_image.get("url"):
                image_url = featured_image["url"]
                try:
                    parsed = urlparse(image_url)
                    image_domain = parsed.netloc
                    image_sources.append((image_domain, image_url))
                except:
                    continue
        
        # Check if article has AI generated images by looking at working_json.generated_images
        article_result = supabase.client.table("press_articles")\
            .select("imagen_uuid, working_json")\
            .eq("id", article_id)\
            .maybe_single()\
            .execute()
        
        has_ai_image = False
        if article_result.data and article_result.data.get("imagen_uuid"):
            imagen_uuid = article_result.data["imagen_uuid"]
            working_json = article_result.data.get("working_json") or {}
            generated_images = working_json.get("article", {}).get("generated_images", [])
            
            # Check if the article's imagen_uuid is in the generated_images list
            ai_image_uuids = [img.get("uuid") for img in generated_images if img.get("uuid")]
            has_ai_image = imagen_uuid in ai_image_uuids
        
        # Build footer
        if references:
            footer_parts.append("<strong>Referencias:</strong>")
            for domain, url in sorted(references):
                footer_parts.append(f'<a href="{url}">{domain}</a>')
        
        # Add image attribution
        if image_sources or has_ai_image:
            footer_parts.append("<strong>Imagen:</strong>")
            
            if has_ai_image:
                footer_parts.append("Generada con IA")
            
            for image_domain, image_url in sorted(set(image_sources)):
                footer_parts.append(f'<a href="{image_url}">{image_domain}</a>')
        
        if footer_parts:
            footer_html = "<br>".join(footer_parts) + "<br>"
            content = f"{content}<br><br>{footer_html}"
            
            logger.info("article_footer_added",
                article_id=article_id,
                references_count=len(references),
                image_sources_count=len(image_sources),
                has_ai_image=has_ai_image
            )
        
        return content
        
    except Exception as e:
        logger.error("add_article_footer_error",
            article_id=article_id,
            error=str(e)
        )
        # Return original content if footer generation fails
        return content


@app.post("/api/v1/articles/{article_id}/publish")
async def publish_article(
    article_id: str,
    request: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Publish an article to multiple platforms.
    
    If publish_now=true, publishes immediately to all specified targets.
    If schedule_time is provided, schedules for that time.
    If neither, backend calculates optimal schedule time.
    
    **Authentication**: Accepts either JWT or API Key
    
    **Body**:
        {
            "publish_now": false,               // optional, default false
            "preserve_original_date": false,    // optional, mantener fecha de publicación original
            "schedule_time": null,              // optional ISO datetime, null = auto-schedule
            "targets": ["uuid1", "uuid2"]       // optional, publication target IDs. If empty, uses default targets, then first available target
        }
    
    **Returns**:
        {
            "success": true,
            "article_id": "xxx",
            "status": "programado",
            "scheduled_for": "2024-12-27T10:00:00Z",
            "publication_results": {
                "uuid1": {"success": true, "url": "https://...", "platform": "wordpress"},
                "uuid2": {"success": false, "error": "Connection failed"}
            }
        }
    """
    try:
        supabase = get_supabase_client()
        
        # Get article to verify it exists and belongs to company
        article_result = supabase.client.table("press_articles")\
            .select("*")\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .single()\
            .execute()
        
        if not article_result.data:
            raise HTTPException(status_code=404, detail="Article not found")
        
        article = article_result.data
        
        # Determine publication strategy first
        publish_now = request.get('publish_now', False)
        preserve_original_date = request.get('preserve_original_date', False)
        
        # Check article state - allow programado articles to be published immediately
        if article['estado'] == 'borrador':
            # Draft articles can be published/scheduled
            pass
        elif article['estado'] == 'programado' and publish_now:
            # Scheduled articles can be published immediately (used by scheduler)
            pass
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Article cannot be processed. Current state: {article['estado']}, publish_now: {publish_now}"
            )
        schedule_time = request.get('schedule_time')
        publication_results = {}
        
        # Handle multi-platform publication if immediate
        if publish_now:
            publication_results = await publish_to_platforms(
                article, 
                company_id, 
                request.get('targets', [])
            )
        
        if publish_now:
            # Determine publication date
            existing_date = article.get('fecha_publicacion')
            
            if preserve_original_date and existing_date:
                # Mantener fecha original
                publication_date = existing_date
                logger.info("preserving_original_publication_date", 
                    article_id=article_id, 
                    original_date=existing_date)
            else:
                # Nueva fecha de publicación
                publication_date = datetime.utcnow().isoformat()
                if existing_date:
                    logger.info("updating_publication_date", 
                        article_id=article_id, 
                        old_date=existing_date, 
                        new_date=publication_date)
            
            # Extract primary publication URL (first successful publication)
            published_url = None
            for target_id, result in publication_results.items():
                if result.get("success") and result.get("url"):
                    published_url = result["url"]
                    break  # Use first successful URL as primary
            
            # Publish immediately
            update_data = {
                "estado": "publicado",
                "fecha_publicacion": publication_date,
                "published_url": published_url,
                "published_date": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            scheduled_for = None
            new_status = "publicado"
        else:
            # Schedule for later
            if schedule_time:
                # Use provided schedule time
                try:
                    scheduled_datetime = datetime.fromisoformat(
                        schedule_time.replace('Z', '+00:00')
                    )
                    if scheduled_datetime <= datetime.utcnow():
                        raise HTTPException(
                            status_code=400,
                            detail="Schedule time must be in the future"
                        )
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid datetime format"
                    )
            else:
                # Calculate optimal schedule time
                scheduled_datetime = await calculate_optimal_schedule_time(company_id)
            
            update_data = {
                "estado": "borrador",
                "to_publish_at": scheduled_datetime.isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            scheduled_for = scheduled_datetime.isoformat()
            new_status = "programado"
        
        # Update article
        update_result = supabase.client.table("press_articles")\
            .update(update_data)\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .execute()
        
        if not update_result.data:
            raise HTTPException(status_code=500, detail="Failed to update article")
        
        logger.info("article_published",
            article_id=article_id,
            company_id=company_id,
            new_status=new_status,
            scheduled_for=scheduled_for
        )
        
        response = {
            "success": True,
            "article_id": article_id,
            "status": new_status,
            "scheduled_for": scheduled_for,
            "message": f"Article {'published' if publish_now else 'scheduled for publication'}"
        }
        
        # Add publication results if we published immediately
        if publish_now and publication_results:
            response["publication_results"] = publication_results
            
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("publish_article_error", 
            error=str(e), 
            article_id=article_id
        )
        raise HTTPException(status_code=500, detail="Failed to publish article")


async def calculate_optimal_schedule_time(company_id: str) -> datetime:
    """
    Calculate optimal publication time for an article.
    
    Strategy:
    - Avoid oversaturation (max 2 articles/hour)
    - Prefer high-engagement hours (9-11, 13-15, 18-20)
    - Distribute evenly across the day
    - Start from 2 hours in the future minimum
    """
    supabase = get_supabase_client()
    
    # Get already scheduled articles for next 48 hours
    now = datetime.utcnow()
    start_time = now + timedelta(hours=2)  # Minimum 2 hours from now
    end_time = now + timedelta(hours=48)
    
    scheduled_result = supabase.client.table("press_articles")\
        .select("to_publish_at")\
        .eq("company_id", company_id)\
        .eq("estado", "programado")\
        .gte("to_publish_at", start_time.isoformat())\
        .lte("to_publish_at", end_time.isoformat())\
        .execute()
    
    # Count articles per hour
    scheduled_by_hour = {}
    for article in scheduled_result.data:
        if article['to_publish_at']:
            scheduled_time = datetime.fromisoformat(
                article['to_publish_at'].replace('Z', '+00:00')
            )
            hour_key = scheduled_time.replace(minute=0, second=0, microsecond=0)
            scheduled_by_hour[hour_key] = scheduled_by_hour.get(hour_key, 0) + 1
    
    # Define optimal hours (in UTC)
    optimal_hours = [9, 10, 11, 13, 14, 15, 18, 19, 20]
    
    # Find next available slot
    check_time = start_time.replace(minute=0, second=0, microsecond=0)
    
    while check_time <= end_time:
        # Check if this hour is optimal
        is_optimal = check_time.hour in optimal_hours
        
        # Check if this hour has capacity (max 2 articles/hour)
        current_count = scheduled_by_hour.get(check_time, 0)
        
        if is_optimal and current_count < 2:
            # Found a good slot, schedule at :00 or :30
            if current_count == 0:
                return check_time  # Schedule at :00
            else:
                return check_time + timedelta(minutes=30)  # Schedule at :30
        elif not is_optimal and current_count == 0:
            # Use non-optimal hour if necessary
            backup_time = check_time
        
        check_time += timedelta(hours=1)
    
    # If no optimal slot found, use the backup or start_time
    return backup_time if 'backup_time' in locals() else start_time


@app.get("/api/v1/executions")
async def list_executions(
    user: Dict = Depends(get_current_user_from_jwt),
    limit: int = 20,
    offset: int = 0
) -> Dict:
    """
    Get paginated list of executions/sources.

    RLS automatically filters by company_id from JWT.
    """
    try:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")

        company_id = user["company_id"]
        supabase = get_supabase_client()

        result = supabase.client.table("executions")\
            .select("*", count="exact")\
            .eq("company_id", company_id)\
            .order("timestamp", desc=True)\
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

    except Exception as e:
        logger.error("list_executions_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch executions: {str(e)}")


@app.get("/api/v1/styles")
async def list_styles(
    user: Dict = Depends(get_current_user_from_jwt)
) -> Dict:
    """
    Get list of available press styles.

    Returns active styles for the user's company.
    """
    try:
        company_id = user["company_id"]
        supabase = get_supabase_client()

        result = supabase.client.table("press_styles")\
            .select("*")\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .order("created_at", desc=True)\
            .execute()

        return {
            "items": result.data or []
        }

    except Exception as e:
        logger.error("list_styles_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch styles: {str(e)}")


@app.post("/api/v1/context-units/search-vector")
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


# ============================================
# IMAGE ENDPOINTS
# ============================================

class ImageUploadRequest(BaseModel):
    """Request model for base64 image upload."""
    base64: str = Field(..., description="Base64 encoded image data (with or without data URI prefix)")
    filename: Optional[str] = Field(None, description="Original filename (optional, used for extension detection)")

@app.put("/api/v1/images")
async def upload_image(
    image_file: Optional[UploadFile] = File(None),
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """
    Upload an independent image and get a UUID to retrieve it later.
    
    Supports two methods:
    1. Multipart form upload: PUT /api/v1/images with file in 'image_file' field
    2. Base64 JSON: PUT /api/v1/images with JSON body containing base64 data
    
    **Authentication**: Accepts either JWT or API Key
    
    Returns:
        {
            "success": true,
            "image_id": "uuid-generated",
            "size_bytes": 1024,
            "format": "png",
            "url": "/api/v1/images/uuid-generated"
        }
    """
    import uuid
    from utils.context_unit_images import ContextUnitImageProcessor
    
    try:
        # Generate unique UUID for this image
        image_uuid = str(uuid.uuid4())
        
        if image_file:
            # Method 1: Multipart file upload
            if not image_file.content_type or not image_file.content_type.startswith('image/'):
                raise HTTPException(status_code=400, detail="File must be an image")
            
            # Read file content
            image_data = await image_file.read()
            
            # Validate size
            if len(image_data) > ContextUnitImageProcessor.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413, 
                    detail=f"Image too large. Max size: {ContextUnitImageProcessor.MAX_FILE_SIZE} bytes"
                )
            
            # Validate image format and dimensions
            if not ContextUnitImageProcessor.validate_image(image_data):
                raise HTTPException(status_code=400, detail="Invalid image format or dimensions")
            
            # Detect format
            extension = ContextUnitImageProcessor.detect_image_format(image_data)
            if not extension:
                # Fallback to filename extension
                extension = ContextUnitImageProcessor.get_extension_from_filename(image_file.filename or "")
                if not extension:
                    extension = ".jpg"  # Default
            
        else:
            # Method 2: JSON request with base64 (read from request body)
            raise HTTPException(
                status_code=400, 
                detail="Multipart file upload required. Send image as 'image_file' field."
            )
        
        # Save to cache directory with UUID
        cache_dir = Path("/app/cache/images")
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        cache_filename = f"{image_uuid}{extension}"
        cache_path = cache_dir / cache_filename
        
        # Write to disk
        with open(cache_path, "wb") as f:
            f.write(image_data)
        
        logger.info("independent_image_uploaded",
            image_uuid=image_uuid,
            filename=cache_filename,
            size_bytes=len(image_data),
            content_type=image_file.content_type if image_file else "unknown",
            company_id=company_id
        )
        
        return {
            "success": True,
            "image_id": image_uuid,
            "size_bytes": len(image_data),
            "format": extension[1:],  # Remove dot from extension
            "url": f"/api/v1/images/{image_uuid}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_image_error", error=str(e), company_id=company_id)
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")

@app.post("/api/v1/images")
async def upload_image_base64(
    request: ImageUploadRequest,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """
    Upload an image using base64 encoding.
    
    **Authentication**: Accepts either JWT or API Key
    
    Body:
        {
            "base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
            "filename": "my-image.png"  // optional
        }
    
    Returns:
        {
            "success": true,
            "image_id": "uuid-generated",
            "size_bytes": 1024,
            "format": "png",
            "url": "/api/v1/images/uuid-generated"
        }
    """
    import uuid
    from utils.context_unit_images import ContextUnitImageProcessor
    
    try:
        # Generate unique UUID for this image
        image_uuid = str(uuid.uuid4())
        
        # Decode base64 image
        try:
            image_data = ContextUnitImageProcessor.decode_base64_image(request.base64)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Validate image format and dimensions
        if not ContextUnitImageProcessor.validate_image(image_data):
            raise HTTPException(status_code=400, detail="Invalid image format or dimensions")
        
        # Detect format
        extension = ContextUnitImageProcessor.detect_image_format(image_data)
        if not extension:
            # Fallback to filename extension
            extension = ContextUnitImageProcessor.get_extension_from_filename(request.filename or "")
            if not extension:
                extension = ".jpg"  # Default
        
        # Save to cache directory with UUID
        cache_dir = Path("/app/cache/images")
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        cache_filename = f"{image_uuid}{extension}"
        cache_path = cache_dir / cache_filename
        
        # Write to disk
        with open(cache_path, "wb") as f:
            f.write(image_data)
        
        logger.info("independent_image_uploaded_base64",
            image_uuid=image_uuid,
            filename=cache_filename,
            size_bytes=len(image_data),
            original_filename=request.filename,
            company_id=company_id
        )
        
        return {
            "success": True,
            "image_id": image_uuid,
            "size_bytes": len(image_data),
            "format": extension[1:],  # Remove dot from extension
            "url": f"/api/v1/images/{image_uuid}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_image_base64_error", error=str(e), company_id=company_id)
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")


# ============================================
# POOL ENDPOINTS (DEPRECATED - Use /api/v1/context-units with include_pool=true)
# ============================================
# Pool content is now unified into PostgreSQL press_context_units table
# with company_id = 99999999-9999-9999-9999-999999999999
# 
# Access pool content via:
# - GET /api/v1/context-units?include_pool=true
# - POST /api/v1/context-units/search-vector with include_pool=true
#
# Discovery and ingestion still use pool_* jobs in scheduler.py

async def verify_system_access(system_key: str = Header(None, alias="X-System-Key")):
    """Verify System API key (admin operations)."""
    if system_key != settings.system_api_key:
        raise HTTPException(status_code=403, detail="Forbidden - Invalid system key")
    return True


# ============================================
# COMPANY SETTINGS ENDPOINTS
# ============================================

class CompanySettingsUpdate(BaseModel):
    """Model for updating company settings."""
    autogenerate_enabled: Optional[bool] = None
    autogenerate_max: Optional[int] = Field(None, ge=1, le=20)
    autogenerate_min_quality: Optional[float] = Field(None, ge=1.0, le=5.0)
    email_alias: Optional[str] = None
    article_general_settings: Optional[str] = Field(None, max_length=2000)


@app.get("/api/v1/companies/{company_id}/settings")
async def get_company_settings(
    company_id: str,
    auth_company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Get company settings.
    
    **Authentication**: Accepts either JWT or API Key
    
    **Access Control**: Users can only access their own company settings
    """
    try:
        # Verify user can access this company
        if auth_company_id != company_id:
            raise HTTPException(status_code=403, detail="Access denied to this company")
        
        supabase = get_supabase_client()
        
        # Get company with settings
        result = supabase.client.table("companies")\
            .select("id, company_name, settings, is_active")\
            .eq("id", company_id)\
            .eq("is_active", True)\
            .single()\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Company not found")
        
        company = result.data
        
        logger.info("company_settings_retrieved", 
            company_id=company_id,
            auth_company_id=auth_company_id
        )
        
        # Filter out administrative fields from settings
        settings = company.get("settings", {})
        user_settings = {k: v for k, v in settings.items() 
                        if k not in ['unlimited_usage', 'data_ttl_days', 'store_in_qdrant', 'llm_model']}
        
        return {
            "success": True,
            "company": {
                "id": company["id"],
                "name": company["company_name"],
                "settings": user_settings,
                "is_active": company["is_active"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_company_settings_error", 
            error=str(e), 
            company_id=company_id,
            auth_company_id=auth_company_id
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve company settings")


@app.patch("/api/v1/companies/{company_id}/settings")
async def update_company_settings(
    company_id: str,
    settings_update: CompanySettingsUpdate,
    auth_company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Update company settings.
    
    **Authentication**: Accepts either JWT or API Key
    
    **Access Control**: Users can only update their own company settings
    
    **Body**:
        {
            "autogenerate_enabled": true,         // Enable daily article generation
            "autogenerate_max": 5,                // Max articles per day (1-20)
            "autogenerate_min_quality": 3.0,     // Min quality score (1.0-5.0)
            "email_alias": "p.company@ekimen.ai", // Email alias for routing
            "article_general_settings": "Escribir en tono formal y profesional..." // General instructions for article writing (max 2000 chars)
        }
    """
    try:
        # Verify user can access this company
        if auth_company_id != company_id:
            raise HTTPException(status_code=403, detail="Access denied to this company")
        
        supabase = get_supabase_client()
        
        # Get current company settings
        result = supabase.client.table("companies")\
            .select("id, company_name, settings")\
            .eq("id", company_id)\
            .eq("is_active", True)\
            .single()\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Company not found")
        
        company = result.data
        current_settings = company.get("settings", {})
        
        # Build update data (only include non-None values)
        settings_dict = settings_update.model_dump(exclude_none=True)
        
        if not settings_dict:
            raise HTTPException(status_code=400, detail="No settings provided for update")
        
        # Merge with current settings
        updated_settings = {**current_settings, **settings_dict}
        
        # Update in database
        update_result = supabase.client.table("companies")\
            .update({
                "settings": updated_settings,
                "updated_at": datetime.utcnow().isoformat()
            })\
            .eq("id", company_id)\
            .execute()
        
        if not update_result.data:
            raise HTTPException(status_code=500, detail="Failed to update company settings")
        
        logger.info("company_settings_updated", 
            company_id=company_id,
            auth_company_id=auth_company_id,
            updated_fields=list(settings_dict.keys()),
            settings_preview=settings_dict
        )
        
        return {
            "success": True,
            "message": "Company settings updated successfully",
            "company": {
                "id": company_id,
                "name": company["company_name"],
                "settings": updated_settings
            },
            "updated_fields": list(settings_dict.keys())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_company_settings_error", 
            error=str(e), 
            company_id=company_id,
            auth_company_id=auth_company_id
        )
        raise HTTPException(status_code=500, detail="Failed to update company settings")


@app.get("/api/v1/companies/current/settings")
async def get_current_company_settings(
    auth_company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Get settings for the authenticated company.
    
    **Authentication**: Accepts either JWT or API Key
    
    Convenience endpoint that automatically uses the company from auth token.
    """
    try:
        supabase = get_supabase_client()
        
        # Get company with settings
        result = supabase.client.table("companies")\
            .select("id, company_name, settings, is_active")\
            .eq("id", auth_company_id)\
            .eq("is_active", True)\
            .single()\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Company not found")
        
        company = result.data
        
        logger.info("current_company_settings_retrieved", 
            company_id=auth_company_id
        )
        
        # Filter out administrative fields from settings
        settings = company.get("settings", {})
        user_settings = {k: v for k, v in settings.items() 
                        if k not in ['unlimited_usage', 'data_ttl_days', 'store_in_qdrant', 'llm_model']}
        
        return {
            "success": True,
            "company": {
                "id": company["id"],
                "name": company["company_name"],
                "settings": user_settings,
                "is_active": company["is_active"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_current_company_settings_error", 
            error=str(e), 
            company_id=auth_company_id
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve current company settings")


@app.patch("/api/v1/companies/current/settings")
async def update_current_company_settings(
    settings_update: CompanySettingsUpdate,
    auth_company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Update settings for the authenticated company.
    
    **Authentication**: Accepts either JWT or API Key
    
    Convenience endpoint that automatically uses the company from auth token.
    Same body format as PATCH /api/v1/companies/{company_id}/settings
    """
    try:
        supabase = get_supabase_client()
        
        # Get current company settings
        result = supabase.client.table("companies")\
            .select("id, company_name, settings")\
            .eq("id", auth_company_id)\
            .eq("is_active", True)\
            .single()\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Company not found")
        
        company = result.data
        current_settings = company.get("settings", {})
        
        # Build update data (only include non-None values)
        settings_dict = settings_update.model_dump(exclude_none=True)
        
        if not settings_dict:
            raise HTTPException(status_code=400, detail="No settings provided for update")
        
        # Merge with current settings
        updated_settings = {**current_settings, **settings_dict}
        
        # Update in database
        update_result = supabase.client.table("companies")\
            .update({
                "settings": updated_settings,
                "updated_at": datetime.utcnow().isoformat()
            })\
            .eq("id", auth_company_id)\
            .execute()
        
        if not update_result.data:
            raise HTTPException(status_code=500, detail="Failed to update company settings")
        
        logger.info("current_company_settings_updated", 
            company_id=auth_company_id,
            updated_fields=list(settings_dict.keys()),
            settings_preview=settings_dict
        )
        
        return {
            "success": True,
            "message": "Company settings updated successfully",
            "company": {
                "id": auth_company_id,
                "name": company["company_name"],
                "settings": updated_settings
            },
            "updated_fields": list(settings_dict.keys())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_current_company_settings_error", 
            error=str(e), 
            company_id=auth_company_id
        )
        raise HTTPException(status_code=500, detail="Failed to update current company settings")


# ============================================
# PUBLICATION TARGETS ENDPOINTS
# ============================================

@app.get("/api/v1/publication-targets")
async def list_publication_targets(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Get all publication targets for the company.
    
    Returns list without encrypted credentials for security.
    """
    try:
        supabase = get_supabase_client()
        
        result = supabase.client.table("press_publication_targets")\
            .select("id, platform_type, name, base_url, is_default, is_active, created_at, updated_at, last_tested_at, test_result")\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .order("created_at", desc=True)\
            .execute()
        
        logger.info("publication_targets_listed",
            company_id=company_id,
            count=len(result.data) if result.data else 0
        )
        
        return {
            "targets": result.data or []
        }
        
    except Exception as e:
        logger.error("list_publication_targets_error",
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to fetch publication targets")


@app.post("/api/v1/publication-targets")
async def create_publication_target(
    target_data: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Create a new publication target with encrypted credentials."""
    try:
        from utils.credential_manager import CredentialManager
        from publishers.publisher_factory import PublisherFactory
        
        logger.info("create_publication_target_request",
            company_id=company_id,
            received_fields=list(target_data.keys())
        )
        
        # Validate required fields
        required_fields = ['platform_type', 'name', 'base_url', 'credentials']
        for field in required_fields:
            if field not in target_data:
                logger.error("missing_required_field", field=field, received_data=target_data)
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        platform_type = target_data['platform_type']
        if platform_type not in PublisherFactory.get_supported_platforms():
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported platform: {platform_type}. Supported: {PublisherFactory.get_supported_platforms()}"
            )
        
        # Encrypt credentials
        credentials = target_data['credentials']
        masked_creds = CredentialManager.mask_credentials_for_logging(credentials)
        logger.info("publication_target_validation_passed",
            company_id=company_id,
            platform_type=platform_type,
            name=target_data['name'],
            base_url=target_data['base_url'],
            credentials=masked_creds
        )
        
        credentials_encrypted = CredentialManager.encrypt_credentials(credentials)
        
        # Test connection before saving
        publisher = PublisherFactory.create_publisher(
            platform_type, 
            target_data['base_url'], 
            credentials_encrypted
        )
        
        test_result = await publisher.test_connection()
        
        logger.info("wordpress_connection_test_result",
            company_id=company_id,
            platform_type=platform_type,
            base_url=target_data['base_url'],
            success=test_result.get('success'),
            message=test_result.get('message', 'No message')
        )
        
        if not test_result.get('success'):
            raise HTTPException(
                status_code=400,
                detail=f"Connection test failed: {test_result.get('message')}"
            )
        
        # Save to database
        supabase = get_supabase_client()
        
        insert_data = {
            "company_id": company_id,
            "platform_type": platform_type,
            "name": target_data['name'],
            "base_url": target_data['base_url'],
            "credentials_encrypted": credentials_encrypted.hex(),  # Convert bytes to hex string
            "is_default": target_data.get('is_default', False),
            "last_tested_at": datetime.utcnow().isoformat(),
            "test_result": test_result
        }
        
        result = supabase.client.table("press_publication_targets")\
            .insert(insert_data)\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create publication target")
        
        created_target = result.data[0]
        
        # Remove encrypted credentials from response
        response_data = {k: v for k, v in created_target.items() if k != 'credentials_encrypted'}
        
        logger.info("publication_target_created",
            target_id=created_target['id'],
            company_id=company_id,
            platform=platform_type,
            name=target_data['name']
        )
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_publication_target_error",
            company_id=company_id,
            target_data=str(target_data),
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Failed to create publication target: {str(e)}")


@app.get("/api/v1/publication-targets/{target_id}")
async def get_publication_target(
    target_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Get a specific publication target (without credentials)."""
    try:
        supabase = get_supabase_client()
        
        result = supabase.client.table("press_publication_targets")\
            .select("id, platform_type, name, base_url, is_default, is_active, created_at, updated_at, last_tested_at, test_result")\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .maybe_single()\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Publication target not found")
        
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_publication_target_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to fetch publication target")


@app.put("/api/v1/publication-targets/{target_id}")
async def update_publication_target(
    target_id: str,
    target_data: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Update publication target."""
    try:
        from utils.credential_manager import CredentialManager
        
        supabase = get_supabase_client()
        
        # Check target exists and belongs to company
        existing = supabase.client.table("press_publication_targets")\
            .select("*")\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .maybe_single()\
            .execute()
        
        if not existing.data:
            raise HTTPException(status_code=404, detail="Publication target not found")
        
        update_data = {}
        
        # Handle credential update
        if 'credentials' in target_data:
            credentials_encrypted = CredentialManager.encrypt_credentials(target_data['credentials'])
            # Convert bytes to hex string for database storage
            update_data['credentials_encrypted'] = credentials_encrypted.hex()
        
        # Handle other field updates
        updatable_fields = ['name', 'base_url', 'is_default']
        for field in updatable_fields:
            if field in target_data:
                update_data[field] = target_data[field]
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        
        update_data['updated_at'] = datetime.utcnow().isoformat()
        
        result = supabase.client.table("press_publication_targets")\
            .update(update_data)\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to update publication target")
        
        updated_target = result.data[0]
        
        # Remove encrypted credentials from response
        response_data = {k: v for k, v in updated_target.items() if k != 'credentials_encrypted'}
        
        logger.info("publication_target_updated",
            target_id=target_id,
            company_id=company_id,
            updated_fields=list(update_data.keys())
        )
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_publication_target_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to update publication target")


@app.delete("/api/v1/publication-targets/{target_id}")
async def delete_publication_target(
    target_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Soft delete (deactivate) a publication target."""
    try:
        supabase = get_supabase_client()
        
        result = supabase.client.table("press_publication_targets")\
            .update({"is_active": False, "updated_at": datetime.utcnow().isoformat()})\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Publication target not found")
        
        logger.info("publication_target_deleted",
            target_id=target_id,
            company_id=company_id
        )
        
        return {"success": True, "message": "Publication target deactivated"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_publication_target_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to delete publication target")


@app.post("/api/v1/publication-targets/{target_id}/test")
async def test_publication_target(
    target_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Test connection to a publication target."""
    try:
        from publishers.publisher_factory import PublisherFactory
        
        supabase = get_supabase_client()
        
        # Get target with credentials
        result = supabase.client.table("press_publication_targets")\
            .select("*")\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .maybe_single()\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Publication target not found")
        
        target = result.data
        
        # Create publisher and test
        publisher = PublisherFactory.create_publisher(
            target['platform_type'],
            target['base_url'],
            target['credentials_encrypted']
        )
        
        test_result = await publisher.test_connection()
        
        # Update test result in database
        supabase.client.table("press_publication_targets")\
            .update({
                "last_tested_at": datetime.utcnow().isoformat(),
                "test_result": test_result
            })\
            .eq("id", target_id)\
            .execute()
        
        logger.info("publication_target_tested",
            target_id=target_id,
            company_id=company_id,
            success=test_result.get('success')
        )
        
        return test_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("test_publication_target_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to test publication target")


def _generate_slug_from_title(title: str) -> str:
    """Generate WordPress-compatible slug from title."""
    import re
    
    # Convert to lowercase and replace common Spanish characters
    slug = title.lower()
    
    # Replace Spanish characters
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u',
        'ñ': 'n', 'ç': 'c'
    }
    
    for char, replacement in replacements.items():
        slug = slug.replace(char, replacement)
    
    # Remove special characters and replace spaces with hyphens
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = slug.strip('-')
    
    # Limit length to 200 characters (WordPress limit)
    return slug[:200]


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
