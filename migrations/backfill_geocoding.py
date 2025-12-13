"""Backfill geocoding for existing press_context_units.

Adds geo_location to source_metadata.connector_specific for all existing
context units that don't have it yet.

RATE LIMIT PROTECTION:
- 1.2 second sleep between each geocoding API call
- Static DB cache (99% hits, 0 API calls)
- Perpetual cache (no duplicate API calls)

Usage:
    # Dry-run (safe, shows changes)
    python migrations/backfill_geocoding.py --dry-run --limit 10
    
    # Execute (updates DB)
    python migrations/backfill_geocoding.py --no-dry-run
"""

import asyncio
import argparse
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, '/app')

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.geocoder import geocode_with_context, STATIC_LOCATIONS

logger = get_logger("backfill_geocoding")


async def backfill_geocoding(dry_run: bool = True, limit: int = None):
    """Backfill geocoding for existing context units.
    
    Args:
        dry_run: If True, only show what would be updated
        limit: Optional limit on number of records to process
    """
    logger.info("backfill_geocoding_start", dry_run=dry_run, limit=limit)
    
    supabase = get_supabase_client()
    
    # Get ALL context units (we'll check geo_location in code)
    query = supabase.client.table("press_context_units")\
        .select("id, title, summary, source_metadata, atomic_statements")\
        .order("created_at", desc=True)
    
    if limit:
        query = query.limit(limit)
    
    result = query.execute()
    
    logger.info("context_units_fetched", total=len(result.data))
    
    # Filter out units that already have geo_location
    units_to_process = []
    for unit in result.data:
        source_metadata = unit.get("source_metadata") or {}
        connector_specific = source_metadata.get("connector_specific") or {}
        
        if not connector_specific.get("geo_location"):
            units_to_process.append(unit)
    
    total = len(units_to_process)
    logger.info("context_units_without_geocoding", total=total)
    
    if total == 0:
        logger.info("all_context_units_already_geocoded")
        return
    
    updated = 0
    skipped = 0
    failed = 0
    
    for i, unit in enumerate(units_to_process):
        unit_id = unit["id"]
        title = unit.get("title", "")
        
        logger.info("processing_unit", 
            index=i+1,
            total=total,
            unit_id=unit_id,
            title=title[:50]
        )
        
        try:
            # Extract locations from title and summary using pattern matching
            text = f"{title} {unit.get('summary', '')}"
            locations = extract_locations_from_text(text)
            
            if not locations:
                logger.debug("no_locations_found", 
                    unit_id=unit_id,
                    title=title[:50]
                )
                skipped += 1
                continue
            
            # Geocode locations (uses 3-tier cache, minimal API calls)
            geo_location = await geocode_with_context(locations)
            
            if not geo_location:
                logger.warn("geocoding_failed", 
                    unit_id=unit_id,
                    locations=locations
                )
                failed += 1
                continue
            
            logger.info("location_geocoded",
                unit_id=unit_id,
                primary=geo_location.get("primary_name"),
                lat=geo_location.get("lat"),
                lon=geo_location.get("lon")
            )
            
            if dry_run:
                logger.info("dry_run_would_update",
                    unit_id=unit_id,
                    title=title[:50],
                    geo_location={
                        "primary": geo_location.get("primary_name"),
                        "lat": geo_location.get("lat"),
                        "lon": geo_location.get("lon")
                    }
                )
                updated += 1
            else:
                # Update source_metadata
                source_metadata = unit.get("source_metadata") or {}
                if "connector_specific" not in source_metadata:
                    source_metadata["connector_specific"] = {}
                elif source_metadata["connector_specific"] is None:
                    source_metadata["connector_specific"] = {}
                
                source_metadata["connector_specific"]["geo_location"] = geo_location
                
                # Update in DB
                supabase.client.table("press_context_units")\
                    .update({"source_metadata": source_metadata})\
                    .eq("id", unit_id)\
                    .execute()
                
                logger.info("context_unit_updated",
                    unit_id=unit_id,
                    title=title[:50],
                    lat=geo_location.get("lat"),
                    lon=geo_location.get("lon")
                )
                updated += 1
            
            # RATE LIMIT PROTECTION: 1.2 sec between geocoding calls
            # (Nominatim limit: 1 request/sec)
            await asyncio.sleep(1.2)
        
        except Exception as e:
            logger.error("backfill_error",
                unit_id=unit_id,
                title=title[:50],
                error=str(e),
                error_type=type(e).__name__
            )
            failed += 1
    
    logger.info("backfill_geocoding_completed",
        total=total,
        updated=updated,
        skipped=skipped,
        failed=failed,
        dry_run=dry_run
    )
    
    if not dry_run:
        print(f"\n✅ Backfill completed:")
        print(f"   Total processed: {total}")
        print(f"   Updated: {updated}")
        print(f"   Skipped (no locations): {skipped}")
        print(f"   Failed: {failed}")


def extract_locations_from_text(text: str) -> list:
    """Extract locations from text using pattern matching.
    
    Searches for known cities/provinces in text (from STATIC_LOCATIONS).
    This is lightweight and doesn't require calling LLM again.
    
    Args:
        text: Text to search for locations
        
    Returns:
        List of location dicts in LLM format
    """
    text_lower = text.lower()
    locations = []
    
    # Search for cities and provinces in text
    cities_found = []
    provinces_found = []
    
    # Sort locations by length (longest first) to match "San Sebastián" before "Sebastián"
    sorted_locations = sorted(
        STATIC_LOCATIONS.items(), 
        key=lambda x: len(x[0]), 
        reverse=True
    )
    
    for location_name, location_data in sorted_locations:
        if location_name in text_lower:
            location_type = location_data.get("type", "city")
            
            # Capitalize properly
            if location_name == "bilbao":
                display_name = "Bilbao"
            elif location_name == "vitoria-gasteiz":
                display_name = "Vitoria-Gasteiz"
            elif location_name == "donostia-san sebastián":
                display_name = "Donostia-San Sebastián"
            elif location_name == "álava":
                display_name = "Álava"
            elif location_name == "bizkaia":
                display_name = "Bizkaia"
            elif location_name == "gipuzkoa":
                display_name = "Gipuzkoa"
            elif location_name == "país vasco":
                display_name = "País Vasco"
            elif location_name == "euskadi":
                display_name = "Euskadi"
            else:
                display_name = location_name.title()
            
            if location_type == "city" and display_name not in [c["name"] for c in cities_found]:
                cities_found.append({
                    "name": display_name,
                    "type": "city",
                    "level": "primary"
                })
            elif location_type in ["province", "region"] and display_name not in [p["name"] for p in provinces_found]:
                provinces_found.append({
                    "name": display_name,
                    "type": location_type,
                    "level": "context"
                })
    
    # Build location hierarchy
    # Primary: First city found
    if cities_found:
        locations.append(cities_found[0])
    
    # Context: Provinces/regions
    locations.extend(provinces_found[:2])  # Max 2 provinces
    
    # Always add Spain as country context
    if locations:
        locations.append({
            "name": "España",
            "type": "country",
            "level": "context"
        })
    
    return locations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill geocoding for existing context units"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be updated without making changes (default: True)"
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually update the database"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of records to process"
    )
    
    args = parser.parse_args()
    
    # Determine dry_run mode
    dry_run = not args.no_dry_run
    
    if not dry_run:
        print("\n⚠️  WARNING: This will UPDATE the database!")
        print("⚠️  This will make API calls to Nominatim (rate limit: 1/sec)")
        print(f"⚠️  Estimated time: ~{args.limit or 'all'} records × 1.2 sec")
        print("\nPress Ctrl+C to cancel, or wait 5 seconds to continue...")
        try:
            import time
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(0)
    
    # Run backfill
    asyncio.run(backfill_geocoding(dry_run=dry_run, limit=args.limit))
