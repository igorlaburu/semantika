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
    enrichments: List[Dict[str, Any]] = None,
    image_info: Dict[str, Any] = None
) -> str:
    """Generate markdown references section for article.
    
    Args:
        context_units: List of context units used (must have 'id' and 'source_metadata.url')
        enrichments: Optional list of enrichment references (must have 'url')
        image_info: Optional image information (source, ai_generated flag)
        
    Returns:
        Markdown formatted references section
    """
    sections = []
    
    # Generate sources/references section
    if context_units or enrichments:
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
                lines.append(f"[{domain}]({url})")
        
        # Add enrichment references
        if enrichments:
            for enrichment in enrichments:
                url = enrichment.get("url")
                
                if not url or url in seen_urls:
                    continue
                
                seen_urls.add(url)
                domain = extract_domain(url)
                lines.append(f"[{domain}]({url})")
        
        if len(lines) > 1:  # Has actual references beyond header
            sections.append("\n".join(lines))
    
    # Generate images section
    if image_info:
        image_lines = ["## Imágenes\n"]
        
        if image_info.get("ai_generated", False):
            image_lines.append("Generada con IA")
        elif image_info.get("source_url"):
            domain = extract_domain(image_info["source_url"])
            image_lines.append(f"[{domain}]({image_info['source_url']})")
        elif image_info.get("source_domain"):
            # When we only have domain info
            image_lines.append(f"{image_info['source_domain']}")
        
        if len(image_lines) > 1:  # Has actual image info beyond header
            sections.append("\n".join(image_lines))
    
    return "\n\n".join(sections) if sections else ""


def append_references_to_content(
    content: str,
    context_units: List[Dict[str, Any]],
    enrichments: List[Dict[str, Any]] = None,
    image_info: Dict[str, Any] = None
) -> str:
    """Append references section to article content.
    
    Args:
        content: Original article content (markdown)
        context_units: List of context units used
        enrichments: Optional list of enrichment references
        image_info: Optional image information (source, ai_generated flag)
        
    Returns:
        Content with references appended
    """
    references = generate_references_section(context_units, enrichments, image_info)
    
    if not references:
        return content
    
    # Ensure content ends with newline
    if not content.endswith('\n'):
        content += '\n'
    
    # Add spacing before references
    return content + '\n' + references
