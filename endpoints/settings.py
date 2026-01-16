"""Settings and integrations endpoints."""

import os
import uuid
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_company_id_from_auth

logger = get_logger("api.settings")
router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# MCP Server URL - configurable via environment variable
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://mcp.ekimen.ai")


@router.get("/integrations")
async def get_integrations(company_id: str = Depends(get_company_id_from_auth)) -> Dict[str, Any]:
    """
    Get integration settings for the current user's company.

    Returns API key and MCP configuration for Claude Desktop.

    Auth: JWT or API Key

    Returns:
        {
            "api_key": "sk-client-...",
            "mcp_url": "https://api.ekimen.ai/mcp/sse",
            "mcp_config": {
                "mcpServers": {
                    "semantika": {
                        "url": "...",
                        "headers": {"X-API-Key": "..."}
                    }
                }
            }
        }
    """
    try:
        supabase = get_supabase_client()

        # Get the active client for this company
        result = supabase.client.table("clients")\
            .select("api_key, client_name")\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .limit(1)\
            .execute()

        if not result.data:
            logger.warn("no_active_client_for_company", company_id=company_id)
            raise HTTPException(
                status_code=404,
                detail="No active API client found for your company. Contact support."
            )

        api_key = result.data[0]["api_key"]
        client_name = result.data[0].get("client_name", "semantika")

        logger.info("integrations_retrieved",
            company_id=company_id,
            client_name=client_name
        )

        return {
            "api_key": api_key,
            "mcp_url": MCP_SERVER_URL,
            "mcp_config": {
                "mcpServers": {
                    "semantika": {
                        "url": MCP_SERVER_URL,
                        "headers": {
                            "X-API-Key": api_key
                        }
                    }
                }
            },
            "instructions": {
                "es": "Copia este JSON en tu archivo de configuración de Claude Desktop (~/.config/claude/claude_desktop_config.json en Linux, ~/Library/Application Support/Claude/claude_desktop_config.json en Mac)",
                "en": "Copy this JSON to your Claude Desktop config file"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("integrations_error", error=str(e), company_id=company_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve integration settings")


@router.post("/integrations/regenerate-key")
async def regenerate_api_key(company_id: str = Depends(get_company_id_from_auth)) -> Dict[str, Any]:
    """
    Regenerate API key for the current user's company.

    This will invalidate the old key immediately.

    Auth: JWT or API Key

    Returns:
        {
            "success": true,
            "api_key": "sk-new-...",
            "message": "API key regenerated successfully"
        }
    """
    try:
        supabase = get_supabase_client()

        # Get the active client for this company
        result = supabase.client.table("clients")\
            .select("client_id, client_name")\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .limit(1)\
            .execute()

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="No active API client found for your company"
            )

        client_id = result.data[0]["client_id"]
        client_name = result.data[0].get("client_name", "unknown")

        # Generate new API key
        new_api_key = f"sk-{client_name}-{uuid.uuid4()}"

        # Update the client with the new key
        update_result = supabase.client.table("clients")\
            .update({
                "api_key": new_api_key,
                "updated_at": datetime.utcnow().isoformat()
            })\
            .eq("client_id", client_id)\
            .execute()

        if not update_result.data:
            raise HTTPException(status_code=500, detail="Failed to update API key")

        logger.info("api_key_regenerated",
            company_id=company_id,
            client_id=client_id,
            client_name=client_name
        )

        return {
            "success": True,
            "api_key": new_api_key,
            "message": "API key regenerated successfully. The old key is now invalid."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("regenerate_key_error", error=str(e), company_id=company_id)
        raise HTTPException(status_code=500, detail="Failed to regenerate API key")
