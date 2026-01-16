"""MCP Server for Semantika.

Standalone server that exposes Semantika functionality via MCP protocol.
Runs on port 8001 and is proxied via nginx at /mcp.

Usage:
    python mcp_server.py

Environment:
    Same .env as main API (Supabase, etc.)
"""

import os
import sys
import asyncio
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client

logger = get_logger("mcp_server")

# ============================================
# AUTHENTICATION
# ============================================

async def authenticate_api_key(api_key: str) -> dict:
    """
    Validate API key and return client info.

    Args:
        api_key: The X-API-Key header value

    Returns:
        Dict with client_id, company_id, client_name

    Raises:
        HTTPException if invalid
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    supabase = get_supabase_client()

    result = supabase.client.table("clients")\
        .select("client_id, company_id, client_name, is_active")\
        .eq("api_key", api_key)\
        .maybe_single()\
        .execute()

    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not result.data.get("is_active"):
        raise HTTPException(status_code=403, detail="Client is inactive")

    if not result.data.get("company_id"):
        raise HTTPException(status_code=403, detail="Client has no company assigned")

    return result.data


# ============================================
# MCP SERVER FACTORY
# ============================================

# Cache of MCP servers per company (avoid recreating on each request)
_mcp_servers = {}


def get_mcp_server(company_id: str, client_name: str):
    """Get or create MCP server for a company."""
    from mcp_tools.tools import create_mcp_server

    if company_id not in _mcp_servers:
        logger.info("mcp_server_created", company_id=company_id, client_name=client_name)
        _mcp_servers[company_id] = create_mcp_server(company_id, client_name)

    return _mcp_servers[company_id]


# ============================================
# FASTAPI APP
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("mcp_server_starting", port=8001)
    yield
    logger.info("mcp_server_stopping")


app = FastAPI(
    title="Semantika MCP Server",
    description="MCP interface for Semantika platform",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for browser-based MCP clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "semantika-mcp",
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint with server info."""
    return {
        "name": "Semantika MCP Server",
        "version": "1.0.0",
        "protocol": "MCP (Model Context Protocol)",
        "auth": "X-API-Key header required",
        "tools": [
            "search_news",
            "get_news_detail",
            "list_articles",
            "get_article",
            "create_article",
            "update_article",
            "publish_article",
            "get_filter_options",
            "get_company_stats"
        ]
    }


@app.get("/tools")
async def list_tools(x_api_key: str = Header(None, alias="X-API-Key")):
    """
    List available MCP tools.

    Returns tool definitions in MCP format.
    """
    client = await authenticate_api_key(x_api_key)
    mcp_server = get_mcp_server(client["company_id"], client["client_name"])

    # Get tools from the MCP server
    tools = []

    # Access the registered tools from FastMCP
    if hasattr(mcp_server, '_tool_manager') and hasattr(mcp_server._tool_manager, 'tools'):
        for name, tool in mcp_server._tool_manager.tools.items():
            tools.append({
                "name": name,
                "description": tool.description if hasattr(tool, 'description') else None,
                "inputSchema": tool.parameters if hasattr(tool, 'parameters') else {}
            })

    return {"tools": tools}


@app.post("/call")
async def call_tool(
    request: Request,
    x_api_key: str = Header(None, alias="X-API-Key")
):
    """
    Call an MCP tool directly.

    Body:
        {
            "tool": "search_news",
            "arguments": {
                "query": "energías renovables",
                "days_back": 7
            }
        }

    Returns:
        Tool execution result
    """
    client = await authenticate_api_key(x_api_key)
    mcp_server = get_mcp_server(client["company_id"], client["client_name"])

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    tool_name = body.get("tool")
    arguments = body.get("arguments", {})

    if not tool_name:
        raise HTTPException(status_code=400, detail="Missing 'tool' field")

    logger.info("mcp_tool_call",
        company_id=client["company_id"],
        client_name=client["client_name"],
        tool=tool_name
    )

    try:
        # Get the tool function from FastMCP
        if hasattr(mcp_server, '_tool_manager'):
            tool_manager = mcp_server._tool_manager
            if hasattr(tool_manager, 'tools') and tool_name in tool_manager.tools:
                tool = tool_manager.tools[tool_name]
                # Call the tool function
                if asyncio.iscoroutinefunction(tool.fn):
                    result = await tool.fn(**arguments)
                else:
                    result = tool.fn(**arguments)

                return {"result": result}

        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    except HTTPException:
        raise
    except TypeError as e:
        # Handle argument errors
        raise HTTPException(status_code=400, detail=f"Invalid arguments: {str(e)}")
    except Exception as e:
        logger.error("mcp_tool_call_error",
            tool=tool_name,
            error=str(e),
            company_id=client["company_id"]
        )
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# SSE TRANSPORT (for native MCP clients)
# ============================================

@app.get("/sse")
async def mcp_sse(
    request: Request,
    x_api_key: str = Header(None, alias="X-API-Key")
):
    """
    SSE endpoint for MCP protocol.

    This is the native MCP transport for Claude Desktop and other MCP clients.
    """
    client = await authenticate_api_key(x_api_key)
    mcp_server = get_mcp_server(client["company_id"], client["client_name"])

    logger.info("mcp_sse_connection",
        company_id=client["company_id"],
        client_name=client["client_name"]
    )

    # For now, return instructions on how to use the API
    # Full SSE implementation requires more complex handling
    return JSONResponse({
        "message": "SSE transport coming soon. Use /call endpoint for now.",
        "example": {
            "method": "POST",
            "url": "/call",
            "headers": {"X-API-Key": "sk-xxx", "Content-Type": "application/json"},
            "body": {"tool": "search_news", "arguments": {"query": "bilbao"}}
        }
    })


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MCP_PORT", "8001"))

    logger.info("starting_mcp_server", host="0.0.0.0", port=port)

    uvicorn.run(
        "mcp_server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )
