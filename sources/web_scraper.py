"""Web scraper with LLM extraction for semantika.

Scrapes web pages respecting robots.txt and extracts content using LLM.
"""

from typing import List, Dict, Optional
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from utils.logger import get_logger
from utils.llm_client import get_llm_client

logger = get_logger("web_scraper")


class WebScraper:
    """Web scraper with robots.txt compliance and LLM extraction."""

    def __init__(self):
        """Initialize web scraper."""
        self.openrouter = get_llm_client()
        self.user_agent = "semantika-bot/0.1.0"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def _check_robots_txt(self, url: str) -> bool:
        """
        Check if URL is allowed by robots.txt.

        Args:
            url: URL to check

        Returns:
            True if allowed, False otherwise
        """
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            rp = RobotFileParser()
            rp.set_url(robots_url)
            rp.read()

            is_allowed = rp.can_fetch(self.user_agent, url)

            logger.info(
                "robots_txt_checked",
                url=url,
                allowed=is_allowed
            )

            return is_allowed

        except Exception as e:
            logger.warn("robots_txt_check_failed", url=url, error=str(e))
            # On error, be conservative and allow
            return True

    async def scrape_url(
        self,
        url: str,
        extract_multiple: bool = False,
        check_robots: bool = True
    ) -> List[Dict[str, str]]:
        """
        Scrape URL and extract content.

        Args:
            url: URL to scrape
            extract_multiple: Extract multiple articles/sections
            check_robots: Check robots.txt before scraping

        Returns:
            List of extracted documents with title and text
        """
        try:
            logger.info("scrape_start", url=url, extract_multiple=extract_multiple)

            # Check robots.txt
            if check_robots and not self._check_robots_txt(url):
                logger.warn("robots_txt_disallowed", url=url)
                return []

            # Fetch page
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            logger.debug("page_fetched", url=url, status=response.status_code)

            # Parse HTML
            soup = BeautifulSoup(response.content, "lxml")

            # Remove script and style elements
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()

            # Get HTML for LLM processing
            html_content = str(soup)

            # Extract content using LLM
            if extract_multiple:
                documents = await self.openrouter.extract_entities(html_content)
            else:
                # Single document extraction
                # Get main text
                text = soup.get_text(separator="\n", strip=True)
                # Clean up extra whitespace
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                text = "\n".join(lines)

                # Get title
                title = soup.title.string if soup.title else urlparse(url).path

                documents = [{
                    "title": title.strip(),
                    "text": text
                }]

            logger.info(
                "scrape_completed",
                url=url,
                documents_extracted=len(documents)
            )

            return documents

        except requests.exceptions.RequestException as e:
            logger.error("scrape_request_error", url=url, error=str(e))
            return []
        except Exception as e:
            logger.error("scrape_error", url=url, error=str(e))
            return []

    async def scrape_and_ingest(
        self,
        url: str,
        client_id: str,
        extract_multiple: bool = False,
        skip_guardrails: bool = False
    ) -> Dict[str, int]:
        """
        Scrape URL and ingest documents.

        Args:
            url: URL to scrape
            client_id: Client UUID
            extract_multiple: Extract multiple articles
            skip_guardrails: Skip PII/Copyright checks

        Returns:
            Dict with ingestion stats
        """
        from core_ingest import IngestPipeline

        try:
            # Scrape
            documents = await self.scrape_url(url, extract_multiple=extract_multiple)

            if not documents:
                return {
                    "documents_scraped": 0,
                    "documents_ingested": 0,
                    "errors": ["No documents extracted from URL"]
                }

            # Ingest each document
            pipeline = IngestPipeline(client_id=client_id)
            total_ingested = 0
            total_duplicates = 0
            errors = []

            for doc in documents:
                result = await pipeline.ingest_text(
                    text=doc["text"],
                    title=doc["title"],
                    metadata={
                        "source": "web",
                        "url": url,
                    },
                    skip_guardrails=skip_guardrails
                )

                total_ingested += result["documents_added"]
                total_duplicates += result["duplicates_skipped"]

                if result.get("errors"):
                    errors.extend(result["errors"])

            logger.info(
                "scrape_and_ingest_completed",
                url=url,
                documents_scraped=len(documents),
                documents_ingested=total_ingested,
                duplicates=total_duplicates
            )

            return {
                "documents_scraped": len(documents),
                "documents_ingested": total_ingested,
                "duplicates_skipped": total_duplicates,
                "errors": errors
            }

        except Exception as e:
            logger.error("scrape_and_ingest_error", url=url, error=str(e))
            return {
                "documents_scraped": 0,
                "documents_ingested": 0,
                "errors": [str(e)]
            }
