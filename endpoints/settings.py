"""Settings and integrations endpoints."""

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_company_id_from_auth

logger = get_logger("api.settings")
router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# MCP Server URL - will be configurable via env in production
MCP_SERVER_URL = "https://api.ekimen.ai/mcp/sse"


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
