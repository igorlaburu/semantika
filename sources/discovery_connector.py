"""
Discovery connector for Pool source hunting.

Analyzes GNews articles to discover their origin sources (press rooms, blogs, etc.)
"""

import aiohttp
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from utils.logger import get_logger
from utils.llm_client import get_llm_client

logger = get_logger("discovery_connector")


class DiscoveryConnector:
    """Connector for discovering news sources."""
    
    def __init__(self):
        """Initialize discovery connector."""
        self.llm = get_llm_client()
        self.user_agent = "semantika-discovery-bot/0.1.0"
        
        logger.info("discovery_connector_initialized")
    
    def extract_domain(self, url: str) -> Optional[str]:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except Exception as e:
            logger.error("domain_extraction_error", url=url, error=str(e))
            return None
    
    async def fetch_page(self, url: str) -> Optional[str]:
        """Fetch page content."""
        try:
            headers = {"User-Agent": self.user_agent}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True
                ) as response:
                    
                    if response.status != 200:
                        logger.warn("fetch_failed",
                            url=url,
                            status=response.status
                        )
                        return None
                    
                    content = await response.text()
                    return content
        
        except Exception as e:
            logger.error("fetch_error", url=url, error=str(e))
            return None
    
    async def analyze_press_room(self, url: str, html_content: str) -> Dict[str, Any]:
        """
        Analyze if URL is a press room and extract metadata.
        
        Args:
            url: Source URL
            html_content: HTML content
            
        Returns:
            Analysis result with is_press_room, press_room_url, etc.
        """
        try:
            soup = BeautifulSoup(html_content, "lxml")
            
            # Remove noise
            for element in soup(["script", "style", "nav", "footer"]):
                element.decompose()
            
            # Get visible text
            text = soup.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            text_sample = "\n".join(lines[:100])  # First 100 lines
            
            # Get title
            title = soup.title.string if soup.title else ""
            
            # Look for press/media links
            press_links = []
            for link in soup.find_all("a", href=True):
                href = link.get("href", "").lower()
                text = link.get_text().lower()
                
                if any(keyword in href or keyword in text for keyword in [
                    "prensa", "press", "sala-prensa", "press-room",
                    "media", "noticias", "news", "comunicados"
                ]):
                    press_links.append(link.get("href"))
            
            # Analyze with LLM
            prompt = f"""Analiza esta página web y determina:

1. ¿Es una sala de prensa / press room / blog de organización?
2. ¿Publica noticias o comunicados regularmente?
3. ¿Cuál es el nombre de la organización?
4. ¿Tiene un email de contacto visible?
5. Calidad estimada (0.0-1.0) basada en:
   - Frecuencia aparente de publicación
   - Profesionalidad del diseño
   - Relevancia del contenido

URL: {url}
Título: {title}
Enlaces relacionados: {press_links[:5]}

Muestra de texto:
{text_sample[:1000]}

Responde en JSON:
{{
    "is_press_room": true/false,
    "confidence": 0.0-1.0,
    "org_name": "Nombre organización",
    "press_room_url": "URL sala prensa si es diferente",
    "contact_email": "email@example.com o null",
    "estimated_quality": 0.0-1.0,
    "notes": "Breve justificación"
}}"""

            analysis = await self.llm.analyze_atomic(
                text=prompt,
                fast_mode=True
            )
            
            logger.info("press_room_analyzed",
                url=url,
                is_press_room=analysis.get("is_press_room"),
                confidence=analysis.get("confidence")
            )
            
            return analysis
        
        except Exception as e:
            logger.error("press_room_analysis_error", url=url, error=str(e))
            return {
                "is_press_room": False,
                "confidence": 0.0,
                "error": str(e)
            }
    
    async def discover_origin(self, article_url: str) -> Optional[Dict[str, Any]]:
        """
        Discover the origin source of an article.
        
        Args:
            article_url: URL of the article
            
        Returns:
            Discovery result with source metadata
        """
        try:
            logger.info("discovering_origin", url=article_url)
            
            # Fetch article page
            content = await self.fetch_page(article_url)
            if not content:
                return None
            
            # Extract domain
            domain = self.extract_domain(article_url)
            if not domain:
                return None
            
            # Try to find press room URL
            base_url = f"{urlparse(article_url).scheme}://{domain}"
            
            # Common press room paths
            press_paths = [
                "/sala-prensa",
                "/prensa",
                "/press",
                "/press-room",
                "/noticias",
                "/news",
                "/comunicados",
                "/blog"
            ]
            
            # Try each path
            press_room_url = None
            press_room_content = None
            
            for path in press_paths:
                test_url = base_url + path
                test_content = await self.fetch_page(test_url)
                
                if test_content:
                    # Quick check if it looks like press room
                    if any(keyword in test_content.lower() for keyword in [
                        "comunicado", "nota de prensa", "press release"
                    ]):
                        press_room_url = test_url
                        press_room_content = test_content
                        break
            
            # If no press room found, use base URL
            if not press_room_url:
                press_room_url = base_url
                press_room_content = content
            
            # Analyze press room
            analysis = await self.analyze_press_room(
                press_room_url,
                press_room_content
            )
            
            # Build result
            result = {
                "article_url": article_url,
                "domain": domain,
                "press_room_url": press_room_url,
                "is_press_room": analysis.get("is_press_room", False),
                "confidence": analysis.get("confidence", 0.0),
                "org_name": analysis.get("org_name"),
                "contact_email": analysis.get("contact_email"),
                "estimated_quality": analysis.get("estimated_quality", 0.5),
                "notes": analysis.get("notes", "")
            }
            
            logger.info("origin_discovered",
                article_url=article_url,
                press_room_url=press_room_url,
                is_press_room=result["is_press_room"],
                confidence=result["confidence"]
            )
            
            return result
        
        except Exception as e:
            logger.error("discover_origin_error",
                url=article_url,
                error=str(e)
            )
            return None


def get_discovery_connector() -> DiscoveryConnector:
    """Get discovery connector instance."""
    return DiscoveryConnector()
