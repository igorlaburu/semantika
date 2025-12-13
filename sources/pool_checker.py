"""Lightweight pool source checker with rotation.

Checks one source at a time in rotation:
1. Pick next source (by last_checked_at)
2. Fetch HTML
3. Hash comparison (lightweight)
4. If change detected → LLM enrichment (heavyweight)
5. Update last_checked_at
6. EXIT (process dies)

Designed to run every 5 minutes via scheduler.
"""

from typing import Optional, Dict, Any
from datetime import datetime
import asyncio

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.content_hasher import compute_content_hashes
from sources.scraper_workflow import scrape_url

logger = get_logger("pool_checker")


async def get_next_source_to_check() -> Optional[Dict[str, Any]]:
    """Get next source to check (rotation by last_checked_at).
    
    Returns:
        Source dict or None if no sources available
    """
    try:
        supabase = get_supabase_client()
        
        # Get next source to check (oldest last_checked_at or never checked)
        # Only scraping sources (system jobs don't have URLs)
        result = supabase.client.table("sources")\
            .select("*")\
            .eq("is_active", True)\
            .eq("source_type", "scraping")\
            .order("last_checked_at", desc=False, nullsfirst=True)\
            .limit(1)\
            .execute()
        
        if not result.data:
            logger.warn("no_active_sources_to_check")
            return None
        
        source = result.data[0]
        
        logger.info("next_source_selected",
            source_id=source["source_id"],
            source_name=source["source_name"],
            last_checked_at=source.get("last_checked_at")
        )
        
        return source
    
    except Exception as e:
        logger.error("get_next_source_error", error=str(e))
        return None


async def check_source_for_changes(source: Dict[str, Any]) -> Dict[str, Any]:
    """Check single source for changes.
    
    Lightweight hash check first, heavy LLM processing only if changed.
    
    Args:
        source: Source from database
        
    Returns:
        Result dict with status and stats
    """
    source_id = source["source_id"]
    source_name = source["source_name"]
    company_id = source["company_id"]
    config = source.get("config", {})
    url = config.get("url")
    
    if not url:
        logger.error("source_missing_url", source_id=source_id)
        return {
            "success": False,
            "reason": "missing_url",
            "source_id": source_id
        }
    
    logger.info("checking_source",
        source_id=source_id,
        source_name=source_name,
        url=url
    )
    
    try:
        # STEP 1: Lightweight scrape (just fetch + hash)
        # Use scraper_workflow which already has change detection
        url_type = config.get("url_type", "article")
        
        result = await scrape_url(
            company_id=company_id,
            source_id=source_id,
            url=url,
            url_type=url_type
        )
        
        change_type = result.get("change_info", {}).get("change_type", "unknown")
        context_units_created = len(result.get("context_unit_ids", []))
        workflow_error = result.get("error")
        
        logger.info("source_check_completed",
            source_id=source_id,
            source_name=source_name,
            change_type=change_type,
            context_units_created=context_units_created,
            had_error=bool(workflow_error)
        )
        
        return {
            "success": True,
            "source_id": source_id,
            "source_name": source_name,
            "change_type": change_type,
            "context_units_created": context_units_created,
            "error": workflow_error
        }
    
    except Exception as e:
        logger.error("check_source_error",
            source_id=source_id,
            source_name=source_name,
            error=str(e)
        )
        return {
            "success": False,
            "reason": "exception",
            "source_id": source_id,
            "error": str(e)
        }


async def update_last_checked(source_id: str):
    """Update last_checked_at timestamp for source.
    
    Args:
        source_id: Source UUID
    """
    try:
        supabase = get_supabase_client()
        
        supabase.client.table("sources")\
            .update({"last_checked_at": datetime.utcnow().isoformat()})\
            .eq("source_id", source_id)\
            .execute()
        
        logger.debug("last_checked_updated", source_id=source_id)
    
    except Exception as e:
        logger.error("update_last_checked_error",
            source_id=source_id,
            error=str(e)
        )


async def check_next_source():
    """Main function: Check next source in rotation and exit.
    
    Called by scheduler every N minutes.
    Process dies after execution.
    """
    logger.info("pool_checker_start")
    
    try:
        # Get next source to check
        source = await get_next_source_to_check()
        
        if not source:
            logger.info("pool_checker_no_sources", message="No active sources to check")
            return
        
        source_id = source["source_id"]
        
        # Check source for changes
        result = await check_source_for_changes(source)
        
        # Update last_checked_at timestamp
        await update_last_checked(source_id)
        
        # Log result
        if result.get("success"):
            logger.info("pool_checker_completed",
                source_id=source_id,
                source_name=result.get("source_name"),
                change_type=result.get("change_type"),
                context_units_created=result.get("context_units_created", 0)
            )
        else:
            logger.error("pool_checker_failed",
                source_id=source_id,
                reason=result.get("reason"),
                error=result.get("error")
            )
    
    except Exception as e:
        logger.error("pool_checker_error", error=str(e))
    
    finally:
        logger.info("pool_checker_end", message="Process exiting")
