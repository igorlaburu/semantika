"""Source content data structures for semantika.

Standardized data structure for content from different sources (email, web, API, etc.)
that flows through the processing pipeline.
"""

from typing import Optional, Dict, Any
from datetime import datetime
import uuid


class SourceContent:
    """
    Standardized content structure for multi-source ingestion.
    
    Used by email monitor, web scraper, API connectors, etc. to pass
    content to company-specific workflows.
    """
    
    def __init__(
        self,
        source_type: str,
        source_id: str,
        organization_slug: str,
        text_content: str,
        metadata: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
        language: Optional[str] = None
    ):
        """
        Initialize source content.
        
        Args:
            source_type: Type of source (email, web, api, file, etc.)
            source_id: Unique identifier within source system
            organization_slug: Organization slug for routing
            text_content: Main text content to process
            metadata: Additional metadata from source
            title: Content title (optional)
            language: Content language (optional, auto-detected if None)
        """
        self.id = str(uuid.uuid4())
        self.source_type = source_type
        self.source_id = source_id
        self.organization_slug = organization_slug
        self.text_content = text_content
        self.metadata = metadata or {}
        self.title = title
        self.language = language
        self.created_at = datetime.utcnow()
        
        # Add creation timestamp to metadata
        self.metadata.update({
            "content_id": self.id,
            "created_at": self.created_at.isoformat(),
            "source_type": self.source_type,
            "source_id": self.source_id
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "organization_slug": self.organization_slug,
            "text_content": self.text_content,
            "metadata": self.metadata,
            "title": self.title,
            "language": self.language,
            "created_at": self.created_at.isoformat()
        }
    
    def get_display_title(self) -> str:
        """Get a display-friendly title."""
        if self.title:
            return self.title
        
        # Generate title from source type and metadata
        if self.source_type == "email":
            subject = self.metadata.get("subject", "")
            return f"Email: {subject}" if subject else "Email (No Subject)"
        elif self.source_type == "email_attachment":
            filename = self.metadata.get("filename", "attachment")
            return f"Attachment: {filename}"
        elif self.source_type == "email_audio":
            filename = self.metadata.get("filename", "audio")
            return f"Audio: {filename}"
        elif self.source_type == "web":
            url = self.metadata.get("url", "")
            return f"Web: {url}" if url else "Web Content"
        elif self.source_type == "api":
            source = self.metadata.get("api_source", "API")
            return f"API: {source}"
        else:
            return f"{self.source_type.title()}: {self.source_id}"
    
    def get_text_preview(self, max_length: int = 200) -> str:
        """Get a preview of the text content."""
        if len(self.text_content) <= max_length:
            return self.text_content
        
        return self.text_content[:max_length - 3] + "..."
    
    def get_word_count(self) -> int:
        """Get approximate word count."""
        return len(self.text_content.split())
    
    def add_metadata(self, key: str, value: Any) -> None:
        """Add metadata field."""
        self.metadata[key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata field with default."""
        return self.metadata.get(key, default)
    
    def __str__(self) -> str:
        """String representation."""
        return f"SourceContent({self.source_type}, {self.get_display_title()}, {self.get_word_count()} words)"
    
    def __repr__(self) -> str:
        """Detailed representation."""
        return (
            f"SourceContent(id={self.id}, source_type={self.source_type}, "
            f"source_id={self.source_id}, organization_slug={self.organization_slug}, "
            f"word_count={self.get_word_count()})"
        )