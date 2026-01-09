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
from datetime import datetime, timedelta, timezone
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
        
        # 1. Get 2 sources normal rotation (oldest scraped first)
        normal_result = supabase.client.table("discovered_sources")\
            .select("*")\
            .eq("company_id", POOL_COMPANY_ID)\
            .eq("is_active", True)\
            .eq("circuit_breaker_open", False)\
            .order("last_scraped_at", desc=False, nullsfirst=True)\
            .limit(2)\
            .execute()
        
        sources = list(normal_result.data) if normal_result.data else []
        
        # 2. Get high-frequency sources (top sources reviewed every 5 cycles)
        # Check if any high-activity source needs frequent review
        high_freq_result = supabase.client.table("discovered_sources")\
            .select("*")\
            .eq("company_id", POOL_COMPANY_ID)\
            .eq("is_active", True)\
            .eq("circuit_breaker_open", False)\
            .gte("content_count_7d", 2)\
            .order("content_count_7d", desc=True)\
            .limit(10)\
            .execute()
        
        if high_freq_result.data:
            # Find sources that haven't been scraped in the last 5 cycles (50 minutes)
            cutoff_time = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(minutes=50)
            
            high_freq_candidates = [
                s for s in high_freq_result.data
                if not s.get("last_scraped_at") or 
                datetime.fromisoformat(s["last_scraped_at"].replace("Z", "+00:00")) < cutoff_time
            ]
            
            if high_freq_candidates:
                # Pick the most active one that needs review
                bonus_source = max(high_freq_candidates, key=lambda s: s.get("content_count_7d", 0))
                
                # Avoid duplicates - check if bonus source already in normal sources
                source_ids = {s["source_id"] for s in sources}
                if bonus_source["source_id"] not in source_ids:
                    sources.append(bonus_source)
        
        if not sources:
            logger.warn("no_healthy_sources", 
                message="All sources have circuit breaker open or are inactive")
            return []
        
        logger.info("smart_sources_selected",
            normal_count=len(normal_result.data) if normal_result.data else 0,
            high_freq_added=len(sources) > 2,
            total_sources=len(sources),
            sources=[{
                "source_id": s["source_id"],
                "source_name": s["source_name"],
                "activity_7d": s.get("content_count_7d", 0),
                "last_scraped_at": s.get("last_scraped_at"),
                "type": "high_frequency" if i >= 2 else "normal"
            } for i, s in enumerate(sources)]
        )
        
        return sources
    
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
        # Scrape with timeout (120s max for index pages with 10+ articles)
        # Breakdown: extract_links (13s) + 10 articles × 7s (70s) + save/geocode (20s) = ~103s
        result = await asyncio.wait_for(
            scrape_url(
                company_id=company_id,
                source_id=source_id,
                url=url,
                url_type="index"
            ),
            timeout=120.0
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
        error_msg = "Timeout after 120s"
        await update_source_metrics(source_id, success=False, error=error_msg)
        logger.error("source_check_timeout",
            source_id=source_id,
            source_name=source_name,
            timeout_seconds=120
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


async def check_next_sources():
    """Main function: Check next 2-3 sources in parallel (2 normal + 1 high-frequency).
    
    Strategy:
    - 2 sources: Normal rotation (oldest scraped first)
    - 1 source: High-frequency from top 10 sources with 2+ content_count_7d (every 5 cycles = 50min)
    
    Called by scheduler every 10 minutes.
    """
    logger.info("pool_checker_v2_start")
    
    try:
        # Get next 2 healthy sources
        sources = await get_next_healthy_source()
        
        if not sources:
            logger.warn("pool_checker_no_healthy_sources")
            return
        
        # Check sources in parallel
        tasks = [check_source_robust(source) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Log summary
        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("pool_checker_task_exception",
                    source_id=sources[i]["source_id"],
                    error=str(result)
                )
                continue
            
            if result.get("success"):
                success_count += 1
                logger.info("pool_checker_v2_completed_success",
                    source_id=sources[i]["source_id"],
                    source_name=result.get("source_name"),
                    change_type=result.get("change_type"),
                    context_units_created=result.get("context_units_created", 0)
                )
            else:
                logger.warn("pool_checker_v2_completed_failure",
                    source_id=sources[i]["source_id"],
                    reason=result.get("reason"),
                    error=result.get("error")
                )
        
        logger.info("pool_checker_v2_batch_completed",
            sources_checked=len(sources),
            successful=success_count,
            failed=len(sources) - success_count
        )
    
    except Exception as e:
        logger.error("pool_checker_v2_error", error=str(e))
    
    finally:
        logger.info("pool_checker_v2_end")
