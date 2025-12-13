"""Helper functions for generating article references section."""

from typing import List, Dict, Any
from urllib.parse import urlparse


def extract_domain(url: str) -> str:
    """Extract domain from URL (e.g., https://araba.eus/foo -> araba.eus).
    
    Args:
        url: Full URL
        
    Returns:
        Domain name without www prefix
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        
        return domain
    except Exception:
        return url


def generate_references_section(
    context_units: List[Dict[str, Any]],
    enrichments: List[Dict[str, Any]] = None
) -> str:
    """Generate markdown references section for article.
    
    Args:
        context_units: List of context units used (must have 'id' and 'source_metadata.url')
        enrichments: Optional list of enrichment references (must have 'url')
        
    Returns:
        Markdown formatted references section
    """
    if not context_units and not enrichments:
        return ""
    
    lines = ["## Referencias\n"]
    
    # Track unique URLs to avoid duplicates
    seen_urls = set()
    
    # Add context unit references
    if context_units:
        for unit in context_units:
            source_metadata = unit.get("source_metadata") or {}
            url = source_metadata.get("url")
            
            if not url or url in seen_urls:
                continue
            
            seen_urls.add(url)
            domain = extract_domain(url)
            lines.append(f"- [{domain}]({url})")
    
    # Add enrichment references
    if enrichments:
        for enrichment in enrichments:
            url = enrichment.get("url")
            
            if not url or url in seen_urls:
                continue
            
            seen_urls.add(url)
            domain = extract_domain(url)
            lines.append(f"- [{domain}]({url})")
    
    if len(lines) == 1:
        # Only header, no actual references
        return ""
    
    return "\n".join(lines)


def append_references_to_content(
    content: str,
    context_units: List[Dict[str, Any]],
    enrichments: List[Dict[str, Any]] = None
) -> str:
    """Append references section to article content.
    
    Args:
        content: Original article content (markdown)
        context_units: List of context units used
        enrichments: Optional list of enrichment references
        
    Returns:
        Content with references appended
    """
    references = generate_references_section(context_units, enrichments)
    
    if not references:
        return content
    
    # Ensure content ends with newline
    if not content.endswith('\n'):
        content += '\n'
    
    # Add spacing before references
    return content + '\n' + references
