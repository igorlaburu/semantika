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
    
    async def analyze_press_room(self, url: str) -> Dict[str, Any]:
        """
        Analyze if URL is a press room and extract metadata.
        
        Args:
            url: Source URL to analyze
            
        Returns:
            Analysis result with is_press_room, confidence, org_name, etc.
        """
        try:
            # Fetch page
            html_content = await self.fetch_page(url)
            if not html_content:
                return {
                    "is_press_room": False,
                    "confidence": 0.0,
                    "error": "Failed to fetch page"
                }
            
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
                link_text = link.get_text().lower()
                
                if any(keyword in href or keyword in link_text for keyword in [
                    "prensa", "press", "sala-prensa", "press-room",
                    "media", "noticias", "news", "comunicados"
                ]):
                    press_links.append(link.get("href"))
            
            # Analyze with LLM using groq_fast directly
            prompt = f"""Analiza esta página web y determina:

1. ¿Es una sala de prensa / press room / comunicados de organización pública?
2. ¿Publica noticias o comunicados regularmente?
3. ¿Cuál es el nombre de la organización?
4. ¿Tiene un email de contacto visible?
5. Calidad estimada (0.0-1.0) basada en frecuencia de publicación y profesionalidad

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
    "contact_email": "email@example.com o null",
    "estimated_quality": 0.0-1.0,
    "notes": "Breve justificación"
}}"""

            # Call groq_fast directly
            from utils.llm_registry import get_llm_registry
            import json
            
            registry = get_llm_registry()
            provider = registry.get('groq_fast')
            
            config = {
                'tracking': {
                    'organization_id': 'SYSTEM-POOL',
                    'operation': 'analyze_press_room'
                }
            }
            
            response = await provider.ainvoke(prompt, config=config)
            
            # Clean markdown
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            analysis = json.loads(content)
            
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
    


def get_discovery_connector() -> DiscoveryConnector:
    """Get discovery connector instance."""
    return DiscoveryConnector()
