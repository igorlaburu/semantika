"""LangGraph workflow for intelligent web scraping with change detection.

Workflow nodes:
1. fetch_url - Download HTML content
2. parse_content - Extract title, summary, text
3. detect_changes - Multi-tier change detection
4. extract_date - Multi-source date extraction
5. filter_content - Decide if content should be ingested
6. save_monitored_url - Update monitored_urls table
7. save_url_content - Save to url_content_units
8. ingest_to_context - Create press_context_unit

Supports:
- Index pages (portadas) → article URLs
- Article pages → content extraction
- Multi-noticia detection (one URL, multiple news items)
"""

from typing import Dict, Any, List, Optional, TypedDict
from datetime import datetime
import asyncio

from langgraph.graph import StateGraph, END
from bs4 import BeautifulSoup
import aiohttp

from utils.logger import get_logger
from utils.content_hasher import compute_content_hashes, normalize_html
from utils.change_detector import get_change_detector
from utils.date_extractor import extract_publication_date
from utils.embedding_generator import generate_embedding
from utils.context_unit_saver import save_from_scraping
from utils.supabase_client import get_supabase_client
from utils.llm_client import get_llm_client
from utils.image_extractor import extract_featured_image
from utils.geocoder import geocode_with_context

logger = get_logger("scraper_workflow")


async def auto_cache_featured_image(context_unit_id: str, featured_image: Dict[str, Any]):
    """Auto-cache featured image immediately after context unit creation.
    
    Args:
        context_unit_id: Context unit UUID
        featured_image: Featured image metadata dict
    """
    try:
        from pathlib import Path
        
        image_url = featured_image.get("url")
        if not image_url:
            return
        
        cache_dir = Path("/app/cache/images")
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Download and cache with ordinal suffix format
        timeout = aiohttp.ClientTimeout(total=10)  # Quick timeout for background caching
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; SemantikaScraper/1.0)',
            'Accept': 'image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(image_url, headers=headers) as response:
                if response.status == 200:
                    image_bytes = await response.read()
                    content_type = response.headers.get("Content-Type", "image/jpeg")
                    
                    # Determine extension
                    ext_map = {
                        "image/jpeg": ".jpg",
                        "image/png": ".png", 
                        "image/webp": ".webp",
                        "image/gif": ".gif",
                        "image/bmp": ".bmp"
                    }
                    ext = ext_map.get(content_type, ".jpg")
                    
                    # Cache with ordinal suffix (always _0 for featured images)
                    cache_file = cache_dir / f"{context_unit_id}_0{ext}"
                    cache_file.write_bytes(image_bytes)
                    
                    logger.info("featured_image_auto_cached",
                        context_unit_id=context_unit_id,
                        image_url=image_url,
                        size_bytes=len(image_bytes),
                        cache_path=str(cache_file),
                        extraction_source=featured_image.get("source", "unknown")
                    )
                else:
                    logger.warn("featured_image_auto_cache_failed",
                        context_unit_id=context_unit_id,
                        image_url=image_url,
                        status=response.status
                    )
    except Exception as e:
        logger.warn("featured_image_auto_cache_error",
            context_unit_id=context_unit_id,
            image_url=image_url,
            error=str(e)
        )


# Workflow state
class ScraperState(TypedDict):
    """State for scraper workflow."""
    # Input
    company_id: str
    source_id: str
    url: str
    url_type: str  # 'index' or 'article'
    
    # Fetch stage
    html: Optional[str]
    fetch_error: Optional[str]
    
    # Parse stage
    title: Optional[str]
    summary: Optional[str]
    content_items: List[Dict[str, Any]]  # For multi-noticia
    parse_error: Optional[str]
    
    # Change detection stage
    old_monitored_url: Optional[Dict[str, Any]]
    change_info: Optional[Dict[str, Any]]
    should_process: bool
    
    # Date extraction stage
    published_at: Optional[str]
    date_source: Optional[str]
    date_confidence: Optional[float]
    
    # Save stage
    monitored_url_id: Optional[str]
    url_content_unit_ids: List[str]
    context_unit_ids: List[str]
    
    # Metadata
    workflow_start: str
    workflow_end: Optional[str]
    error: Optional[str]


async def fetch_url(state: ScraperState) -> ScraperState:
    """Fetch URL content (Node 1).
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state with HTML or error
    """
    url = state["url"]
    
    logger.info("fetch_url_start", url=url)
    
    try:
        import ssl
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        ssl_context.set_ciphers('DEFAULT@SECLEVEL=1')
        
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
                }
            ) as response:
                if response.status != 200:
                    error_msg = f"HTTP {response.status}"
                    logger.error("fetch_url_failed", url=url, status=response.status)
                    state["fetch_error"] = error_msg
                    state["error"] = error_msg
                    return state
                
                html = await response.text()
                state["html"] = html
                
                logger.info("fetch_url_success", 
                    url=url, 
                    html_length=len(html)
                )
                
                return state
                
    except asyncio.TimeoutError:
        error_msg = "Timeout fetching URL"
        logger.error("fetch_url_timeout", url=url)
        state["fetch_error"] = error_msg
        state["error"] = error_msg
        return state
        
    except Exception as e:
        error_msg = f"Fetch error: {str(e)}"
        logger.error("fetch_url_error", url=url, error=str(e))
        state["fetch_error"] = error_msg
        state["error"] = error_msg
        return state


async def parse_content(state: ScraperState) -> ScraperState:
    """Parse HTML content and extract items (Node 2).
    
    For articles: Extract single content item
    For index pages: Extract multiple article links
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state with parsed content
    """
    url = state["url"]
    html = state["html"]
    url_type = state["url_type"]
    
    logger.info("parse_content_start", url=url, url_type=url_type)
    
    if not html:
        error_msg = "No HTML to parse"
        logger.error("parse_content_no_html", url=url)
        state["parse_error"] = error_msg
        return state
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        if url_type == "article":
            # Extract single article content
            await parse_article(state, soup)
        else:
            # Extract article links from index
            await parse_index(state, soup)
        
        logger.info("parse_content_success",
            url=url,
            url_type=url_type,
            items_found=len(state.get("content_items", []))
        )
        
        return state
        
    except Exception as e:
        error_msg = f"Parse error: {str(e)}"
        logger.error("parse_content_error", url=url, error=str(e))
        state["parse_error"] = error_msg
        state["error"] = error_msg
        return state


async def parse_article(state: ScraperState, soup: BeautifulSoup):
    """Parse article page content using LLM.
    
    Detects if page contains multiple news items or single article.
    
    Args:
        state: Workflow state
        soup: BeautifulSoup object
    """
    url = state["url"]
    html = state["html"]
    
    # Extract title
    title_tag = soup.find('title')
    page_title = title_tag.get_text(strip=True) if title_tag else "Untitled"
    
    # Extract main content (for hashing/change detection)
    semantic_content_normalized = normalize_html(html)
    
    # Extract full text for LLM (less aggressive cleanup)
    # Remove only scripts, styles, nav, header, footer
    soup_copy = BeautifulSoup(html, 'html.parser')
    for tag in soup_copy(['script', 'style', 'nav', 'header', 'footer', 'aside']):
        tag.decompose()
    full_text_for_llm = soup_copy.get_text(separator=' ', strip=True)
    full_text_for_llm = ' '.join(full_text_for_llm.split())  # Normalize whitespace
    
    # Detect if this is a multi-noticia page (multiple news on same URL)
    # Look for common news containers with stricter heuristics
    news_blocks = soup.find_all(['article', 'div'], class_=lambda c: c and any(
        keyword in str(c).lower() for keyword in ['noticia', 'news', 'post', 'item', 'entry']
    ))
    
    # Filter blocks: Must have minimum content and heading
    valid_blocks = []
    for block in news_blocks:
        block_text = block.get_text(separator=' ', strip=True)
        has_heading = block.find(['h1', 'h2', 'h3', 'h4']) is not None
        has_link = block.find('a', href=True) is not None
        
        # Valid multi-noticia block must:
        # - Have 50-2000 chars (not too short, not full article)
        # - Have a heading tag
        # - Have a link (typical for index pages)
        if 50 <= len(block_text) <= 2000 and has_heading and has_link:
            valid_blocks.append(block)
    
    # Only treat as multi-noticia if we have 3+ valid blocks
    # (2 blocks could be article + sidebar, need 3+ to be confident it's an index)
    if len(valid_blocks) >= 3:
        logger.info("multi_noticia_detected", 
            url=url, 
            blocks_found=len(news_blocks),
            valid_blocks=len(valid_blocks)
        )
        await parse_multi_noticia(state, valid_blocks, soup)
    else:
        # Single article (or false positive multi-noticia)
        if len(news_blocks) > 1:
            logger.debug("multi_noticia_rejected_false_positive",
                url=url,
                blocks_found=len(news_blocks),
                valid_blocks=len(valid_blocks),
                reason="Not enough valid blocks or blocks too large (likely single article)"
            )
        await parse_single_article(state, page_title, semantic_content_normalized, full_text_for_llm)


async def parse_single_article(state: ScraperState, page_title: str, semantic_content_normalized: str, full_text_for_llm: str = None):
    """Parse single article with unified content enricher.
    
    Args:
        state: Workflow state
        page_title: Page title from HTML
        semantic_content_normalized: Normalized content for hashing (may be short)
        full_text_for_llm: Full text for LLM extraction (less aggressive cleanup)
    """
    url = state["url"]
    company_id = state["company_id"]
    
    from utils.unified_content_enricher import enrich_content
    
    # Use full text for LLM if available, otherwise fall back to normalized
    text_for_llm = full_text_for_llm if full_text_for_llm else semantic_content_normalized
    
    # Pre-fill page title if available (fallback for LLM)
    pre_filled = {"title": page_title} if page_title and page_title.strip() else {}
    
    result = await enrich_content(
        raw_text=text_for_llm[:8000],
        source_type="scraping",
        company_id=company_id,
        pre_filled=pre_filled
    )
    
    title = result.get("title", "Sin título")
    atomic_statements = result.get("atomic_statements", [])
    
    # Check if LLM detected no newsworthy content
    NO_CONTENT_MARKERS = [
        "sin contenido noticioso",
        "no news content", 
        "not newsworthy",
        "no relevant content",
        "contenido no relevante"
    ]
    
    # Skip only if:
    # 1. Title is a "no content" marker, OR
    # 2. Content is very short (<100 chars) AND LLM extracted no statements
    # This allows pages with short normalized content but valid LLM extraction
    if title.lower() in NO_CONTENT_MARKERS or (len(semantic_content_normalized.strip()) < 100 and len(atomic_statements) == 0):
        logger.info("article_skipped_no_content",
            url=url,
            title=title,
            normalized_content_length=len(semantic_content_normalized),
            full_text_length=len(text_for_llm),
            statements_extracted=len(atomic_statements),
            enrichment_model=result.get("enrichment_model")
        )
        state["should_process"] = False
        state["title"] = title
        state["summary"] = "Contenido sin interés noticioso"
        state["content_items"] = []
        return
    
    state["title"] = title
    state["summary"] = result.get("summary", "")
    
    # Quality gate: require at least 2 atomic statements
    if len(atomic_statements) < 2:
        logger.info("article_skipped_quality_gate",
            url=url,
            title=title[:50],
            statements_count=len(atomic_statements),
            reason="insufficient_statements"
        )
        state["should_process"] = False
        state["content_items"] = []
        return
    
    # Extract featured image AND geocode (quality gate passed: statements >= 2)
    featured_image = None
    geo_location = None
    
    # Extract featured image
    try:
        soup = BeautifulSoup(state["html"], 'html.parser')
        featured_image = extract_featured_image(soup, url)
        if featured_image:
            logger.debug("featured_image_extracted",
                url=url,
                image_url=featured_image.get("url", "")[:80],
                source=featured_image.get("source")
            )
    except Exception as e:
        logger.warn("featured_image_extraction_failed",
            url=url,
            error=str(e)
        )
    
    # Geocode locations (if LLM extracted any)
    locations = result.get("locations", [])
    if locations:
        try:
            geo_location = await geocode_with_context(locations)
            if geo_location:
                logger.info("location_geocoded",
                    url=url,
                    primary=geo_location.get("primary_name"),
                    lat=geo_location.get("lat"),
                    lon=geo_location.get("lon")
                )
        except Exception as e:
            logger.warn("geocoding_failed",
                url=url,
                locations=locations,
                error=str(e)
            )
    
    state["content_items"] = [{
        "position": 1,
        "title": title,
        "summary": result.get("summary", ""),
        "content": text_for_llm[:8000],
        "tags": result.get("tags", []),
        "category": result.get("category", "general"),
        "atomic_statements": result.get("atomic_statements", []),
        "featured_image": featured_image,
        "geo_location": geo_location
    }]
    
    logger.info("article_parsed",
        url=url,
        title=title[:50],
        category=result.get("category"),
        statements_count=len(result.get("atomic_statements", [])),
        enrichment_model=result.get("enrichment_model", "unknown"),
        has_featured_image=featured_image is not None
    )


async def parse_multi_noticia(state: ScraperState, news_blocks, soup: BeautifulSoup):
    """Parse multiple news items from same page."""
    url = state["url"]
    company_id = state["company_id"]
    llm_client = get_llm_client()
    
    content_items = []
    
    for i, block in enumerate(news_blocks[:10]):  # Limit to 10 news items
        try:
            # Extract text from this block
            block_text = block.get_text(separator=' ', strip=True)
            
            if len(block_text) < 50:  # Skip very short blocks
                continue
            
            # Extract date from this block
            from utils.date_extractor import extract_from_css_selectors, extract_date_from_text
            block_html = str(block)
            block_soup = BeautifulSoup(block_html, 'html.parser')
            
            # Try CSS selectors first (time tags, .date classes)
            dates_found = extract_from_css_selectors(block_soup)
            published_at = None
            date_source = None
            date_confidence = None
            
            if dates_found:
                # Take first (most reliable) date found
                published_at, date_source, date_confidence = dates_found[0]
                logger.debug("multi_noticia_date_from_css",
                    url=url,
                    block_index=i,
                    date=published_at.isoformat(),
                    source=date_source
                )
            else:
                # Fallback: try to extract from text
                extracted_date = extract_date_from_text(block_text)
                if extracted_date:
                    published_at = extracted_date
                    date_source = "text_pattern"
                    date_confidence = 0.70
                    logger.debug("multi_noticia_date_from_text",
                        url=url,
                        block_index=i,
                        date=published_at.isoformat()
                    )
            
            from utils.unified_content_enricher import enrich_content
            
            result = await enrich_content(
                raw_text=block_text[:4000],
                source_type="scraping",
                company_id=company_id,
                pre_filled={}
            )
            
            title = result.get("title", "")
            atomic_statements = result.get("atomic_statements", [])
            
            # Quality gate: require valid title AND at least 2 atomic statements
            if title and title.lower() not in ["sin contenido noticioso", "no news content", ""] and len(atomic_statements) >= 2:
                # Extract featured image after quality gate
                featured_image = None
                if len(atomic_statements) >= 2:
                    try:
                        featured_image = extract_featured_image(block_soup, url)
                    except Exception:
                        pass
                
                content_items.append({
                    "position": len(content_items) + 1,
                    "title": title,
                    "summary": result.get("summary", ""),
                    "content": block_text[:4000],
                    "tags": result.get("tags", []),
                    "category": result.get("category", "general"),
                    "atomic_statements": atomic_statements,
                    "published_at": published_at.isoformat() if published_at else None,
                    "date_source": date_source,
                    "date_confidence": date_confidence,
                    "featured_image": featured_image
                })
                
                logger.debug("news_block_parsed",
                    url=url,
                    position=len(content_items),
                    title=title[:50],
                    category=result.get("category"),
                    statements_count=len(result.get("atomic_statements", [])),
                    published_at=published_at.isoformat() if published_at else "unknown"
                )
            else:
                logger.debug("news_block_skipped_quality_gate",
                    url=url,
                    block_index=i,
                    title=title[:50] if title else "no_title",
                    statements_count=len(atomic_statements),
                    reason="insufficient_statements" if atomic_statements is not None and len(atomic_statements) < 2 else "no_content_marker"
                )
        except Exception as e:
            logger.error("news_block_parse_error", 
                url=url, 
                block_index=i, 
                error=str(e)
            )
            continue
    
    if len(content_items) > 1:
        # Multiple valid news items found
        state["title"] = f"{len(content_items)} noticias de {url}"
        state["summary"] = f"Página con {len(content_items)} noticias"
        state["content_items"] = content_items
        
        logger.info("multi_noticia_parsed",
            url=url,
            items_extracted=len(content_items)
        )
    else:
        # Fallback to single article if 0 or 1 items (likely false positive multi-noticia detection)
        logger.warn("multi_noticia_fallback_to_single", 
            url=url,
            items_found=len(content_items),
            reason="Too few valid items, treating as single article"
        )
        
        # Get page title from soup
        title_tag = soup.find('title')
        page_title = title_tag.get_text(strip=True) if title_tag else "Untitled"
        
        semantic_content = normalize_html(state["html"])
        await parse_single_article(state, page_title, semantic_content)


async def parse_index(state: ScraperState, soup: BeautifulSoup):
    """Parse index page using Groq to extract article links, then scrape them.

    Args:
        state: Workflow state
        soup: BeautifulSoup object
    """
    url = state["url"]
    html = state["html"]
    company_id = state["company_id"]

    logger.info("parse_index_start",
        url=url,
        html_length=len(html),
        company_id=company_id
    )

    # Use Groq to intelligently extract news links
    llm_client = get_llm_client()

    try:
        logger.info("parse_index_calling_extract_news_links", url=url)

        result = await llm_client.extract_news_links(
            html=html,
            base_url=url,
            organization_id=company_id
        )

        logger.info("parse_index_extract_result",
            url=url,
            result_type=type(result).__name__,
            result_keys=list(result.keys()) if isinstance(result, dict) else "not_dict",
            articles_raw_count=len(result.get("articles", [])) if isinstance(result, dict) else 0
        )

        articles = result.get("articles", [])[:10]  # Limit to 10 most recent

        logger.info("index_links_extracted",
            url=url,
            articles_found=len(articles),
            articles_preview=[{
                "title": a.get("title", "")[:50],
                "url": a.get("url", "")[:80]
            } for a in articles[:3]]
        )

        if not articles:
            logger.warn("no_articles_found_in_index",
                url=url,
                result=result
            )
            state["content_items"] = []
            return

        # Now scrape each article in parallel (max 3 concurrent)
        logger.info("parse_index_starting_article_scraping",
            url=url,
            article_count=len(articles)
        )

        content_items = await scrape_articles_from_index(
            articles=articles,
            company_id=company_id,
            max_concurrent=3
        )

        logger.info("parse_index_article_scraping_completed",
            url=url,
            items_scraped=len(content_items)
        )

        state["content_items"] = content_items
        state["title"] = f"{len(content_items)} noticias de índice"
        state["summary"] = f"Extraídas {len(content_items)} noticias del índice"

        logger.info("index_parsed_and_scraped",
            url=url,
            articles_scraped=len(content_items)
        )

    except Exception as e:
        logger.error("parse_index_error",
            url=url,
            error=str(e),
            error_type=type(e).__name__
        )
        import traceback
        logger.error("parse_index_traceback", traceback=traceback.format_exc())
        state["content_items"] = []


async def scrape_articles_from_index(
    articles: List[Dict[str, Any]],
    company_id: str,
    max_concurrent: int = 3
) -> List[Dict[str, Any]]:
    """Scrape multiple articles from index in parallel.
    
    Args:
        articles: List of {"title": "...", "url": "...", "date": "..."}
        company_id: Company UUID
        max_concurrent: Maximum concurrent requests
        
    Returns:
        List of content_items with parsed articles
    """
    import asyncio
    import aiohttp
    from datetime import datetime, timedelta
    from dateutil import parser as date_parser
    
    # Filter articles older than 30 days (generous buffer)
    cutoff_date = datetime.utcnow() - timedelta(days=30)
    articles_filtered = []
    
    for article in articles:
        article_date_str = article.get("date")
        if not article_date_str:
            # No date - REJECT by default (conservative approach)
            # Too risky: could be category pages with mixed old/new content
            logger.debug("article_filtered_no_date",
                url=article.get("url"),
                title=article.get("title", "")[:50],
                reason="LLM could not extract date, rejecting to avoid old content"
            )
            continue
        
        try:
            article_date = date_parser.parse(article_date_str)
            if article_date.tzinfo is None:
                # Assume UTC if no timezone
                article_date = article_date.replace(tzinfo=datetime.now().astimezone().tzinfo)
            
            if article_date.replace(tzinfo=None) >= cutoff_date:
                articles_filtered.append(article)
            else:
                logger.debug("article_filtered_too_old",
                    url=article.get("url"),
                    title=article.get("title", "")[:50],
                    date=article_date_str,
                    age_hours=int((datetime.utcnow() - article_date.replace(tzinfo=None)).total_seconds() / 3600)
                )
        except Exception as e:
            # Date parsing failed - REJECT (conservative approach)
            logger.warn("article_date_parse_failed_rejected",
                url=article.get("url"),
                date_str=article_date_str,
                error=str(e),
                reason="Could not parse date, rejecting to avoid old content"
            )
    
    if len(articles_filtered) < len(articles):
        logger.info("articles_filtered_by_date",
            total=len(articles),
            kept=len(articles_filtered),
            filtered_out=len(articles) - len(articles_filtered)
        )
    
    articles = articles_filtered
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def scrape_one(article: Dict[str, Any], position: int) -> Optional[Dict[str, Any]]:
        """Scrape single article with semaphore."""
        async with semaphore:
            try:
                article_url = article["url"]
                
                logger.debug("scraping_article_from_index",
                    url=article_url,
                    position=position
                )
                
                # Fetch article HTML
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        article_url,
                        timeout=aiohttp.ClientTimeout(total=30),
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; SemantikaScraper/1.0)'}
                    ) as response:
                        if response.status != 200:
                            logger.warn("article_fetch_failed",
                                url=article_url,
                                status=response.status
                            )
                            return None
                        
                        article_html = await response.text()
                
                # Parse with LLM via unified enricher
                from utils.content_hasher import normalize_html
                from utils.unified_content_enricher import enrich_content
                
                semantic_content = normalize_html(article_html)
                
                result = await enrich_content(
                    raw_text=semantic_content,
                    source_type="scraping",
                    company_id=company_id,
                    pre_filled={}
                )
                
                title = result.get("title", "")
                atomic_statements = result.get("atomic_statements", [])
                
                # Quality gate: require valid title AND at least 2 atomic statements
                if not title:
                    logger.warn("article_parse_failed_no_title", 
                        url=article_url,
                        position=position,
                        semantic_content_length=len(semantic_content)
                    )
                    return None
                
                if len(atomic_statements) < 2:
                    logger.info("article_skipped_quality_gate",
                        url=article_url,
                        position=position,
                        title=title[:50],
                        statements_count=len(atomic_statements),
                        reason="insufficient_statements",
                        semantic_content_length=len(semantic_content)
                    )
                    return None
                
                logger.info("article_scraped_from_index_success",
                    url=article_url,
                    position=position,
                    title=title[:50],
                    category=result.get("category"),
                    atomic_count=len(atomic_statements),
                    has_featured_image=False
                )
                
                # Extract featured image after quality gate
                featured_image = None
                if len(atomic_statements) >= 2:
                    try:
                        article_soup = BeautifulSoup(article_html, 'html.parser')
                        featured_image = extract_featured_image(article_soup, article_url)
                    except Exception:
                        pass
                
                # Geocode locations if present
                geo_location = None
                locations = result.get("locations", [])
                if locations and len(atomic_statements) >= 2:
                    try:
                        geo_location = await geocode_with_context(locations)
                        if geo_location:
                            logger.debug("article_geocoded_from_index",
                                url=article_url,
                                primary=geo_location.get("primary_name"),
                                lat=geo_location.get("lat"),
                                lon=geo_location.get("lon")
                            )
                    except Exception as e:
                        logger.warn("article_geocoding_failed_from_index",
                            url=article_url,
                            error=str(e)
                        )
                
                return {
                    "position": position,
                    "title": result.get("title", article.get("title", "Untitled")),
                    "summary": result.get("summary", ""),
                    "content": semantic_content[:8000],
                    "tags": result.get("tags", []),
                    "category": result.get("category", "general"),
                    "atomic_statements": atomic_statements,
                    "source_url": article_url,
                    "index_date": article.get("date"),
                    "featured_image": featured_image,
                    "geo_location": geo_location
                }
                
            except asyncio.TimeoutError:
                logger.error("article_scrape_timeout", 
                    url=article.get("url"),
                    position=position
                )
                return None
            except Exception as e:
                import traceback
                logger.error("article_scrape_error",
                    url=article.get("url"),
                    position=position,
                    error=str(e),
                    error_type=type(e).__name__,
                    traceback=traceback.format_exc()[:500]
                )
                return None
    
    # Scrape all articles in parallel (with semaphore limit)
    tasks = [scrape_one(article, i+1) for i, article in enumerate(articles)]
    results = await asyncio.gather(*tasks)
    
    # Filter out None (failed scrapes)
    content_items = [item for item in results if item is not None]
    
    failed_count = len(articles) - len(content_items)
    logger.info("articles_scraped_from_index_summary",
        total_articles=len(articles),
        successful_scrapes=len(content_items),
        failed_scrapes=failed_count,
        success_rate=f"{(len(content_items)/len(articles)*100):.1f}%" if articles else "0%"
    )
    
    return content_items


async def detect_changes(state: ScraperState) -> ScraperState:
    """Detect changes using multi-tier detection (Node 3).
    
    For multi-noticia pages: Always process to detect new items
    For single articles: Use hash-based change detection
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state with change detection results
    """
    url = state["url"]
    company_id = state["company_id"]
    url_type = state["url_type"]
    
    logger.info("detect_changes_start", url=url, url_type=url_type)
    
    try:
        supabase = get_supabase_client()
        
        # Check if URL already monitored
        result = supabase.client.table("monitored_urls").select(
            "*"
        ).eq("company_id", company_id).eq("url", url).execute()
        
        old_monitored_url = None
        if result.data and len(result.data) > 0:
            old_monitored_url = result.data[0]
            logger.debug("found_existing_monitored_url", 
                url=url, 
                monitored_url_id=old_monitored_url["id"]
            )
        
        state["old_monitored_url"] = old_monitored_url
        
        # Index pages: Check individual scraped articles instead of index HTML
        # Use url_type to detect index pages (not len(content_items) which may be 0-1 after quality gate)
        content_items = state.get("content_items", [])
        
        if url_type == "index":
            # Index page: Check individual scraped articles instead of index HTML
            # Compute hash of index HTML for monitored_urls tracking
            from utils.content_hasher import compute_content_hashes
            new_hash, new_simhash = compute_content_hashes(html=state["html"])
            
            if old_monitored_url:
                # Get existing url_content_units for this monitored_url
                existing_units = supabase.client.table("url_content_units").select(
                    "title, content_hash"
                ).eq("monitored_url_id", old_monitored_url["id"]).execute()
                
                existing_titles = {u["title"] for u in (existing_units.data or [])}
                new_items = [item for item in content_items if item.get("title") not in existing_titles]
                
                logger.info("index_page_change_detection",
                    url=url,
                    total_items_scraped=len(content_items),
                    existing_items=len(existing_titles),
                    new_items=len(new_items)
                )
                
                if new_items:
                    # Process only new items
                    state["content_items"] = new_items
                    state["change_info"] = {
                        "change_type": "new_items",
                        "requires_processing": True,
                        "detection_tier": 1,
                        "new_hash": new_hash,
                        "new_simhash": new_simhash
                    }
                    state["should_process"] = True
                else:
                    # No new items
                    state["change_info"] = {
                        "change_type": "no_new_items",
                        "requires_processing": False,
                        "detection_tier": 1,
                        "new_hash": new_hash,
                        "new_simhash": new_simhash
                    }
                    state["should_process"] = False
            else:
                # New index URL, process all items
                state["change_info"] = {
                    "change_type": "new",
                    "requires_processing": True,
                    "detection_tier": 1,
                    "new_hash": new_hash,
                    "new_simhash": new_simhash
                }
                state["should_process"] = True
        else:
            # Single article: Use standard change detection
            detector = get_change_detector()
            
            change_info = await detector.detect_change(
                old_content=old_monitored_url,
                new_html=state["html"],
                new_title=state.get("title"),
                new_summary=state.get("summary"),
                company_id=company_id,
                url=url
            )
            
            state["change_info"] = change_info
            state["should_process"] = change_info["requires_processing"]
        
        logger.info("detect_changes_completed",
            url=url,
            change_type=state["change_info"]["change_type"],
            should_process=state["should_process"]
        )
        
        return state
        
    except Exception as e:
        logger.error("detect_changes_error", url=url, error=str(e))
        # On error, assume we should process (safer)
        state["should_process"] = True
        state["error"] = f"Change detection error: {str(e)}"
        return state


async def extract_date(state: ScraperState) -> ScraperState:
    """Extract publication date (Node 4).
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state with date info
    """
    url = state["url"]
    html = state["html"]
    title = state.get("title")
    
    logger.info("extract_date_start", url=url)
    
    try:
        date_info = await extract_publication_date(
            html=html,
            url=url,
            title=title,
            use_llm_fallback=True
        )
        
        if date_info["published_at"]:
            state["published_at"] = date_info["published_at"].isoformat()
            state["date_source"] = date_info["date_source"]
            state["date_confidence"] = date_info["date_confidence"]
            
            logger.info("extract_date_success",
                url=url,
                published_at=state["published_at"],
                source=state["date_source"]
            )
        else:
            logger.warn("extract_date_not_found", url=url)
        
        return state
        
    except Exception as e:
        logger.error("extract_date_error", url=url, error=str(e))
        # Continue without date
        return state


async def filter_content(state: ScraperState) -> ScraperState:
    """Filter content - decide if should continue processing (Node 5).
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state
    """
    url = state["url"]
    should_process = state["should_process"]
    
    logger.info("filter_content",
        url=url,
        should_process=should_process,
        change_type=state.get("change_info", {}).get("change_type")
    )
    
    # State already has should_process from change detection
    # This node is mainly for logging and potential future filtering logic
    
    return state


async def save_monitored_url(state: ScraperState) -> ScraperState:
    """Save or update monitored_url (Node 6).
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state with monitored_url_id
    """
    url = state["url"]
    company_id = state["company_id"]
    source_id = state["source_id"]
    
    logger.info("save_monitored_url_start", url=url)
    
    try:
        supabase = get_supabase_client()
        change_info = state.get("change_info", {})
        
        # Determine source_table based on company_id
        # Pool uses discovered_sources, regular clients use sources
        is_pool = company_id == "99999999-9999-9999-9999-999999999999"
        source_table = "discovered_sources" if is_pool else "sources"
        
        monitored_url_data = {
            "company_id": company_id,
            "source_id": source_id,
            "source_table": source_table,
            "url": url,
            "url_type": state["url_type"],
            "title": state.get("title"),
            "semantic_content": normalize_html(state["html"])[:10000],
            "content_hash": change_info.get("new_hash"),
            "simhash": change_info.get("new_simhash"),
            "published_at": state.get("published_at"),
            "date_source": state.get("date_source"),
            "date_confidence": state.get("date_confidence"),
            "last_scraped_at": datetime.utcnow().isoformat(),
            "status": "active",
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Upsert (insert or update)
        old_monitored_url = state.get("old_monitored_url")
        
        if old_monitored_url:
            # Update existing
            result = supabase.client.table("monitored_urls").update(
                monitored_url_data
            ).eq("id", old_monitored_url["id"]).execute()
            
            monitored_url_id = old_monitored_url["id"]
            logger.info("monitored_url_updated", 
                url=url, 
                monitored_url_id=monitored_url_id
            )
        else:
            # Insert new
            monitored_url_data["created_at"] = datetime.utcnow().isoformat()
            
            result = supabase.client.table("monitored_urls").insert(
                monitored_url_data
            ).execute()
            
            if result.data and len(result.data) > 0:
                monitored_url_id = result.data[0]["id"]
                logger.info("monitored_url_created",
                    url=url,
                    monitored_url_id=monitored_url_id
                )
            else:
                raise Exception("No data returned from insert")
        
        state["monitored_url_id"] = monitored_url_id
        
        return state
        
    except Exception as e:
        logger.error("save_monitored_url_error", url=url, error=str(e))
        state["error"] = f"Save monitored URL error: {str(e)}"
        return state


async def save_url_content(state: ScraperState) -> ScraperState:
    """Save url_content_units (Node 7).
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state with url_content_unit_ids
    """
    url = state["url"]
    monitored_url_id = state.get("monitored_url_id")
    
    if not monitored_url_id:
        logger.error("save_url_content_no_monitored_url_id", url=url)
        return state
    
    logger.info("save_url_content_start", 
        url=url, 
        items_count=len(state.get("content_items", []))
    )
    
    try:
        supabase = get_supabase_client()
        company_id = state["company_id"]
        content_items = state.get("content_items", [])
        
        url_content_unit_ids = []
        
        for i, item in enumerate(content_items):
            # Generate embedding for this content unit
            embedding = await generate_embedding(
                title=item.get("title", ""),
                summary=item.get("summary"),
                company_id=company_id
            )
            
            # Compute hashes
            from utils.content_hasher import compute_content_hashes
            content_hash, simhash = compute_content_hashes(
                text=item.get("content", "")
            )
            
            url_content_data = {
                "company_id": company_id,
                "monitored_url_id": monitored_url_id,
                "content_position": i + 1,
                "title": item.get("title", "Untitled"),
                "summary": item.get("summary"),
                "raw_content": item.get("content"),
                "content_hash": content_hash,
                "simhash": simhash,
                "embedding": embedding,
                "published_at": item.get("published_at") or state.get("published_at"),
                "date_source": item.get("date_source") or state.get("date_source"),
                "date_confidence": item.get("date_confidence") or state.get("date_confidence"),
                "status": "active",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            result = supabase.client.table("url_content_units").upsert(
                url_content_data,
                on_conflict="monitored_url_id,content_position"
            ).execute()
            
            if result.data and len(result.data) > 0:
                url_content_unit_id = result.data[0]["id"]
                url_content_unit_ids.append(url_content_unit_id)
                
                logger.debug("url_content_unit_saved",
                    url=url,
                    position=i+1,
                    url_content_unit_id=url_content_unit_id
                )
        
        state["url_content_unit_ids"] = url_content_unit_ids
        
        logger.info("save_url_content_completed",
            url=url,
            units_saved=len(url_content_unit_ids)
        )
        
        return state
        
    except Exception as e:
        logger.error("save_url_content_error", url=url, error=str(e))
        state["error"] = f"Save URL content error: {str(e)}"
        return state


async def ingest_to_context(state: ScraperState) -> ScraperState:
    """Ingest to press_context_units (Node 8).
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state with context_unit_ids
    """
    url = state["url"]
    url_content_unit_ids = state.get("url_content_unit_ids", [])
    
    logger.info("ingest_to_context_start",
        url=url,
        units_count=len(url_content_unit_ids)
    )
    
    try:
        context_unit_ids = []
        content_items = state.get("content_items", [])
        
        for i, url_content_unit_id in enumerate(url_content_unit_ids):
            item = content_items[i] if i < len(content_items) else {}
            
            result = await save_from_scraping(
                company_id=state["company_id"],
                source_id=state["source_id"],
                url_content_unit_id=url_content_unit_id,
                scraping_data={
                    "title": item.get("title", "Untitled"),
                    "summary": item.get("summary"),
                    "content": item.get("content"),
                    "tags": item.get("tags", []),
                    "atomic_statements": item.get("atomic_statements", []),
                    "category": item.get("category"),
                    "url": item.get("source_url", url),
                    "scraped_at": datetime.utcnow().isoformat(),
                    "published_at": item.get("published_at") or item.get("index_date") or state.get("published_at"),
                    "featured_image": item.get("featured_image"),
                    "geo_location": item.get("geo_location")
                }
            )
            
            if result["success"]:
                context_unit_ids.append(result["context_unit_id"])
                logger.debug("context_unit_created",
                    url=url,
                    context_unit_id=result["context_unit_id"]
                )
                
                # Auto-cache featured image if present
                if item.get("featured_image"):
                    await auto_cache_featured_image(
                        result["context_unit_id"],
                        item["featured_image"]
                    )
            elif result["duplicate"]:
                logger.info("context_unit_duplicate_skipped",
                    url=url,
                    duplicate_id=result["duplicate_id"]
                )
        
        state["context_unit_ids"] = context_unit_ids
        
        logger.info("ingest_to_context_completed",
            url=url,
            context_units_created=len(context_unit_ids)
        )
        
        return state
        
    except Exception as e:
        logger.error("ingest_to_context_error", url=url, error=str(e))
        state["error"] = f"Ingest to context error: {str(e)}"
        return state


# Conditional routing
def should_continue_after_fetch(state: ScraperState) -> str:
    """Route after fetch."""
    if state.get("fetch_error"):
        return "end"
    return "parse_content"


def should_continue_after_parse(state: ScraperState) -> str:
    """Route after parse."""
    if state.get("parse_error"):
        return "end"
    return "detect_changes"


def should_continue_after_filter(state: ScraperState) -> str:
    """Route after filter."""
    if not state.get("should_process"):
        # No changes detected, just update monitored_url
        return "save_monitored_url_only"
    return "save_monitored_url"


def should_continue_after_save_monitored(state: ScraperState) -> str:
    """Route after save monitored URL."""
    if state.get("error"):
        return "end"
    
    # If should_process, continue to save content
    if state.get("should_process"):
        return "save_url_content"
    
    return "end"


# Build workflow
def build_scraper_workflow() -> StateGraph:
    """Build LangGraph scraper workflow.
    
    Returns:
        Compiled workflow
    """
    workflow = StateGraph(ScraperState)
    
    # Add nodes
    workflow.add_node("fetch_url", fetch_url)
    workflow.add_node("parse_content", parse_content)
    workflow.add_node("detect_changes", detect_changes)
    workflow.add_node("extract_date", extract_date)
    workflow.add_node("filter_content", filter_content)
    workflow.add_node("save_monitored_url", save_monitored_url)
    workflow.add_node("save_url_content", save_url_content)
    workflow.add_node("ingest_to_context", ingest_to_context)
    
    # Set entry point
    workflow.set_entry_point("fetch_url")
    
    # Add edges
    workflow.add_conditional_edges(
        "fetch_url",
        should_continue_after_fetch,
        {
            "parse_content": "parse_content",
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "parse_content",
        should_continue_after_parse,
        {
            "detect_changes": "detect_changes",
            "end": END
        }
    )
    
    workflow.add_edge("detect_changes", "extract_date")
    workflow.add_edge("extract_date", "filter_content")
    
    workflow.add_conditional_edges(
        "filter_content",
        should_continue_after_filter,
        {
            "save_monitored_url": "save_monitored_url",
            "save_monitored_url_only": "save_monitored_url"
        }
    )
    
    workflow.add_conditional_edges(
        "save_monitored_url",
        should_continue_after_save_monitored,
        {
            "save_url_content": "save_url_content",
            "end": END
        }
    )
    
    workflow.add_edge("save_url_content", "ingest_to_context")
    workflow.add_edge("ingest_to_context", END)
    
    return workflow.compile()


# Main execution function
async def scrape_url(
    company_id: str,
    source_id: str,
    url: str,
    url_type: str = "article"
) -> Dict[str, Any]:
    """Execute scraper workflow for a URL.
    
    Args:
        company_id: Company UUID
        source_id: Source UUID
        url: URL to scrape
        url_type: 'article' or 'index'
        
    Returns:
        Final workflow state
    """
    logger.info("scrape_url_start",
        company_id=company_id,
        source_id=source_id,
        url=url,
        url_type=url_type
    )
    
    # Build workflow
    workflow = build_scraper_workflow()
    
    # Initial state
    initial_state = {
        "company_id": company_id,
        "source_id": source_id,
        "url": url,
        "url_type": url_type,
        "html": None,
        "fetch_error": None,
        "title": None,
        "summary": None,
        "content_items": [],
        "parse_error": None,
        "old_monitored_url": None,
        "change_info": None,
        "should_process": False,
        "published_at": None,
        "date_source": None,
        "date_confidence": None,
        "monitored_url_id": None,
        "url_content_unit_ids": [],
        "context_unit_ids": [],
        "workflow_start": datetime.utcnow().isoformat(),
        "workflow_end": None,
        "error": None
    }
    
    # Run workflow
    try:
        final_state = await workflow.ainvoke(initial_state)
        final_state["workflow_end"] = datetime.utcnow().isoformat()
        
        logger.info("scrape_url_completed",
            url=url,
            context_units_created=len(final_state.get("context_unit_ids", [])),
            error=final_state.get("error")
        )
        
        return final_state
        
    except Exception as e:
        logger.error("scrape_url_workflow_error", url=url, error=str(e))
        return {
            **initial_state,
            "error": str(e),
            "workflow_end": datetime.utcnow().isoformat()
        }
