"""FastAPI server for semantika API.

Handles all HTTP requests for document ingestion, search, and aggregation.

Version: 2025-10-28
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
import asyncio
import subprocess
import io
import re
from pathlib import Path

from fastapi import FastAPI, Request, Header, HTTPException, Depends, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response, HTMLResponse
from pydantic import BaseModel, Field
import aiohttp
import os
from urllib.parse import parse_qs

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client
from utils.supabase_auth import get_current_user_from_jwt
from utils.usage_tracker import get_usage_tracker
from utils.llm_registry import get_llm_registry
from utils.unified_context_ingester import ingest_context_unit
from core_ingest import IngestPipeline
from publishers.twitter_publisher import TwitterPublisher

# Import endpoint routers
from endpoints import tts as tts_router
from endpoints import companies as companies_router
from endpoints import publication_targets as publication_targets_router
from endpoints import oauth_twitter as oauth_twitter_router
from endpoints import oauth_linkedin as oauth_linkedin_router
from endpoints import oauth_facebook as oauth_facebook_router
from endpoints import auth as auth_router
from endpoints import legacy as legacy_router
from endpoints import images as images_router
from endpoints import process as process_router
from endpoints import context_units as context_units_router
from endpoints import articles as articles_router
from endpoints import settings as settings_router

# Import shared auth dependencies
from utils.auth_dependencies import (
    get_api_key,
    get_current_client,
    get_current_user_from_jwt_optional,
    get_current_client_optional,
    get_company_id_from_auth,
    get_auth_context
)

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

# Include endpoint routers
app.include_router(tts_router.router)
app.include_router(companies_router.router)
app.include_router(publication_targets_router.router)
app.include_router(oauth_twitter_router.router)
app.include_router(oauth_linkedin_router.router)
app.include_router(oauth_facebook_router.router)
app.include_router(auth_router.router)
app.include_router(legacy_router.router)
app.include_router(images_router.router)
app.include_router(process_router.router)
app.include_router(context_units_router.router)
app.include_router(articles_router.router)
app.include_router(settings_router.router)


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
async def get_me(auth: Dict = Depends(get_auth_context)) -> Dict:
    """
    Get current authenticated client information.

    Requires: X-API-Key header

    Returns:
        Client information
    """
    return {
        "client_id": auth["client_id"],
        "client_name": auth.get("client_name"),
        "email": auth.get("email"),
        "is_active": auth.get("is_active"),
        "created_at": auth.get("created_at"),
        "auth_type": auth.get("auth_type")
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
