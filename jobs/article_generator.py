"""Automatic article generation jobs.

Handles:
- Daily article generation for companies with autogenerate_enabled
- Quality evaluation of context units
- Publishing of scheduled articles
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any

import aiohttp

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client
from utils.llm_client import LLMClient

logger = get_logger("jobs.article_generator")


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
                company_settings = company.get('settings', {})
                if not company_settings.get('autogenerate_enabled', False):
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
                    max_articles=company_settings.get('autogenerate_max', 5)
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

                    elif response.status == 400:
                        # Empty content - LLM failed to generate, skip this unit
                        logger.warn("article_generation_empty_content",
                            company_id=company_id,
                            unit_id=unit['id'],
                            unit_title=unit.get('title', '')[:50]
                        )
                        # Continue to next unit

                    elif response.status == 409:
                        # Duplicate - article already exists with this context unit
                        logger.info("article_generation_skipped_duplicate",
                            company_id=company_id,
                            unit_id=unit['id'],
                            unit_title=unit.get('title', '')[:50]
                        )
                        # Continue to next unit

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

    # 3. Filter: unused + quality (at least 2 atomic_statements) + fresh published_at
    eligible_units = []
    published_at_cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).date()

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

        # Skip if published_at is too old (even if recently scraped)
        source_metadata = unit.get('source_metadata') or {}
        published_at_str = source_metadata.get('published_at', '')
        if published_at_str:
            try:
                # Handle various date formats
                if 'T' in published_at_str:
                    published_date = datetime.fromisoformat(published_at_str.replace('Z', '+00:00')).date()
                else:
                    published_date = datetime.strptime(published_at_str[:10], '%Y-%m-%d').date()

                if published_date < published_at_cutoff:
                    logger.debug("skipping_old_published_at",
                        unit_id=unit_id,
                        published_at=published_at_str,
                        cutoff=str(published_at_cutoff)
                    )
                    continue
            except (ValueError, TypeError):
                pass  # If date parsing fails, don't filter by it

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


async def process_scheduled_publications():
    """Process individual scheduled publications from scheduled_publications table.

    This handles the new per-target scheduling system where each target
    can have a different schedule time.
    """
    from publishers.publisher_factory import PublisherFactory
    from itertools import groupby

    try:
        logger.info("process_scheduled_publications_start")

        supabase = get_supabase_client()
        now = datetime.utcnow()

        # Get all pending scheduled publications that are due
        pending_result = supabase.client.table("scheduled_publications")\
            .select("*, press_articles!inner(id, titulo, contenido, excerpt, slug, tags, category, imagen_uuid, working_json, published_url, company_id), press_publication_targets!inner(id, platform_type, name, base_url, credentials_encrypted)")\
            .eq("status", "scheduled")\
            .lte("scheduled_for", now.isoformat())\
            .order("article_id")\
            .order("scheduled_for")\
            .execute()

        if not pending_result.data:
            logger.debug("no_scheduled_publications_pending")
            return

        pending = pending_result.data
        logger.info("scheduled_publications_found", count=len(pending))

        # Group by article_id for batch processing
        pending_sorted = sorted(pending, key=lambda x: x['article_id'])
        grouped = {}
        for pub in pending_sorted:
            article_id = pub['article_id']
            if article_id not in grouped:
                grouped[article_id] = []
            grouped[article_id].append(pub)

        published_count = 0
        failed_count = 0

        for article_id, publications in grouped.items():
            try:
                # Get article data from first publication
                article = publications[0]['press_articles']

                # Separate WordPress vs Social targets
                wp_pubs = [p for p in publications if p['platform_type'] == 'wordpress']
                social_pubs = [p for p in publications if p['platform_type'] != 'wordpress']

                wordpress_url = article.get('published_url')

                # Step 1: Publish WordPress first (to get URL for social)
                for pub in wp_pubs:
                    try:
                        target = pub['press_publication_targets']

                        publisher = PublisherFactory.create_publisher(
                            target['platform_type'],
                            target['base_url'],
                            target['credentials_encrypted']
                        )

                        # Prepare content
                        content = article.get('contenido', '')

                        # Add footer with related articles
                        try:
                            from endpoints.articles import _add_article_footer
                            content = await _add_article_footer(content, article_id, article['company_id'])
                        except Exception as e:
                            logger.warn("add_footer_failed", error=str(e))

                        result = await publisher.publish_article(
                            title=article.get('titulo', 'Untitled'),
                            content=content,
                            excerpt=article.get('excerpt', ''),
                            tags=article.get('tags', []),
                            category=article.get('category'),
                            status="publish",
                            slug=article.get('slug'),
                            imagen_uuid=article.get('imagen_uuid')
                        )

                        # Update scheduled_publication record
                        update_data = {
                            "status": "published" if result.success else "failed",
                            "published_at": datetime.utcnow().isoformat() if result.success else None,
                            "error_message": result.error if not result.success else None,
                            "publication_result": {
                                "success": result.success,
                                "url": result.url,
                                "external_id": result.external_id,
                                "error": result.error
                            }
                        }

                        supabase.client.table("scheduled_publications")\
                            .update(update_data)\
                            .eq("id", pub['id'])\
                            .execute()

                        if result.success:
                            wordpress_url = result.url
                            published_count += 1
                            logger.info("scheduled_wp_published",
                                article_id=article_id,
                                target_id=target['id'],
                                url=result.url
                            )
                        else:
                            failed_count += 1
                            logger.error("scheduled_wp_failed",
                                article_id=article_id,
                                target_id=target['id'],
                                error=result.error
                            )

                    except Exception as e:
                        logger.error("scheduled_wp_publication_error",
                            article_id=article_id,
                            pub_id=pub['id'],
                            error=str(e)
                        )
                        supabase.client.table("scheduled_publications")\
                            .update({
                                "status": "failed",
                                "error_message": str(e)
                            })\
                            .eq("id", pub['id'])\
                            .execute()
                        failed_count += 1

                # Brief delay before social media
                if wp_pubs and social_pubs and wordpress_url:
                    await asyncio.sleep(2)

                # Step 2: Publish to social media with hook
                for pub in social_pubs:
                    try:
                        target = pub['press_publication_targets']

                        # Get hook from scheduled_publication record
                        hook_text = pub.get('social_hook') or article.get('titulo', '')[:147]
                        if len(hook_text) > 150:
                            hook_text = hook_text[:147] + "..."

                        # Build social content
                        social_content = f"{hook_text}\n\n{wordpress_url}" if wordpress_url else hook_text

                        publisher = PublisherFactory.create_publisher(
                            target['platform_type'],
                            target.get('base_url', ''),
                            target['credentials_encrypted']
                        )

                        result = await publisher.publish_social(
                            content=social_content,
                            url=wordpress_url,
                            image_uuid=article.get('imagen_uuid'),
                            tags=[]
                        )

                        # Update scheduled_publication record
                        update_data = {
                            "status": "published" if result.success else "failed",
                            "published_at": datetime.utcnow().isoformat() if result.success else None,
                            "error_message": result.error if not result.success else None,
                            "publication_result": {
                                "success": result.success,
                                "url": result.url,
                                "external_id": result.external_id,
                                "error": result.error
                            }
                        }

                        supabase.client.table("scheduled_publications")\
                            .update(update_data)\
                            .eq("id", pub['id'])\
                            .execute()

                        if result.success:
                            published_count += 1
                            logger.info("scheduled_social_published",
                                article_id=article_id,
                                platform=target['platform_type'],
                                url=result.url
                            )
                        else:
                            failed_count += 1
                            logger.error("scheduled_social_failed",
                                article_id=article_id,
                                platform=target['platform_type'],
                                error=result.error
                            )

                    except Exception as e:
                        logger.error("scheduled_social_publication_error",
                            article_id=article_id,
                            pub_id=pub['id'],
                            error=str(e)
                        )
                        supabase.client.table("scheduled_publications")\
                            .update({
                                "status": "failed",
                                "error_message": str(e)
                            })\
                            .eq("id", pub['id'])\
                            .execute()
                        failed_count += 1

                # Check if all publications for this article are done
                remaining_result = supabase.client.table("scheduled_publications")\
                    .select("id")\
                    .eq("article_id", article_id)\
                    .eq("status", "scheduled")\
                    .execute()

                if not remaining_result.data:
                    # All done - update article to published
                    supabase.client.table("press_articles")\
                        .update({
                            "estado": "publicado",
                            "published_url": wordpress_url,
                            "fecha_publicacion": datetime.utcnow().isoformat(),
                            "updated_at": datetime.utcnow().isoformat()
                        })\
                        .eq("id", article_id)\
                        .execute()

                    logger.info("article_all_publications_complete",
                        article_id=article_id
                    )

            except Exception as e:
                logger.error("process_article_publications_failed",
                    article_id=article_id,
                    error=str(e)
                )

        if published_count > 0 or failed_count > 0:
            logger.info("process_scheduled_publications_completed",
                total_processed=len(pending),
                published=published_count,
                failed=failed_count
            )

    except Exception as e:
        logger.error("process_scheduled_publications_failed", error=str(e))
