"""Standard schema for source_metadata across all connectors.

DESIGN PRINCIPLES:
- ALL connectors MUST use the same top-level fields
- Connector-specific data goes in 'connector_specific' subclave
- URL is ALWAYS the canonical source URL
- Dates are ALWAYS ISO 8601 format
"""

from typing import Dict, Any, Optional
from datetime import datetime


def normalize_source_metadata(
    url: Optional[str] = None,
    source_name: Optional[str] = None,
    published_at: Optional[str] = None,
    scraped_at: Optional[str] = None,
    connector_type: Optional[str] = None,
    connector_specific: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Normalize source_metadata to standard format.
    
    STANDARD FIELDS (top-level):
    - url: str - Canonical source URL (REQUIRED for web sources)
    - source_name: str - Human-readable source name (e.g., "RTVE", "Diario Vasco")
    - published_at: str - ISO 8601 publication date (e.g., "2025-12-11T17:22:50Z")
    - scraped_at: str - ISO 8601 capture timestamp (e.g., "2025-12-11T17:25:00Z")
    - connector_type: str - Connector identifier (e.g., "perplexity_news", "scraping", "email")
    - connector_specific: dict - Connector-specific metadata
    
    Args:
        url: Canonical source URL
        source_name: Human-readable source name
        published_at: ISO 8601 publication date
        scraped_at: ISO 8601 capture timestamp
        connector_type: Connector type identifier
        connector_specific: Connector-specific metadata dict
        
    Returns:
        Normalized source_metadata dict
        
    Examples:
        >>> # Perplexity connector
        >>> normalize_source_metadata(
        ...     url="https://www.rtve.es/play/videos/...",
        ...     source_name="RTVE",
        ...     published_at="2025-12-11T00:00:00Z",
        ...     scraped_at="2025-12-11T17:22:50Z",
        ...     connector_type="perplexity_news",
        ...     connector_specific={
        ...         "perplexity_query": "Bilbao, Bizkaia",
        ...         "perplexity_index": 5,
        ...         "enrichment_model": "gpt-4o-mini",
        ...         "enrichment_cost_usd": 0.0
        ...     }
        ... )
        
        >>> # Scraping connector
        >>> normalize_source_metadata(
        ...     url="https://www.diputacionbizkaia.eus/noticias/123",
        ...     source_name="Diputación Foral de Bizkaia",
        ...     published_at="2025-12-10T14:30:00Z",
        ...     scraped_at="2025-12-11T09:15:00Z",
        ...     connector_type="scraping",
        ...     connector_specific={
        ...         "monitored_url_id": "uuid-123",
        ...         "change_type": "major_update",
        ...         "date_source": "meta_tag",
        ...         "date_confidence": 0.95
        ...     }
        ... )
        
        >>> # Email connector
        >>> normalize_source_metadata(
        ...     url=None,  # Emails don't have URLs
        ...     source_name="sender@example.com",
        ...     published_at="2025-12-11T08:45:00Z",
        ...     scraped_at="2025-12-11T08:46:00Z",
        ...     connector_type="email",
        ...     connector_specific={
        ...         "subject": "Informe mensual",
        ...         "from": "sender@example.com",
        ...         "message_id": "<abc123@example.com>",
        ...         "has_attachments": True
        ...     }
        ... )
    """
    # Auto-generate scraped_at if not provided
    if not scraped_at:
        scraped_at = datetime.utcnow().isoformat() + "Z"
    
    # Build standard metadata
    metadata = {
        "url": url,
        "source_name": source_name,
        "published_at": published_at,
        "scraped_at": scraped_at,
        "connector_type": connector_type,
        "connector_specific": connector_specific or {}
    }
    
    return metadata


def extract_url_from_metadata(source_metadata: Dict[str, Any]) -> Optional[str]:
    """Extract canonical URL from source_metadata (backward compatibility).
    
    Supports both new and old formats:
    - New format: source_metadata["url"]
    - Old Perplexity format: source_metadata["perplexity_source"]
    - Old scraping format: source_metadata["url"]
    
    Args:
        source_metadata: Source metadata dict
        
    Returns:
        Canonical URL or None
    """
    if not source_metadata:
        return None
    
    # Try new standard format first
    url = source_metadata.get("url")
    if url:
        return url
    
    # Fallback to old formats (backward compatibility)
    connector_type = source_metadata.get("connector_type")
    
    if connector_type == "perplexity_news":
        # Old format: perplexity_source
        return source_metadata.get("perplexity_source")
    
    # For scraping, url was already standard
    # For email, there's no URL
    return None


def migrate_old_metadata(old_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate old source_metadata format to new standard.
    
    Detects connector type and migrates accordingly.
    
    Args:
        old_metadata: Old-format metadata
        
    Returns:
        New-format metadata
    """
    connector_type = old_metadata.get("connector_type")
    
    if not connector_type:
        # Try to infer from fields
        if "perplexity_query" in old_metadata or "perplexity_source" in old_metadata:
            connector_type = "perplexity_news"
        elif "monitored_url_id" in old_metadata or "change_type" in old_metadata:
            connector_type = "scraping"
        elif "subject" in old_metadata or "from" in old_metadata:
            connector_type = "email"
    
    # Perplexity migration
    if connector_type == "perplexity_news":
        return normalize_source_metadata(
            url=old_metadata.get("perplexity_source"),
            source_name=None,  # Extract from URL domain
            published_at=old_metadata.get("perplexity_date"),
            scraped_at=None,  # Will auto-generate
            connector_type="perplexity_news",
            connector_specific={
                "perplexity_query": old_metadata.get("perplexity_query"),
                "perplexity_index": old_metadata.get("perplexity_index"),
                "enrichment_model": old_metadata.get("enrichment_model"),
                "enrichment_cost_usd": old_metadata.get("enrichment_cost_usd")
            }
        )
    
    # Scraping migration (already mostly standard)
    elif connector_type == "scraping":
        return normalize_source_metadata(
            url=old_metadata.get("url"),
            source_name=old_metadata.get("source_name"),
            published_at=old_metadata.get("published_at"),
            scraped_at=old_metadata.get("scraped_at"),
            connector_type="scraping",
            connector_specific={
                "monitored_url_id": old_metadata.get("monitored_url_id"),
                "change_type": old_metadata.get("change_type"),
                "date_source": old_metadata.get("date_source"),
                "date_confidence": old_metadata.get("date_confidence")
            }
        )
    
    # Email migration
    elif connector_type == "email":
        return normalize_source_metadata(
            url=None,
            source_name=old_metadata.get("from"),
            published_at=old_metadata.get("date"),
            scraped_at=None,
            connector_type="email",
            connector_specific={
                "subject": old_metadata.get("subject"),
                "from": old_metadata.get("from"),
                "message_id": old_metadata.get("message_id"),
                "has_attachments": old_metadata.get("has_attachments")
            }
        )
    
    # Unknown format - return as-is with warning
    return old_metadata
