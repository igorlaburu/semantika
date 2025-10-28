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


async def email_listener_job():
    """
    IMAP email listener job for multi-org context units.

    Fetches emails from IMAP, matches to organizations, and processes via UniversalPipeline.
    """
    if not settings.imap_listener_enabled:
        return

    logger.info("email_listener_job_start")

    try:
        email_source = EmailSource()
        pipeline = UniversalPipeline()

        # Fetch new emails
        source_contents = await email_source.fetch()
        logger.info("emails_fetched", count=len(source_contents))

        # Process each email
        for source_content in source_contents:
            try:
                # Process through universal pipeline
                result = await pipeline.process_source_content(source_content)

                logger.info(
                    "email_processed",
                    org=source_content.organization_slug,
                    cu_id=result["context_unit_id"]
                )

                # Acknowledge email (mark as read)
                await email_source.acknowledge(source_content.source_id)

            except Exception as e:
                logger.error(
                    "email_processing_error",
                    org=source_content.organization_slug,
                    source_id=source_content.source_id,
                    error=str(e)
                )

    except Exception as e:
        logger.error("email_listener_job_error", error=str(e))


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


async def execute_task(task: Dict[str, Any]):
    """Execute a scheduled task based on source type."""
    task_id = task["task_id"]
    client_id = task["client_id"]
    source_type = task["source_type"]
    target = task["target"]

    logger.info(
        "executing_task",
        task_id=task_id,
        client_id=client_id,
        source_type=source_type,
        target=target
    )

    supabase = get_supabase_client()
    execution_time = datetime.utcnow().isoformat() + "Z"

    try:
        if source_type == "web_llm":
            # Web scraping with LLM extraction
            # Get config values, use defaults if not specified
            config = task.get("config", {})
            extract_multiple = config.get("extract_multiple", True)
            skip_guardrails = config.get("skip_guardrails", False)

            scraper = WebScraper()
            result = await scraper.scrape_and_ingest(
                url=target,
                client_id=client_id,
                extract_multiple=extract_multiple,
                skip_guardrails=skip_guardrails
            )
            logger.info("task_completed", task_id=task_id, result=result)

        elif source_type == "twitter":
            logger.warn("task_not_implemented", task_id=task_id, source_type=source_type)

        elif source_type in ["api_efe", "api_reuters", "api_wordpress"]:
            logger.warn("task_not_implemented", task_id=task_id, source_type=source_type)

        elif source_type == "manual":
            logger.debug("task_manual_skip", task_id=task_id)

        else:
            logger.error("unknown_source_type", task_id=task_id, source_type=source_type)

        # Update last_run timestamp in Supabase
        await supabase.update_task_last_run(task_id, execution_time)

    except Exception as e:
        logger.error("task_execution_error", task_id=task_id, error=str(e))
        # Still update last_run even on error to track execution attempts
        await supabase.update_task_last_run(task_id, execution_time)


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


async def schedule_tasks(scheduler: AsyncIOScheduler):
    """Load tasks from Supabase and schedule them."""
    logger.info("loading_tasks")

    try:
        # Schedule IMAP email listener
        if settings.imap_listener_enabled:
            scheduler.add_job(
                email_listener_job,
                trigger=IntervalTrigger(seconds=settings.imap_listener_interval),
                id='imap_email_listener',
                name='IMAP Email Listener',
                replace_existing=True
            )
            logger.info("imap_listener_scheduled", interval=settings.imap_listener_interval)

        supabase = get_supabase_client()
        tasks = await supabase.get_all_active_tasks()

        logger.info("tasks_loaded", count=len(tasks))

        for task in tasks:
            task_id = task["task_id"]
            frequency_min = task["frequency_min"]

            # Schedule task with interval trigger
            scheduler.add_job(
                execute_task,
                trigger=IntervalTrigger(minutes=frequency_min),
                args=[task],
                id=f"task_{task_id}",
                replace_existing=True,
                max_instances=1
            )

            logger.info(
                "task_scheduled",
                task_id=task_id,
                frequency_min=frequency_min,
                source_type=task["source_type"]
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
        logger.error("schedule_tasks_error", error=str(e))


async def main():
    """Main scheduler entry point."""
    logger.info("scheduler_starting")

    try:
        # Initialize APScheduler
        scheduler = AsyncIOScheduler()
        scheduler.start()
        logger.info("apscheduler_started")

        # Load and schedule tasks from Supabase
        await schedule_tasks(scheduler)

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
