"""
Ingestion flow for Pool sources.

Orchestrates:
1. Get active sources from discovered_sources
2. Scrape each source
3. Quality gate (threshold 0.4)
4. Ingest to Pool (Qdrant)
5. Update source stats
"""

from typing import Dict, Any, List
from datetime import datetime, timedelta

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.pool_client import get_pool_client
from utils.unified_content_enricher import enrich_content
from sources.web_scraper import WebScraper

logger = get_logger("ingestion_flow")


class IngestionFlow:
    """Flow for ingesting content to Pool."""
    
    def __init__(self):
        """Initialize ingestion flow."""
        self.supabase = get_supabase_client()
        self.pool = get_pool_client()
        self.scraper = WebScraper()
        
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
        Scrape a source and extract content items.
        
        Args:
            source: Source from discovered_sources
            
        Returns:
            List of extracted content items
        """
        try:
            url = source["url"]
            source_id = source["source_id"]
            
            logger.info("scraping_source",
                source_id=source_id,
                url=url
            )
            
            # Use WebScraper directly (no need for sources table)
            # Try to scrape as single article first
            documents = await self.scraper.scrape_url(
                url=url,
                extract_multiple=False,
                check_robots=True
            )
            
            if not documents:
                logger.warn("no_content_extracted",
                    source_id=source_id,
                    url=url
                )
                return []
            
            # Convert to content items format
            content_items = []
            for doc in documents:
                content_items.append({
                    "title": doc.get("title", "Untitled"),
                    "raw_text": doc.get("text", ""),
                    "url": url,
                    "published_at": None  # Will be extracted by enricher if possible
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
            title = item.get("title", "Untitled")
            raw_text = item.get("raw_text", "")
            url = item.get("url", source["url"])
            
            logger.info("enriching_content",
                title=title[:50],
                source_id=source["source_id"]
            )
            
            # Enrich content with SYSTEM org for tracking
            enriched = await enrich_content(
                raw_text=raw_text,
                source_type="scraping",
                company_id="00000000-0000-0000-0000-000000000999",  # Pool company UUID
                organization_id="88044361-8529-46c8-8196-d1345ca7bbe8",  # SYSTEM org UUID
                pre_filled={
                    "title": title
                }
            )
            
            # Check quality threshold
            quality_score = enriched.get("quality_score", 0.5)
            
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
            
            # Ingest to Pool
            result = await self.pool.ingest_to_pool(
                title=enriched["title"],
                content=raw_text,
                url=url,
                source_id=source["source_id"],
                quality_score=quality_score,
                category=enriched.get("category"),
                tags=enriched.get("tags", []),
                published_at=item.get("published_at"),
                atomic_statements=enriched.get("atomic_statements", []),
                metadata={
                    "source_name": source["source_name"],
                    "source_code": source["source_code"],
                    "enrichment_model": enriched.get("enrichment_model"),
                    "enrichment_cost_usd": enriched.get("enrichment_cost_usd")
                }
            )
            
            if result.get("success"):
                logger.info("item_ingested_to_pool",
                    title=title[:50],
                    point_id=result.get("point_id"),
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
            # Update stats
            self.supabase.client.table("discovered_sources")\
                .update({
                    "content_count_7d": items_ingested,
                    "avg_quality_score": avg_quality,
                    "last_scraped_at": datetime.utcnow().isoformat(),
                    "last_evaluated_at": datetime.utcnow().isoformat()
                })\
                .eq("source_id", source_id)\
                .execute()
            
            logger.info("source_stats_updated",
                source_id=source_id,
                items_ingested=items_ingested,
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


async def execute_ingestion_job() -> Dict[str, Any]:
    """
    Execute hourly ingestion job.
    
    Called by scheduler.
    """
    flow = IngestionFlow()
    return await flow.run_ingestion()
