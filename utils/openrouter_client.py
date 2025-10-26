"""OpenRouter client for semantika using LangChain.

Handles LLM interactions for guardrails, extraction, and aggregation using LangChain chains.
"""

from typing import Optional, List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.runnables import RunnableSequence

from .config import settings
from .logger import get_logger

logger = get_logger("openrouter_client")


class OpenRouterClient:
    """OpenRouter client wrapper using LangChain chains."""

    def __init__(self):
        """Initialize OpenRouter client with LangChain."""
        try:
            # Initialize LLM clients for different use cases
            self.llm_sonnet = ChatOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.openrouter_api_key,
                model="anthropic/claude-3.5-sonnet",
                temperature=0.0
            )

            self.llm_fast = ChatOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.openrouter_api_key,
                model="openai/gpt-4o-mini",
                temperature=0.0
            )

            # Initialize chains
            self._init_chains()

            logger.info("openrouter_connected")
        except Exception as e:
            logger.error("openrouter_connection_failed", error=str(e))
            raise

    def _init_chains(self):
        """Initialize all LangChain chains."""

        # 1. PII Detection Chain
        pii_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a PII detection system. Analyze text and detect any Personally Identifiable Information."),
            ("user", """Analyze the following text and detect any PII (Personally Identifiable Information).

Look for: names, emails, phone numbers, addresses, IDs, credit cards, etc.

Text:
{text}

Respond in JSON format:
{{"has_pii": true/false, "entities": [{{"type": "email", "value": "example@test.com", "start": 10, "end": 25}}]}}""")
        ])

        self.pii_chain = RunnableSequence(
            pii_prompt | self.llm_sonnet | JsonOutputParser()
        )

        # 2. Copyright Detection Chain
        copyright_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a copyright detection system. Analyze if text contains copyrighted material."),
            ("user", """Analyze if the following text contains copyrighted material (articles, books, song lyrics, movie scripts, etc.).

Text:
{text}

Respond in JSON format:
{{"is_copyrighted": true/false, "confidence": 0.0-1.0, "reason": "explanation"}}""")
        ])

        self.copyright_chain = RunnableSequence(
            copyright_prompt | self.llm_fast | JsonOutputParser()
        )

        # 3. Entity Extraction Chain (multiple articles from HTML)
        extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a content extraction system. Extract all meaningful content units from HTML."),
            ("user", """Extract all meaningful content units from this HTML (articles, sections, blog posts, etc.).

For each unit, extract:
- title: Clear title or heading
- text: Main content (clean text, no HTML)

HTML:
{html}

Respond in JSON format:
{{"documents": [{{"title": "...", "text": "..."}}, ...]}}""")
        ])

        self.extraction_chain = RunnableSequence(
            extraction_prompt | self.llm_sonnet | JsonOutputParser()
        )

        # 4. Document Aggregation Chain
        aggregation_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a summarization system. Generate comprehensive summaries from multiple documents."),
            ("user", """Based on these documents, generate a comprehensive answer to the query: "{query}"

Documents:
{documents}

Generate a well-structured, informative summary that directly answers the query.""")
        ])

        self.aggregation_chain = RunnableSequence(
            aggregation_prompt | self.llm_sonnet | StrOutputParser()
        )

    async def detect_pii(self, text: str) -> Dict[str, Any]:
        """
        Detect PII in text using LangChain chain.

        Args:
            text: Text to analyze

        Returns:
            Dict with has_pii (bool) and entities (list)
        """
        try:
            result = await self.pii_chain.ainvoke({
                "text": text[:2000]
            })

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
        Detect copyrighted content using LangChain chain.

        Args:
            text: Text to analyze

        Returns:
            Dict with is_copyrighted (bool) and confidence (float)
        """
        try:
            result = await self.copyright_chain.ainvoke({
                "text": text[:2000]
            })

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
        Extract multiple semantic units from HTML using LangChain chain.

        Args:
            html: HTML content

        Returns:
            List of extracted documents with title and text
        """
        try:
            result = await self.extraction_chain.ainvoke({
                "html": html[:4000]
            })

            documents = result.get("documents", [])
            logger.info("entities_extracted", count=len(documents))
            return documents

        except Exception as e:
            logger.error("entity_extraction_error", error=str(e))
            return []

    async def aggregate_documents(self, documents: List[str], query: str) -> str:
        """
        Generate summary from multiple documents using LangChain chain.

        Args:
            documents: List of document texts
            query: Original search query

        Returns:
            Generated summary
        """
        try:
            combined_text = "\n\n---\n\n".join(documents[:10])  # Limit to 10 docs

            summary = await self.aggregation_chain.ainvoke({
                "query": query,
                "documents": combined_text[:8000]
            })

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
