"""Company settings endpoints."""

from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_company_id_from_auth

logger = get_logger("api.companies")
router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


class CompanySettingsUpdate(BaseModel):
    """Model for updating company settings."""
    # Auto-generation settings
    autogenerate_enabled: Optional[bool] = None
    autogenerate_max: Optional[int] = Field(None, ge=1, le=20)
    autogenerate_min_quality: Optional[float] = Field(None, ge=1.0, le=5.0)
    # General settings
    email_alias: Optional[str] = None
    article_general_settings: Optional[str] = Field(None, max_length=2000)
    # Notification settings
    disable_ai_notification: Optional[bool] = None
    disable_probabilistic_mark: Optional[bool] = None


@router.get("/{company_id}/settings")
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


@router.patch("/{company_id}/settings")
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


@router.get("/current/settings")
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


@router.patch("/current/settings")
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
