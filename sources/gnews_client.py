"""
GNews client for Pool discovery.

Fetches news from GNews API for discovering new content sources.
"""

import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from utils.logger import get_logger
from utils.config import settings

logger = get_logger("gnews_client")


class GNewsClient:
    """Client for GNews API."""
    
    def __init__(self, api_key: str):
        """
        Initialize GNews client.
        
        Args:
            api_key: GNews API key
        """
        self.api_key = api_key
        self.api_url = "https://gnews.io/api/v4/search"
        
        logger.info("gnews_client_initialized")
    
    async def search_news(
        self,
        query: str = "España",
        lang: str = "es",
        country: str = "es",
        max_results: int = 100,
        hours_back: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Search news from GNews API.
        
        Args:
            query: Search query
            lang: Language code (es, eu, etc.)
            country: Country code (es)
            max_results: Max articles to fetch
            hours_back: Hours to look back (default 24h)
            
        Returns:
            List of news articles
        """
        try:
            # Calculate date range
            to_date = datetime.utcnow()
            from_date = to_date - timedelta(hours=hours_back)
            
            # Format dates for GNews (ISO format)
            from_str = from_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            to_str = to_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            params = {
                "q": query,
                "lang": lang,
                "country": country,
                "max": max_results,
                "from": from_str,
                "to": to_str,
                "apikey": self.api_key
            }
            
            logger.info("gnews_search_start",
                query=query,
                lang=lang,
                country=country,
                max_results=max_results,
                hours_back=hours_back
            )
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error("gnews_api_error",
                            status=response.status,
                            error=error_text
                        )
                        return []
                    
                    data = await response.json()
                    articles = data.get("articles", [])
                    
                    logger.info("gnews_search_completed",
                        query=query,
                        articles_found=len(articles)
                    )
                    
                    return articles
        
        except Exception as e:
            logger.error("gnews_search_error", query=query, error=str(e))
            return []
    
    def extract_domain(self, url: str) -> Optional[str]:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc
        except Exception as e:
            logger.error("domain_extraction_error", url=url, error=str(e))
            return None


def get_gnews_client() -> GNewsClient:
    """Get GNews client with configured API key."""
    api_key = settings.gnews_api_key
    if not api_key:
        raise ValueError("GNEWS_API_KEY not configured")
    return GNewsClient(api_key)
