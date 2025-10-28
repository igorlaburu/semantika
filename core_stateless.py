"""Stateless processing pipeline for semantika.

Processes documents without storing in Qdrant. Returns immediate results.
Used for:
- Content analysis (title, summary, tags, atomic facts)
- Article generation with custom styles
- Style guide generation from example articles
"""

from typing import Dict, Any, List, Optional
from sources.web_scraper import WebScraper
from utils.openrouter_client import get_openrouter_client
from utils.logger import get_logger

logger = get_logger("stateless_pipeline")


class StatelessPipeline:
    """Pipeline for stateless document processing (no Qdrant storage)."""

    def __init__(self, organization_id: Optional[str] = None, client_id: Optional[str] = None):
        """
        Initialize stateless pipeline.

        Args:
            organization_id: Organization UUID (for usage tracking)
            client_id: Client UUID (for usage tracking)
        """
        self.openrouter = get_openrouter_client()
        self.organization_id = organization_id
        self.client_id = client_id
        logger.debug("stateless_pipeline_initialized")

    async def analyze(self, text: str) -> Dict[str, Any]:
        """
        Analyze text and extract: title, summary, tags.

        Args:
            text: Text to analyze

        Returns:
            Dict with title, summary, tags
        """
        logger.info("analyze_start", text_length=len(text))

        try:
            result = await self.openrouter.analyze(
                text=text,
                organization_id=self.organization_id,
                client_id=self.client_id
            )

            logger.info("analyze_completed", result_keys=list(result.keys()))
            return result

        except Exception as e:
            logger.error("analyze_error", error=str(e))
            raise

    async def analyze_atomic(self, text: str) -> Dict[str, Any]:
        """
        Analyze text and extract: title, summary, tags, atomic facts.

        Args:
            text: Text to analyze

        Returns:
            Dict with title, summary, tags, atomic_facts
        """
        logger.info("analyze_atomic_start", text_length=len(text))

        try:
            result = await self.openrouter.analyze_atomic(
                text=text,
                organization_id=self.organization_id,
                client_id=self.client_id
            )

            logger.info(
                "analyze_atomic_completed",
                atomic_facts_count=len(result.get("atomic_facts", []))
            )
            return result

        except Exception as e:
            logger.error("analyze_atomic_error", error=str(e))
            raise

    async def redact_news(
        self,
        text: str,
        style_guide: Optional[str] = None,
        language: str = "es"
    ) -> Dict[str, Any]:
        """
        Generate news article from text/facts with specific style.

        Args:
            text: Source text or atomic facts
            style_guide: Markdown style guide (optional)
            language: Target language (default: es)

        Returns:
            Dict with article, title, summary, tags
        """
        logger.info(
            "redact_news_start",
            text_length=len(text),
            has_style_guide=style_guide is not None,
            language=language
        )

        try:
            result = await self.openrouter.redact_news(
                text=text,
                style_guide=style_guide,
                language=language,
                organization_id=self.organization_id,
                client_id=self.client_id
            )

            logger.info(
                "redact_news_completed",
                article_length=len(result.get("article", ""))
            )
            return result

        except Exception as e:
            logger.error("redact_news_error", error=str(e))
            raise

    async def process_url(
        self,
        url: str,
        action: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Scrape URL and process content.

        Args:
            url: URL to scrape
            action: Action to perform (analyze, analyze_atomic, redact_news)
            params: Optional parameters for the action

        Returns:
            Processing result
        """
        logger.info("process_url_start", url=url, process_action=action)

        try:
            # Scrape URL (returns list of documents)
            scraper = WebScraper()
            documents = await scraper.scrape_url(url, extract_multiple=False)

            if not documents or len(documents) == 0:
                raise ValueError("No content extracted from URL")

            # Get first document text
            text = documents[0].get("text", "")

            if not text or len(text) < 100:
                raise ValueError("Insufficient content extracted from URL")

            logger.info("url_scraped", url=url, text_length=len(text))

            # Process based on action
            if action == "analyze":
                result = await self.analyze(text)
            elif action == "analyze_atomic":
                result = await self.analyze_atomic(text)
            elif action == "redact_news":
                params = params or {}
                result = await self.redact_news(
                    text=text,
                    style_guide=params.get("style_guide"),
                    language=params.get("language", "es")
                )
            else:
                raise ValueError(f"Unknown action: {action}")

            logger.info("process_url_completed", url=url, process_action=action)
            return result

        except Exception as e:
            logger.error("process_url_error", url=url, error=str(e))
            raise

    async def generate_style_guide(
        self,
        urls: List[str],
        style_name: str
    ) -> Dict[str, Any]:
        """
        Generate writing style guide from example articles.

        Args:
            urls: List of URLs to analyze
            style_name: Name for this style

        Returns:
            Dict with style_guide_markdown, articles_analyzed, etc.
        """
        logger.info(
            "generate_style_guide_start",
            style_name=style_name,
            urls_count=len(urls)
        )

        try:
            scraper = WebScraper()

            # 1. Scrape all URLs
            articles = []
            for url in urls[:20]:  # Limit to 20 articles
                try:
                    documents = await scraper.scrape_url(url, extract_multiple=False)
                    if documents and len(documents) > 0:
                        text = documents[0].get("text", "")
                        if text and len(text) > 200:
                            articles.append({
                                "url": url,
                                "text": text
                            })
                            logger.debug("article_scraped", url=url, length=len(text))
                except Exception as e:
                    logger.warn("article_scrape_failed", url=url, error=str(e))
                    continue

            if len(articles) < 3:
                raise ValueError(f"Insufficient articles scraped: {len(articles)}/20")

            logger.info("articles_scraped", count=len(articles))

            # 2. Analyze structure of each article
            article_analyses = []
            for article in articles[:15]:  # Analyze max 15
                try:
                    analysis = await self.openrouter.analyze_article_structure(
                        article["text"]
                    )
                    article_analyses.append(analysis)
                except Exception as e:
                    logger.warn("article_analysis_failed", error=str(e))
                    continue

            logger.info("articles_analyzed", count=len(article_analyses))

            # 3. Calculate statistics
            statistics = self._calculate_statistics(article_analyses)

            # 4. Select representative sample articles (3-5)
            sample_articles = [a["text"] for a in articles[:5]]

            # 5. Generate style guide with LLM
            style_guide_markdown = await self.openrouter.generate_style_guide(
                style_name=style_name,
                statistics=statistics,
                sample_articles=sample_articles,
                article_count=len(articles)
            )

            result = {
                "status": "ok",
                "style_name": style_name,
                "style_guide_markdown": style_guide_markdown,
                "articles_analyzed": len(articles),
                "articles_with_structure": len(article_analyses)
            }

            logger.info(
                "generate_style_guide_completed",
                style_name=style_name,
                articles_analyzed=len(articles)
            )

            return result

        except Exception as e:
            logger.error("generate_style_guide_error", error=str(e))
            raise

    def _calculate_statistics(self, analyses: List[Dict]) -> Dict[str, Any]:
        """Calculate aggregate statistics from article analyses."""
        if not analyses:
            return {}

        # Calculate averages
        avg_paragraphs = sum(a.get("paragraph_count", 0) for a in analyses) / len(analyses)
        avg_paragraph_length = sum(a.get("avg_paragraph_length_words", 0) for a in analyses) / len(analyses)
        avg_title_length = sum(a.get("title_length_words", 0) for a in analyses) / len(analyses)

        has_quotes_count = sum(1 for a in analyses if a.get("has_quotes", False))
        quote_percentage = (has_quotes_count / len(analyses)) * 100

        return {
            "avg_paragraph_count": round(avg_paragraphs, 1),
            "avg_paragraph_length_words": round(avg_paragraph_length, 1),
            "avg_title_length_words": round(avg_title_length, 1),
            "articles_with_quotes_percentage": round(quote_percentage, 1),
            "sample_size": len(analyses)
        }
