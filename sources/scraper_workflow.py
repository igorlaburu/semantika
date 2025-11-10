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

logger = get_logger("scraper_workflow")


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
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; SemantikaScraper/1.0)'
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
    
    Args:
        state: Workflow state
        soup: BeautifulSoup object
    """
    url = state["url"]
    html = state["html"]
    
    # Extract title
    title_tag = soup.find('title')
    title = title_tag.get_text(strip=True) if title_tag else "Untitled"
    
    # Extract main content
    semantic_content = normalize_html(html)
    
    # Use LLM to extract structured content
    llm_client = get_llm_client()
    
    try:
        # Use analyze_atomic to get title, summary, and atomic facts
        result = await llm_client.analyze_atomic(
            text=semantic_content[:8000],
            organization_id=state["company_id"]
        )
        
        state["title"] = result.get("title", title)
        state["summary"] = result.get("summary", "")
        
        # Single content item for article
        state["content_items"] = [{
            "position": 1,
            "title": result.get("title", title),
            "summary": result.get("summary", ""),
            "content": semantic_content[:8000],
            "tags": result.get("tags", []),
            "atomic_statements": result.get("atomic_facts", [])
        }]
        
        logger.debug("article_parsed_with_llm",
            url=url,
            title=state["title"][:50]
        )
        
    except Exception as e:
        logger.error("llm_parse_failed_using_fallback", url=url, error=str(e))
        
        # Fallback: basic extraction
        state["title"] = title
        state["summary"] = semantic_content[:500]
        state["content_items"] = [{
            "position": 1,
            "title": title,
            "summary": semantic_content[:500],
            "content": semantic_content[:8000],
            "tags": [],
            "atomic_statements": []
        }]


async def parse_index(state: ScraperState, soup: BeautifulSoup):
    """Parse index page to extract article links.
    
    Args:
        state: Workflow state
        soup: BeautifulSoup object
    """
    url = state["url"]
    
    # Extract all links
    links = soup.find_all('a', href=True)
    
    # Filter for article links (heuristic)
    article_links = []
    for link in links:
        href = link['href']
        
        # Make absolute URL
        from urllib.parse import urljoin
        absolute_url = urljoin(url, href)
        
        # Filter out navigation, social, etc.
        if any(skip in absolute_url.lower() for skip in [
            'facebook.com', 'twitter.com', 'instagram.com',
            'mailto:', 'javascript:', '#'
        ]):
            continue
        
        # Get link text
        link_text = link.get_text(strip=True)
        
        if link_text and len(link_text) > 10:  # Meaningful link text
            article_links.append({
                "url": absolute_url,
                "title": link_text
            })
    
    # Remove duplicates
    seen_urls = set()
    unique_links = []
    for link in article_links:
        if link["url"] not in seen_urls:
            seen_urls.add(link["url"])
            unique_links.append(link)
    
    # Store as content items (to be processed separately)
    state["content_items"] = unique_links[:50]  # Limit to 50 links
    
    logger.info("index_parsed",
        url=url,
        total_links=len(article_links),
        unique_links=len(unique_links)
    )


async def detect_changes(state: ScraperState) -> ScraperState:
    """Detect changes using multi-tier detection (Node 3).
    
    Args:
        state: Workflow state
        
    Returns:
        Updated state with change detection results
    """
    url = state["url"]
    company_id = state["company_id"]
    
    logger.info("detect_changes_start", url=url)
    
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
        
        # Detect changes
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
            change_type=change_info["change_type"],
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
        
        monitored_url_data = {
            "company_id": company_id,
            "source_id": source_id,
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
                "published_at": state.get("published_at"),
                "date_source": state.get("date_source"),
                "date_confidence": state.get("date_confidence"),
                "status": "active",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            result = supabase.client.table("url_content_units").insert(
                url_content_data
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
                    "url": url,
                    "scraped_at": datetime.utcnow().isoformat(),
                    "published_at": state.get("published_at")
                }
            )
            
            if result["success"]:
                context_unit_ids.append(result["context_unit_id"])
                logger.debug("context_unit_created",
                    url=url,
                    context_unit_id=result["context_unit_id"]
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
