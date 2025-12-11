"""Migration script: Standardize source_metadata across all context units.

Migrates old formats to new standard schema:
- Perplexity: perplexity_source → url
- All: Adds scraped_at, published_at in ISO 8601
- All: Moves connector-specific fields to connector_specific subclave

Usage:
    python migrations/migrate_source_metadata.py [--dry-run] [--limit N]
"""

import asyncio
import sys
import argparse
from datetime import datetime
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, '/Users/igor/Documents/semantika')

from utils.supabase_client import get_supabase_client
from utils.source_metadata_schema import migrate_old_metadata
from utils.logger import get_logger

logger = get_logger("migrate_source_metadata")


async def migrate_context_units(dry_run: bool = True, limit: int = None):
    """Migrate source_metadata in press_context_units.
    
    Args:
        dry_run: If True, only log changes without updating database
        limit: Maximum number of records to process (None = all)
    """
    try:
        supabase = get_supabase_client()
        
        # Get all context units with old metadata format
        query = supabase.client.table("press_context_units")\
            .select("id, source_metadata, source_type, created_at")\
            .not_.is_("source_metadata", "null")\
            .order("created_at", desc=True)
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        
        total_records = len(result.data)
        logger.info("migration_start",
            total_records=total_records,
            dry_run=dry_run,
            limit=limit
        )
        
        migrated_count = 0
        skipped_count = 0
        error_count = 0
        
        for record in result.data:
            try:
                record_id = record["id"]
                old_metadata = record.get("source_metadata") or {}
                
                # Skip if already migrated (has 'url' or 'connector_specific' keys)
                if "connector_specific" in old_metadata:
                    logger.debug("already_migrated", record_id=record_id)
                    skipped_count += 1
                    continue
                
                # Skip if empty metadata
                if not old_metadata or old_metadata == {}:
                    logger.debug("empty_metadata", record_id=record_id)
                    skipped_count += 1
                    continue
                
                # Migrate metadata
                new_metadata = migrate_old_metadata(old_metadata)
                
                logger.info("migrating_record",
                    record_id=record_id,
                    old_keys=list(old_metadata.keys()),
                    new_keys=list(new_metadata.keys()),
                    connector_type=new_metadata.get("connector_type")
                )
                
                if not dry_run:
                    # Update database
                    update_result = supabase.client.table("press_context_units")\
                        .update({"source_metadata": new_metadata})\
                        .eq("id", record_id)\
                        .execute()
                    
                    if update_result.data:
                        migrated_count += 1
                        logger.info("record_migrated", record_id=record_id)
                    else:
                        error_count += 1
                        logger.error("record_update_failed", record_id=record_id)
                else:
                    migrated_count += 1
                    logger.info("record_would_migrate", record_id=record_id)
                
            except Exception as e:
                error_count += 1
                logger.error("record_migration_error",
                    record_id=record.get("id"),
                    error=str(e)
                )
                continue
        
        logger.info("migration_complete",
            total_records=total_records,
            migrated=migrated_count,
            skipped=skipped_count,
            errors=error_count,
            dry_run=dry_run
        )
        
        return {
            "success": True,
            "total_records": total_records,
            "migrated": migrated_count,
            "skipped": skipped_count,
            "errors": error_count
        }
        
    except Exception as e:
        logger.error("migration_failed", error=str(e))
        return {
            "success": False,
            "error": str(e)
        }


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate source_metadata to standard schema"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry run mode (default: True). Use --no-dry-run to execute."
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Execute migration (write to database)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of records to process"
    )
    
    args = parser.parse_args()
    
    logger.info("migration_script_start",
        dry_run=args.dry_run,
        limit=args.limit
    )
    
    if not args.dry_run:
        confirm = input("⚠️  This will MODIFY the database. Continue? (yes/no): ")
        if confirm.lower() != "yes":
            logger.info("migration_cancelled_by_user")
            return
    
    result = await migrate_context_units(
        dry_run=args.dry_run,
        limit=args.limit
    )
    
    if result["success"]:
        print(f"\n✅ Migration {'dry-run' if args.dry_run else 'execution'} completed:")
        print(f"   Total records: {result['total_records']}")
        print(f"   Migrated: {result['migrated']}")
        print(f"   Skipped: {result['skipped']}")
        print(f"   Errors: {result['errors']}")
        
        if args.dry_run:
            print(f"\n💡 To execute migration, run: python migrations/migrate_source_metadata.py --no-dry-run")
    else:
        print(f"\n❌ Migration failed: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
