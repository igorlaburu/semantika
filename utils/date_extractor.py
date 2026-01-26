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
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from .logger import get_logger

logger = get_logger("date_extractor")

# Common date patterns
DATE_PATTERNS = {
    'iso8601': r'\d{4}-\d{2}-\d{2}',
    'iso_slash': r'\d{4}/\d{2}/\d{2}',  # YYYY/MM/DD (Vidrala style)
    'slash': r'\d{1,2}/\d{1,2}/\d{4}',
    'dot': r'\d{1,2}\.\d{1,2}\.\d{4}',
    'spanish': r'\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\d{4}',
    'english': r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
    'english_day_month': r'\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}'  # 11 December 2025
}

# Month name mappings (full names and abbreviations)
SPANISH_MONTHS = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
    # Abbreviations (with and without dot)
    'ene': 1, 'ene.': 1, 'feb': 2, 'feb.': 2, 'mar': 3, 'mar.': 3,
    'abr': 4, 'abr.': 4, 'may': 5, 'may.': 5, 'jun': 6, 'jun.': 6,
    'jul': 7, 'jul.': 7, 'ago': 8, 'ago.': 8, 'sep': 9, 'sep.': 9,
    'sept': 9, 'sept.': 9, 'oct': 10, 'oct.': 10, 'nov': 11, 'nov.': 11,
    'dic': 12, 'dic.': 12
}

ENGLISH_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
    # Abbreviations (with and without dot)
    'jan': 1, 'jan.': 1, 'feb': 2, 'feb.': 2, 'mar': 3, 'mar.': 3,
    'apr': 4, 'apr.': 4, 'jun': 6, 'jun.': 6, 'jul': 7, 'jul.': 7,
    'aug': 8, 'aug.': 8, 'sep': 9, 'sep.': 9, 'sept': 9, 'sept.': 9,
    'oct': 10, 'oct.': 10, 'nov': 11, 'nov.': 11, 'dec': 12, 'dec.': 12
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

    # Try YYYY/MM/DD format (Vidrala style)
    iso_slash_match = re.search(r'(\d{4})/(\d{2})/(\d{2})', date_str)
    if iso_slash_match:
        try:
            return datetime.strptime(iso_slash_match.group(0), '%Y/%m/%d')
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

    # Try Spanish month names (escape dots in abbreviations like "ene.")
    spanish_months_pattern = '|'.join(re.escape(m) for m in SPANISH_MONTHS.keys())
    spanish_match = re.search(
        r'(\d{1,2})\s+(?:de\s+)?(' + spanish_months_pattern + r')\.?\s+(?:de\s+)?(\d{4})',
        date_str.lower()
    )
    if spanish_match:
        try:
            day = int(spanish_match.group(1))
            month_key = spanish_match.group(2).rstrip('.')
            month = SPANISH_MONTHS.get(month_key) or SPANISH_MONTHS.get(spanish_match.group(2))
            year = int(spanish_match.group(3))
            return datetime(year, month, day)
        except (ValueError, KeyError, TypeError):
            pass

    # Try English month names: "January 15, 2025" or "January 15 2025" (escape dots in abbreviations)
    english_months_pattern = '|'.join(re.escape(m) for m in ENGLISH_MONTHS.keys())
    english_match = re.search(
        r'(' + english_months_pattern + r')\.?\s+(\d{1,2}),?\s+(\d{4})',
        date_str.lower()
    )
    if english_match:
        try:
            # Remove trailing dot if present for lookup
            month_key = english_match.group(1).rstrip('.')
            month = ENGLISH_MONTHS.get(month_key) or ENGLISH_MONTHS.get(english_match.group(1))
            day = int(english_match.group(2))
            year = int(english_match.group(3))
            return datetime(year, month, day)
        except (ValueError, KeyError, TypeError):
            pass

    # Try English format: "15 January 2025" (day month year)
    english_dmy_match = re.search(
        r'(\d{1,2})\s+(' + english_months_pattern + r')\.?\s+(\d{4})',
        date_str.lower()
    )
    if english_dmy_match:
        try:
            day = int(english_dmy_match.group(1))
            month_key = english_dmy_match.group(2).rstrip('.')
            month = ENGLISH_MONTHS.get(month_key) or ENGLISH_MONTHS.get(english_dmy_match.group(2))
            year = int(english_dmy_match.group(3))
            return datetime(year, month, day)
        except (ValueError, KeyError, TypeError):
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
                dates.append((dt, 'meta_tag', 0.95))
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
                            dates.append((dt, 'jsonld', 0.95))
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
                    dates.append((dt, 'url_pattern', 0.80))
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
                        dates.append((dt, 'css_selector', 0.75))
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


def extract_flexible_date(text: str) -> List[Tuple[datetime, str, float]]:
    """Flexible date extraction - looks for year + month patterns nearby (70% confidence).

    Strategy: Find current/previous year, then look for month indicators nearby.
    More permissive than strict pattern matching.

    Args:
        text: Plain text content

    Returns:
        List of (datetime, source, confidence) tuples
    """
    dates = []
    now = datetime.now()
    text_lower = text.lower()

    # All month names (Spanish + English)
    all_months = {**SPANISH_MONTHS, **ENGLISH_MONTHS}

    # Only current year (after Jan 7, no previous year content)
    current_year = now.year
    year_pattern = r'\b(' + str(current_year) + r')\b'

    for year_match in re.finditer(year_pattern, text):
        year = int(year_match.group(1))
        year_pos = year_match.start()

        # Look in a window around the year (100 chars before and after)
        window_start = max(0, year_pos - 100)
        window_end = min(len(text), year_pos + 100)
        window = text_lower[window_start:window_end]

        month = None
        day = None

        # Try to find month name in window
        for month_name, month_num in all_months.items():
            if month_name in window:
                month = month_num
                # Try to find day near the month name
                month_pos = window.find(month_name)
                day_window = window[max(0, month_pos-20):month_pos+len(month_name)+20]
                day_match = re.search(r'\b(\d{1,2})\b', day_window)
                if day_match:
                    potential_day = int(day_match.group(1))
                    if 1 <= potential_day <= 31:
                        day = potential_day
                break

        # Try numeric month (01-12) if no month name found
        if not month:
            # Look for patterns like /01/, -01-, .01. near the year
            month_patterns = [
                r'[/\-\.](\d{2})[/\-\.]',  # /01/ or -01- or .01.
                r'\b(\d{2})\b'  # Just a two-digit number
            ]
            for mp in month_patterns:
                month_match = re.search(mp, window)
                if month_match:
                    potential_month = int(month_match.group(1))
                    if 1 <= potential_month <= 12:
                        month = potential_month
                        # Look for day
                        remaining = window.replace(month_match.group(0), '', 1)
                        day_match = re.search(r'\b(\d{1,2})\b', remaining)
                        if day_match:
                            potential_day = int(day_match.group(1))
                            if 1 <= potential_day <= 31:
                                day = potential_day
                        break

        # If we found year and month, create a date
        if month:
            try:
                if not day:
                    day = 1  # Default to first of month
                dt = datetime(year, month, day)
                if dt <= now:
                    dates.append((dt, 'flexible_pattern', 0.70))
                    logger.debug("date_from_flexible_pattern",
                        year=year, month=month, day=day,
                        date=dt.isoformat()
                    )
            except ValueError:
                pass

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

    # Cutoff for "recent" dates (30 days - last month's content)
    recent_cutoff = datetime.now() - timedelta(days=30)

    def filter_recent(dates_list):
        """Filter to only keep recent dates (within 2 years)."""
        return [(dt, src, conf) for dt, src, conf in dates_list if dt >= recent_cutoff]

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

    # 5. Flexible pattern matching (70% confidence) - before LLM
    if not filter_recent(all_dates):
        # Only try flexible if no recent structured dates found
        text_content = soup.get_text(separator=' ', strip=True)[:5000]
        all_dates.extend(extract_flexible_date(text_content))

    # Filter to only recent dates before deciding on LLM
    recent_dates = filter_recent(all_dates)

    # 6. LLM fallback (60% confidence) - only if NO recent dates found
    if not recent_dates and use_llm_fallback and title:
        llm_dates = await extract_from_llm(html, title)
        # Also filter LLM results for recency
        recent_llm = filter_recent(llm_dates)
        all_dates.extend(recent_llm)
        recent_dates = filter_recent(all_dates)

    logger.info("dates_extracted",
        url=url,
        total_dates_found=len(all_dates),
        recent_dates_found=len(recent_dates)
    )
    
    # No recent dates found
    if not recent_dates:
        logger.warn("no_publication_date_found", url=url,
            old_dates_found=len(all_dates),
            reason="no_recent_dates" if all_dates else "no_dates_at_all"
        )
        return {
            "published_at": None,
            "date_source": "unknown",
            "date_confidence": 0.0,
            "all_dates": []
        }

    # Select MOST RECENT date from recent_dates
    # Changed strategy: for news, we want the most recent date (not oldest)
    selected_date = max(recent_dates, key=lambda x: x[0])

    # If multiple sources agree on same date, boost confidence
    same_date_count = sum(1 for dt, _, _ in recent_dates if dt.date() == selected_date[0].date())
    confidence_boost = min(0.05 * same_date_count, 0.10)  # Max +10% boost

    final_confidence = min(1.0, selected_date[2] + confidence_boost)

    logger.info("publication_date_selected",
        url=url,
        date=selected_date[0].isoformat(),
        source=selected_date[1],
        confidence=final_confidence,
        total_dates_found=len(all_dates),
        recent_dates_found=len(recent_dates),
        agreement_count=same_date_count
    )

    return {
        "published_at": selected_date[0],
        "date_source": selected_date[1].split(':')[0],  # Extract source type (meta_tag, jsonld, etc.)
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
