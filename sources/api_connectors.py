"""API connectors for semantika (PLACEHOLDER - Future implementation).

Generic connectors for external APIs: EFE, Reuters, WordPress, etc.
"""

from typing import List, Dict, Optional
from utils.logger import get_logger

logger = get_logger("api_connectors")


class APIConnector:
    """
    Base class for API connectors.

    PLACEHOLDER FOR FUTURE IMPLEMENTATION
    """

    def __init__(self, name: str, config: Dict):
        """
        Initialize API connector.

        Args:
            name: Connector name
            config: Configuration dict
        """
        self.name = name
        self.config = config
        logger.info("api_connector_initialized", name=name, status="placeholder")

    async def fetch_data(self, **kwargs) -> List[Dict]:
        """
        Fetch data from API.

        PLACEHOLDER - TO BE IMPLEMENTED

        Returns:
            List of documents
        """
        logger.warn("api_connector_not_implemented", name=self.name)
        raise NotImplementedError(
            f"{self.name} connector not yet implemented. "
            "Will be available in future release."
        )


class EFEConnector(APIConnector):
    """
    EFE News Agency API connector.

    PLACEHOLDER FOR FUTURE IMPLEMENTATION

    Planned features:
    - Fetch news by category
    - Date range filtering
    - Language selection
    """

    def __init__(self, api_key: str):
        """
        Initialize EFE connector.

        Args:
            api_key: EFE API key
        """
        super().__init__("EFE", {"api_key": api_key})


class ReutersConnector(APIConnector):
    """
    Reuters News API connector.

    PLACEHOLDER FOR FUTURE IMPLEMENTATION

    Planned features:
    - Search articles by topic
    - Real-time news feed
    - Metadata extraction
    """

    def __init__(self, api_key: str):
        """
        Initialize Reuters connector.

        Args:
            api_key: Reuters API key
        """
        super().__init__("Reuters", {"api_key": api_key})


class WordPressConnector(APIConnector):
    """
    WordPress REST API connector.

    PLACEHOLDER FOR FUTURE IMPLEMENTATION

    Planned features:
    - Fetch posts from WordPress sites
    - Category and tag filtering
    - Custom post types
    - Media extraction
    """

    def __init__(self, site_url: str, auth: Optional[Dict] = None):
        """
        Initialize WordPress connector.

        Args:
            site_url: WordPress site URL
            auth: Optional authentication (username, password or API token)
        """
        super().__init__("WordPress", {"site_url": site_url, "auth": auth})

    async def fetch_posts(
        self,
        per_page: int = 10,
        categories: Optional[List[int]] = None,
        **kwargs
    ) -> List[Dict]:
        """
        Fetch WordPress posts.

        PLACEHOLDER - TO BE IMPLEMENTED

        Args:
            per_page: Posts per page
            categories: Category IDs to filter
            **kwargs: Additional WP_Query parameters

        Returns:
            List of post data
        """
        logger.warn("wordpress_connector_not_implemented", site=self.config["site_url"])
        raise NotImplementedError(
            "WordPress connector not yet implemented. "
            "Will use WP REST API in future release."
        )


# Future implementation notes:
#
# 1. EFE API
#    - Endpoint: https://api.efe.com/...
#    - Authentication: API key
#    - Response format: XML or JSON
#
# 2. Reuters API
#    - Endpoint: TBD (depends on Reuters offering)
#    - Authentication: OAuth or API key
#    - Response format: JSON
#
# 3. WordPress REST API
#    - Endpoint: {site_url}/wp-json/wp/v2/posts
#    - Authentication: Optional (Basic Auth, JWT, Application Passwords)
#    - Response format: JSON
#    - Pagination: Use 'page' and 'per_page' parameters
#    - Filtering: categories, tags, search, author
#
# 4. Common patterns
#    - Implement retry logic with exponential backoff
#    - Handle rate limiting
#    - Cache responses when appropriate
#    - Store API credentials in Supabase api_credentials table
#    - Normalize all responses to common Document format
