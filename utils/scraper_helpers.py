"""Helper functions for configuring and managing scraper sources.

Utilities for:
- Creating scraping sources
- Updating scraping configurations
- Testing scraper workflow
"""

from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from .supabase_client import get_supabase_client
from .logger import get_logger

logger = get_logger("scraper_helpers")


async def create_scraping_source(
    company_id: str,
    client_id: str,
    url: str,
    source_name: str,
    url_type: str = "article",
    frequency_minutes: int = 60,
    cron_schedule: Optional[str] = None,
    is_active: bool = True,
    description: Optional[str] = None,
    tags: Optional[list] = None
) -> Dict[str, Any]:
    """Create a new scraping source with intelligent monitoring.
    
    Args:
        company_id: Company UUID
        client_id: Client UUID
        url: URL to scrape
        source_name: Human-readable source name
        url_type: 'article' or 'index'
        frequency_minutes: Scraping frequency in minutes
        cron_schedule: Optional cron schedule (format: "HH:MM")
        is_active: Is source active
        description: Optional description
        tags: Optional list of tags
        
    Returns:
        Dict with source_id and creation status
    """
    logger.info("create_scraping_source_start",
        company_id=company_id,
        url=url,
        url_type=url_type
    )
    
    try:
        supabase = get_supabase_client()
        
        source_id = str(uuid.uuid4())
        source_code = f"scraper_{source_name.lower().replace(' ', '_')}"
        
        # Build config
        config = {
            "url": url,
            "url_type": url_type
        }
        
        # Build schedule config
        schedule_config = {}
        if cron_schedule:
            schedule_config["cron"] = cron_schedule
        else:
            schedule_config["frequency_minutes"] = frequency_minutes
        
        # Create source
        source_data = {
            "source_id": source_id,
            "client_id": client_id,
            "company_id": company_id,
            "source_code": source_code,
            "source_name": source_name,
            "source_type": "scraping",
            "config": config,
            "schedule_config": schedule_config,
            "is_active": is_active,
            "is_test": False,
            "priority": "normal",
            "description": description or f"Web scraping: {url}",
            "tags": tags or ["scraping", url_type],
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        result = supabase.client.table("sources").insert(source_data).execute()
        
        if result.data and len(result.data) > 0:
            logger.info("scraping_source_created",
                source_id=source_id,
                source_name=source_name,
                url=url
            )
            return {
                "success": True,
                "source_id": source_id,
                "source": result.data[0]
            }
        else:
            logger.error("scraping_source_creation_failed",
                source_name=source_name
            )
            return {
                "success": False,
                "error": "No data returned"
            }
            
    except Exception as e:
        logger.error("create_scraping_source_error",
            source_name=source_name,
            error=str(e)
        )
        return {
            "success": False,
            "error": str(e)
        }


async def update_scraping_source_config(
    source_id: str,
    url: Optional[str] = None,
    url_type: Optional[str] = None,
    frequency_minutes: Optional[int] = None,
    cron_schedule: Optional[str] = None,
    is_active: Optional[bool] = None
) -> Dict[str, Any]:
    """Update scraping source configuration.
    
    Args:
        source_id: Source UUID
        url: New URL (optional)
        url_type: New URL type (optional)
        frequency_minutes: New frequency (optional)
        cron_schedule: New cron schedule (optional)
        is_active: New active status (optional)
        
    Returns:
        Update result
    """
    logger.info("update_scraping_source_config_start", source_id=source_id)
    
    try:
        supabase = get_supabase_client()
        
        # Fetch current source
        result = supabase.client.table("sources").select("*").eq(
            "source_id", source_id
        ).execute()
        
        if not result.data or len(result.data) == 0:
            return {"success": False, "error": "Source not found"}
        
        current_source = result.data[0]
        current_config = current_source.get("config", {})
        current_schedule = current_source.get("schedule_config", {})
        
        # Update config
        if url:
            current_config["url"] = url
        if url_type:
            current_config["url_type"] = url_type
        
        # Update schedule
        if cron_schedule:
            current_schedule["cron"] = cron_schedule
            current_schedule.pop("frequency_minutes", None)
        elif frequency_minutes is not None:
            current_schedule["frequency_minutes"] = frequency_minutes
            current_schedule.pop("cron", None)
        
        # Build update data
        update_data = {
            "config": current_config,
            "schedule_config": current_schedule,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if is_active is not None:
            update_data["is_active"] = is_active
        
        # Update
        update_result = supabase.client.table("sources").update(
            update_data
        ).eq("source_id", source_id).execute()
        
        if update_result.data:
            logger.info("scraping_source_updated", source_id=source_id)
            return {
                "success": True,
                "source": update_result.data[0]
            }
        else:
            return {"success": False, "error": "Update failed"}
            
    except Exception as e:
        logger.error("update_scraping_source_error",
            source_id=source_id,
            error=str(e)
        )
        return {"success": False, "error": str(e)}


async def test_scraping_source(
    company_id: str,
    source_id: str,
    url: str,
    url_type: str = "article"
) -> Dict[str, Any]:
    """Test scraping workflow on a URL without saving to database.
    
    Args:
        company_id: Company UUID
        source_id: Source UUID
        url: URL to test
        url_type: 'article' or 'index'
        
    Returns:
        Workflow execution result
    """
    logger.info("test_scraping_source_start",
        company_id=company_id,
        url=url,
        url_type=url_type
    )
    
    try:
        from sources.scraper_workflow import scrape_url
        
        result = await scrape_url(
            company_id=company_id,
            source_id=source_id,
            url=url,
            url_type=url_type
        )
        
        # Format test result
        return {
            "success": not result.get("error"),
            "url": url,
            "url_type": url_type,
            "title": result.get("title"),
            "summary": result.get("summary"),
            "change_type": result.get("change_info", {}).get("change_type"),
            "published_at": result.get("published_at"),
            "date_source": result.get("date_source"),
            "content_items_found": len(result.get("content_items", [])),
            "context_units_created": len(result.get("context_unit_ids", [])),
            "monitored_url_id": result.get("monitored_url_id"),
            "error": result.get("error")
        }
        
    except Exception as e:
        logger.error("test_scraping_source_error",
            url=url,
            error=str(e)
        )
        return {
            "success": False,
            "error": str(e)
        }


async def get_monitored_urls_for_source(
    source_id: str,
    company_id: str,
    limit: int = 100
) -> Dict[str, Any]:
    """Get all monitored URLs for a scraping source.
    
    Args:
        source_id: Source UUID
        company_id: Company UUID
        limit: Maximum number of URLs to return
        
    Returns:
        List of monitored URLs
    """
    try:
        supabase = get_supabase_client()
        
        result = supabase.client.table("monitored_urls").select(
            "id, url, url_type, title, status, last_scraped_at, published_at, created_at"
        ).eq("source_id", source_id).eq("company_id", company_id).limit(limit).execute()
        
        if result.data:
            return {
                "success": True,
                "count": len(result.data),
                "monitored_urls": result.data
            }
        else:
            return {
                "success": True,
                "count": 0,
                "monitored_urls": []
            }
            
    except Exception as e:
        logger.error("get_monitored_urls_error",
            source_id=source_id,
            error=str(e)
        )
        return {
            "success": False,
            "error": str(e)
        }


async def get_url_change_history(
    monitored_url_id: str,
    limit: int = 50
) -> Dict[str, Any]:
    """Get change history for a monitored URL.
    
    Args:
        monitored_url_id: Monitored URL UUID
        limit: Maximum number of changes to return
        
    Returns:
        List of changes
    """
    try:
        supabase = get_supabase_client()
        
        result = supabase.client.table("url_change_log").select(
            "*"
        ).eq("monitored_url_id", monitored_url_id).order(
            "detected_at", desc=True
        ).limit(limit).execute()
        
        if result.data:
            return {
                "success": True,
                "count": len(result.data),
                "changes": result.data
            }
        else:
            return {
                "success": True,
                "count": 0,
                "changes": []
            }
            
    except Exception as e:
        logger.error("get_url_change_history_error",
            monitored_url_id=monitored_url_id,
            error=str(e)
        )
        return {
            "success": False,
            "error": str(e)
        }
