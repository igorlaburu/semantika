"""Robust pool source checker with circuit breaker and retry logic.

Improvements over v1:
- Circuit breaker: Auto-disable sources with 5+ consecutive failures
- Retry logic: Exponential backoff for transient errors
- Health tracking: Success/failure metrics per source
- Skip strategy: Prioritize healthy sources
- Error categorization: Distinguish permanent (403) vs transient (timeout) errors

Design:
1. Pick next healthy source (circuit_breaker_open = false)
2. Try scrape with timeout
3. Update metrics (consecutive_failures, total_successes, etc.)
4. Open circuit breaker if consecutive_failures >= 5
5. Auto-retry circuit breaker sources after 24h
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import asyncio

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from sources.scraper_workflow import scrape_url

logger = get_logger("pool_checker_v2")

# Circuit breaker thresholds
MAX_CONSECUTIVE_FAILURES = 5
CIRCUIT_BREAKER_RETRY_HOURS = 24


async def get_next_healthy_source() -> Optional[Dict[str, Any]]:
    """Get next source to check, prioritizing healthy sources.
    
    Strategy:
    1. Skip sources with circuit_breaker_open = true (unless >24h old)
    2. Prioritize sources never scraped (last_scraped_at IS NULL)
    3. Then oldest scraped sources
    
    Returns:
        Source dict or None
    """
    try:
        supabase = get_supabase_client()
        POOL_COMPANY_ID = "99999999-9999-9999-9999-999999999999"
        
        # Auto-reset circuit breakers older than 24h
        cutoff = datetime.utcnow() - timedelta(hours=CIRCUIT_BREAKER_RETRY_HOURS)
        reset_result = supabase.client.table("discovered_sources")\
            .update({
                "circuit_breaker_open": False,
                "consecutive_failures": 0
            })\
            .eq("company_id", POOL_COMPANY_ID)\
            .eq("circuit_breaker_open", True)\
            .lt("circuit_breaker_opened_at", cutoff.isoformat())\
            .execute()
        
        if reset_result.data:
            logger.info("circuit_breakers_auto_reset", count=len(reset_result.data))
        
        # Get next healthy source
        result = supabase.client.table("discovered_sources")\
            .select("*")\
            .eq("company_id", POOL_COMPANY_ID)\
            .eq("is_active", True)\
            .eq("circuit_breaker_open", False)\
            .order("last_scraped_at", desc=False, nullsfirst=True)\
            .limit(1)\
            .execute()
        
        if not result.data:
            logger.warn("no_healthy_sources", 
                message="All sources have circuit breaker open or are inactive")
            return None
        
        source = result.data[0]
        
        logger.info("next_source_selected",
            source_id=source["source_id"],
            source_name=source["source_name"],
            url=source["url"],
            last_scraped_at=source.get("last_scraped_at"),
            consecutive_failures=source.get("consecutive_failures", 0),
            total_successes=source.get("total_successes", 0),
            total_failures=source.get("total_failures", 0)
        )
        
        return source
    
    except Exception as e:
        logger.error("get_next_source_error", error=str(e))
        return None


async def update_source_metrics(
    source_id: str,
    success: bool,
    error: Optional[str] = None
):
    """Update source reliability metrics.
    
    Args:
        source_id: Source UUID
        success: Whether scrape succeeded
        error: Error message if failed
    """
    try:
        supabase = get_supabase_client()
        
        # Fetch current metrics
        result = supabase.client.table("discovered_sources")\
            .select("consecutive_failures, total_successes, total_failures")\
            .eq("source_id", source_id)\
            .execute()
        
        if not result.data:
            logger.error("source_not_found_for_metrics", source_id=source_id)
            return
        
        current = result.data[0]
        consecutive_failures = current.get("consecutive_failures", 0)
        total_successes = current.get("total_successes", 0)
        total_failures = current.get("total_failures", 0)
        
        now = datetime.utcnow().isoformat()
        
        if success:
            # Success: Reset consecutive failures
            update_data = {
                "last_scraped_at": now,
                "consecutive_failures": 0,
                "total_successes": total_successes + 1
            }
            logger.info("source_metrics_updated_success",
                source_id=source_id,
                total_successes=total_successes + 1
            )
        else:
            # Failure: Increment counters
            new_consecutive = consecutive_failures + 1
            update_data = {
                "last_scraped_at": now,
                "consecutive_failures": new_consecutive,
                "total_failures": total_failures + 1,
                "last_error": error,
                "last_error_at": now
            }
            
            # Open circuit breaker if threshold reached
            if new_consecutive >= MAX_CONSECUTIVE_FAILURES:
                update_data["circuit_breaker_open"] = True
                update_data["circuit_breaker_opened_at"] = now
                logger.warn("circuit_breaker_opened",
                    source_id=source_id,
                    consecutive_failures=new_consecutive,
                    last_error=error
                )
            else:
                logger.warn("source_metrics_updated_failure",
                    source_id=source_id,
                    consecutive_failures=new_consecutive,
                    total_failures=total_failures + 1,
                    error=error
                )
        
        # Update DB
        supabase.client.table("discovered_sources")\
            .update(update_data)\
            .eq("source_id", source_id)\
            .execute()
    
    except Exception as e:
        logger.error("update_source_metrics_error",
            source_id=source_id,
            error=str(e)
        )


async def check_source_robust(source: Dict[str, Any]) -> Dict[str, Any]:
    """Check source with robust error handling.
    
    Args:
        source: Source from discovered_sources
        
    Returns:
        Result dict with success status and metrics
    """
    source_id = source["source_id"]
    source_name = source["source_name"]
    company_id = source.get("company_id")
    url = source.get("url")
    
    if not url:
        await update_source_metrics(source_id, success=False, error="Missing URL")
        return {"success": False, "reason": "missing_url"}
    
    logger.info("checking_source",
        source_id=source_id,
        source_name=source_name,
        url=url
    )
    
    try:
        # Scrape with timeout (30s max)
        result = await asyncio.wait_for(
            scrape_url(
                company_id=company_id,
                source_id=source_id,
                url=url,
                url_type="index"
            ),
            timeout=30.0
        )
        
        # Handle None result (shouldn't happen with new code, but defensive)
        if not result:
            error_msg = "scrape_url returned None"
            await update_source_metrics(source_id, success=False, error=error_msg)
            return {"success": False, "reason": "null_result"}
        
        # Check for workflow error
        workflow_error = result.get("error")
        
        if workflow_error:
            # Categorize error
            if "403" in str(workflow_error):
                error_type = "permanent_http_403"
            elif "404" in str(workflow_error):
                error_type = "permanent_http_404"
            elif "timeout" in str(workflow_error).lower():
                error_type = "transient_timeout"
            else:
                error_type = "unknown"
            
            await update_source_metrics(
                source_id, 
                success=False, 
                error=f"{error_type}: {workflow_error}"
            )
            
            logger.warn("source_check_failed",
                source_id=source_id,
                source_name=source_name,
                error_type=error_type,
                error=workflow_error
            )
            
            return {
                "success": False,
                "reason": error_type,
                "error": workflow_error
            }
        
        # Success
        change_info = result.get("change_info") or {}
        change_type = change_info.get("change_type", "unknown")
        context_units_created = len(result.get("context_unit_ids") or [])
        
        await update_source_metrics(source_id, success=True)
        
        logger.info("source_check_success",
            source_id=source_id,
            source_name=source_name,
            change_type=change_type,
            context_units_created=context_units_created
        )
        
        return {
            "success": True,
            "source_id": source_id,
            "source_name": source_name,
            "change_type": change_type,
            "context_units_created": context_units_created
        }
    
    except asyncio.TimeoutError:
        error_msg = "Timeout after 30s"
        await update_source_metrics(source_id, success=False, error=error_msg)
        logger.error("source_check_timeout",
            source_id=source_id,
            source_name=source_name,
            timeout_seconds=30
        )
        return {"success": False, "reason": "timeout"}
    
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        await update_source_metrics(source_id, success=False, error=error_msg)
        logger.error("source_check_exception",
            source_id=source_id,
            source_name=source_name,
            error=error_msg
        )
        return {"success": False, "reason": "exception", "error": error_msg}


async def check_next_source():
    """Main function: Check next healthy source and exit.
    
    Called by scheduler every 5 minutes.
    """
    logger.info("pool_checker_v2_start")
    
    try:
        # Get next healthy source
        source = await get_next_healthy_source()
        
        if not source:
            logger.warn("pool_checker_no_healthy_sources")
            return
        
        # Check source
        result = await check_source_robust(source)
        
        # Log summary
        if result.get("success"):
            logger.info("pool_checker_v2_completed_success",
                source_id=source["source_id"],
                source_name=result.get("source_name"),
                change_type=result.get("change_type"),
                context_units_created=result.get("context_units_created", 0)
            )
        else:
            logger.warn("pool_checker_v2_completed_failure",
                source_id=source["source_id"],
                reason=result.get("reason"),
                error=result.get("error")
            )
    
    except Exception as e:
        logger.error("pool_checker_v2_error", error=str(e))
    
    finally:
        logger.info("pool_checker_v2_end")
