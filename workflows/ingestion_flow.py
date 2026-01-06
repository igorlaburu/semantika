"""
Ingestion flow for Pool sources (Hourly scraping + Qdrant ingestion).

PURPOSE:
Scrape discovered sources, enrich content, and ingest to shared Pool collection in Qdrant.

FULL FLOW:
1. Get active sources from discovered_sources table (status='trial' or 'active')
2. For each source:
   a. Scrape URL with WebScraper (respects robots.txt, extracts content)
   b. Enrich content with LLM (extract title, summary, category, atomic facts)
   c. Quality gate: Reject if quality_score < 0.4
   d. Ingest to Qdrant Pool collection via pool_client.ingest_to_pool()
   e. Update source stats (content_count_7d, avg_quality_score, last_scraped_at)

KEY ARCHITECTURE:
- Uses WebScraper directly (NO sources table needed - Pool is independent)
- Uses pool_client.py for Qdrant operations (768d embeddings, deduplication)
- Company ID: 99999999-9999-9999-9999-999999999999 (Pool company UUID)
- Qdrant collection: 'pool' (shared across all companies)

QUALITY THRESHOLD:
- Only content with quality_score >= 0.4 is ingested
- Quality score based on: richness, atomic facts count, professional tone

SCHEDULING:
- Runs every hour (see scheduler.py)
- Triggered by: pool_ingestion_job()

OUTPUT:
- New points in Qdrant Pool collection
- Updated stats in discovered_sources table
- Low-quality sources get low avg_quality_score → eventually archived

CONSUMED BY:
- GET /pool/search (search endpoint)
- GET /pool/context/{id} (detail endpoint)
- POST /pool/adopt (companies can adopt Pool content)
"""

from typing import Dict, Any, List
from datetime import datetime, timedelta
import gc

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.unified_context_ingester import ingest_context_unit
from utils.unified_content_enricher import enrich_content
from utils.source_metadata_schema import normalize_source_metadata

logger = get_logger("ingestion_flow")


class IngestionFlow:
    """Flow for ingesting content to Pool."""
    
    def __init__(self):
        """Initialize ingestion flow."""
        self.supabase = get_supabase_client()
        
        logger.info("ingestion_flow_initialized")
    
    async def get_active_sources(self) -> List[Dict[str, Any]]:
        """
        Get active sources from discovered_sources table.
        
        Returns:
            List of active sources
        """
        try:
            result = self.supabase.client.table("discovered_sources")\
                .select("*")\
                .eq("is_active", True)\
                .in_("status", ["trial", "active"])\
                .execute()
            
            sources = result.data or []
            
            logger.info("active_sources_fetched", count=len(sources))
            
            return sources
        
        except Exception as e:
            logger.error("get_active_sources_error", error=str(e))
            return []
    
    async def scrape_source(
        self,
        source: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Scrape a source and extract content items using advanced workflow.
        
        Args:
            source: Source from discovered_sources
            
        Returns:
            List of extracted content items
        """
        try:
            from sources.scraper_workflow import scrape_url
            
            url = source["url"]
            source_id = source["source_id"]
            
            logger.info("scraping_source",
                source_id=source_id,
                url=url
            )
            
            # Use advanced scraper workflow (supports index detection)
            # Start with url_type="index" to extract article links
            result = await scrape_url(
                company_id="99999999-9999-9999-9999-999999999999",
                source_id=source_id,
                url=url,
                url_type="index"  # Treat as index to extract article links
            )
            
            # Extract content items from workflow result
            workflow_items = result.get("content_items", [])
            
            if not workflow_items:
                logger.warn("no_content_extracted",
                    source_id=source_id,
                    url=url
                )
                return []
            
            # Convert workflow format to ingestion format
            content_items = []
            for item in workflow_items:
                item_title = item.get("title", "").strip()
                if not item_title or item_title == "Sin título":
                    item_title = None
                
                content_items.append({
                    "title": item_title,
                    "raw_text": item.get("content", ""),
                    "url": url,
                    "published_at": None,
                    "tags": item.get("tags", []),
                    "category": item.get("category", "general"),
                    "atomic_statements": item.get("atomic_statements", [])
                })
            
            logger.info("source_scraped",
                source_id=source_id,
                items_found=len(content_items)
            )
            
            return content_items
        
        except Exception as e:
            logger.error("scrape_source_error",
                source_id=source.get("source_id"),
                error=str(e)
            )
            return []
    
    async def ingest_item_to_pool(
        self,
        item: Dict[str, Any],
        source: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Ingest content item to Pool.
        
        Args:
            item: Content item from scraper
            source: Source metadata
            
        Returns:
            Ingest result
        """
        try:
            title = item.get("title")
            raw_text = item.get("raw_text", "")
            url = item.get("url", source["url"])
            
            # Check if content is already enriched by scraper_workflow
            # If yes, use it directly to avoid double LLM calls
            # IMPORTANT: Check title is valid (not "Sin título")
            has_valid_title = title and title.strip() and title != "Sin título"
            is_pre_enriched = (
                has_valid_title and
                item.get("tags") and 
                item.get("category") and 
                item.get("atomic_statements") and
                len(item.get("atomic_statements", [])) >= 2
            )
            
            if is_pre_enriched:
                logger.info("using_pre_enriched_content",
                    title=title[:50],
                    source_id=source["source_id"]
                )
                enriched = {
                    "title": title,
                    "summary": item.get("summary", ""),
                    "tags": item.get("tags", []),
                    "category": item.get("category", "general"),
                    "atomic_statements": item.get("atomic_statements", []),
                    "enrichment_cost_usd": 0.0,  # Already enriched
                    "enrichment_model": "scraper_workflow"
                }
            else:
                logger.info("enriching_content",
                    has_partial_data=(title is not None),
                    source_id=source["source_id"]
                )
                
                # Enrich content (tracked under Pool company)
                # Pass valid title if available, otherwise LLM will generate
                pre_filled = {}
                if has_valid_title:
                    pre_filled["title"] = title
                
                enriched = await enrich_content(
                    raw_text=raw_text,
                    source_type="scraping",
                    company_id="99999999-9999-9999-9999-999999999999",
                    pre_filled=pre_filled
                )
            
            # Quality gate: Check both quality_score AND statement count
            quality_score = enriched.get("quality_score", 0.5)
            atomic_statements = enriched.get("atomic_statements", [])
            statement_count = len(atomic_statements)
            
            if quality_score < 0.4:
                logger.info("item_rejected_quality",
                    title=title[:50],
                    quality_score=quality_score
                )
                return {
                    "success": False,
                    "reason": "quality_too_low",
                    "quality_score": quality_score
                }
            
            if statement_count < 2:
                logger.info("item_rejected_statements",
                    title=title[:50],
                    statement_count=statement_count
                )
                return {
                    "success": False,
                    "reason": "insufficient_statements",
                    "statement_count": statement_count
                }
            
            # Normalize metadata to standard schema for pool sources
            metadata = normalize_source_metadata(
                url=url,
                source_name=source["source_name"],
                published_at=item.get("published_at"),
                scraped_at=None,  # Will auto-generate current time
                connector_type="pool_scraping",
                connector_specific={
                    "source_code": source["source_code"],
                    "quality_score": quality_score,
                    "is_pool": True,
                    "ingestion_flow": True
                }
            )
            
            # DEBUG LOG: Track metadata creation
            logger.info("ingestion_flow_metadata_created",
                source_code=source["source_code"],
                url=url,
                has_url_in_metadata=bool(metadata.get("url")),
                metadata_url_preview=metadata.get("url", "NO_URL")[:100],
                connector_type=metadata.get("connector_type"),
                title=title[:50]
            )
            
            # Ingest to PostgreSQL via unified ingester
            pool_company_id = "99999999-9999-9999-9999-999999999999"
            result = await ingest_context_unit(
                company_id=pool_company_id,
                source_id=source["source_id"],
                raw_text=raw_text,
                title=enriched.get("title"),
                summary=enriched.get("summary"),
                category=enriched.get("category"),
                tags=enriched.get("tags", []),
                atomic_statements=enriched.get("atomic_statements", []),
                source_type="scraping",
                source_metadata=metadata
            )
            
            if result.get("success"):
                logger.info("item_ingested_to_pool",
                    title=title[:50],
                    context_unit_id=result.get("context_unit_id"),
                    quality_score=quality_score
                )
            
            return result
        
        except Exception as e:
            logger.error("ingest_item_error",
                title=item.get("title", "")[:50],
                error=str(e)
            )
            return {
                "success": False,
                "reason": "error",
                "error": str(e)
            }
    
    async def update_source_stats(
        self,
        source_id: str,
        items_ingested: int,
        avg_quality: float
    ):
        """
        Update source statistics after ingestion.
        
        Args:
            source_id: Source UUID
            items_ingested: Number of items ingested
            avg_quality: Average quality score
        """
        try:
            # Get current content_count_7d and increment it
            current_result = self.supabase.client.table("discovered_sources")\
                .select("content_count_7d")\
                .eq("source_id", source_id)\
                .execute()
            
            current_count = 0
            if current_result.data:
                current_count = current_result.data[0].get("content_count_7d", 0)
            
            new_count = current_count + items_ingested
            
            # Update stats with incremented content_count_7d
            self.supabase.client.table("discovered_sources")\
                .update({
                    "content_count_7d": new_count,
                    "avg_quality_score": avg_quality,
                    "last_scraped_at": datetime.utcnow().isoformat(),
                    "last_evaluated_at": datetime.utcnow().isoformat()
                })\
                .eq("source_id", source_id)\
                .execute()
            
            logger.info("source_stats_updated",
                source_id=source_id,
                items_ingested=items_ingested,
                new_count=new_count,
                avg_quality=avg_quality
            )
        
        except Exception as e:
            logger.error("update_source_stats_error",
                source_id=source_id,
                error=str(e)
            )
    
    async def run_ingestion(self) -> Dict[str, Any]:
        """
        Run ingestion flow for all active sources.
        
        Returns:
            Ingestion result summary
        """
        try:
            logger.info("ingestion_flow_start")
            
            # Get active sources
            sources = await self.get_active_sources()
            
            if not sources:
                logger.warn("no_active_sources")
                return {
                    "success": True,
                    "sources_processed": 0,
                    "items_ingested": 0
                }
            
            total_items_ingested = 0
            sources_processed = 0
            
            # Process each source
            for source in sources:
                try:
                    source_id = source["source_id"]
                    
                    # Scrape source
                    items = await self.scrape_source(source)
                    
                    if not items:
                        logger.debug("no_items_from_source",
                            source_id=source_id
                        )
                        continue
                    
                    # Ingest each item
                    ingested_count = 0
                    quality_scores = []
                    
                    for item in items:
                        result = await self.ingest_item_to_pool(item, source)
                        
                        if result.get("success"):
                            ingested_count += 1
                            quality_scores.append(result.get("quality_score", 0.5))
                    
                    # Update source stats
                    if ingested_count > 0:
                        avg_quality = sum(quality_scores) / len(quality_scores)
                        await self.update_source_stats(
                            source_id,
                            ingested_count,
                            avg_quality
                        )
                    
                    total_items_ingested += ingested_count
                    sources_processed += 1
                    
                    logger.info("source_processing_completed",
                        source_id=source_id,
                        items_found=len(items),
                        items_ingested=ingested_count
                    )
                    
                    # Force garbage collection after each source to free memory
                    gc.collect()
                
                except Exception as e:
                    logger.error("source_processing_error",
                        source_id=source.get("source_id"),
                        error=str(e)
                    )
                    continue
            
            logger.info("ingestion_flow_completed",
                sources_processed=sources_processed,
                items_ingested=total_items_ingested
            )
            
            # Final garbage collection
            gc.collect()
            
            return {
                "success": True,
                "sources_processed": sources_processed,
                "items_ingested": total_items_ingested
            }
        
        except Exception as e:
            logger.error("ingestion_flow_error", error=str(e))
            return {
                "success": False,
                "error": str(e)
            }


async def reset_weekly_counters():
    """
    Reset content_count_7d counters weekly (every Monday at 00:00 UTC).
    
    Called by scheduler.
    """
    try:
        logger.info("resetting_weekly_counters")
        
        supabase = get_supabase_client()
        
        # Reset all content_count_7d to 0
        result = supabase.client.table("discovered_sources")\
            .update({"content_count_7d": 0})\
            .eq("company_id", "99999999-9999-9999-9999-999999999999")\
            .execute()
        
        reset_count = len(result.data) if result.data else 0
        
        logger.info("weekly_counters_reset", sources_reset=reset_count)
        
        return {
            "success": True,
            "sources_reset": reset_count
        }
    
    except Exception as e:
        logger.error("reset_weekly_counters_error", error=str(e))
        return {"success": False, "error": str(e)}


async def execute_ingestion_job() -> Dict[str, Any]:
    """
    Execute hourly ingestion job.
    
    Called by scheduler.
    """
    flow = IngestionFlow()
    return await flow.run_ingestion()
