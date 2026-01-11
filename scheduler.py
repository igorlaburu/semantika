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
from utils.llm_client import LLMClient
from utils.image_generator import generate_image_from_prompt
from utils.image_extractor import extract_featured_image
import uuid
import aiohttp
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
            connector_type = config.get("connector_type")
            
            # Check if it's a Perplexity news source
            if connector_type == "perplexity_news":
                from sources.perplexity_news_connector import execute_perplexity_news_task
                
                result = await execute_perplexity_news_task(source)
                
                logger.info("perplexity_api_task_completed", 
                    source_id=source_id, 
                    result=result
                )
            
            else:
                logger.warn("unknown_api_connector_type", 
                    source_id=source_id,
                    connector_type=connector_type
                )

        elif source_type == "manual":
            logger.debug("manual_source_skip", source_id=source_id)

        elif source_type == "system":
            system_job = config.get("system_job")
            
            if not system_job:
                logger.error("system_source_missing_job", source_id=source_id)
                return
            
            logger.info("system_job_starting", 
                source_id=source_id,
                system_job=system_job
            )
            
            # Execute system jobs async (fire-and-forget to avoid blocking scheduler)
            if system_job == "pool_discovery":
                asyncio.create_task(pool_discovery_job())
            elif system_job == "pool_ingestion":
                asyncio.create_task(pool_ingestion_job())
            elif system_job == "pool_checker":
                asyncio.create_task(pool_checker_job())
            elif system_job == "ttl_cleanup":
                asyncio.create_task(cleanup_old_data())
            else:
                logger.error("unknown_system_job",
                    source_id=source_id,
                    system_job=system_job
                )

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


async def pool_discovery_job():
    """Pool discovery job (daily at 8:00 AM UTC)."""
    logger.info("starting_pool_discovery_job")
    
    try:
        from workflows.discovery_flow import execute_discovery_job
        
        result = await execute_discovery_job()
        
        if result.get("success"):
            logger.info("pool_discovery_job_completed",
                articles_found=result.get("articles_found"),
                sources_discovered=result.get("sources_discovered")
            )
        else:
            logger.error("pool_discovery_job_failed", error=result.get("error"))
    
    except Exception as e:
        logger.error("pool_discovery_job_error", error=str(e))


async def pool_ingestion_job():
    """Pool ingestion job (hourly)."""
    logger.info("starting_pool_ingestion_job")
    
    try:
        from workflows.ingestion_flow import execute_ingestion_job
        
        result = await execute_ingestion_job()
        
        if result.get("success"):
            logger.info("pool_ingestion_job_completed",
                sources_processed=result.get("sources_processed"),
                items_ingested=result.get("items_ingested")
            )
        else:
            logger.error("pool_ingestion_job_failed", error=result.get("error"))
    
    except Exception as e:
        logger.error("pool_ingestion_job_error", error=str(e))


async def pool_checker_job():
    """Pool checker job - checks one source in rotation (v2 with circuit breaker)."""
    logger.info("starting_pool_checker_job")
    
    try:
        from sources.pool_checker_v2 import check_next_sources
        
        await check_next_sources()
        
        logger.info("pool_checker_job_completed")
    
    except Exception as e:
        logger.error("pool_checker_job_error", error=str(e))


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
            schedule_config_raw = source.get("schedule_config", {})
            source_type = source["source_type"]
            
            if isinstance(schedule_config_raw, str):
                try:
                    import json
                    schedule_config = json.loads(schedule_config_raw)
                except json.JSONDecodeError as e:
                    logger.error("schedule_config_parse_error", source_id=source_id, error=str(e))
                    continue
            else:
                schedule_config = schedule_config_raw
            
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
                    job_id = f"source_{source_id}"
                    existing_job = scheduler.get_job(job_id)

                    # Check if job needs to be added/updated
                    needs_update = False
                    if existing_job is None:
                        needs_update = True
                        logger.debug("cron_job_new", source_id=source_id)
                    else:
                        # Check if cron trigger changed
                        if isinstance(existing_job.trigger, CronTrigger):
                            # Compare hour and minute fields
                            # APScheduler CronTrigger fields are BaseField objects, not lists
                            # Access first expression value directly
                            existing_hour = existing_job.trigger.fields[5].expressions[0].first if existing_job.trigger.fields[5].expressions else None
                            existing_minute = existing_job.trigger.fields[6].expressions[0].first if existing_job.trigger.fields[6].expressions else None
                            if existing_hour != hour or existing_minute != minute:
                                needs_update = True
                                logger.debug("cron_job_changed",
                                    source_id=source_id,
                                    old_time=f"{existing_hour}:{existing_minute}" if existing_hour is not None else "unknown",
                                    new_time=f"{hour:02d}:{minute:02d}"
                                )
                        else:
                            needs_update = True
                            logger.debug("cron_job_trigger_type_changed", source_id=source_id)

                    if needs_update:
                        scheduler.add_job(
                            execute_source_task,
                            trigger=CronTrigger(hour=hour, minute=minute),
                            args=[source],
                            id=job_id,
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
                    else:
                        logger.debug("cron_job_unchanged_skipping",
                            source_id=source_id,
                            source_name=source["source_name"],
                            cron_time=f"{hour:02d}:{minute:02d}"
                        )
                    continue
            
            # Fallback to interval scheduling for scraping, API, and system sources
            if source_type in ["scraping", "api", "system"] and frequency_min > 0:
                job_id = f"source_{source_id}"
                existing_job = scheduler.get_job(job_id)

                # Check if job needs to be added/updated
                needs_update = False
                if existing_job is None:
                    needs_update = True
                    logger.debug("interval_job_new", source_id=source_id)
                else:
                    # Check if trigger changed
                    if isinstance(existing_job.trigger, IntervalTrigger):
                        existing_interval = existing_job.trigger.interval.total_seconds() / 60
                        if abs(existing_interval - frequency_min) > 0.1:
                            needs_update = True
                            logger.debug("interval_job_changed",
                                source_id=source_id,
                                old_interval=existing_interval,
                                new_interval=frequency_min
                            )
                    else:
                        needs_update = True
                        logger.debug("interval_job_trigger_type_changed", source_id=source_id)

                if needs_update:
                    # Schedule source with interval trigger
                    scheduler.add_job(
                        execute_source_task,
                        trigger=IntervalTrigger(minutes=frequency_min),
                        args=[source],
                        id=job_id,
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
                else:
                    logger.debug("interval_job_unchanged_skipping",
                        source_id=source_id,
                        source_name=source["source_name"],
                        frequency_min=frequency_min
                    )

        # System jobs (pool_discovery, pool_ingestion, ttl_cleanup) are now managed
        # via sources table with source_type='system' and company_id='99999999-9999-9999-9999-999999999999'
        # They are loaded and scheduled automatically by schedule_sources() every 5 minutes

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


async def force_garbage_collection():
    """Force Python garbage collection to prevent memory leaks."""
    import gc
    
    logger.info("garbage_collection_starting")
    collected = gc.collect()
    logger.info("garbage_collection_completed", objects_collected=collected)


async def schedule_garbage_collection(scheduler):
    """Schedule periodic garbage collection every 30 minutes."""
    logger.info("scheduling_garbage_collection", interval_minutes=30)
    
    scheduler.add_job(
        force_garbage_collection,
        trigger=IntervalTrigger(minutes=30),
        id="garbage_collection",
        replace_existing=True,
        max_instances=1
    )
    
    logger.info("garbage_collection_scheduled", interval_minutes=30)


async def daily_article_generation():
    """Generate daily articles for companies with autogenerate_enabled=true."""
    
    try:
        logger.info("daily_article_generation_start")
        
        supabase = get_supabase_client()
        
        # Get companies with autogeneration enabled
        result = supabase.client.table("companies")\
            .select("id, company_name, settings")\
            .eq("is_active", True)\
            .execute()
        
        companies = result.data if result.data else []
        
        logger.info("daily_generation_companies_found", 
            count=len(companies)
        )
        
        total_generated = 0
        
        for company in companies:
            try:
                # Check if company has autogeneration enabled in settings
                settings = company.get('settings', {})
                if not settings.get('autogenerate_enabled', False):
                    continue
                
                # Check if already generated today
                today = datetime.utcnow().date()
                existing = supabase.client.table("press_articles")\
                    .select("id, working_json")\
                    .eq("company_id", company['id'])\
                    .eq("estado", "borrador")\
                    .gte("created_at", f"{today}T00:00:00Z")\
                    .execute()
                
                # Count auto-generated articles today
                auto_generated_today = sum(
                    1 for a in existing.data 
                    if a.get('working_json', {}).get('auto_generated', False)
                )
                
                if auto_generated_today > 0:
                    logger.info("company_already_generated_today",
                        company_id=company['id'],
                        company_name=company['company_name'],
                        count=auto_generated_today
                    )
                    continue
                
                # Generate articles for this company
                generated = await generate_articles_for_company(
                    company_id=company['id'],
                    company_name=company['company_name'],
                    max_articles=settings.get('autogenerate_max', 5)
                )
                
                total_generated += generated
                
                # Small delay between companies
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error("company_generation_failed",
                    company_id=company['id'],
                    company_name=company['company_name'],
                    error=str(e)
                )
        
        logger.info("daily_generation_completed",
            companies_processed=len(companies),
            total_articles_generated=total_generated
        )
        
    except Exception as e:
        logger.error("daily_generation_job_failed", error=str(e))


async def generate_articles_for_company(
    company_id: str,
    company_name: str,
    max_articles: int
) -> int:
    """Generate articles for a specific company using /process/redact-news-rich endpoint.

    Uses the same endpoint and flow as the frontend with save_article=true.
    """

    logger.info("company_generation_start",
        company_id=company_id,
        company_name=company_name,
        max_articles=max_articles
    )

    supabase = get_supabase_client()
    llm_client = LLMClient()

    # Get unused context units
    unused_units = get_unused_context_units(
        company_id=company_id,
        limit=max_articles * 2  # Get extra to have choice
    )

    if not unused_units:
        logger.info("no_unused_context_units",
            company_id=company_id,
            company_name=company_name
        )
        return 0

    # Get company settings to check quality threshold
    company_result = supabase.client.table("companies").select("settings").eq("id", company_id).execute()
    company_settings = company_result.data[0].get('settings', {}) if company_result.data else {}
    min_quality = company_settings.get('autogenerate_min_quality', 3.0)

    if min_quality > 0:
        evaluated_units = await evaluate_units_quality(unused_units, llm_client)
        selected_units = [
            u for u in evaluated_units
            if u.get('quality_score', 0) >= min_quality
        ][:max_articles]
    else:
        selected_units = unused_units[:max_articles]

    if not selected_units:
        logger.info("no_quality_units",
            company_id=company_id,
            evaluated=len(unused_units),
            min_quality=min_quality
        )
        return 0

    # Get API key for this company
    client_result = supabase.client.table("clients")\
        .select("api_key")\
        .eq("company_id", company_id)\
        .eq("is_active", True)\
        .limit(1)\
        .execute()

    if not client_result.data:
        logger.error("no_api_key_found_for_company",
            company_id=company_id,
            company_name=company_name
        )
        return 0

    api_key = client_result.data[0]['api_key']

    # Generate articles using /process/redact-news-rich with save_article=true
    generation_batch_id = str(uuid.uuid4())
    generated_count = 0

    async with aiohttp.ClientSession() as session:
        for unit in selected_units:
            try:
                # Call /process/redact-news-rich with save_article=true
                url = "http://semantika-api:8000/process/redact-news-rich"

                headers = {
                    'X-API-Key': api_key,
                    'Content-Type': 'application/json'
                }

                payload = {
                    'context_unit_ids': [unit['id']],
                    'save_article': True
                }

                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as response:
                    if response.status == 200:
                        result = await response.json()
                        saved_article = result.get('saved_article', {})
                        article_id = saved_article.get('id')

                        if article_id:
                            # Update working_json with auto_generated metadata
                            working_json = saved_article.get('working_json', {})
                            working_json.update({
                                "auto_generated": True,
                                "generation_date": datetime.utcnow().isoformat(),
                                "generation_batch_id": generation_batch_id,
                                "quality_score": unit.get('quality_score'),
                                "llm_model": settings.llm_writer_model
                            })

                            # Update article with auto_generated flag
                            supabase.client.table("press_articles")\
                                .update({"working_json": working_json})\
                                .eq("id", article_id)\
                                .execute()

                            generated_count += 1

                            logger.info("article_auto_generated",
                                company_id=company_id,
                                article_id=article_id,
                                context_unit_id=unit['id'],
                                title=saved_article.get('titulo', '')[:50]
                            )
                        else:
                            logger.error("article_generation_no_id_returned",
                                company_id=company_id,
                                unit_id=unit['id'],
                                response=result
                            )

                    elif response.status == 429:
                        logger.warn("article_generation_rate_limited",
                            company_id=company_id,
                            unit_id=unit['id']
                        )
                        break  # Stop generating for this company if rate limited

                    else:
                        response_text = await response.text()
                        logger.error("article_generation_endpoint_failed",
                            company_id=company_id,
                            unit_id=unit['id'],
                            status_code=response.status,
                            response=response_text[:200]
                        )

                # Small delay between articles to avoid overwhelming the system
                await asyncio.sleep(2)

            except asyncio.TimeoutError:
                logger.error("article_generation_timeout",
                    company_id=company_id,
                    unit_id=unit['id']
                )
            except Exception as e:
                logger.error("article_generation_failed",
                    company_id=company_id,
                    unit_id=unit['id'],
                    error=str(e)
                )

    logger.info("company_generation_completed",
        company_id=company_id,
        company_name=company_name,
        requested=max_articles,
        generated=generated_count,
        batch_id=generation_batch_id
    )

    return generated_count


def get_unused_context_units(company_id: str, limit: int, max_age_days: int = 7) -> list:
    """Get high-quality, fresh context units not used in any article.

    Filters:
    1. Fresh: Only units from last N days (default 7) - news must be current
    2. Quality: At least 2 atomic_statements (passed quality gate)
    3. Unused: Not already used in any article for this company

    Args:
        company_id: Company UUID
        limit: Max units to return
        max_age_days: Max age in days (default 7 for fresh news)

    Returns:
        List of eligible context units, sorted by created_at desc
    """

    supabase = get_supabase_client()

    # 1. Get ALL context_unit_ids already used by this company's articles
    # Check BOTH: context_unit_ids column (new) AND working_json.source_context_units (legacy)
    articles = supabase.client.table("press_articles")\
        .select("context_unit_ids, working_json")\
        .eq("company_id", company_id)\
        .execute()

    used_unit_ids = set()
    for article in articles.data:
        # New format: context_unit_ids column (array)
        context_unit_ids = article.get('context_unit_ids') or []
        if context_unit_ids:
            used_unit_ids.update(context_unit_ids)

        # Legacy format: working_json.source_context_units
        working_json = article.get('working_json') or {}
        source_units = working_json.get('source_context_units') or []
        if source_units:
            used_unit_ids.update(source_units)

        # Also check working_json.context_unit_ids (another legacy location)
        wj_context_ids = working_json.get('context_unit_ids') or []
        if wj_context_ids:
            used_unit_ids.update(wj_context_ids)

    logger.debug("used_context_units_found",
        company_id=company_id,
        used_count=len(used_unit_ids)
    )

    # 2. Get fresh units from last N days (news must be current)
    cutoff_date = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()
    pool_id = "99999999-9999-9999-9999-999999999999"

    # Query: fresh + from company or pool + ordered by newest first
    all_units = supabase.client.table("press_context_units")\
        .select("*")\
        .in_("company_id", [company_id, pool_id])\
        .gte("created_at", cutoff_date)\
        .order("created_at", desc=True)\
        .limit(limit * 5)\
        .execute()

    # 3. Filter: unused + quality (at least 2 atomic_statements)
    eligible_units = []
    for unit in all_units.data:
        unit_id = unit.get('id')

        # Skip if already used
        if unit_id in used_unit_ids:
            continue

        # Skip if low quality (less than 2 atomic_statements)
        atomic_statements = unit.get('atomic_statements') or []
        if len(atomic_statements) < 2:
            continue

        # Skip if no title or summary (incomplete)
        if not unit.get('title') or not unit.get('summary'):
            continue

        eligible_units.append(unit)

        # Stop if we have enough
        if len(eligible_units) >= limit:
            break

    logger.info("eligible_context_units_selected",
        company_id=company_id,
        total_fetched=len(all_units.data),
        used_filtered=len(used_unit_ids),
        eligible_count=len(eligible_units),
        max_age_days=max_age_days
    )

    return eligible_units


async def evaluate_units_quality(units: list, llm_client) -> list:
    """Evaluate context units quality with LLM."""
    
    if not units:
        return []
    
    prompt = """Evalúa la calidad periodística de estas noticias del 1 al 5.
    
Criterios:
- 5: Excelente - Muy relevante, actual, completa
- 4: Buena - Relevante y actual
- 3: Regular - Algo relevante
- 2: Pobre - Poco relevante
- 1: Mala - Sin valor periodístico

Para cada noticia responde en JSON: {"unit_id": "xxx", "quality_score": 4, "reason": "..."}

Noticias:
"""
    
    # Process in batches of 10
    for i in range(0, len(units), 10):
        batch = units[i:i+10]
        units_text = "\n\n".join([
            f"ID: {u['id']}\nTítulo: {u['title']}\nResumen: {u.get('summary', '')[:200]}"
            for u in batch
        ])
        
        try:
            result = await llm_client.analyze(prompt + units_text)
            
            # Map scores back to units
            if isinstance(result, list):
                for unit in batch:
                    eval_data = next(
                        (e for e in result if e.get('unit_id') == unit['id']),
                        {"quality_score": 3}
                    )
                    unit['quality_score'] = eval_data.get('quality_score', 3)
                    unit['quality_reason'] = eval_data.get('reason', '')
            
        except Exception as e:
            logger.error("quality_evaluation_failed", error=str(e))
            # Default score if evaluation fails
            for unit in batch:
                unit['quality_score'] = 3
    
    return units



async def publish_scheduled_articles():
    """Check and publish articles that are scheduled for publication."""
    
    try:
        logger.info("scheduled_publication_check_start")
        
        supabase = get_supabase_client()
        
        # Get all scheduled articles ready to publish
        now = datetime.utcnow()
        
        scheduled = supabase.client.table("press_articles")\
            .select("id, titulo, company_id")\
            .eq("estado", "programado")\
            .lte("to_publish_at", now.isoformat())\
            .execute()
        
        if not scheduled.data:
            logger.debug("no_articles_to_publish")
            return
        
        logger.info("scheduled_articles_found", count=len(scheduled.data))
        
        published_count = 0
        failed_count = 0
        
        # Call the publish endpoint for each article to use the full publication flow
        async with aiohttp.ClientSession() as session:
            for article in scheduled.data:
                try:
                    # Call the internal API endpoint to use the complete publication flow
                    url = f"http://semantika-api:8000/api/v1/articles/{article['id']}/publish"
                    
                    # Get API key for this company (we need to get a valid API key)
                    # For now, use the company_id as client_id to find the API key
                    client_result = supabase.client.table("clients")\
                        .select("api_key")\
                        .eq("company_id", article['company_id'])\
                        .eq("is_active", True)\
                        .limit(1)\
                        .execute()
                    
                    if not client_result.data:
                        logger.error("no_api_key_found_for_company",
                            article_id=article['id'],
                            company_id=article['company_id']
                        )
                        failed_count += 1
                        continue
                    
                    api_key = client_result.data[0]['api_key']
                    
                    headers = {
                        'X-API-Key': api_key,
                        'Content-Type': 'application/json'
                    }
                    
                    payload = {
                        'publish_now': True
                    }
                    
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status == 200:
                            published_count += 1
                            logger.info("article_auto_published_via_endpoint",
                                article_id=article['id'],
                                title=article['titulo'][:50],
                                company_id=article['company_id']
                            )
                        else:
                            response_text = await response.text()
                            logger.error("article_publication_endpoint_failed",
                                article_id=article['id'],
                                status_code=response.status,
                                response=response_text[:200]
                            )
                            failed_count += 1
                
                except Exception as e:
                    logger.error("article_publication_failed",
                        article_id=article['id'],
                        error=str(e)
                    )
                    failed_count += 1
        
        if published_count > 0 or failed_count > 0:
            logger.info("scheduled_publication_completed",
                total_found=len(scheduled.data),
                published=published_count,
                failed=failed_count
            )
        
    except Exception as e:
        logger.error("scheduled_publication_check_failed", error=str(e))


async def main():
    """Main scheduler entry point."""
    logger.info("scheduler_starting")

    try:
        # Load geocoding cache
        try:
            from utils.geocoder import load_cache_from_db
            logger.info("loading_geocoding_cache")
            await load_cache_from_db()
            logger.info("geocoding_cache_loaded")
        except Exception as e:
            logger.warn("geocoding_cache_load_failed", error=str(e))
        
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
        
        # Schedule periodic garbage collection (every 30 minutes)
        await schedule_garbage_collection(scheduler)
        
        # Schedule daily article generation at 08:00 UTC (5 articles)
        scheduler.add_job(
            daily_article_generation,
            trigger=CronTrigger(hour=8, minute=0),
            id="daily_article_generation",
            replace_existing=True,
            max_instances=1
        )
        logger.info("daily_article_generation_scheduled", time="08:00 UTC")
        
        # Schedule publication check every 5 minutes
        scheduler.add_job(
            publish_scheduled_articles,
            trigger=IntervalTrigger(minutes=5),
            id="publish_scheduled_articles",
            replace_existing=True,
            max_instances=1
        )
        logger.info("scheduled_publication_check_scheduled", interval_minutes=5)

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
