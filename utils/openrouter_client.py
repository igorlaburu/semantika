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

        # 5. Analyze Chain (title + summary + tags)
        analyze_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a content analyst. Extract key information from text."),
            ("user", """Analyze this content and extract:
- A clear, concise title
- A summary (2-3 sentences)
- 3-5 relevant tags

Text:
{text}

Respond in JSON:
{{"title": "...", "summary": "...", "tags": ["tag1", "tag2", ...]}}""")
        ])

        self.analyze_chain = RunnableSequence(
            analyze_prompt | self.llm_sonnet | JsonOutputParser()
        )

        # 6. Analyze Atomic Chain (title + summary + tags + atomic facts)
        analyze_atomic_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a content analyst specializing in fact extraction."),
            ("user", """Analyze this content and extract:
1. A clear, concise title
2. A summary (2-3 sentences)
3. 3-5 relevant tags
4. Atomic facts: self-contained statements of facts. Each fact should:
   - Be a complete sentence
   - Contain one single fact
   - Be independently understandable
   - Be factual and verifiable

Text:
{text}

Respond in JSON:
{{"title": "...", "summary": "...", "tags": [...], "atomic_facts": ["fact 1", "fact 2", ...]}}""")
        ])

        self.analyze_atomic_chain = RunnableSequence(
            analyze_atomic_prompt | self.llm_sonnet | JsonOutputParser()
        )

        # 7. Article Structure Analyzer Chain
        article_structure_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a structural analyst for news articles."),
            ("user", """Analyze the structure of this article:

Article:
{text}

Extract and respond in JSON:
{{
  "title": "exact title from article",
  "title_length_words": 10,
  "paragraph_count": 8,
  "avg_paragraph_length_words": 45,
  "has_quotes": true,
  "quote_percentage": 25,
  "lead_paragraph": "exact first paragraph",
  "closing_paragraph": "exact last paragraph"
}}""")
        ])

        self.article_structure_chain = RunnableSequence(
            article_structure_prompt | self.llm_sonnet | JsonOutputParser()
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

    async def analyze(self, text: str) -> Dict[str, Any]:
        """
        Analyze text and extract title, summary, tags.

        Args:
            text: Text to analyze

        Returns:
            Dict with title, summary, tags
        """
        try:
            result = await self.analyze_chain.ainvoke({
                "text": text[:8000]
            })

            logger.debug("analyze_completed", title_length=len(result.get("title", "")))
            return result

        except Exception as e:
            logger.error("analyze_error", error=str(e))
            return {"title": "", "summary": "", "tags": []}

    async def analyze_atomic(self, text: str) -> Dict[str, Any]:
        """
        Analyze text and extract title, summary, tags, atomic facts.

        Args:
            text: Text to analyze

        Returns:
            Dict with title, summary, tags, atomic_facts
        """
        try:
            result = await self.analyze_atomic_chain.ainvoke({
                "text": text[:8000]
            })

            logger.debug(
                "analyze_atomic_completed",
                atomic_facts=len(result.get("atomic_facts", []))
            )
            return result

        except Exception as e:
            logger.error("analyze_atomic_error", error=str(e))
            return {"title": "", "summary": "", "tags": [], "atomic_facts": []}

    async def analyze_article_structure(self, text: str) -> Dict[str, Any]:
        """
        Analyze article structure for style guide generation.

        Args:
            text: Article text

        Returns:
            Dict with structural analysis
        """
        try:
            result = await self.article_structure_chain.ainvoke({
                "text": text[:6000]
            })

            logger.debug("article_structure_analyzed", paragraphs=result.get("paragraph_count", 0))
            return result

        except Exception as e:
            logger.error("article_structure_error", error=str(e))
            return {}

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
            language: Target language

        Returns:
            Dict with article, title, summary, tags
        """
        try:
            # Build dynamic system prompt based on style guide
            if style_guide:
                system_prompt = f"""You are a professional journalist. Write news articles following this style guide:

{style_guide[:4000]}

Follow the style guide precisely in your writing."""
            else:
                system_prompt = f"""You are a professional journalist. Write clear, objective news articles in {language}.

Use:
- Inverted pyramid structure
- Active voice
- Short paragraphs (2-3 sentences)
- Neutral, professional tone
- Clear, specific titles"""

            # Create dynamic chain
            redact_prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("user", """Based on this source content, write a professional news article.

Source content:
{text}

Requirements:
- Write a complete, well-structured article
- Create an engaging, accurate title
- Write a brief summary (2-3 sentences)
- Generate 3-5 relevant tags
- Format article with clear paragraph breaks (use \\n\\n between paragraphs)
- Each paragraph should be 2-4 sentences
- NO advertisement blocks or meta-content

Respond in JSON:
{{"article": "Full article text...", "title": "...", "summary": "...", "tags": [...]}}""")
            ])

            redact_chain = RunnableSequence(
                redact_prompt | self.llm_sonnet | JsonOutputParser()
            )

            result = await redact_chain.ainvoke({"text": text[:8000]})

            logger.debug(
                "redact_news_completed",
                article_length=len(result.get("article", ""))
            )
            return result

        except Exception as e:
            logger.error("redact_news_error", error=str(e))
            return {"article": "", "title": "", "summary": "", "tags": []}

    async def generate_style_guide(
        self,
        style_name: str,
        statistics: Dict[str, Any],
        sample_articles: List[str],
        article_count: int
    ) -> str:
        """
        Generate comprehensive style guide in Markdown.

        Args:
            style_name: Name of the style
            statistics: Aggregate statistics from articles
            sample_articles: 3-5 representative articles
            article_count: Total number of articles analyzed

        Returns:
            Style guide in Markdown format
        """
        try:
            # Prepare statistics text
            stats_text = f"""
- Average article length: {statistics.get('avg_paragraph_count', 0)} paragraphs
- Average paragraph length: {statistics.get('avg_paragraph_length_words', 0)} words
- Average title length: {statistics.get('avg_title_length_words', 0)} words
- Articles with quotes: {statistics.get('articles_with_quotes_percentage', 0)}%
- Sample size: {statistics.get('sample_size', 0)} articles
"""

            # Prepare sample articles (limited)
            samples_text = "\n\n---ARTICLE---\n\n".join(sample_articles[:3])

            style_guide_prompt = ChatPromptTemplate.from_messages([
                ("system", "You are an expert editor creating detailed writing style guides."),
                ("user", """Based on analysis of {article_count} articles, generate a comprehensive style guide in Markdown format for: {style_name}

IMPORTANT: Focus ONLY on editorial content. IGNORE and EXCLUDE:
- Advertisement blocks (e.g., "PUBLICIDAD", "SIGUE LEYENDO")
- Navigation elements (menus, headers, footers)
- Social media sharing buttons
- Related article links
- Any non-editorial metadata

Statistical Analysis:
{statistics}

Sample Articles (use these for extracting real examples):
{samples}

Create a detailed style guide with these sections:

# Estilo: {style_name}

## Características Generales
(length, tone, perspective, based on statistics)

## Estructura del Titular
(length, style, active/passive voice)
- Include 2-3 REAL examples from the sample articles

## Apertura / Lead
(structure, length, what it answers)
- Include 1-2 REAL examples from sample articles

## Desarrollo del Cuerpo
(paragraph structure, progression)
- Include 1 REAL example paragraph with quote if available

## Tratamiento de Fuentes
(how sources are cited)
- Include REAL example if available

## Uso de Datos y Cifras
(how numbers are integrated)
- Include REAL example if available

## Cierre del Artículo
(closing style, last paragraph purpose)
- Include 1 REAL example from samples

## Vocabulario Característico
(typical verbs, terms, what to avoid)

## Ejemplo Completo de Artículo
(Include ONE complete article from the samples - choose the most representative one)

Use specific, concrete examples extracted from the actual articles. Be detailed and prescriptive.""")
            ])

            style_guide_chain = RunnableSequence(
                style_guide_prompt | self.llm_sonnet | StrOutputParser()
            )

            result = await style_guide_chain.ainvoke({
                "style_name": style_name,
                "article_count": article_count,
                "statistics": stats_text,
                "samples": samples_text[:15000]  # Limit to avoid token overflow
            })

            logger.info(
                "style_guide_generated",
                style_name=style_name,
                guide_length=len(result)
            )
            return result

        except Exception as e:
            logger.error("style_guide_generation_error", error=str(e))
            return f"# Error generating style guide\n\nError: {str(e)}"

    async def generate_context_unit(self, text: str) -> Dict[str, Any]:
        """
        Generate structured context unit from any content source.

        Analyzes content and extracts:
        - Title (clear, concise)
        - Summary (2-3 sentences)
        - Tags (3-7 keywords)
        - Atomic statements (ordered facts, questions, answers, quotes)

        Args:
            text: Aggregated content from any source

        Returns:
            Dict with title, summary, tags, atomic_statements
        """
        try:
            context_unit_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are an expert content analyzer and structurer.

Extract a structured context unit from the provided content. The content may be:
- A news article with facts
- An interview with questions and answers
- A primary news source
- Mixed content (email with attachments, transcriptions, etc.)

Your task:
1. Extract a clear TITLE (concise, informative)
2. Write a SUMMARY (2-3 sentences capturing essence)
3. Generate TAGS (3-7 relevant keywords)
4. Extract ATOMIC STATEMENTS in strict source order:
   - Each statement is ONE fact, question, answer, or quote
   - Preserve original order from source
   - If interview: identify speakers, mark questions/answers
   - If news: extract factual statements
   - Type each statement: fact, question, answer, quote, context

IMPORTANT:
- Maintain STRICT chronological order from source
- Each statement is independent and complete
- Include speaker attribution when identifiable
- Do NOT invent information
- NO advertisement blocks or meta-content"""),
                ("user", """Analyze this content and generate a context unit:

{text}

Respond in JSON:
{{
  "title": "Clear, concise title",
  "summary": "2-3 sentence summary",
  "tags": ["tag1", "tag2", ...],
  "atomic_statements": [
    {{
      "order": 1,
      "type": "fact|question|answer|quote|context",
      "speaker": "Name or null",
      "text": "Complete statement"
    }},
    ...
  ]
}}""")
            ])

            context_chain = RunnableSequence(
                context_unit_prompt | self.llm_sonnet | JsonOutputParser()
            )

            result = await context_chain.ainvoke({"text": text[:12000]})

            logger.debug(
                "context_unit_generated",
                statements_count=len(result.get("atomic_statements", []))
            )
            return result

        except Exception as e:
            logger.error("context_unit_generation_error", error=str(e))
            return {
                "title": "",
                "summary": "",
                "tags": [],
                "atomic_statements": []
            }


# Global OpenRouter client instance
_openrouter_client: Optional[OpenRouterClient] = None


def get_openrouter_client() -> OpenRouterClient:
    """Get or create OpenRouter client singleton."""
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = OpenRouterClient()
    return _openrouter_client
