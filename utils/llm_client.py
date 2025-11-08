"""LLM client for semantika using LangChain with multi-provider support.

Handles LLM interactions for guardrails, extraction, and aggregation.
Supports OpenRouter, Groq, and future providers with automatic cost tracking.
"""

from typing import Optional, List, Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.runnables import RunnableSequence

from .config import settings
from .logger import get_logger
from .llm_registry import get_llm_registry

logger = get_logger("llm_client")


class LLMClient:
    """Multi-provider LLM client using centralized registry."""

    def __init__(self):
        """Initialize LLM client with registry."""
        try:
            self.registry = get_llm_registry()
            
            # Get LLM instances from registry
            self.llm_sonnet_premium = self.registry.get('sonnet_premium')._client
            self.llm_fast = self.registry.get('fast')._client
            self.llm_sonnet = self.llm_fast  # Alias for backward compatibility
            
            # Groq models (if available)
            if settings.groq_api_key:
                self.llm_groq_fast = self.registry.get('groq_fast')._client
                self.llm_groq_writer = self.registry.get('groq_writer')._client
            
            # Initialize chains
            self._init_chains()

            logger.info("llm_client_initialized", models=self.registry.list_models())
        except Exception as e:
            logger.error("llm_client_initialization_failed", error=str(e))
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
        """Detect PII in text using LangChain chain."""
        try:
            result = await self.pii_chain.ainvoke({"text": text[:2000]})
            logger.debug("pii_detection_completed", has_pii=result.get("has_pii", False))
            return result
        except Exception as e:
            logger.error("pii_detection_error", error=str(e))
            return {"has_pii": False, "entities": []}

    async def anonymize_pii(self, text: str, entities: List[Dict]) -> str:
        """Anonymize PII entities in text."""
        anonymized = text
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
        """Detect copyrighted content using LangChain chain."""
        try:
            result = await self.copyright_chain.ainvoke({"text": text[:2000]})
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
        """Extract multiple semantic units from HTML using LangChain chain."""
        try:
            result = await self.extraction_chain.ainvoke({"html": html[:4000]})
            documents = result.get("documents", [])
            logger.info("entities_extracted", count=len(documents))
            return documents
        except Exception as e:
            logger.error("entity_extraction_error", error=str(e))
            return []

    async def aggregate_documents(self, documents: List[str], query: str) -> str:
        """Generate summary from multiple documents using LangChain chain."""
        try:
            combined_text = "\n\n---\n\n".join(documents[:10])

            summary = await self.aggregation_chain.ainvoke({
                "query": query,
                "documents": combined_text[:8000]
            })

            logger.info("documents_aggregated", documents_count=len(documents), query=query)
            return summary
        except Exception as e:
            logger.error("aggregation_error", error=str(e))
            return "Error generating summary."

    async def analyze(
        self,
        text: str,
        organization_id: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze text and extract title, summary, tags."""
        try:
            provider = self.registry.get('fast')
            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'analyze',
                    'client_id': client_id
                }

            # Call through provider for tracking
            response = await provider.ainvoke(
                self.analyze_chain.first.format_messages(text=text[:8000]),
                config=config
            )
            
            import json
            result = json.loads(response.content)
            logger.debug("analyze_completed", title_length=len(result.get("title", "")))
            return result
        except Exception as e:
            logger.error("analyze_error", error=str(e))
            return {"title": "", "summary": "", "tags": []}

    async def analyze_atomic(
        self,
        text: str,
        organization_id: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze text and extract title, summary, tags, atomic facts."""
        try:
            provider = self.registry.get('fast')
            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'analyze_atomic',
                    'client_id': client_id
                }

            response = await provider.ainvoke(
                self.analyze_atomic_chain.first.format_messages(text=text[:8000]),
                config=config
            )
            
            import json
            result = json.loads(response.content)
            logger.debug("analyze_atomic_completed", atomic_facts=len(result.get("atomic_facts", [])))
            return result
        except Exception as e:
            logger.error("analyze_atomic_error", error=str(e))
            return {"title": "", "summary": "", "tags": [], "atomic_facts": []}

    async def analyze_article_structure(self, text: str) -> Dict[str, Any]:
        """Analyze article structure for style guide generation."""
        try:
            result = await self.article_structure_chain.ainvoke({"text": text[:6000]})
            logger.debug("article_structure_analyzed", paragraphs=result.get("paragraph_count", 0))
            return result
        except Exception as e:
            logger.error("article_structure_error", error=str(e))
            return {}

    async def redact_news(
        self,
        text: str,
        style_guide: Optional[str] = None,
        language: str = "es",
        organization_id: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate news article from simple text or facts (SINGLE SOURCE)."""
        try:
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

            redact_prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("user", """Based on this source content, write a professional news article.

Source content:
{text}

CRITICAL REQUIREMENTS:
- Use ONLY information explicitly stated in the source content above
- Do NOT add facts, data, quotes, or details not present in the source
- Do NOT invent names, dates, locations, or statistics
- Do NOT make assumptions or inferences beyond what is stated
- If source lacks information, DO NOT fill gaps with invented content
- Every fact in your article MUST be traceable to the source content

Article structure:
- Write a complete, well-structured article
- Create an engaging, accurate title based ONLY on source content
- Write a brief summary (2-3 sentences) reflecting ONLY source information
- Generate 3-5 relevant tags from topics in the source
- Format article with clear paragraph breaks (use \\n\\n between paragraphs)
- Each paragraph should be 2-4 sentences
- NO advertisement blocks or meta-content

Formatting rules:
- Use **bold** for proper names (people, organizations, brands)
- Use **bold** for place names (cities, countries, regions)
- For sections with clearly defined context and substantial length (3+ paragraphs), add an H2 subtitle (## Subtitle)

IMPORTANT: Respond with ONLY raw JSON. Do NOT wrap in markdown code blocks or add any text before/after.

Response format:
{{"article": "Full article text...", "title": "...", "summary": "...", "tags": [...], "author": "Redacción"}}""")
            ])

            redact_chain = RunnableSequence(
                redact_prompt | self.registry.get('sonnet_premium') | JsonOutputParser()
            )

            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'redact_news',
                    'client_id': client_id
                }

            result = await redact_chain.ainvoke(
                {"text": text[:8000]},
                config=config
            )

            logger.debug("redact_news_completed", article_length=len(result.get("article", "")))
            return result
        except Exception as e:
            logger.error("redact_news_error", error=str(e))
            return {"article": "", "title": "", "summary": "", "tags": []}

    async def redact_news_rich(
        self,
        source_text: str,
        title_suggestion: str = "",
        instructions: str = "",
        style_guide: Optional[str] = None,
        language: str = "es",
        organization_id: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate RICH news article from MULTIPLE context units with advanced controls."""
        try:
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

            if title_suggestion and instructions:
                user_instructions = f"""Title suggestion: {title_suggestion}

Additional instructions: {instructions}

Follow the title suggestion and instructions when writing the article."""
            elif title_suggestion:
                user_instructions = f"""Title suggestion: {title_suggestion}

Use this title or similar when writing the article."""
            elif instructions:
                user_instructions = f"""Additional instructions: {instructions}

Follow these instructions when writing the article."""
            else:
                user_instructions = "Generate an appropriate title and write the article freely based on the sources."

            redact_rich_prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("user", """Based on these source materials from multiple context units, write a comprehensive news article.

{user_instructions}

Source materials:
{source_text}

CRITICAL REQUIREMENTS:
- Use ONLY information explicitly stated in the source materials above
- Do NOT add facts, data, quotes, or details not present in the sources
- Do NOT invent names, dates, locations, or statistics
- Do NOT make assumptions or inferences beyond what is stated
- If sources lack information, DO NOT fill gaps with invented content
- Every fact in your article MUST be traceable to the source materials

Article structure:
- Write a complete, well-structured article that SYNTHESIZES information from ALL provided sources
- ALL sources marked with ## headers MUST be represented in the article - do not ignore any source
- Create an engaging, accurate title based ONLY on source content
- Write a brief summary (2-3 sentences) reflecting ONLY source information from ALL sources
- Generate 3-5 relevant tags from topics in ALL the sources
- Format article with clear paragraph breaks (use \\n\\n between paragraphs)
- Each paragraph should be 2-4 sentences
- Integrate facts and information from ALL context units provided, not just the first one
- NO advertisement blocks or meta-content

Formatting rules:
- Use **bold** for proper names (people, organizations, brands)
- Use **bold** for place names (cities, countries, regions)
- For sections with clearly defined context and substantial length (3+ paragraphs), add an H2 subtitle (## Subtitle)

IMPORTANT: Respond with ONLY raw JSON. Do NOT wrap in markdown code blocks or add any text before/after.

Response format:
{{"article": "Full article text...", "title": "...", "summary": "...", "tags": [...], "author": "Redacción"}}""")
            ])

            redact_rich_chain = RunnableSequence(
                redact_rich_prompt | self.registry.get('sonnet_premium') | JsonOutputParser()
            )

            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'redact_news_rich',
                    'client_id': client_id
                }

            result = await redact_rich_chain.ainvoke(
                {
                    "source_text": source_text[:12000],
                    "user_instructions": user_instructions
                },
                config=config
            )

            logger.debug("redact_news_rich_completed", article_length=len(result.get("article", "")))
            return result
        except Exception as e:
            logger.error("redact_news_rich_error", error=str(e))
            return {"article": "", "title": "", "summary": "", "tags": []}

    async def generate_style_guide(
        self,
        style_name: str,
        statistics: Dict[str, Any],
        sample_articles: List[str],
        article_count: int
    ) -> str:
        """Generate comprehensive style guide in Markdown."""
        try:
            stats_text = f"""
- Average article length: {statistics.get('avg_paragraph_count', 0)} paragraphs
- Average paragraph length: {statistics.get('avg_paragraph_length_words', 0)} words
- Average title length: {statistics.get('avg_title_length_words', 0)} words
- Articles with quotes: {statistics.get('articles_with_quotes_percentage', 0)}%
- Sample size: {statistics.get('sample_size', 0)} articles
"""

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
                "samples": samples_text[:15000]
            })

            logger.info("style_guide_generated", style_name=style_name, guide_length=len(result))
            return result
        except Exception as e:
            logger.error("style_guide_generation_error", error=str(e))
            return f"# Error generating style guide\n\nError: {str(e)}"

    async def generate_context_unit(
        self,
        text: str,
        organization_id: Optional[str] = None,
        context_unit_id: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate structured context unit from any content source."""
        try:
            context_unit_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are an expert content analyzer and structurer.

Extract a structured context unit from the provided content. The content may be:
- A news article with facts
- An interview with questions and answers
- A primary news source
- Mixed content (email with attachments, transcriptions, etc.)

Your task:
1. Extract a clear TITLE (concise, informative) in SPANISH
2. Write a SUMMARY (2-3 sentences capturing essence) in SPANISH
3. Generate TAGS (3-7 relevant keywords) in SPANISH
4. Extract ATOMIC STATEMENTS in strict source order:
   - Each statement is ONE fact, question, answer, or quote
   - Preserve original order from source
   - If interview: identify speakers, mark questions/answers clearly
   - If news: extract factual statements
   - Type each statement PRECISELY:
     * "fact" - A verifiable factual statement (e.g., dates, events, data)
     * "quote" - Direct quote from a person (use quotation marks)
     * "question" - A question asked (from interview/Q&A)
     * "answer" - An answer given (from interview/Q&A)
     * "context" - Background or contextual information
   - Write ALL statements in SPANISH

IMPORTANT:
- ALL OUTPUT (title, summary, tags, statements) MUST be in SPANISH
- Maintain STRICT chronological order from source
- Each statement is independent and complete
- Include speaker attribution when identifiable
- Do NOT invent information
- NO advertisement blocks or meta-content
- Use EXACT type labels: fact, quote, question, answer, or context"""),
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
      "type": "fact|quote|question|answer|context",
      "speaker": "Name or null",
      "text": "Complete statement"
    }},
    ...
  ]
}}""")
            ])

            provider = self.registry.get('fast')
            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'context_unit',
                    'context_unit_id': context_unit_id,
                    'client_id': client_id
                }

            response = await provider.ainvoke(
                context_unit_prompt.format_messages(text=text[:12000]),
                config=config
            )

            import json
            result = json.loads(response.content)
            logger.debug("context_unit_generated", statements_count=len(result.get("atomic_statements", [])))
            return result
        except Exception as e:
            logger.error("context_unit_generation_error", error=str(e))
            return {
                "title": "",
                "summary": "",
                "tags": [],
                "atomic_statements": []
            }

    async def micro_edit(
        self,
        text: str,
        command: str,
        context: Optional[str] = None,
        language: str = "es",
        preserve_meaning: bool = True,
        style_guide: Optional[str] = None,
        max_length: Optional[int] = None,
        organization_id: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Perform micro-editing on text using Groq ultrafast LLM."""
        try:
            system_parts = [
                f"Eres un editor experto de textos en {language}.",
                "Tu tarea es realizar micro-ediciones siguiendo las instrucciones específicas del usuario."
            ]

            if preserve_meaning:
                system_parts.append("IMPORTANTE: Preserva siempre el significado original del texto.")

            if style_guide:
                system_parts.append(f"Sigue esta guía de estilo:\n\n{style_guide[:2000]}")

            if max_length:
                system_parts.append(f"El texto editado no debe exceder {max_length} caracteres.")

            system_prompt = "\n\n".join(system_parts)

            user_parts = [
                f"Texto original:\n{text}",
                f"Instrucción: {command}"
            ]

            if context:
                user_parts.append(f"Contexto: {context}")

            user_parts.append("""
Responde SOLO con JSON válido, sin texto adicional:
{{"edited_text": "texto editado siguiendo la instrucción", "explanation": "breve explicación de los cambios realizados"}}""")

            user_prompt = "\n\n".join(user_parts)

            micro_edit_prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("user", user_prompt)
            ])

            # Use Groq writer model for micro-edits (ultrafast)
            provider = self.registry.get('groq_writer') if settings.groq_api_key else self.registry.get('fast')
            
            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'micro_edit',
                    'client_id': client_id
                }

            response = await provider.ainvoke(
                micro_edit_prompt.format_messages(),
                config=config
            )

            import json
            try:
                result = json.loads(response.content)
            except Exception as e:
                logger.error("micro_edit_json_parsing_failed", error=str(e), content=response.content[:500])
                return {
                    "original_text": text,
                    "edited_text": text,
                    "explanation": f"Error parsing JSON: {str(e)}",
                    "word_count_change": 0
                }

            original_words = len(text.split())
            edited_words = len(result.get("edited_text", "").split())
            word_count_change = edited_words - original_words

            response = {
                "original_text": text,
                "edited_text": result.get("edited_text", text),
                "explanation": result.get("explanation", ""),
                "word_count_change": word_count_change
            }

            logger.info("micro_edit_completed",
                original_length=len(text),
                edited_length=len(response["edited_text"]),
                word_count_change=word_count_change,
                provider=provider.get_provider_name()
            )

            return response
        except Exception as e:
            logger.error("micro_edit_error", error=str(e))
            return {
                "original_text": text,
                "edited_text": text,
                "explanation": f"Error: {str(e)}",
                "word_count_change": 0
            }


# Global LLM client instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


# Backward compatibility alias
get_openrouter_client = get_llm_client
OpenRouterClient = LLMClient
