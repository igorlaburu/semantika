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
        """Helper: Query organization by company email alias.

        Args:
            email_address: Email to search for

        Returns:
            Organization slug if found
        """
        from utils.supabase_client import get_supabase_client

        try:
            supabase = get_supabase_client()

            # PHASE 2: Look for company by email_alias in settings
            company = await supabase.get_company_by_email_alias(email_address.lower())
            
            if not company:
                self.logger.warn("no_company_matched_by_email", email=email_address)
                return None

            # Get first active organization for this company
            # Simplified: 1 company = 1 organization for now
            result = supabase.client.table("organizations")\
                .select("slug")\
                .eq("company_id", company["id"])\
                .eq("is_active", True)\
                .limit(1)\
                .execute()

            if result.data and len(result.data) > 0:
                org_slug = result.data[0]["slug"]
                self.logger.info("org_matched_via_company", 
                    email=email_address, 
                    company_code=company["company_code"],
                    org_slug=org_slug
                )
                return org_slug
            else:
                self.logger.warn("no_org_found_for_company", 
                    email=email_address,
                    company_id=company["id"]
                )
                return None

        except Exception as e:
            self.logger.error("org_email_lookup_error", email=email_address, error=str(e))
            return None
