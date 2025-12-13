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


def _log_llm_error(operation: str, error: Exception):
    """Log LLM errors with special handling for credit/quota issues.

    Args:
        operation: Name of the operation that failed
        error: The exception that occurred
    """
    error_str = str(error)

    # Detect credit/quota errors (402, "credit", "afford", "quota", "limit exceeded")
    if any(keyword in error_str.lower() for keyword in ["402", "credit", "afford", "quota", "limit exceeded"]):
        logger.error(f"{operation}_credit_error",
            error=error_str,
            error_type="INSUFFICIENT_CREDITS",
            message=f"⚠️  CRITICAL: OpenRouter credits exhausted or max_tokens too high for {operation}"
        )
    else:
        import traceback
        logger.error(f"{operation}_error",
            error=error_str,
            error_type=type(error).__name__,
            traceback=traceback.format_exc()
        )


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

        # 6. Analyze Atomic Chain (title + summary + tags + atomic facts + category)
        analyze_atomic_prompt = ChatPromptTemplate.from_messages([
            ("system", "Extractor de hechos atómicos."),
            ("user", """Extrae hechos del texto. IGNORA: menús, footers, descripciones genéricas.

Si NO hay contenido noticioso:
{{"title": "Sin contenido noticioso", "summary": "Sin información novedosa", "tags": [], "atomic_facts": [], "category": "general", "locations": []}}

Si HAY contenido, extrae:
1. Título
2. Resumen (3 frases)
3. 5-10 tags
4. 10-20 hechos: {{"order": N, "type": "fact"/"quote"/"context", "speaker": null/"Name", "text": "..."}}
5. Categoría (UNA): política, economía, sociedad, cultura, deportes, tecnología, medio_ambiente, infraestructuras, seguridad, salud, turismo, internacional, general
6. Ubicaciones (con jerarquía):
   - level: "primary" (ciudad principal del evento) o "context" (provincia/región/país)
   - type: "city", "province", "region", "country"
   Ejemplo: [{{"name": "Vitoria-Gasteiz", "type": "city", "level": "primary"}}, {{"name": "Álava", "type": "province", "level": "context"}}, {{"name": "España", "type": "country", "level": "context"}}]
   Si NO hay ubicaciones específicas: "locations": []

Texto:
{text}

JSON:
{{"title": "...", "summary": "...", "tags": [...], "atomic_facts": [...], "category": "...", "locations": [...]}}""")
        ])

        self.analyze_atomic_chain = RunnableSequence(
            analyze_atomic_prompt | self.llm_sonnet | JsonOutputParser()
        )
        
        # 6b. Extract News Links from Index (for index pages)
        extract_links_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a news link extractor. Identify real news articles from HTML."),
            ("user", """Analyze this HTML from a news index page.
Extract ONLY links to actual news articles (ignore menus, footers, navigation, etc.).

For each news article, extract:
- title: Article title from link text or nearby heading
- url: Full article URL (make absolute if relative)
- date: Publication date if visible (ISO format YYYY-MM-DD, or null)

Return the 10 MOST RECENT news articles.

HTML:
{html}

Base URL (for making relative URLs absolute): {base_url}

Respond in JSON:
{{"articles": [{{"title": "...", "url": "...", "date": "2025-11-10" or null}}, ...]}}""")
        ])
        
        self.extract_links_chain = RunnableSequence(
            extract_links_prompt | self.llm_fast | JsonOutputParser()  # Changed from groq_fast to fast (gpt-4o-mini) to avoid rate limits
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
        company_id: Optional[str] = None,
        client_id: Optional[str] = None  # Deprecated, kept for backward compatibility
    ) -> Dict[str, Any]:
        """Analyze text and extract title, summary, tags, atomic facts.

        Uses Groq Llama 3.3 70B (fast and free) for scraping tasks.
        """
        import json

        try:
            # Use Groq for fast, free processing (ideal for scraping)
            provider = self.registry.get('groq_fast')
            config = {}
            if company_id:
                config['tracking'] = {
                    'company_id': company_id,
                    'operation': 'analyze_atomic'
                }

            logger.debug("analyze_atomic_start",
                text_length=len(text),
                slice_length=min(len(text), 8000)
            )

            response = await provider.ainvoke(
                self.analyze_atomic_chain.first.format_messages(text=text[:8000]),
                config=config
            )

            logger.info("analyze_atomic_groq_response_received",
                response_length=len(response.content),
                response_preview=response.content[:200]
            )

            # Clean response content (remove markdown if present)
            content = response.content
            if content.startswith("```json"):
                content = content[7:]
                logger.debug("analyze_atomic_stripped_markdown", type="json")
            elif content.startswith("```"):
                content = content[3:]
                logger.debug("analyze_atomic_stripped_markdown", type="generic")
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            logger.debug("analyze_atomic_parsing_json",
                content_length=len(content),
                content_preview=content[:200]
            )

            result = json.loads(content)

            logger.info("analyze_atomic_completed",
                atomic_facts=len(result.get("atomic_facts", [])),
                has_title=bool(result.get("title")),
                has_summary=bool(result.get("summary")),
                provider="groq_fast"
            )
            return result
        except json.JSONDecodeError as e:
            logger.error("analyze_atomic_json_error",
                error=str(e),
                content_preview=content[:300] if 'content' in locals() else 'N/A'
            )
            return {"title": "", "summary": "", "tags": [], "atomic_facts": []}
        except Exception as e:
            logger.error("analyze_atomic_error",
                error=str(e),
                error_type=type(e).__name__
            )
            return {"title": "", "summary": "", "tags": [], "atomic_facts": []}
    
    async def search_original_source(
        self,
        headline: str,
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search for original public source of a news headline.
        
        Delegates to discovery_search module which routes between:
        - groq_compound: Groq Compound model (free, rate limited)
        - tavily_openai: Tavily Search + OpenAI o1-mini (paid, reliable)
        
        Provider configured via DISCOVERY_SEARCH_PROVIDER env var.
        
        Args:
            headline: News headline to search for
            organization_id: Organization ID for tracking (legacy, kept for compatibility)
            
        Returns:
            Dict with sources: [{"url": "...", "type": "press_room"|"media", "title": "..."}, ...]
        """
        from utils.discovery_search import search_original_source as search_impl
        
        try:
            logger.debug("search_original_source_start", headline=headline[:100])
            
            # Delegate to discovery_search module (handles provider routing)
            source_url = await search_impl(headline, snippet="")
            
            if not source_url:
                logger.debug("no_original_source_found", headline=headline[:100])
                return {"sources": []}
            
            # Return in expected format (legacy compatibility)
            return {
                "sources": [{
                    "url": source_url,
                    "type": "institutional",
                    "title": headline[:100],
                    "organization": ""  # Could extract domain name if needed
                }]
            }
            
        except Exception as e:
            logger.error("search_original_source_error",
                headline=headline[:100],
                error_type=type(e).__name__,
                error=str(e)
            )
            return {"sources": []}
    
    async def search_original_source_legacy(
        self,
        headline: str,
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """LEGACY: Old Groq Compound implementation (kept for reference).
        
        This method is no longer used but kept for backward compatibility.
        Use search_original_source() instead which delegates to discovery_search module.
        """
        import json
        
        try:
            # Get SYSTEM organization ID if not provided
            if not organization_id:
                from utils.supabase_client import get_supabase_client
                supabase = get_supabase_client()
                system_org = supabase.client.table('organizations')\
                    .select('id')\
                    .eq('slug', 'system')\
                    .execute()
                if system_org.data:
                    organization_id = system_org.data[0]['id']
                else:
                    logger.warn("system_org_not_found", message="SYSTEM org not found, skipping tracking")
                    organization_id = None
            
            provider = self.registry.get('groq_compound')
            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'search_original_source'
                }
            
            prompt = f"""Busca la FUENTE ORIGINAL PÚBLICA de esta noticia:

"{headline}"

IMPORTANTE:
- Busca salas de prensa corporativas (.com/newsroom, .es/sala-prensa, etc.)
- Busca comunicados de ayuntamientos, instituciones públicas
- Ignora medios generalistas (abc.es, elmundo.es, etc.)
- Si no hay fuente pública clara, devuelve lista vacía

Responde en JSON:
{{
    "sources": [
        {{
            "url": "https://empresa.com/newsroom/comunicado-123",
            "type": "press_room",
            "title": "Título del comunicado original",
            "organization": "Nombre organización"
        }}
    ]
}}

Si NO encuentras fuente pública original, devuelve: {{"sources": []}}"""

            logger.debug("search_original_source_start", headline=headline[:100])
            
            # Groq Compound expects messages array (not LangChain messages)
            messages = [{"role": "user", "content": prompt}]
            
            response = await provider.ainvoke(messages, config=config)
            
            # Groq Compound returns different response format
            content = response.choices[0].message.content
            
            logger.info("search_original_source_response_received",
                response_length=len(content),
                response_preview=content[:200]
            )
            
            # Clean markdown and extract JSON
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Extract JSON object (handle LLM returning text before JSON)
            json_start = content.find('{')
            json_end = content.rfind('}')
            
            if json_start == -1 or json_end == -1:
                logger.error("search_original_source_no_json",
                    headline=headline[:100],
                    content_preview=content[:500]
                )
                return {"sources": []}
            
            content = content[json_start:json_end+1]
            
            logger.debug("search_original_source_parsing_json", content_preview=content[:200])
            
            result = json.loads(content)
            
            logger.info("search_original_source_completed",
                sources_found=len(result.get("sources", [])),
                provider="groq_compound"
            )
            
            return result
        
        except Exception as e:
            logger.error("search_original_source_error",
                headline=headline[:100],
                error=str(e),
                error_type=type(e).__name__
            )
            return {"sources": []}
    
    async def extract_news_links(
        self,
        html: str,
        base_url: str,
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Extract news article links from index page HTML using Groq.
        
        Args:
            html: HTML content of index page
            base_url: Base URL for making relative URLs absolute
            organization_id: Organization UUID for tracking
            
        Returns:
            Dict with articles: [{"title": "...", "url": "...", "date": "..."}, ...]
        """
        try:
            provider = self.registry.get('groq_fast')
            config = {}
            if organization_id:
                config['tracking'] = {
                    'organization_id': organization_id,
                    'operation': 'extract_news_links'
                }
            
            # Clean HTML: remove scripts, styles to maximize useful content
            from bs4 import BeautifulSoup
            import json

            logger.info("extract_news_links_html_cleaning_start",
                html_original_length=len(html),
                base_url=base_url
            )

            soup = BeautifulSoup(html, 'html.parser')

            # Count elements before cleaning
            scripts_count = len(soup.find_all('script'))
            styles_count = len(soup.find_all('style'))
            iframes_count = len(soup.find_all('iframe'))

            logger.debug("extract_news_links_html_elements",
                scripts=scripts_count,
                styles=styles_count,
                iframes=iframes_count
            )

            # Remove scripts, styles, iframes
            for tag in soup(['script', 'style', 'iframe']):
                tag.decompose()

            # Extract only body content (skip head entirely)
            body = soup.find('body')
            if body:
                cleaned_html = str(body)
                logger.debug("extract_news_links_body_extracted", body_found=True)
            else:
                cleaned_html = str(soup)
                logger.warn("extract_news_links_no_body_found", using_full_html=True)

            # Limit to 30k chars (~9k tokens, well under 12k Groq limit)
            slice_size = 30000
            html_slice = cleaned_html[:slice_size]

            logger.info("extract_news_links_html_cleaned",
                original_length=len(html),
                cleaned_length=len(cleaned_html),
                slice_length=len(html_slice),
                html_preview=html_slice[:500]
            )

            response = await provider.ainvoke(
                self.extract_links_chain.first.format_messages(
                    html=html_slice,
                    base_url=base_url
                ),
                config=config
            )

            logger.info("extract_news_links_groq_response_received",
                response_length=len(response.content),
                response_preview=response.content[:200]
            )

            # Clean response content (remove markdown if present)
            content = response.content
            if content.startswith("```json"):
                content = content[7:]
                logger.debug("extract_news_links_stripped_markdown", type="json")
            elif content.startswith("```"):
                content = content[3:]
                logger.debug("extract_news_links_stripped_markdown", type="generic")
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            logger.info("extract_news_links_parsing_json",
                content_length=len(content),
                content_preview=content[:300]
            )

            result = json.loads(content)
            logger.info("extract_news_links_completed",
                articles_found=len(result.get("articles", [])),
                provider="groq_fast"
            )
            return result
        except json.JSONDecodeError as e:
            logger.error("extract_news_links_json_error",
                error=str(e),
                content_preview=content[:200] if 'content' in locals() else 'N/A'
            )
            return {"articles": []}
        except Exception as e:
            logger.error("extract_news_links_error", error=str(e))
            return {"articles": []}

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
                system_prompt = f"""You are a professional journalist. Write clear, objective, comprehensive news articles in {language}.

Use:
- Inverted pyramid structure
- Active voice
- Well-developed paragraphs (3-5 sentences each)
- Neutral, professional tone
- Clear, specific titles
- Thorough coverage of all available information"""

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
- Write a COMPREHENSIVE, well-developed article
- Create an engaging, accurate title based ONLY on source content
- Write a brief summary (2-3 sentences) reflecting ONLY source information
- Generate 3-5 relevant tags from topics in the source
- Format article with clear paragraph breaks (use \\n\\n between paragraphs)
- Each paragraph should be well-developed with 3-5 sentences providing context, details, and background
- Aim for a complete article of at least 6-10 paragraphs that fully explores the topic
- Develop each point thoroughly with context, implications, and relevant details from the source
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
                redact_prompt | self.registry.get('sonnet_premium').get_runnable() | JsonOutputParser()
            )

            result = await redact_chain.ainvoke({"text": text[:8000]})

            logger.debug("redact_news_completed", article_length=len(result.get("article", "")))
            return result
        except Exception as e:
            _log_llm_error("redact_news", e)
            return {"article": "", "title": "", "summary": "", "tags": [], "error": str(e)}

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
                system_prompt = f"""You are a professional journalist. Write clear, objective, comprehensive news articles in {language}.

Use:
- Inverted pyramid structure
- Active voice
- Well-developed paragraphs (3-5 sentences each)
- Neutral, professional tone
- Clear, specific titles
- Thorough coverage of all available information"""

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
- Write a COMPREHENSIVE, well-developed article that SYNTHESIZES information from ALL provided sources
- ALL sources marked with ## headers MUST be represented in the article - do not ignore any source
- Create an engaging, accurate title based ONLY on source content
- Title capitalization: Use sentence case (only capitalize first word and proper nouns/place names), not title case
- Write a brief summary (2-3 sentences) reflecting ONLY source information from ALL sources
- Generate 3-5 relevant tags from topics in ALL the sources
- Format article with clear paragraph breaks (use \\n\\n between paragraphs)
- Each paragraph should be well-developed with 3-5 sentences providing context, details, and background
- Aim for a complete article of at least 8-12 paragraphs that fully explores the topic
- Integrate facts and information from ALL context units provided, not just the first one
- Develop each point thoroughly with context, implications, and relevant details from the sources
- NO advertisement blocks or meta-content

Formatting rules:
- Use **bold** for proper names (people, organizations, brands)
- Use **bold** for place names (cities, countries, regions)
- For sections with clearly defined context and substantial length (3+ paragraphs), add an H2 subtitle (## Subtitle)

MANDATORY STATEMENT TRACKING:
- CRITICAL: You MUST track which statements you use from each context unit
- Each statement has an order number in brackets like [0], [1], [2], etc.
- Each source has a context unit ID in the header like ## Title [CU:uuid-here]
- Extract the UUID from [CU:uuid] markers in the source headers
- For EACH context unit UUID, list ALL statement order numbers you actually used in your article
- Example: If you used statements [0], [3], [5] from context unit "5f038203-bb89-4543-910a-dead6d1dfdd1":
  {{"5f038203-bb89-4543-910a-dead6d1dfdd1": [0, 3, 5]}}
- If using multiple context units, include all of them:
  {{"uuid-1": [0, 1, 3], "uuid-2": [16, 17, 20]}}
- The statements_used field is REQUIRED in your response - do not omit it

IMPORTANT: Respond with ONLY raw JSON. Do NOT wrap in markdown code blocks or add any text before/after.

Response format:
{{"article": "Full article text...", "title": "...", "summary": "...", "tags": [...], "author": "Redacción", "statements_used": {{"context-unit-uuid": [0, 1, 3]}}}}""")
            ])

            redact_rich_chain = RunnableSequence(
                redact_rich_prompt | self.registry.get('sonnet_premium').get_runnable() | JsonOutputParser()
            )

            # Debug: call LLM and inspect raw response
            logger.info("redact_news_rich_calling_llm", source_text_length=len(source_text[:12000]))

            # Call LLM directly to see raw response
            raw_response = await (redact_rich_prompt | self.registry.get('sonnet_premium').get_runnable()).ainvoke({
                "source_text": source_text[:12000],
                "user_instructions": user_instructions
            })

            logger.info("redact_news_rich_raw_response",
                       raw_response_type=type(raw_response).__name__,
                       raw_content_preview=str(raw_response.content)[:500] if hasattr(raw_response, 'content') else str(raw_response)[:500])

            # Parse the response
            result = JsonOutputParser().parse(raw_response.content if hasattr(raw_response, 'content') else str(raw_response))

            logger.debug("redact_news_rich_completed",
                        article_length=len(result.get("article", "")),
                        result_keys=list(result.keys()),
                        has_statements_used="statements_used" in result,
                        statements_used_value=result.get("statements_used", "NOT_PRESENT"))
            return result
        except Exception as e:
            _log_llm_error("redact_news_rich", e)
            return {"article": "", "title": "", "summary": "", "tags": [], "error": str(e)}

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
            _log_llm_error("generate_style_guide", e)
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
            _log_llm_error("generate_context_unit", e)
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
                f"Eres un editor quirúrgico de textos en {language}.",
                "Cambia SOLO lo que el usuario solicita. Preserva TODO lo demás: significado, formato markdown, negritas (**texto**), saltos de línea simples (\\n) y dobles (\\n\\n), puntuación, espaciado."
            ]

            if preserve_meaning:
                system_parts.append("CRÍTICO: Mínima intervención. Edición quirúrgica exclusivamente en lo solicitado.")

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
IMPORTANTE: Responde con JSON puro. NO uses ```json ni decoración markdown.

Formato exacto:
{{"edited_text": "texto editado", "explanation": "cambios realizados"}}""")

            user_prompt = "\n\n".join(user_parts)

            micro_edit_prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("user", user_prompt)
            ])

            # Use Groq ultrafast model for micro-edits
            provider = self.registry.get('groq_fast') if settings.groq_api_key else self.registry.get('fast')
            
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
            _log_llm_error("micro_edit", e)
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
