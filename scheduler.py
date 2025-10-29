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
            # Web scraping
            target_url = config.get("url")
            if not target_url:
                logger.error("scraping_source_missing_url", source_id=source_id)
                return

            extract_multiple = config.get("extract_multiple", True)
            skip_guardrails = config.get("skip_guardrails", False)

            scraper = WebScraper()
            result = await scraper.scrape_and_ingest(
                url=target_url,
                client_id=client_id,
                extract_multiple=extract_multiple,
                skip_guardrails=skip_guardrails
            )
            logger.info("source_task_completed", source_id=source_id, result=result)
            
            # Log execution
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            await supabase.log_execution(
                client_id=client_id,
                company_id=company_id,
                source_name=source_name,
                source_type="scraping",
                items_count=result.get("documents_scraped", 0),
                status_code=200 if result.get("documents_scraped", 0) > 0 else 404,
                status="success" if result.get("documents_scraped", 0) > 0 else "error",
                details=f"{result.get('documents_scraped', 0)} noticias procesadas correctamente" if result.get("documents_scraped", 0) > 0 else "Página no encontrada - sitio web caído",
                metadata={
                    "url": target_url,
                    "documents_scraped": result.get("documents_scraped", 0),
                    "documents_ingested": result.get("documents_ingested", 0),
                    "extract_multiple": extract_multiple
                },
                duration_ms=duration_ms,
                workflow_code=source.get("workflow_code")
            )
            
            # Update source execution stats
            await supabase.update_source_execution_stats(
                source_id, 
                success=result.get("documents_scraped", 0) > 0,
                items_processed=result.get("documents_scraped", 0)
            )

        elif source_type == "webhook":
            logger.debug("webhook_source_skip", source_id=source_id, message="Webhooks are triggered externally")

        elif source_type == "api":
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
    logger.info("loading_sources")

    try:
        supabase = get_supabase_client()
        sources = await supabase.get_scheduled_sources()

        logger.info("sources_loaded", count=len(sources))

        for source in sources:
            source_id = source["source_id"]
            schedule_config = source.get("schedule_config", {})
            
            # Get frequency from schedule config (default 60 minutes if not specified)
            frequency_min = schedule_config.get("frequency_minutes", 60)
            
            # Only schedule scraping sources that have valid schedule config
            if source["source_type"] == "scraping" and frequency_min > 0:
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
                    "source_scheduled",
                    source_id=source_id,
                    source_name=source["source_name"],
                    frequency_min=frequency_min,
                    source_type=source["source_type"]
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


async def main():
    """Main scheduler entry point."""
    logger.info("scheduler_starting")

    try:
        # Initialize APScheduler
        scheduler = AsyncIOScheduler()
        scheduler.start()
        logger.info("apscheduler_started")

        # Load and schedule sources from Supabase
        await schedule_sources(scheduler)

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
