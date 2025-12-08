"""
Discovery flow for Pool sources (Auto-discovery system).

PURPOSE:
Automatically discover new press rooms and institutional sources from news headlines.

FULL FLOW:
1. Read active configs from pool_discovery_config table (geographic filters: Álava, Bizkaia, etc.)
2. For each config:
   a. Fetch news from GNews API (last 24h, filtered by area)
   b. Sample 5% of articles randomly
   c. For each sampled headline:
      - Search original source with Groq Compound (web search LLM)
      - Extract INDEX URL from article URL (find /news, /sala-prensa parent page)
      - Analyze press room (validate it's institutional, extract metadata)
      - Save to discovered_sources table with status='trial'

KEY IMPROVEMENTS:
- extract_index_url(): Converts specific article URLs to index/listing URLs
  Example: /events/106714-foo → /events
- Uses Groq Compound for web search (finds original sources before media republishes)
- Geographic filtering via pool_discovery_config table

SCHEDULING:
- Runs every 3 days at 8:00 UTC (see scheduler.py)
- Triggered by: pool_discovery_job()

OUTPUT:
- New entries in discovered_sources table
- Status: 'trial' (needs validation via ingestion quality)

NEXT STEP:
- Ingestion flow scrapes these discovered sources hourly
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
        query: str = None,
        lang: str = None,
        country: str = None,
        max_articles: int = None,
        sample_rate: float = None,
        config_id: str = None
    ) -> Dict[str, Any]:
        """
        Run discovery flow using pool_discovery_config.
        
        Args:
            query: GNews search query (overrides config)
            lang: Language code (overrides config)
            country: Country code (overrides config)
            max_articles: Max articles from GNews (overrides config)
            sample_rate: Sampling rate (overrides config)
            config_id: Specific config to use (default: all active configs)
            
        Returns:
            Discovery result summary
        """
        try:
            # Load active discovery configs from DB
            if config_id:
                configs_result = self.supabase.client.table("pool_discovery_config")\
                    .select("*")\
                    .eq("config_id", config_id)\
                    .eq("is_active", True)\
                    .execute()
            else:
                configs_result = self.supabase.client.table("pool_discovery_config")\
                    .select("*")\
                    .eq("is_active", True)\
                    .order("priority")\
                    .execute()
            
            if not configs_result.data:
                logger.warn("no_active_discovery_configs")
                return {
                    "success": False,
                    "error": "No active discovery configs found"
                }
            
            # Process each config
            total_articles = 0
            total_sampled = 0
            all_discovered_sources = []
            
            for config in configs_result.data:
                # Use config values or overrides
                _query = query or config.get("search_query")
                _lang = lang or config.get("gnews_lang", "es")
                _country = country or config.get("gnews_country", "es")
                _max_articles = max_articles or config.get("max_articles", 100)
                _sample_rate = sample_rate or config.get("sample_rate", 0.05)
                
                logger.info("discovery_flow_start",
                    config_id=config.get("config_id"),
                    geographic_area=config.get("geographic_area"),
                    query=_query,
                    lang=_lang,
                    max_articles=_max_articles,
                    sample_rate=_sample_rate
                )
            
                # Step 1: Fetch news from GNews (24h)
                articles = await self.gnews.search_news(
                    query=_query,
                    lang=_lang,
                    country=_country,
                    max_results=_max_articles,
                    hours_back=24
                )
                
                if not articles:
                    logger.warn("no_articles_found",
                        config_id=config.get("config_id"),
                        query=_query
                    )
                    continue
                
                logger.info("gnews_articles_fetched",
                    config_id=config.get("config_id"),
                    count=len(articles)
                )
                
                total_articles += len(articles)
                
                # Step 2: Sample articles
                sample_size = max(1, int(len(articles) * _sample_rate))
                sampled_articles = random.sample(articles, sample_size)
                
                total_sampled += len(sampled_articles)
                
                logger.info("articles_sampled",
                    config_id=config.get("config_id"),
                    total=len(articles),
                    sampled=len(sampled_articles)
                )
                
                # Get excluded domains from config
                excluded_domains = set(config.get("excluded_domains", []))
                target_types = set(config.get("target_source_types", ["press_room"]))
                
                # Step 3: Search original sources for each headline
                discovered_sources = []
                sources_seen = set()
            
                for article in sampled_articles:
                    try:
                        title = article.get("title", "")
                        article_url = article.get("url", "")
                        if not title:
                            continue
                        
                        # Skip if article is from excluded domain
                        from urllib.parse import urlparse
                        article_domain = urlparse(article_url).netloc
                        if any(excluded in article_domain for excluded in excluded_domains):
                            logger.debug("skipping_excluded_domain",
                                title=title[:80],
                                domain=article_domain
                            )
                            continue
                        
                        logger.info("searching_original_source",
                            config_id=config.get("config_id"),
                            title=title[:80]
                        )
                        
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
                            
                            # Skip if not in target types
                            if source_type not in target_types:
                                logger.debug("skipping_non_target_type",
                                    url=source_url,
                                    type=source_type,
                                    target_types=list(target_types)
                                )
                                continue
                        
                            # Skip if already seen
                            if source_url in sources_seen:
                                logger.debug("source_already_processed", url=source_url)
                                continue
                            
                            sources_seen.add(source_url)
                            
                            # STEP 1: Extract index URL from specific article
                            # The LLM search might return a specific article URL, not the index
                            # Use extract_index_url() to find the parent index/listing page
                            logger.info("extracting_index_url",
                                original_url=source_url[:80]
                            )
                            
                            html_content = await self.discovery.fetch_page(source_url)
                            if not html_content:
                                logger.warn("fetch_failed_for_index_extraction", url=source_url)
                                continue
                            
                            index_result = await self.discovery.extract_index_url(source_url, html_content)
                            index_url = index_result.get("index_url", source_url)
                            index_confidence = index_result.get("confidence", 0.0)
                            
                            logger.info("index_url_found",
                                original_url=source_url[:80],
                                index_url=index_url[:80],
                                confidence=index_confidence,
                                method=index_result.get("method")
                            )
                            
                            # Use index URL from now on
                            final_url = index_url
                            
                            # Check if index already in database
                            existing = self.supabase.client.table("discovered_sources")\
                                .select("source_id")\
                                .eq("url", final_url)\
                                .execute()
                            
                            if existing.data:
                                logger.debug("source_already_in_db", url=final_url)
                                continue
                            
                            # STEP 2: Analyze press room (now with index URL)
                            analysis = await self.discovery.analyze_press_room(final_url)
                            
                            if not analysis.get("is_press_room"):
                                logger.debug("not_confirmed_press_room", url=final_url)
                                continue
                            
                            # Only save if confidence > 0.5
                            confidence = analysis.get("confidence", 0.0)
                            if confidence < 0.5:
                                logger.debug("low_confidence_skipped",
                                    url=final_url,
                                    confidence=confidence
                                )
                                continue
                            
                            # Extract domain for source_code (use final index URL)
                            from urllib.parse import urlparse
                            domain = urlparse(final_url).netloc
                            source_code = domain.replace(".", "_").replace("-", "_")
                            
                            # STEP 3: Save to discovered_sources (with index URL)
                            source_data = {
                                "source_name": analysis.get("org_name", source_info.get("organization", domain)),
                                "source_type": "scraping",
                                "source_code": source_code,
                                "url": final_url,  # Store index URL, not article URL
                                "config": {
                                    "discovered_from_headline": title,
                                    "original_gnews_article": article.get("url"),
                                    "original_source_url": source_url,  # Keep the original article URL
                                    "index_url": final_url,  # The extracted index URL
                                    "index_extraction_method": index_result.get("method"),
                                    "index_extraction_confidence": index_confidence,
                                    "llm_search_result": source_info,
                                    "discovery_config_id": config.get("config_id"),
                                    "geographic_area": config.get("geographic_area")
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
                            "company_id": "00000000-0000-0000-0000-000000000999",  # Pool company UUID
                            "is_active": True
                        }
                        
                        result = self.supabase.client.table("discovered_sources")\
                            .insert(source_data)\
                            .execute()
                        
                            if result.data:
                                discovered_sources.append(result.data[0])
                                all_discovered_sources.append(result.data[0])
                                logger.info("source_discovered_and_saved",
                                    config_id=config.get("config_id"),
                                    index_url=final_url[:80],
                                    original_article_url=source_url[:80],
                                    source_name=source_data["source_name"],
                                    confidence=confidence,
                                    quality=analysis.get("estimated_quality")
                                )
                    
                    except Exception as e:
                        logger.error("headline_discovery_error",
                            config_id=config.get("config_id"),
                            title=article.get("title", "")[:80],
                            error=str(e)
                        )
                        continue
                
                logger.info("config_discovery_completed",
                    config_id=config.get("config_id"),
                    geographic_area=config.get("geographic_area"),
                    articles_found=len(articles),
                    articles_sampled=len(sampled_articles),
                    sources_discovered=len(discovered_sources)
                )
            
            logger.info("discovery_flow_completed",
                configs_processed=len(configs_result.data),
                total_articles=total_articles,
                total_sampled=total_sampled,
                total_sources_discovered=len(all_discovered_sources)
            )
            
            return {
                "success": True,
                "configs_processed": len(configs_result.data),
                "total_articles": total_articles,
                "total_sampled": total_sampled,
                "total_sources_discovered": len(all_discovered_sources),
                "discovered_sources": all_discovered_sources
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
