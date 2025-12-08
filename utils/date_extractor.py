"""Multi-source date extraction for web content.

Extracts publication dates from multiple sources with confidence scoring:
- Meta tags (95% confidence)
- JSON-LD (95% confidence)
- URL patterns (80% confidence)
- CSS selectors (75% confidence)
- LLM fallback (60% confidence)

Strategy: Extract dates from all sources, take the OLDEST (avoids detecting redesigns as new content).
"""

import re
import json
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from .logger import get_logger

logger = get_logger("date_extractor")

# Common date patterns
DATE_PATTERNS = {
    'iso8601': r'\d{4}-\d{2}-\d{2}',
    'slash': r'\d{1,2}/\d{1,2}/\d{4}',
    'dot': r'\d{1,2}\.\d{1,2}\.\d{4}',
    'spanish': r'\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\d{4}',
    'english': r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}'
}

# Month name mappings
SPANISH_MONTHS = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
}

ENGLISH_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12
}


def parse_date_string(date_str: str) -> Optional[datetime]:
    """Parse date string to datetime object.
    
    Args:
        date_str: Date string in various formats
        
    Returns:
        datetime object or None if parsing fails
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    # Try ISO 8601 format first (most common in meta tags)
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), '%Y-%m-%d')
        except ValueError:
            pass
    
    # Try ISO 8601 with time
    iso_time_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', date_str)
    if iso_time_match:
        try:
            return datetime.strptime(iso_time_match.group(1), '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            pass
    
    # Try slash format (MM/DD/YYYY or DD/MM/YYYY)
    slash_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_str)
    if slash_match:
        try:
            # Try DD/MM/YYYY first (common in Spanish sites)
            return datetime.strptime(slash_match.group(0), '%d/%m/%Y')
        except ValueError:
            try:
                # Try MM/DD/YYYY
                return datetime.strptime(slash_match.group(0), '%m/%d/%Y')
            except ValueError:
                pass
    
    # Try Spanish month names
    spanish_match = re.search(
        r'(\d{1,2})\s+(?:de\s+)?(' + '|'.join(SPANISH_MONTHS.keys()) + r')\s+(?:de\s+)?(\d{4})',
        date_str.lower()
    )
    if spanish_match:
        try:
            day = int(spanish_match.group(1))
            month = SPANISH_MONTHS[spanish_match.group(2)]
            year = int(spanish_match.group(3))
            return datetime(year, month, day)
        except (ValueError, KeyError):
            pass
    
    # Try English month names
    english_match = re.search(
        r'(' + '|'.join(ENGLISH_MONTHS.keys()) + r')\s+(\d{1,2}),?\s+(\d{4})',
        date_str.lower()
    )
    if english_match:
        try:
            month = ENGLISH_MONTHS[english_match.group(1)]
            day = int(english_match.group(2))
            year = int(english_match.group(3))
            return datetime(year, month, day)
        except (ValueError, KeyError):
            pass
    
    return None


def extract_from_meta_tags(soup: BeautifulSoup) -> List[Tuple[datetime, str, float]]:
    """Extract dates from HTML meta tags (95% confidence).
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        List of (datetime, source, confidence) tuples
    """
    dates = []
    now = datetime.now()
    
    # Common meta tag names for publication date
    meta_names = [
        'article:published_time',
        'publishdate',
        'pubdate',
        'date',
        'publication_date',
        'publish_date',
        'sailthru.date',
        'dc.date',
        'dcterms.created'
    ]
    
    for name in meta_names:
        # Try property attribute
        tag = soup.find('meta', property=name)
        if not tag:
            # Try name attribute
            tag = soup.find('meta', attrs={'name': name})
        
        if tag and tag.get('content'):
            dt = parse_date_string(tag['content'])
            if dt and dt <= now:
                dates.append((dt, f'meta_tag:{name}', 0.95))
                logger.debug("date_from_meta_tag", 
                    meta_name=name, 
                    date=dt.isoformat()
                )
            elif dt and dt > now:
                logger.warn("future_date_ignored_meta",
                    meta_name=name,
                    date=dt.isoformat()
                )
    
    return dates


def extract_from_jsonld(soup: BeautifulSoup) -> List[Tuple[datetime, str, float]]:
    """Extract dates from JSON-LD structured data (95% confidence).
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        List of (datetime, source, confidence) tuples
    """
    dates = []
    now = datetime.now()
    
    # Find all JSON-LD script tags
    jsonld_scripts = soup.find_all('script', type='application/ld+json')
    
    for script in jsonld_scripts:
        try:
            data = json.loads(script.string)
            
            # Handle both single objects and arrays
            if isinstance(data, list):
                items = data
            else:
                items = [data]
            
            for item in items:
                # Look for datePublished, dateCreated
                for key in ['datePublished', 'dateCreated', 'publishDate']:
                    if key in item:
                        dt = parse_date_string(item[key])
                        if dt and dt <= now:
                            dates.append((dt, f'jsonld:{key}', 0.95))
                            logger.debug("date_from_jsonld",
                                key=key,
                                date=dt.isoformat()
                            )
                        elif dt and dt > now:
                            logger.warn("future_date_ignored_jsonld",
                                key=key,
                                date=dt.isoformat()
                            )
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.debug("jsonld_parse_error", error=str(e))
            continue
    
    return dates


def extract_from_url(url: str) -> List[Tuple[datetime, str, float]]:
    """Extract dates from URL patterns (80% confidence).
    
    Args:
        url: Page URL
        
    Returns:
        List of (datetime, source, confidence) tuples
    """
    dates = []
    
    # Common URL date patterns
    # /2024/11/10/article-title
    # /article/2024-11-10
    # ?date=2024-11-10
    
    patterns = [
        r'/(\d{4})/(\d{2})/(\d{2})/',  # /YYYY/MM/DD/
        r'/(\d{4})-(\d{2})-(\d{2})/',  # /YYYY-MM-DD/
        r'date=(\d{4})-(\d{2})-(\d{2})',  # ?date=YYYY-MM-DD
        r'/(\d{4})(\d{2})(\d{2})/',  # /YYYYMMDD/
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            try:
                year = int(match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))
                dt = datetime(year, month, day)
                
                # Sanity check: date shouldn't be in the future
                if dt <= datetime.now():
                    dates.append((dt, f'url_pattern:{pattern}', 0.80))
                    logger.debug("date_from_url",
                        pattern=pattern,
                        date=dt.isoformat()
                    )
            except (ValueError, IndexError):
                continue
    
    return dates


def extract_from_css_selectors(soup: BeautifulSoup) -> List[Tuple[datetime, str, float]]:
    """Extract dates from common CSS selectors (75% confidence).
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        List of (datetime, source, confidence) tuples
    """
    dates = []
    now = datetime.now()
    
    # Common CSS selectors for date display
    selectors = [
        'time[datetime]',
        '.published-date',
        '.publish-date',
        '.article-date',
        '.post-date',
        '.entry-date',
        '.date-published',
        'span.date',
        'p.date',
        '.byline time',
        'article time'
    ]
    
    for selector in selectors:
        try:
            elements = soup.select(selector)
            for elem in elements:
                # Try datetime attribute first (for <time> tags)
                date_str = elem.get('datetime')
                if not date_str:
                    # Try text content
                    date_str = elem.get_text(strip=True)
                
                if date_str:
                    dt = parse_date_string(date_str)
                    if dt and dt <= now:
                        dates.append((dt, f'css_selector:{selector}', 0.75))
                        logger.debug("date_from_css_selector",
                            selector=selector,
                            date=dt.isoformat()
                        )
                    elif dt and dt > now:
                        logger.warn("future_date_ignored_css",
                            selector=selector,
                            date=dt.isoformat()
                        )
        except Exception as e:
            logger.debug("css_selector_error", selector=selector, error=str(e))
            continue
    
    return dates


async def extract_from_llm(html: str, title: str) -> List[Tuple[datetime, str, float]]:
    """Extract date using LLM fallback (60% confidence).
    
    Args:
        html: HTML content (first 2000 chars)
        title: Page title
        
    Returns:
        List of (datetime, source, confidence) tuples
    """
    try:
        from .llm_client import get_llm_client
        
        llm_client = get_llm_client()
        
        # Build prompt with HTML preview
        html_preview = html[:2000]
        
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser
        
        llm_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a date extraction system. Extract publication dates from HTML."),
            ("user", """Extract the publication date from this HTML content.

Title: {title}

HTML preview:
{html_preview}

Look for publication date indicators like "Publicado", "Published", date strings, etc.

Respond with JSON format (use quotes for keys and values):
{{{{date: "YYYY-MM-DD", confidence: "high|medium|low", source: "where you found it"}}}}

If no date found, respond: {{{{date: null}}}}""")
        ])
        
        chain = llm_prompt | llm_client.llm_fast | JsonOutputParser()
        result = await chain.ainvoke({"title": title, "html_preview": html_preview})
        
        if result.get('date'):
            dt = parse_date_string(result['date'])
            now = datetime.now()
            if dt and dt <= now:
                # Lower confidence (60%) since LLM can hallucinate
                logger.info("date_from_llm",
                    date=dt.isoformat(),
                    llm_confidence=result.get('confidence'),
                    llm_source=result.get('source')
                )
                return [(dt, f'llm:{result.get("source", "unknown")}', 0.60)]
            elif dt and dt > now:
                logger.warn("future_date_ignored_llm",
                    date=dt.isoformat(),
                    llm_confidence=result.get('confidence')
                )
        
        return []
        
    except Exception as e:
        logger.error("llm_date_extraction_error", error=str(e))
        return []


async def extract_publication_date(
    html: str,
    url: str,
    title: Optional[str] = None,
    use_llm_fallback: bool = True
) -> Dict[str, any]:
    """Extract publication date from all available sources.
    
    Strategy:
    1. Try all extraction methods (meta, JSON-LD, URL, CSS)
    2. Optionally use LLM as fallback
    3. Select OLDEST date (avoids treating redesigns as new content)
    4. Return date with source and confidence
    
    Args:
        html: HTML content
        url: Page URL
        title: Page title (for LLM fallback)
        use_llm_fallback: Use LLM if other methods fail
        
    Returns:
        Dict with:
        - published_at: datetime or None
        - date_source: Source identifier
        - date_confidence: Confidence score (0.0-1.0)
        - all_dates: List of all dates found
    """
    logger.debug("extract_publication_date_start", url=url)
    
    # Parse HTML
    soup = BeautifulSoup(html, 'html.parser')
    
    # Collect dates from all sources
    all_dates = []
    
    # 1. Meta tags (95% confidence)
    all_dates.extend(extract_from_meta_tags(soup))
    
    # 2. JSON-LD (95% confidence)
    all_dates.extend(extract_from_jsonld(soup))
    
    # 3. URL patterns (80% confidence)
    all_dates.extend(extract_from_url(url))
    
    # 4. CSS selectors (75% confidence)
    all_dates.extend(extract_from_css_selectors(soup))
    
    # 5. LLM fallback (60% confidence) - only if other methods failed
    if not all_dates and use_llm_fallback and title:
        llm_dates = await extract_from_llm(html, title)
        all_dates.extend(llm_dates)
    
    logger.info("dates_extracted",
        url=url,
        total_dates_found=len(all_dates)
    )
    
    # No dates found
    if not all_dates:
        logger.warn("no_publication_date_found", url=url)
        return {
            "published_at": None,
            "date_source": "unknown",
            "date_confidence": 0.0,
            "all_dates": []
        }
    
    # Select OLDEST date (strategy: oldest date is most likely original publication)
    # This prevents treating content redesigns/updates as new articles
    oldest_date = min(all_dates, key=lambda x: x[0])
    
    # If multiple sources agree on same date, boost confidence
    same_date_count = sum(1 for dt, _, _ in all_dates if dt.date() == oldest_date[0].date())
    confidence_boost = min(0.05 * same_date_count, 0.10)  # Max +10% boost
    
    final_confidence = min(1.0, oldest_date[2] + confidence_boost)
    
    logger.info("publication_date_selected",
        url=url,
        date=oldest_date[0].isoformat(),
        source=oldest_date[1],
        confidence=final_confidence,
        total_dates_found=len(all_dates),
        agreement_count=same_date_count
    )
    
    return {
        "published_at": oldest_date[0],
        "date_source": oldest_date[1].split(':')[0],  # Extract source type (meta_tag, jsonld, etc.)
        "date_confidence": final_confidence,
        "all_dates": [
            {
                "date": dt.isoformat(),
                "source": source,
                "confidence": conf
            }
            for dt, source, conf in all_dates
        ]
    }


def extract_date_from_text(text: str) -> Optional[datetime]:
    """Quick date extraction from plain text.
    
    Args:
        text: Plain text content
        
    Returns:
        datetime object or None
    """
    for pattern in DATE_PATTERNS.values():
        match = re.search(pattern, text)
        if match:
            dt = parse_date_string(match.group(0))
            if dt:
                return dt
    
    return None
