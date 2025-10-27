"""Base abstraction for content sources.

All input channels (email, API, file, webhook) inherit from BaseSource.
This allows easy addition of new channels without modifying core pipeline.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger("base_source")


@dataclass
class SourceContent:
    """Unified content structure from any source."""

    organization_slug: str          # Organization this content belongs to
    source_type: str                # "email", "api", "file", "webhook"
    source_id: str                  # Unique ID from source (email message_id, etc.)
    raw_content: Dict[str, Any]     # Aggregated content from source
    metadata: Dict[str, Any]        # Source-specific metadata

    def __post_init__(self):
        """Validate source_type."""
        valid_types = ["email", "api", "file", "webhook"]
        if self.source_type not in valid_types:
            raise ValueError(f"Invalid source_type: {self.source_type}. Must be one of {valid_types}")


class BaseSource(ABC):
    """Abstract base class for all content sources.

    Implementers must provide:
    - fetch(): Retrieve new content from source
    - acknowledge(): Mark content as processed
    - match_organization(): Determine organization from content
    """

    def __init__(self):
        """Initialize source."""
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    async def fetch(self) -> List[SourceContent]:
        """Fetch new content from source.

        Returns:
            List of SourceContent objects ready for processing
        """
        pass

    @abstractmethod
    async def acknowledge(self, source_id: str):
        """Mark content as processed.

        Actions depend on source:
        - Email: Mark as read or move to processed folder
        - File: Move to processed directory or delete
        - API: No action needed
        - Webhook: No action needed

        Args:
            source_id: Unique identifier from source
        """
        pass

    @abstractmethod
    async def match_organization(self, content: Any) -> Optional[str]:
        """Determine organization slug from content.

        Logic depends on source:
        - Email: Match TO/CC against organization email addresses
        - File: Extract from filename (e.g., "gasteizhoy_document.pdf")
        - API: Provided in request
        - Webhook: Validate signature and extract from payload

        Args:
            content: Raw content object (varies by source)

        Returns:
            Organization slug if matched, None otherwise
        """
        pass

    async def _query_organization_by_email(self, email_address: str) -> Optional[str]:
        """Helper: Query organization by email address in channels.

        Args:
            email_address: Email to search for

        Returns:
            Organization slug if found
        """
        from utils.supabase_client import get_supabase_client

        try:
            supabase = get_supabase_client()

            # Query organizations where email_address is in channels.email.addresses array
            # Use supabase.client.table() - the actual Supabase client
            result = supabase.client.table("organizations").select("slug, channels").eq("is_active", True).execute()

            # Filter in Python (Supabase JSONB queries can be tricky)
            for org in result.data:
                channels = org.get("channels", {})
                email_config = channels.get("email", {})
                addresses = email_config.get("addresses", [])

                if email_address.lower() in [addr.lower() for addr in addresses]:
                    self.logger.info("org_matched", email=email_address, slug=org["slug"])
                    return org["slug"]

            self.logger.warn("no_org_matched", email=email_address)
            return None

        except Exception as e:
            self.logger.error("org_email_lookup_error", email=email_address, error=str(e))
            return None
