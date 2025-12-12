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
    """
    Connector for discovering news sources (Pool system).
    
    Main functions:
    1. extract_index_url() - Find press room index page from specific article URL
    2. analyze_press_room() - Validate if URL is a press room and extract metadata
    
    Used by: workflows/discovery_flow.py
    """
    
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
    
    async def extract_index_url(self, url: str, html_content: str) -> Dict[str, Any]:
        """
        Extract press room index URL from a specific news article page.
        
        Strategy: 
        1. Heuristic URL pattern matching (fast, reliable)
        2. HTML breadcrumb/nav parsing
        3. LLM analysis (fallback)
        
        Args:
            url: Current article URL
            html_content: Full HTML of the page
            
        Returns:
            Dict with:
            - index_url: URL of the index/listing page
            - confidence: 0.0-1.0
            - method: how it was found (url_pattern, breadcrumb_link, navigation_link, llm_inference)
        """
        try:
            from urllib.parse import urlparse, urljoin
            import re
            
            parsed = urlparse(url)
            path = parsed.path
            
            # STEP 1: Heuristic URL pattern matching
            # Remove trailing article ID/slug from common patterns
            index_patterns = [
                (r'(/noticias?|/news|/actualidad|/comunicados?|/sala-prensa|/press|/eventos?|/events)/[^/]+$', r'\1'),
                (r'(/\d{4}/\d{2}/\d{2}/.+)$', lambda m: '/'.join(m.group(1).split('/')[:4])),  # /2024/12/12/article -> /2024/12/12
                (r'/[0-9]+-[a-z0-9-]+$', ''),  # /1721-ambulancias-100... -> remove
                (r'/\d+$', ''),  # /12345 -> remove
            ]
            
            for pattern, replacement in index_patterns:
                if isinstance(replacement, str):
                    match = re.search(pattern, path, re.IGNORECASE)
                    if match:
                        new_path = re.sub(pattern, replacement, path, flags=re.IGNORECASE)
                        index_url = f"{parsed.scheme}://{parsed.netloc}{new_path}"
                        
                        logger.info("index_url_heuristic_match",
                            original_url=url[:80],
                            index_url=index_url[:80],
                            pattern=pattern
                        )
                        
                        return {
                            "index_url": index_url,
                            "confidence": 0.85,
                            "method": "url_pattern"
                        }
            
            # STEP 2: Parse HTML for breadcrumbs and navigation
            soup = BeautifulSoup(html_content, "lxml")
            
            # Look for breadcrumb links
            breadcrumbs = soup.find_all(['nav', 'ol', 'ul'], class_=re.compile(r'breadcrumb|miga', re.I))
            for bc in breadcrumbs:
                links = bc.find_all('a', href=True)
                for link in reversed(links):  # Start from last breadcrumb (closest parent)
                    href = link.get('href', '')
                    text = link.get_text().strip().lower()
                    
                    # Skip homepage and generic links
                    if text in ['inicio', 'home', 'portada'] or href in ['/', '#']:
                        continue
                    
                    # Look for news/press keywords
                    if any(kw in text or kw in href.lower() for kw in [
                        'noticia', 'news', 'actualidad', 'comunicado', 'prensa', 'press', 'evento', 'event'
                    ]):
                        index_url = urljoin(url, href)
                        
                        logger.info("index_url_breadcrumb_found",
                            original_url=url[:80],
                            index_url=index_url[:80],
                            breadcrumb_text=text[:30]
                        )
                        
                        return {
                            "index_url": index_url,
                            "confidence": 0.9,
                            "method": "breadcrumb_link"
                        }
            
            # STEP 3: LLM fallback (only if heuristics failed)
            # Remove noise but keep navigation structure and links
            for element in soup(["script", "style", "svg", "img"]):
                element.decompose()
            
            # Get clean HTML (first 12000 chars for better context)
            clean_html = str(soup)[:12000]
            
            prompt = f"""Analiza este HTML y encuentra la URL del ÍNDICE/LISTADO de noticias (no la homepage).

URL actual: {url}

HTML (navegación y links):
{clean_html}

CRITERIOS ESTRICTOS:
1. DEBE ser un listado de noticias/eventos (no homepage, no contacto, no about)
2. Busca en nav/breadcrumbs links con keywords: noticias, news, actualidad, comunicados, eventos, prensa
3. Si encuentras link claro → úsalo (confidence 0.8+)
4. Si NO hay link → infiere quitando slug final de URL (confidence 0.6)

NUNCA devuelvas la homepage (/, /es, /inicio) como index_url.

Ejemplos CORRECTOS:
- URL: https://esk.eus/.../1721-ambulancias → Index: https://esk.eus/osakidetza/index.php/es/noticias-de-los-centros-de-trabajo
- URL: https://ayala.eus/noticias/evento-123 → Index: https://ayala.eus/noticias

Ejemplos INCORRECTOS:
- ❌ index_url: https://ayala.eus/ (es homepage, no listado)
- ❌ index_url: https://ayala.eus/contacto

Responde SOLO JSON:
{{
    "index_url": "https://...",
    "confidence": 0.8,
    "method": "navigation_link"
}}"""
            
            # Get SYSTEM organization ID for tracking
            from utils.llm_registry import get_llm_registry
            from utils.supabase_client import get_supabase_client
            import json
            
            supabase = get_supabase_client()
            system_org = supabase.client.table('organizations')\
                .select('id')\
                .eq('slug', 'system')\
                .execute()
            
            organization_id = system_org.data[0]['id'] if system_org.data else None
            
            registry = get_llm_registry()
            provider = registry.get('groq_fast')
            
            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'extract_index_url'
                }
            
            response = await provider.ainvoke(prompt, config=config)
            
            # Clean and parse response
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Extract JSON
            json_start = content.find('{')
            json_end = content.rfind('}')
            
            if json_start == -1 or json_end == -1:
                logger.error("extract_index_no_json", url=url)
                return {
                    "index_url": url,  # Fallback to original
                    "confidence": 0.3,
                    "method": "fallback"
                }
            
            content = content[json_start:json_end+1]
            result = json.loads(content)
            
            # Validate LLM result: reject homepage URLs
            index_url = result.get("index_url", url)
            index_parsed = urlparse(index_url)
            
            # Check if it's just a homepage
            if index_parsed.path in ['/', '/es', '/eu', '/en', '/inicio', '/home', '']:
                logger.warn("index_url_is_homepage_rejected",
                    original_url=url[:80],
                    llm_returned=index_url[:80],
                    fallback_to="url_inference"
                )
                
                # Fallback: smart URL trimming
                path_parts = [p for p in parsed.path.split('/') if p]
                if len(path_parts) >= 2:
                    # Keep first meaningful segment (e.g., /noticias, /actualidad)
                    trimmed_path = '/' + '/'.join(path_parts[:-1])
                    index_url = f"{parsed.scheme}://{parsed.netloc}{trimmed_path}"
                    result = {
                        "index_url": index_url,
                        "confidence": 0.5,
                        "method": "url_inference_fallback"
                    }
                else:
                    # Can't infer, return original
                    result = {
                        "index_url": url,
                        "confidence": 0.3,
                        "method": "no_index_found"
                    }
            
            logger.info("index_url_extracted",
                original_url=url[:80],
                index_url=result.get("index_url", "")[:80],
                confidence=result.get("confidence"),
                method=result.get("method")
            )
            
            return result
        
        except Exception as e:
            logger.error("extract_index_url_error", url=url, error=str(e))
            return {
                "index_url": url,  # Fallback to original
                "confidence": 0.0,
                "method": "error",
                "error": str(e)
            }
    
    async def analyze_press_room(self, url: str) -> Dict[str, Any]:
        """
        Analyze if URL is a press room and extract metadata.
        
        IMPORTANT: This should receive an INDEX page URL (e.g., /news, /sala-prensa)
        not a specific article URL. Use extract_index_url() first if needed.
        
        Args:
            url: Press room index URL to analyze
            
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
            from utils.supabase_client import get_supabase_client
            import json
            
            # Get SYSTEM organization ID
            supabase = get_supabase_client()
            system_org = supabase.client.table('organizations')\
                .select('id')\
                .eq('slug', 'system')\
                .execute()
            
            organization_id = None
            if system_org.data:
                organization_id = system_org.data[0]['id']
            else:
                logger.warn("system_org_not_found", message="SYSTEM org not found, skipping tracking")
            
            registry = get_llm_registry()
            provider = registry.get('groq_fast')
            
            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'analyze_press_room'
                }
            
            response = await provider.ainvoke(prompt, config=config)
            
            # Clean markdown and extract JSON
            content = response.content.strip()
            
            logger.debug("press_room_raw_response",
                url=url,
                content_preview=content[:300]
            )
            
            # Remove markdown code blocks
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Handle cases where LLM returns text before JSON
            # Look for first { and last }
            json_start = content.find('{')
            json_end = content.rfind('}')
            
            if json_start == -1 or json_end == -1:
                logger.error("press_room_no_json_found",
                    url=url,
                    content=content[:500]
                )
                return {
                    "is_press_room": False,
                    "confidence": 0.0,
                    "error": "No JSON found in response"
                }
            
            content = content[json_start:json_end+1]
            
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
