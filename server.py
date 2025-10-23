"""FastAPI server for semantika API.

Handles all HTTP requests for document ingestion, search, and aggregation.
"""

from datetime import datetime
from typing import Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from utils.logger import get_logger
from utils.config import settings

# Initialize logger
logger = get_logger("api")

# Initialize FastAPI app
app = FastAPI(
    title="semantika API",
    description="Semantic data pipeline with multi-tenant support",
    version="0.1.0",
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
