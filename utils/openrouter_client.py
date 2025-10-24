"""OpenRouter client for semantika.

Handles LLM interactions for guardrails, extraction, and aggregation.
"""

from typing import Optional, List, Dict, Any
from openai import OpenAI

from .config import settings
from .logger import get_logger

logger = get_logger("openrouter_client")


class OpenRouterClient:
    """OpenRouter client wrapper for semantika."""

    def __init__(self):
        """Initialize OpenRouter client."""
        try:
            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.openrouter_api_key
            )
            logger.info("openrouter_connected")
        except Exception as e:
            logger.error("openrouter_connection_failed", error=str(e))
            raise

    async def detect_pii(self, text: str) -> Dict[str, Any]:
        """
        Detect PII in text.

        Args:
            text: Text to analyze

        Returns:
            Dict with has_pii (bool) and entities (list)
        """
        try:
            prompt = f"""Analyze the following text and detect any PII (Personally Identifiable Information).

Look for: names, emails, phone numbers, addresses, IDs, credit cards, etc.

Text:
{text[:2000]}

Respond in JSON format:
{{"has_pii": true/false, "entities": [{{"type": "email", "value": "example@test.com", "start": 10, "end": 25}}]}}"""

            response = self.client.chat.completions.create(
                model="anthropic/claude-3.5-sonnet",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500
            )

            result_text = response.choices[0].message.content

            # Parse JSON response
            import json
            result = json.loads(result_text.strip())

            logger.debug("pii_detection_completed", has_pii=result.get("has_pii", False))
            return result

        except Exception as e:
            logger.error("pii_detection_error", error=str(e))
            return {"has_pii": False, "entities": []}

    async def anonymize_pii(self, text: str, entities: List[Dict]) -> str:
        """
        Anonymize PII entities in text.

        Args:
            text: Original text
            entities: List of PII entities to redact

        Returns:
            Anonymized text
        """
        anonymized = text

        # Sort entities by start position (reverse) to maintain offsets
        sorted_entities = sorted(entities, key=lambda x: x.get("start", 0), reverse=True)

        for entity in sorted_entities:
            entity_type = entity.get("type", "REDACTED")
            start = entity.get("start")
            end = entity.get("end")

            if start is not None and end is not None:
                anonymized = anonymized[:start] + f"[{entity_type.upper()}]" + anonymized[end:]

        logger.info("pii_anonymized", entities_count=len(entities))
        return anonymized

    async def detect_copyright(self, text: str) -> Dict[str, Any]:
        """
        Detect copyrighted content.

        Args:
            text: Text to analyze

        Returns:
            Dict with is_copyrighted (bool) and confidence (float)
        """
        try:
            prompt = f"""Analyze if the following text contains copyrighted material (articles, books, song lyrics, movie scripts, etc.).

Text:
{text[:2000]}

Respond in JSON format:
{{"is_copyrighted": true/false, "confidence": 0.0-1.0, "reason": "explanation"}}"""

            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=300
            )

            result_text = response.choices[0].message.content

            # Parse JSON response
            import json
            result = json.loads(result_text.strip())

            logger.debug(
                "copyright_detection_completed",
                is_copyrighted=result.get("is_copyrighted", False),
                confidence=result.get("confidence", 0.0)
            )
            return result

        except Exception as e:
            logger.error("copyright_detection_error", error=str(e))
            return {"is_copyrighted": False, "confidence": 0.0, "reason": "error"}

    async def extract_entities(self, html: str) -> List[Dict[str, str]]:
        """
        Extract multiple semantic units from HTML.

        Args:
            html: HTML content

        Returns:
            List of extracted documents with title and text
        """
        try:
            prompt = f"""Extract all meaningful content units from this HTML (articles, sections, blog posts, etc.).

For each unit, extract:
- title: Clear title or heading
- text: Main content (clean text, no HTML)

HTML:
{html[:4000]}

Respond in JSON format:
{{"documents": [{{"title": "...", "text": "..."}}, ...]}}"""

            response = self.client.chat.completions.create(
                model="anthropic/claude-3.5-sonnet",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=4000
            )

            result_text = response.choices[0].message.content

            # Parse JSON response
            import json
            result = json.loads(result_text.strip())

            documents = result.get("documents", [])
            logger.info("entities_extracted", count=len(documents))
            return documents

        except Exception as e:
            logger.error("entity_extraction_error", error=str(e))
            return []

    async def aggregate_documents(self, documents: List[str], query: str) -> str:
        """
        Generate summary from multiple documents.

        Args:
            documents: List of document texts
            query: Original search query

        Returns:
            Generated summary
        """
        try:
            combined_text = "\n\n---\n\n".join(documents[:10])  # Limit to 10 docs

            prompt = f"""Based on these documents, generate a comprehensive answer to the query: "{query}"

Documents:
{combined_text[:8000]}

Generate a well-structured, informative summary that directly answers the query."""

            response = self.client.chat.completions.create(
                model="anthropic/claude-3.5-sonnet",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500
            )

            summary = response.choices[0].message.content

            logger.info("documents_aggregated", documents_count=len(documents), query=query)
            return summary

        except Exception as e:
            logger.error("aggregation_error", error=str(e))
            return "Error generating summary."


# Global OpenRouter client instance
_openrouter_client: Optional[OpenRouterClient] = None


def get_openrouter_client() -> OpenRouterClient:
    """Get or create OpenRouter client singleton."""
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = OpenRouterClient()
    return _openrouter_client
