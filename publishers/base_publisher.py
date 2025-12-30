"""Base publisher interface for multi-platform article publication."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime


class PublicationResult:
    """Result of a publication attempt."""
    
    def __init__(
        self,
        success: bool,
        url: Optional[str] = None,
        external_id: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.success = success
        self.url = url
        self.external_id = external_id
        self.error = error
        self.metadata = metadata or {}
        self.published_at = datetime.utcnow().isoformat() if success else None


class BasePublisher(ABC):
    """Abstract base class for platform publishers."""
    
    def __init__(self, credentials: Dict[str, Any], base_url: str):
        self.credentials = credentials
        self.base_url = base_url
        
    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """Test connection and credentials.
        
        Returns:
            {
                "success": bool,
                "message": str,
                "details": dict (optional)
            }
        """
        pass
    
    @abstractmethod
    async def publish_article(
        self,
        title: str,
        content: str,
        excerpt: Optional[str] = None,
        tags: Optional[list] = None,
        image_url: Optional[str] = None,
        status: str = "publish"
    ) -> PublicationResult:
        """Publish an article to the platform.
        
        Args:
            title: Article title
            content: HTML content
            excerpt: Article summary/excerpt
            tags: List of tags
            image_url: Featured image URL
            status: Publication status ("draft" or "publish")
            
        Returns:
            PublicationResult with success/failure details
        """
        pass
    
    @abstractmethod
    def get_platform_type(self) -> str:
        """Get platform identifier."""
        pass
    
    def sanitize_content(self, content: str) -> str:
        """Clean content for platform-specific requirements."""
        # Base implementation - platforms can override
        return content
    
    def format_tags(self, tags: list) -> Any:
        """Format tags for platform-specific requirements."""
        # Base implementation - platforms can override
        return tags