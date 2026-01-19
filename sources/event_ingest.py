"""Event ingestion workflow for calendar/agenda sources.

Optimized flow:
1. Fetch HTML from event source
2. Check for meaningful changes (SimHash - skip if trivial)
3. Extract events via LLM (only if content changed)
4. For each date:
   - If no existing events → save directly
   - If existing events → LLM fusion (intelligent merge)

Uses multi-tier change detection to minimize LLM calls.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, date, timedelta
from uuid import uuid4
import asyncio
import aiohttp

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.llm_client import get_llm_client
from utils.content_hasher import (
    normalize_html,
    compute_content_hashes,
    simhash_similarity
)

logger = get_logger("event_ingest")

# Threshold for SimHash similarity (95% = trivial change, skip)
SIMHASH_SKIP_THRESHOLD = 0.95


async def fetch_html(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch HTML content from URL.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds

    Returns:
        HTML content or None if failed
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }

    try:
        timeout_config = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    logger.info("html_fetched", url=url, size=len(html))
                    return html
                else:
                    logger.warn("html_fetch_failed", url=url, status=response.status)
                    return None
    except Exception as e:
        logger.error("html_fetch_error", url=url, error=str(e))
        return None


def check_content_changed(
    html: str,
    old_hash: Optional[str],
    old_simhash: Optional[int]
) -> Tuple[bool, str, int, Optional[float]]:
    """Check if content has meaningfully changed using SimHash.

    Args:
        html: New HTML content
        old_hash: Previous SHA256 hash
        old_simhash: Previous SimHash

    Returns:
        Tuple of (has_changed, new_hash, new_simhash, similarity_score)
    """
    # Normalize and compute hashes
    normalized = normalize_html(html)
    new_hash, new_simhash = compute_content_hashes(text=normalized)

    # First time seeing this source
    if old_hash is None or old_simhash is None:
        logger.info("content_check_new_source")
        return (True, new_hash, new_simhash, None)

    # Exact match
    if old_hash == new_hash:
        logger.info("content_check_identical", hash=new_hash[:16])
        return (False, new_hash, new_simhash, 1.0)

    # SimHash fuzzy match
    similarity = simhash_similarity(old_simhash, new_simhash)

    if similarity >= SIMHASH_SKIP_THRESHOLD:
        # Trivial change (timestamp, ad rotation, etc.)
        logger.info("content_check_trivial",
            similarity=round(similarity, 4),
            threshold=SIMHASH_SKIP_THRESHOLD
        )
        return (False, new_hash, new_simhash, similarity)

    # Meaningful change detected
    logger.info("content_check_changed",
        similarity=round(similarity, 4),
        threshold=SIMHASH_SKIP_THRESHOLD
    )
    return (True, new_hash, new_simhash, similarity)


def clean_html_for_llm(html: str) -> str:
    """Clean HTML to reduce token count for LLM processing."""
    from bs4 import BeautifulSoup, Comment

    soup = BeautifulSoup(html, 'html.parser')

    # Remove script and style elements
    for element in soup(['script', 'style', 'noscript', 'iframe', 'svg', 'meta', 'link']):
        element.decompose()

    # Remove comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Get body content
    body = soup.find('body')
    if body:
        html_cleaned = str(body)
    else:
        html_cleaned = str(soup)

    # Normalize whitespace
    import re
    html_cleaned = re.sub(r'\s+', ' ', html_cleaned)

    return html_cleaned


async def extract_events_from_html(
    html: str,
    url: str,
    llm_client
) -> List[Dict[str, Any]]:
    """Extract events from HTML using LLM.

    Args:
        html: Cleaned HTML content
        url: Source URL (for resolving relative links)
        llm_client: LLM client instance

    Returns:
        List of extracted events
    """
    result = await llm_client.extract_events(html, url)
    events = result.get('events', [])

    # Add unique IDs to each event
    for event in events:
        if not event.get('id'):
            event['id'] = str(uuid4())

    return events


def group_events_by_date(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group events by their event_date.

    Args:
        events: List of event dicts with event_date field

    Returns:
        Dict mapping date string (YYYY-MM-DD) to list of events
    """
    grouped = {}

    for event in events:
        event_date = event.get('event_date')
        if not event_date:
            logger.debug("event_missing_date", title=event.get('title', 'Unknown'))
            continue

        if event_date not in grouped:
            grouped[event_date] = []
        grouped[event_date].append(event)

    return grouped


async def get_existing_events(
    supabase,
    company_id: str,
    geographic_area: str,
    event_date: str
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Get existing events for a specific date.

    Args:
        supabase: Supabase client
        company_id: Company UUID
        geographic_area: Geographic area code
        event_date: Date string (YYYY-MM-DD)

    Returns:
        Tuple of (record_id, events_list) or (None, []) if not found
    """
    try:
        result = supabase.client.table('context_events').select('id, events').eq(
            'company_id', company_id
        ).eq(
            'geographic_area', geographic_area
        ).eq(
            'event_date', event_date
        ).execute()

        if result.data and len(result.data) > 0:
            record = result.data[0]
            return (record['id'], record.get('events', []))

        return (None, [])

    except Exception as e:
        logger.error("get_existing_events_error", event_date=event_date, error=str(e))
        return (None, [])


async def merge_events_with_llm(
    existing_events: List[Dict[str, Any]],
    new_events: List[Dict[str, Any]],
    event_date: str,
    llm_client
) -> List[Dict[str, Any]]:
    """Use LLM to intelligently merge existing and new events.

    The LLM acts as an editor that:
    - Identifies duplicate events (even with different wording)
    - Updates event details if new info is available
    - Keeps existing events that aren't in new scrape
    - Returns a clean merged list

    Args:
        existing_events: Current events for the day
        new_events: Newly scraped events
        event_date: Date for context
        llm_client: LLM client instance

    Returns:
        Merged list of events
    """
    import json

    # Build the merge prompt
    result = await llm_client.merge_events(
        existing_events=existing_events,
        new_events=new_events,
        event_date=event_date
    )

    merged = result.get('events', [])

    # Ensure all events have IDs
    for event in merged:
        if not event.get('id'):
            event['id'] = str(uuid4())

    logger.info("events_merged_with_llm",
        event_date=event_date,
        existing_count=len(existing_events),
        new_count=len(new_events),
        merged_count=len(merged)
    )

    return merged


async def save_events_for_date(
    supabase,
    company_id: str,
    geographic_area: str,
    event_date: str,
    events: List[Dict[str, Any]],
    source_name: str,
    record_id: Optional[str] = None
) -> bool:
    """Save events for a specific date.

    Args:
        supabase: Supabase client
        company_id: Company UUID
        geographic_area: Geographic area code
        event_date: Date string (YYYY-MM-DD)
        events: List of events
        source_name: Name of the source for tracking
        record_id: Existing record ID (for update) or None (for insert)

    Returns:
        True if successful
    """
    try:
        now = datetime.utcnow().isoformat()

        if record_id:
            # Update existing record
            supabase.client.table('context_events').update({
                'events': events,
                'last_source': source_name,
                'updated_at': now
            }).eq('id', record_id).execute()

            logger.info("events_updated",
                event_date=event_date,
                events_count=len(events)
            )
        else:
            # Insert new record
            supabase.client.table('context_events').insert({
                'company_id': company_id,
                'geographic_area': geographic_area,
                'event_date': event_date,
                'events': events,
                'last_source': source_name,
                'version': 1
            }).execute()

            logger.info("events_inserted",
                event_date=event_date,
                events_count=len(events)
            )

        return True

    except Exception as e:
        logger.error("events_save_error", event_date=event_date, error=str(e))
        return False


async def update_source_hashes(
    supabase,
    source_id: str,
    content_hash: str,
    simhash: int,
    success: bool,
    events_count: int = 0,
    error_message: Optional[str] = None
):
    """Update event source with new hashes and stats.

    Args:
        supabase: Supabase client
        source_id: Source UUID
        content_hash: New SHA256 hash
        simhash: New SimHash
        success: Whether scraping succeeded
        events_count: Number of events extracted
        error_message: Error message if failed
    """
    try:
        now = datetime.utcnow().isoformat()

        update_data = {
            'last_content_hash': content_hash,
            'last_simhash': simhash,
            'last_scraped_at': now,
            'updated_at': now
        }

        if success:
            update_data.update({
                'consecutive_failures': 0,
                'events_count_30d': events_count,
                'circuit_breaker_open': False
            })
        else:
            # Increment failure counters
            current = supabase.client.table('event_sources').select(
                'consecutive_failures, total_failures'
            ).eq('source_id', source_id).execute()

            if current.data:
                consecutive = current.data[0].get('consecutive_failures', 0) + 1
                total = current.data[0].get('total_failures', 0) + 1
                circuit_open = consecutive >= 5

                update_data.update({
                    'consecutive_failures': consecutive,
                    'total_failures': total,
                    'last_error': error_message,
                    'last_error_at': now,
                    'circuit_breaker_open': circuit_open
                })

        supabase.client.table('event_sources').update(update_data).eq('source_id', source_id).execute()

    except Exception as e:
        logger.error("source_hashes_update_error", source_id=source_id, error=str(e))


async def process_single_source(
    source: Dict[str, Any],
    supabase,
    llm_client
) -> Dict[str, Any]:
    """Process a single event source.

    Flow:
    1. Fetch HTML
    2. Check for changes (SimHash)
    3. If changed → Extract events (LLM)
    4. Return events grouped by date

    Args:
        source: Event source record
        supabase: Supabase client
        llm_client: LLM client instance

    Returns:
        Dict with source_id, events_by_date, skipped, error
    """
    source_id = source['source_id']
    source_name = source['source_name']
    url = source['url']
    default_category = source.get('default_category')
    old_hash = source.get('last_content_hash')
    old_simhash = source.get('last_simhash')

    # Convert simhash from Decimal to int if needed
    if old_simhash is not None:
        old_simhash = int(old_simhash)

    result = {
        'source_id': source_id,
        'source_name': source_name,
        'events_by_date': {},
        'skipped': False,
        'skip_reason': None,
        'error': None
    }

    try:
        # Step 1: Fetch HTML
        html = await fetch_html(url)
        if not html:
            result['error'] = 'fetch_failed'
            await update_source_hashes(supabase, source_id, '', 0, False, 0, 'fetch_failed')
            return result

        # Step 2: Check for meaningful changes
        has_changed, new_hash, new_simhash, similarity = check_content_changed(
            html, old_hash, old_simhash
        )

        if not has_changed:
            # Content hasn't meaningfully changed - skip LLM
            result['skipped'] = True
            result['skip_reason'] = f'content_unchanged (similarity: {similarity:.2%})'
            logger.info("source_skipped_no_changes",
                source_name=source_name,
                similarity=similarity
            )
            # Update hashes but don't increment success counters significantly
            await update_source_hashes(supabase, source_id, new_hash, new_simhash, True, 0)
            return result

        # Step 3: Content changed - extract events via LLM
        logger.info("extracting_events",
            source_name=source_name,
            reason='content_changed'
        )

        html_cleaned = clean_html_for_llm(html)
        events = await extract_events_from_html(html_cleaned, url, llm_client)

        # Add source metadata to events
        for event in events:
            event['source'] = 'scraping'
            event['source_id'] = source_id
            event['source_name'] = source_name
            event['status'] = event.get('status', 'active')
            if not event.get('category') and default_category:
                event['category'] = default_category

        # Group by date
        result['events_by_date'] = group_events_by_date(events)

        # Update source with new hashes
        total_events = len(events)
        await update_source_hashes(supabase, source_id, new_hash, new_simhash, True, total_events)

        logger.info("source_processed",
            source_name=source_name,
            events_extracted=total_events,
            dates_with_events=len(result['events_by_date'])
        )

        return result

    except Exception as e:
        logger.error("source_processing_error",
            source_id=source_id,
            source_name=source_name,
            error=str(e)
        )
        result['error'] = str(e)
        await update_source_hashes(supabase, source_id, '', 0, False, 0, str(e))
        return result


async def ingest_events_for_area(
    company_id: str,
    geographic_area: str
) -> Dict[str, Any]:
    """Main entry point: Ingest events for a geographic area.

    Optimized flow:
    1. Load active sources
    2. Process each source (with change detection)
    3. For dates with new events:
       - No existing → save directly
       - Has existing → LLM merge

    Args:
        company_id: Company UUID (use pool UUID for shared events)
        geographic_area: Geographic area code (e.g., 'alava', 'bizkaia')

    Returns:
        Summary of ingestion results
    """
    logger.info("event_ingest_started",
        company_id=company_id,
        geographic_area=geographic_area
    )

    supabase = get_supabase_client()
    llm_client = get_llm_client()

    # Load active event sources
    sources_response = supabase.client.table('event_sources').select('*').eq(
        'company_id', company_id
    ).eq(
        'geographic_area', geographic_area
    ).eq(
        'is_active', True
    ).eq(
        'circuit_breaker_open', False
    ).execute()

    sources = sources_response.data or []

    if not sources:
        logger.warn("no_active_event_sources",
            company_id=company_id,
            geographic_area=geographic_area
        )
        return {
            'success': False,
            'message': 'No active event sources found',
            'sources_processed': 0,
            'events_extracted': 0
        }

    logger.info("event_sources_loaded", count=len(sources))

    # Process each source
    sources_results = []
    for source in sources:
        result = await process_single_source(source, supabase, llm_client)
        sources_results.append(result)

    # Aggregate events by date across all sources
    all_events_by_date: Dict[str, List[Dict[str, Any]]] = {}
    sources_skipped = 0
    sources_failed = 0
    sources_success = 0
    total_events_extracted = 0

    for result in sources_results:
        if result['error']:
            sources_failed += 1
        elif result['skipped']:
            sources_skipped += 1
        else:
            sources_success += 1
            for event_date, events in result['events_by_date'].items():
                if event_date not in all_events_by_date:
                    all_events_by_date[event_date] = []
                all_events_by_date[event_date].extend(events)
                total_events_extracted += len(events)

    logger.info("sources_processing_summary",
        total=len(sources),
        success=sources_success,
        skipped=sources_skipped,
        failed=sources_failed,
        total_events=total_events_extracted,
        unique_dates=len(all_events_by_date)
    )

    # Save/merge events for each date
    dates_saved = 0
    dates_merged = 0

    for event_date, new_events in all_events_by_date.items():
        # Get existing events for this date
        record_id, existing_events = await get_existing_events(
            supabase, company_id, geographic_area, event_date
        )

        source_names = list(set(e.get('source_name', 'unknown') for e in new_events))
        source_name = ', '.join(source_names[:3])

        if not existing_events:
            # No existing events - save directly (no LLM needed)
            success = await save_events_for_date(
                supabase, company_id, geographic_area, event_date,
                new_events, source_name, record_id
            )
            if success:
                dates_saved += 1
        else:
            # Has existing events - use LLM to merge intelligently
            merged_events = await merge_events_with_llm(
                existing_events, new_events, event_date, llm_client
            )
            success = await save_events_for_date(
                supabase, company_id, geographic_area, event_date,
                merged_events, source_name, record_id
            )
            if success:
                dates_merged += 1

    summary = {
        'success': True,
        'company_id': company_id,
        'geographic_area': geographic_area,
        'sources_total': len(sources),
        'sources_success': sources_success,
        'sources_skipped': sources_skipped,
        'sources_failed': sources_failed,
        'events_extracted': total_events_extracted,
        'dates_new': dates_saved,
        'dates_merged': dates_merged
    }

    logger.info("event_ingest_completed", **summary)

    return summary


# Convenience function for scheduler
async def run_event_ingest(
    company_id: str = "99999999-9999-9999-9999-999999999999",
    geographic_area: str = "alava"
) -> Dict[str, Any]:
    """Scheduler-friendly wrapper for event ingestion."""
    return await ingest_events_for_area(company_id, geographic_area)
