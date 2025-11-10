"""APScheduler daemon for periodic task execution.

Runs:
- File monitor (watches directory for new files)
- Email monitor (watches inbox for new emails)
- Task scheduler (executes scheduled scraping tasks)
- TTL cleanup (daily cleanup of old data)
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import urlparse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client
from utils.qdrant_client import get_qdrant_client
from sources.file_monitor import FileMonitor
from sources.email_monitor import EmailMonitor
from sources.email_source import EmailSource
from sources.web_scraper import WebScraper
from core.universal_pipeline import UniversalPipeline

logger = get_logger("scheduler")


async def run_file_monitor():
    """Run file monitor in background."""
    try:
        if not settings.file_monitor_enabled:
            logger.info("file_monitor_disabled")
            return

        logger.info("starting_file_monitor")

        monitor = FileMonitor(
            watch_dir=settings.file_monitor_watch_dir,
            processed_dir=settings.file_monitor_processed_dir,
            check_interval=settings.file_monitor_interval
        )

        await monitor.start()

    except Exception as e:
        logger.error("file_monitor_error", error=str(e))


# REMOVED: Legacy email_listener_job() - replaced by MultiCompanyEmailMonitor


async def run_email_monitor():
    """Run email monitor in background (LEGACY)."""
    try:
        if not settings.email_monitor_enabled:
            logger.info("email_monitor_disabled")
            return

        logger.info("starting_email_monitor")

        monitor = EmailMonitor(
            imap_server=settings.email_imap_server,
            imap_port=settings.email_imap_port,
            email_address=settings.email_address,
            password=settings.email_password,
            check_interval=settings.email_monitor_interval
        )

        await monitor.start()

    except Exception as e:
        logger.error("email_monitor_error", error=str(e))


async def run_multi_company_email_monitor():
    """Run multi-company email monitor with p.{company}@ekimen.ai routing."""
    try:
        if not settings.imap_listener_enabled:
            logger.info("multi_company_email_monitor_disabled")
            return

        logger.info("starting_multi_company_email_monitor")

        from sources.multi_company_email_monitor import MultiCompanyEmailMonitor

        monitor = MultiCompanyEmailMonitor(
            imap_server=settings.imap_host,
            imap_port=settings.imap_port,
            email_address=settings.imap_user,
            password=settings.imap_password,
            check_interval=settings.imap_listener_interval
        )

        await monitor.start()

    except Exception as e:
        logger.error("multi_company_email_monitor_error", error=str(e))


async def execute_source_task(source: Dict[str, Any]):
    """Execute a scheduled source task based on source type."""
    source_id = source["source_id"]
    client_id = source["client_id"]
    company_id = source.get("company_id")
    source_type = source["source_type"]
    source_name = source["source_name"]
    config = source.get("config", {})

    logger.info(
        "executing_source_task",
        source_id=source_id,
        client_id=client_id,
        source_type=source_type,
        source_name=source_name
    )

    supabase = get_supabase_client()
    start_time = datetime.utcnow()

    try:
        if source_type == "scraping":
            # Web scraping using intelligent workflow
            target_url = config.get("url")
            if not target_url:
                logger.error("scraping_source_missing_url", source_id=source_id)
                return

            # Determine URL type from config (default: article)
            url_type = config.get("url_type", "article")
            
            # Use new LangGraph scraper workflow
            from sources.scraper_workflow import scrape_url
            
            workflow_result = await scrape_url(
                company_id=company_id,
                source_id=source_id,
                url=target_url,
                url_type=url_type
            )
            
            # Extract results
            context_units_created = len(workflow_result.get("context_unit_ids", []))
            url_content_units = len(workflow_result.get("url_content_unit_ids", []))
            change_type = workflow_result.get("change_info", {}).get("change_type", "unknown")
            workflow_error = workflow_result.get("error")
            
            logger.info("scraping_workflow_completed", 
                source_id=source_id, 
                context_units=context_units_created,
                change_type=change_type,
                error=workflow_error
            )
            
            # Log execution
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            await supabase.log_execution(
                client_id=client_id,
                company_id=company_id,
                source_name=source_name,
                source_type="scraping",
                items_count=context_units_created,
                status_code=200 if not workflow_error else 500,
                status="success" if not workflow_error else "error",
                details=f"{context_units_created} context units creadas (cambio: {change_type})" if not workflow_error else f"Error: {workflow_error}",
                metadata={
                    "url": target_url,
                    "url_type": url_type,
                    "context_units_created": context_units_created,
                    "url_content_units": url_content_units,
                    "change_type": change_type,
                    "monitored_url_id": workflow_result.get("monitored_url_id")
                },
                duration_ms=duration_ms,
                workflow_code=source.get("workflow_code")
            )
            
            # Update source execution stats
            await supabase.update_source_execution_stats(
                source_id, 
                success=not workflow_error,
                items_processed=context_units_created
            )

        elif source_type == "webhook":
            logger.debug("webhook_source_skip", source_id=source_id, message="Webhooks are triggered externally")

        elif source_type == "api":
            # Check if it's a Perplexity news source
            if config.get("connector_type") == "perplexity_news":
                from sources.perplexity_news_connector import execute_perplexity_news_task
                
                result = await execute_perplexity_news_task(source)
                
                logger.info("perplexity_api_task_completed", 
                    source_id=source_id, 
                    result=result
                )
                
                # Log execution
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                await supabase.log_execution(
                    client_id=client_id,
                    company_id=company_id,
                    source_name=source_name,
                    source_type="api",
                    items_count=result.get("items_processed", 0),
                    status_code=200 if result.get("success") else 500,
                    status="success" if result.get("success") else "error",
                    details=f"Perplexity API: {result.get('items_processed', 0)} noticias procesadas" if result.get("success") else f"Error: {result.get('error')}",
                    metadata={
                        "connector_type": "perplexity_news",
                        "items_fetched": result.get("items_fetched", 0),
                        "items_processed": result.get("items_processed", 0),
                        "location": config.get("location", "Bilbao/Vizcaya")
                    },
                    duration_ms=duration_ms,
                    workflow_code=source.get("workflow_code")
                )
                
                # Update source execution stats
                await supabase.update_source_execution_stats(
                    source_id, 
                    success=result.get("success", False),
                    items_processed=result.get("items_processed", 0)
                )
            else:
                logger.warn("api_source_not_implemented", source_id=source_id, source_type=source_type)

        elif source_type == "manual":
            logger.debug("manual_source_skip", source_id=source_id)

        else:
            logger.error("unknown_source_type", source_id=source_id, source_type=source_type)

    except Exception as e:
        logger.error("source_task_execution_error", source_id=source_id, error=str(e))
        
        # Log failed execution
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        await supabase.log_execution(
            client_id=client_id,
            company_id=company_id,
            source_name=source_name,
            source_type=source_type,
            items_count=0,
            status_code=500,
            status="error",
            details=f"Error ejecutando fuente: {str(e)}",
            error_message=str(e),
            metadata={
                "source_id": source_id,
                "source_type": source_type,
                "error_type": type(e).__name__
            },
            duration_ms=duration_ms,
            workflow_code=source.get("workflow_code")
        )
        
        # Update source execution stats
        await supabase.update_source_execution_stats(source_id, success=False)


async def cleanup_old_data():
    """Clean up old data based on TTL settings."""
    logger.info("starting_ttl_cleanup", ttl_days=settings.data_ttl_days)

    try:
        qdrant = get_qdrant_client()
        cutoff_date = datetime.utcnow() - timedelta(days=settings.data_ttl_days)
        cutoff_timestamp = int(cutoff_date.timestamp())

        # Delete old points that are not marked as special
        # Points with metadata.special=true are never deleted
        deleted_count = qdrant.delete_old_points(
            cutoff_timestamp=cutoff_timestamp,
            exclude_special=True
        )

        logger.info("ttl_cleanup_completed", deleted_count=deleted_count)

    except Exception as e:
        logger.error("ttl_cleanup_error", error=str(e))


async def schedule_sources(scheduler: AsyncIOScheduler):
    """Load sources from Supabase and schedule them."""
    logger.info("loading_sources", timestamp=datetime.utcnow().isoformat())

    try:
        supabase = get_supabase_client()
        sources = await supabase.get_scheduled_sources()

        logger.info("sources_loaded", count=len(sources))
        
        # Get current source IDs from database
        current_source_ids = {source["source_id"] for source in sources}
        
        # Remove jobs for sources that no longer exist in database
        for job in scheduler.get_jobs():
            if job.id.startswith("source_"):
                job_source_id = job.id.replace("source_", "")
                if job_source_id not in current_source_ids:
                    scheduler.remove_job(job.id)
                    logger.info("source_job_removed", job_id=job.id, reason="source_deleted_from_db")

        for source in sources:
            source_id = source["source_id"]
            schedule_config = source.get("schedule_config", {})
            source_type = source["source_type"]
            
            # Check for cron schedule (specific times like 9:00 AM daily)
            cron_schedule = schedule_config.get("cron")
            frequency_min = schedule_config.get("frequency_minutes", 60)
            
            if cron_schedule:
                # Parse cron format: "HH:MM" (new) or "hour minute" (legacy)
                hour = None
                minute = None
                
                if ":" in cron_schedule:
                    # New format: "08:00" (HH:MM)
                    try:
                        time_parts = cron_schedule.split(":")
                        hour = int(time_parts[0])
                        minute = int(time_parts[1])
                        logger.debug("cron_parsed_new_format", cron=cron_schedule, hour=hour, minute=minute)
                    except (ValueError, IndexError) as e:
                        logger.error("cron_parse_error_new_format", cron=cron_schedule, error=str(e))
                        continue
                        
                elif " " in cron_schedule:
                    # Legacy format: "8 0" (hour minute) - backwards compatibility
                    parts = cron_schedule.split()
                    if len(parts) == 2:
                        try:
                            hour = int(parts[0])
                            minute = int(parts[1])
                            logger.warn("cron_legacy_format_detected", 
                                cron=cron_schedule, 
                                source_id=source_id,
                                suggestion=f"Update to new format: {hour:02d}:{minute:02d}")
                        except ValueError as e:
                            logger.error("cron_parse_error_legacy_format", cron=cron_schedule, error=str(e))
                            continue
                
                if hour is not None and minute is not None:
                    scheduler.add_job(
                        execute_source_task,
                        trigger=CronTrigger(hour=hour, minute=minute),
                        args=[source],
                        id=f"source_{source_id}",
                        replace_existing=True,
                        max_instances=1
                    )
                    
                    logger.info(
                        "source_scheduled_cron",
                        source_id=source_id,
                        source_name=source["source_name"],
                        cron_time=f"{hour:02d}:{minute:02d}",
                        source_type=source_type
                    )
                    continue
            
            # Fallback to interval scheduling for scraping and API sources
            if source_type in ["scraping", "api"] and frequency_min > 0:
                # Schedule source with interval trigger
                scheduler.add_job(
                    execute_source_task,
                    trigger=IntervalTrigger(minutes=frequency_min),
                    args=[source],
                    id=f"source_{source_id}",
                    replace_existing=True,
                    max_instances=1
                )

                logger.info(
                    "source_scheduled_interval",
                    source_id=source_id,
                    source_name=source["source_name"],
                    frequency_min=frequency_min,
                    source_type=source_type
                )

        # Schedule daily TTL cleanup at 3 AM
        scheduler.add_job(
            cleanup_old_data,
            trigger=CronTrigger(hour=3, minute=0),
            id="ttl_cleanup",
            replace_existing=True
        )

        logger.info("ttl_cleanup_scheduled", time="03:00 UTC daily")

    except Exception as e:
        logger.error("schedule_sources_error", error=str(e))


async def reload_sources_periodically(scheduler: AsyncIOScheduler):
    """Reload sources from database every 5 minutes to pick up changes."""
    logger.info("scheduling_sources_reload", interval_minutes=5)
    
    scheduler.add_job(
        schedule_sources,
        trigger=IntervalTrigger(minutes=5),
        args=[scheduler],
        id="sources_reload",
        replace_existing=True,
        max_instances=1
    )
    
    logger.info("sources_reload_scheduled", interval_minutes=5)


async def main():
    """Main scheduler entry point."""
    logger.info("scheduler_starting")

    try:
        # Initialize APScheduler
        scheduler = AsyncIOScheduler()
        scheduler.start()
        logger.info("apscheduler_started")

        # Load and schedule sources from Supabase
        logger.info("calling_schedule_sources")
        await schedule_sources(scheduler)
        logger.info("schedule_sources_completed")
        
        # Schedule periodic reload of sources (every 5 minutes)
        await reload_sources_periodically(scheduler)

        # Create tasks for monitors
        monitor_tasks = []

        if settings.file_monitor_enabled:
            monitor_tasks.append(asyncio.create_task(run_file_monitor()))

        if settings.imap_listener_enabled:
            # Use new multi-company email monitor instead of legacy version
            monitor_tasks.append(asyncio.create_task(run_multi_company_email_monitor()))

        # Keep the scheduler running
        if monitor_tasks:
            # Run monitors concurrently with scheduler
            await asyncio.gather(*monitor_tasks)
        else:
            # Just keep scheduler alive
            logger.info("scheduler_running", message="No monitors enabled, scheduler active")
            while True:
                await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("scheduler_stopping", reason="keyboard_interrupt")
        scheduler.shutdown()
    except Exception as e:
        logger.error("scheduler_error", error=str(e))
        scheduler.shutdown()
        raise


if __name__ == "__main__":
    asyncio.run(main())
