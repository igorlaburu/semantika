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
        sample_rate: float = 0.2
    ) -> Dict[str, Any]:
        """
        Run discovery flow.
        
        Args:
            query: GNews search query
            lang: Language code
            country: Country code
            max_articles: Max articles from GNews
            sample_rate: Sampling rate (0.0-1.0)
            
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
            
            # Step 3: Extract unique domains
            domains_seen = set()
            articles_by_domain = {}
            
            for article in sampled_articles:
                url = article.get("url", "")
                domain = self.gnews.extract_domain(url)
                
                if domain and domain not in domains_seen:
                    domains_seen.add(domain)
                    articles_by_domain[domain] = article
            
            logger.info("unique_domains_extracted", count=len(domains_seen))
            
            # Step 4: Discover origin for each domain
            discovered_sources = []
            
            for domain, article in articles_by_domain.items():
                try:
                    # Check if domain already exists
                    existing = self.supabase.client.table("discovered_sources")\
                        .select("source_id")\
                        .eq("url", article["url"])\
                        .execute()
                    
                    if existing.data:
                        logger.debug("domain_already_exists", domain=domain)
                        continue
                    
                    # Discover origin
                    origin = await self.discovery.discover_origin(article["url"])
                    
                    if not origin:
                        logger.warn("origin_discovery_failed", domain=domain)
                        continue
                    
                    # Only save if confidence > 0.5
                    if origin.get("confidence", 0) < 0.5:
                        logger.debug("low_confidence_skipped",
                            domain=domain,
                            confidence=origin.get("confidence")
                        )
                        continue
                    
                    # Save to discovered_sources
                    source_data = {
                        "source_name": origin.get("org_name", domain),
                        "source_type": "scraping",
                        "source_code": domain.replace(".", "_"),
                        "url": origin.get("press_room_url", article["url"]),
                        "config": {
                            "original_article": article["url"],
                            "discovered_from_gnews": True,
                            "gnews_query": query
                        },
                        "schedule_config": {
                            "frequency_minutes": 360  # Every 6h by default
                        },
                        "status": "trial",
                        "relevance_score": origin.get("confidence", 0.5),
                        "avg_quality_score": origin.get("estimated_quality", 0.5),
                        "content_count_7d": 0,
                        "discovered_from": "gnews_discovery",
                        "discovered_at": datetime.utcnow().isoformat(),
                        "contact_email": origin.get("contact_email"),
                        "company_id": "pool",
                        "is_active": True
                    }
                    
                    result = self.supabase.client.table("discovered_sources")\
                        .insert(source_data)\
                        .execute()
                    
                    if result.data:
                        discovered_sources.append(result.data[0])
                        logger.info("source_discovered_and_saved",
                            domain=domain,
                            source_name=source_data["source_name"],
                            confidence=origin.get("confidence"),
                            quality=origin.get("estimated_quality")
                        )
                
                except Exception as e:
                    logger.error("domain_discovery_error",
                        domain=domain,
                        error=str(e)
                    )
                    continue
            
            logger.info("discovery_flow_completed",
                articles_found=len(articles),
                domains_analyzed=len(domains_seen),
                sources_discovered=len(discovered_sources)
            )
            
            return {
                "success": True,
                "articles_found": len(articles),
                "articles_sampled": len(sampled_articles),
                "domains_analyzed": len(domains_seen),
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
