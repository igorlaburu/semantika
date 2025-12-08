"""
Discovery flow for Pool sources.

Orchestrates:
1. GNews search (24h filter)
2. Random sampling (20%)
3. Origin hunting per domain
4. Press room validation
5. Save to discovered_sources table
"""

import random
from typing import Dict, Any, List
from datetime import datetime

from sources.gnews_client import get_gnews_client
from sources.discovery_connector import get_discovery_connector
from utils.logger import get_logger
from utils.supabase_client import get_supabase_client

logger = get_logger("discovery_flow")


class DiscoveryFlow:
    """Flow for discovering new Pool sources."""
    
    def __init__(self):
        """Initialize discovery flow."""
        self.gnews = get_gnews_client()
        self.discovery = get_discovery_connector()
        self.supabase = get_supabase_client()
        
        logger.info("discovery_flow_initialized")
    
    async def run_discovery(
        self,
        query: str = "España",
        lang: str = "es",
        country: str = "es",
        max_articles: int = 100,
        sample_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Run discovery flow.
        
        Args:
            query: GNews search query
            lang: Language code
            country: Country code
            max_articles: Max articles from GNews
            sample_rate: Sampling rate (0.0-1.0, default 0.05 = 5%)
            
        Returns:
            Discovery result summary
        """
        try:
            logger.info("discovery_flow_start",
                query=query,
                lang=lang,
                max_articles=max_articles,
                sample_rate=sample_rate
            )
            
            # Step 1: Fetch news from GNews (24h)
            articles = await self.gnews.search_news(
                query=query,
                lang=lang,
                country=country,
                max_results=max_articles,
                hours_back=24
            )
            
            if not articles:
                logger.warn("no_articles_found", query=query)
                return {
                    "success": True,
                    "articles_found": 0,
                    "sources_discovered": 0
                }
            
            logger.info("gnews_articles_fetched", count=len(articles))
            
            # Step 2: Sample articles
            sample_size = max(1, int(len(articles) * sample_rate))
            sampled_articles = random.sample(articles, sample_size)
            
            logger.info("articles_sampled",
                total=len(articles),
                sampled=len(sampled_articles)
            )
            
            # Step 3: Search original sources for each headline
            discovered_sources = []
            sources_seen = set()
            
            for article in sampled_articles:
                try:
                    title = article.get("title", "")
                    if not title:
                        continue
                    
                    logger.info("searching_original_source", title=title[:80])
                    
                    # Search original source with LLM (uses SYSTEM org by default)
                    from utils.llm_client import get_llm_client
                    llm = get_llm_client()
                    
                    search_result = await llm.search_original_source(headline=title)
                    
                    found_sources = search_result.get("sources", [])
                    
                    if not found_sources:
                        logger.debug("no_original_source_found", title=title[:80])
                        continue
                    
                    logger.info("original_sources_found",
                        title=title[:80],
                        count=len(found_sources)
                    )
                    
                    # Process each found source
                    for source_info in found_sources:
                        source_url = source_info.get("url", "")
                        source_type = source_info.get("type", "")
                        
                        # Skip if not press_room type
                        if source_type != "press_room":
                            logger.debug("skipping_non_press_room",
                                url=source_url,
                                type=source_type
                            )
                            continue
                        
                        # Skip if already seen
                        if source_url in sources_seen:
                            logger.debug("source_already_processed", url=source_url)
                            continue
                        
                        sources_seen.add(source_url)
                        
                        # Check if already in database
                        existing = self.supabase.client.table("discovered_sources")\
                            .select("source_id")\
                            .eq("url", source_url)\
                            .execute()
                        
                        if existing.data:
                            logger.debug("source_already_in_db", url=source_url)
                            continue
                        
                        # Analyze press room
                        analysis = await self.discovery.analyze_press_room(source_url)
                        
                        if not analysis.get("is_press_room"):
                            logger.debug("not_confirmed_press_room", url=source_url)
                            continue
                        
                        # Only save if confidence > 0.5
                        confidence = analysis.get("confidence", 0.0)
                        if confidence < 0.5:
                            logger.debug("low_confidence_skipped",
                                url=source_url,
                                confidence=confidence
                            )
                            continue
                        
                        # Extract domain for source_code
                        from urllib.parse import urlparse
                        domain = urlparse(source_url).netloc
                        source_code = domain.replace(".", "_").replace("-", "_")
                        
                        # Save to discovered_sources
                        source_data = {
                            "source_name": analysis.get("org_name", source_info.get("organization", domain)),
                            "source_type": "scraping",
                            "source_code": source_code,
                            "url": source_url,
                            "config": {
                                "discovered_from_headline": title,
                                "original_gnews_article": article.get("url"),
                                "llm_search_result": source_info
                            },
                            "schedule_config": {
                                "frequency_minutes": 360  # Every 6h by default
                            },
                            "status": "trial",
                            "relevance_score": confidence,
                            "avg_quality_score": analysis.get("estimated_quality", 0.5),
                            "content_count_7d": 0,
                            "discovered_from": "gnews_llm_search",
                            "discovered_at": datetime.utcnow().isoformat(),
                            "contact_email": analysis.get("contact_email"),
                            "company_id": "pool",
                            "is_active": True
                        }
                        
                        result = self.supabase.client.table("discovered_sources")\
                            .insert(source_data)\
                            .execute()
                        
                        if result.data:
                            discovered_sources.append(result.data[0])
                            logger.info("source_discovered_and_saved",
                                url=source_url,
                                source_name=source_data["source_name"],
                                confidence=confidence,
                                quality=analysis.get("estimated_quality")
                            )
                
                except Exception as e:
                    logger.error("headline_discovery_error",
                        title=article.get("title", "")[:80],
                        error=str(e)
                    )
                    continue
            
            logger.info("discovery_flow_completed",
                articles_found=len(articles),
                articles_sampled=len(sampled_articles),
                sources_discovered=len(discovered_sources)
            )
            
            return {
                "success": True,
                "articles_found": len(articles),
                "articles_sampled": len(sampled_articles),
                "sources_discovered": len(discovered_sources),
                "discovered_sources": discovered_sources
            }
        
        except Exception as e:
            logger.error("discovery_flow_error", error=str(e))
            return {
                "success": False,
                "error": str(e)
            }


async def execute_discovery_job() -> Dict[str, Any]:
    """
    Execute daily discovery job.
    
    Called by scheduler.
    """
    flow = DiscoveryFlow()
    return await flow.run_discovery()
