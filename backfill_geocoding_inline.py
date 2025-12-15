"""Backfill geocoding for existing context units without geo_location.

This script:
1. Fetches context units without geo_location in source_metadata
2. For each unit, checks if LLM returned locations in atomic_statements analysis
3. If locations exist, geocodes them and updates source_metadata
4. Processes in batches to avoid memory issues
"""

import asyncio
import os
from typing import Dict, Any, List, Optional

# Set environment variables from .env
from dotenv import load_dotenv
load_dotenv()

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.geocoder import geocode_with_context
from utils.llm_client import get_llm_client

logger = get_logger("backfill_geocoding")


async def backfill_geocoding(batch_size: int = 50, dry_run: bool = False):
    """Backfill geocoding for context units missing geo_location.
    
    Args:
        batch_size: Number of units to process per batch
        dry_run: If True, only log what would be updated without saving
    """
    supabase = get_supabase_client()
    llm_client = get_llm_client()
    
    # Fetch units without geo_location (last 30 days)
    result = supabase.client.table("press_context_units")\
        .select("id, title, summary, raw_text, source_metadata, atomic_statements")\
        .is_("source_metadata->geo_location", "null")\
        .gte("created_at", "2024-11-14")\
        .order("created_at", desc=True)\
        .limit(batch_size)\
        .execute()
    
    units = result.data if result.data else []
    
    logger.info("backfill_start", 
        total_units=len(units),
        batch_size=batch_size,
        dry_run=dry_run
    )
    
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    for unit in units:
        unit_id = unit["id"]
        title = unit.get("title", "")
        
        try:
            # Strategy 1: Extract locations from raw_text using LLM
            raw_text = unit.get("raw_text") or unit.get("summary", "")
            
            if not raw_text or len(raw_text) < 50:
                logger.debug("unit_skipped_no_text", unit_id=unit_id, title=title[:50])
                skipped_count += 1
                continue
            
            # Call LLM to extract locations
            logger.debug("extracting_locations", unit_id=unit_id, title=title[:50])
            
            llm_result = await llm_client.analyze_atomic(
                text=raw_text[:8000],
                company_id=unit.get("company_id", "00000000-0000-0000-0000-000000000001")
            )
            
            locations = llm_result.get("locations", [])
            
            if not locations:
                logger.debug("unit_skipped_no_locations", unit_id=unit_id, title=title[:50])
                skipped_count += 1
                continue
            
            # Geocode locations
            logger.debug("geocoding_locations", 
                unit_id=unit_id, 
                title=title[:50],
                locations=locations
            )
            
            geo_location = await geocode_with_context(locations)
            
            if not geo_location:
                logger.warn("geocoding_failed", unit_id=unit_id, locations=locations)
                skipped_count += 1
                continue
            
            # Update source_metadata with geo_location
            source_metadata = unit.get("source_metadata") or {}
            source_metadata["geo_location"] = geo_location
            source_metadata["locations"] = locations  # Also store raw locations
            
            if dry_run:
                logger.info("dry_run_would_update",
                    unit_id=unit_id,
                    title=title[:50],
                    geo_location=geo_location,
                    locations=locations
                )
                updated_count += 1
            else:
                # Save to database
                supabase.client.table("press_context_units")\
                    .update({"source_metadata": source_metadata})\
                    .eq("id", unit_id)\
                    .execute()
                
                logger.info("unit_geocoded",
                    unit_id=unit_id,
                    title=title[:50],
                    primary_location=geo_location.get("primary_name"),
                    lat=geo_location.get("lat"),
                    lon=geo_location.get("lon")
                )
                updated_count += 1
        
        except Exception as e:
            logger.error("unit_geocoding_error",
                unit_id=unit_id,
                title=title[:50],
                error=str(e)
            )
            error_count += 1
    
    logger.info("backfill_complete",
        total_processed=len(units),
        updated=updated_count,
        skipped=skipped_count,
        errors=error_count,
        dry_run=dry_run
    )
    
    return {
        "total_processed": len(units),
        "updated": updated_count,
        "skipped": skipped_count,
        "errors": error_count
    }


if __name__ == "__main__":
    import sys
    
    # Parse arguments
    dry_run = "--dry-run" in sys.argv
    batch_size = 50
    
    for arg in sys.argv:
        if arg.startswith("--batch="):
            batch_size = int(arg.split("=")[1])
    
    # Run backfill
    result = asyncio.run(backfill_geocoding(batch_size=batch_size, dry_run=dry_run))
    
    print(f"\n✅ Backfill complete:")
    print(f"   - Processed: {result['total_processed']}")
    print(f"   - Updated: {result['updated']}")
    print(f"   - Skipped: {result['skipped']}")
    print(f"   - Errors: {result['errors']}")
    print(f"   - Mode: {'DRY RUN' if dry_run else 'LIVE'}")
