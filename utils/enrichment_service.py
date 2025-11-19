"""Context unit enrichment service using Groq Compound web search.

Provides enrichment capabilities for context units by performing real-time
web searches and generating suggestions based on:
- Updates: Find recent developments on the story
- Background: Discover historical context
- Verify: Check if information is still current
"""

import json
import re
from typing import Dict, Any, List
from datetime import datetime

from utils.llm_registry import get_llm_registry
from utils.logger import get_logger

logger = get_logger("enrichment_service")


class EnrichmentService:
    """Service for enriching context units with web search."""

    def __init__(self):
        """Initialize enrichment service."""
        self.registry = get_llm_registry()
        self.provider = self.registry.get('groq_compound')

        logger.info("enrichment_service_initialized")

    def extract_keywords(self, text: str, max_keywords: int = 3) -> List[str]:
        """Extract most relevant keywords from text.

        Simple heuristic:
        - Capitalized words (likely proper nouns)
        - Longer words (> 5 chars)
        - Not in common stopwords

        Args:
            text: Text to extract keywords from
            max_keywords: Maximum number of keywords to return

        Returns:
            List of extracted keywords
        """
        stopwords = {
            'según', 'donde', 'cuando', 'durante', 'después',
            'mientras', 'contra', 'entre', 'desde', 'hasta',
            'través', 'además', 'sobre', 'aunque', 'varios'
        }

        # Find capitalized words or long words
        words = re.findall(r'\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{4,}\b|\b[a-záéíóúñ]{6,}\b', text)
        keywords = [w for w in words if w.lower() not in stopwords]

        # Remove duplicates while preserving order
        seen = set()
        unique_keywords = []
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                unique_keywords.append(kw)

        return unique_keywords[:max_keywords]

    def build_search_query(
        self,
        title: str,
        summary: str,
        created_at: str,
        tags: List[str],
        enrich_type: str
    ) -> str:
        """Build optimal search query based on enrich type.

        Args:
            title: Context unit title
            summary: Context unit summary
            created_at: ISO timestamp of context unit creation
            tags: List of tags
            enrich_type: Type of enrichment (update/background/verify)

        Returns:
            Optimized search query string
        """
        # Extract date info - fix malformed timestamps
        try:
            created_at_clean = created_at.replace('Z', '+00:00')

            # Fix microseconds: Python expects 0 or 6 digits after decimal
            if '.' in created_at_clean and '+' in created_at_clean:
                parts = created_at_clean.split('.')
                if len(parts) == 2:
                    microseconds = parts[1].split('+')[0]
                    microseconds = microseconds.ljust(6, '0')
                    created_at_clean = f"{parts[0]}.{microseconds}+00:00"

            dt = datetime.fromisoformat(created_at_clean)
        except Exception:
            # Fallback to current date if parsing fails
            dt = datetime.now()

        month_names = {
            1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
            5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
            9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
        }
        month_name = month_names.get(dt.month, '')
        year = dt.year

        if enrich_type == "update":
            # Search for updates: Title + date + "últimas noticias"
            query = f"{title} últimas noticias {month_name} {year}"

        elif enrich_type == "background":
            # Search for context: Title + keywords + "antecedentes"
            summary_keywords = self.extract_keywords(summary, max_keywords=2)
            keywords = " ".join(summary_keywords) if summary_keywords else ""
            query = f"{title} {keywords} antecedentes contexto historia".strip()

        elif enrich_type == "verify":
            # Verify: Title + "actualización" + date
            query = f"{title} actualización {month_name} {year}"

        else:
            # Default: just title
            query = title

        # Limit query length (search engines work better with concise queries)
        return query[:200]

    async def enrich_context_unit(
        self,
        title: str,
        summary: str,
        created_at: str,
        tags: List[str],
        enrich_type: str,
        organization_id: str,
        context_unit_id: str,
        client_id: str
    ) -> Dict[str, Any]:
        """Enrich context unit with real-time web search.

        Args:
            title: Context unit title
            summary: Context unit summary
            created_at: ISO timestamp
            tags: List of tags
            enrich_type: Type of enrichment (update/background/verify)
            organization_id: Organization UUID (for tracking)
            context_unit_id: Context unit UUID (for tracking)
            client_id: Client UUID (for tracking)

        Returns:
            Enrichment result with suggestions and sources
        """
        import time
        start_time = time.time()

        try:
            # Build search query
            query = self.build_search_query(title, summary, created_at, tags, enrich_type)

            logger.info("enrich_context_unit_start",
                context_unit_id=context_unit_id,
                enrich_type=enrich_type,
                query=query
            )

            # Calculate age - fix malformed timestamps
            try:
                created_at_clean = created_at.replace('Z', '+00:00')

                if '.' in created_at_clean and '+' in created_at_clean:
                    parts = created_at_clean.split('.')
                    if len(parts) == 2:
                        microseconds = parts[1].split('+')[0]
                        microseconds = microseconds.ljust(6, '0')
                        created_at_clean = f"{parts[0]}.{microseconds}+00:00"

                dt = datetime.fromisoformat(created_at_clean)
                age_days = (datetime.now(dt.tzinfo) - dt).days
            except Exception as e:
                logger.error("timestamp_parse_error",
                    created_at=created_at,
                    error=str(e)
                )
                age_days = 0

            # Build prompt based on enrich_type
            prompts = {
                "update": f"""Busca NOVEDADES sobre este tema (noticia de hace {age_days} días):

Título: {title}
Resumen: {summary}

¿Hay desarrollos recientes? ¿Sentencias, arrestos, nuevos datos, actualizaciones?

Responde SOLO con JSON puro (sin markdown):
{{
    "has_updates": true/false,
    "new_developments": [
        {{"text": "desarrollo1", "source_url": "url_fuente1"}},
        {{"text": "desarrollo2", "source_url": "url_fuente2"}}
    ],
    "sources": ["url1", "url2"],
    "suggestion": "qué añadir al context unit"
}}""",

                "background": f"""Busca CONTEXTO HISTÓRICO Y ANTECEDENTES para este tema:

Título: {title}
Resumen: {summary}

¿Qué antecedentes explican este suceso? ¿Historia previa? ¿Datos de contexto?

Responde SOLO con JSON puro (sin markdown):
{{
    "background_facts": [
        {{"text": "antecedente1", "source_url": "url_fuente1"}},
        {{"text": "antecedente2", "source_url": "url_fuente2"}}
    ],
    "historical_context": "explicación breve del contexto",
    "sources": ["url1", "url2"],
    "suggestion": "cómo añadir contexto al artículo"
}}""",

                "verify": f"""Verifica si esta noticia sigue siendo ACTUAL Y PRECISA:

Título: {title}
Resumen: {summary}
Edad: {age_days} días

¿Es información vigente? ¿Hay actualizaciones? ¿Rectificaciones?

Responde SOLO con JSON puro (sin markdown):
{{
    "is_current": true/false,
    "status": "vigente|obsoleta|actualizada",
    "issues": [
        {{"text": "problema1 si existe", "source_url": "url_fuente1"}}
    ],
    "latest_info": "información más reciente encontrada",
    "sources": ["url1"],
    "suggestion": "usar sin cambios|actualizar|descartar"
}}"""
            }

            prompt = prompts.get(enrich_type, prompts["verify"])

            # Call Groq Compound via provider
            response = await self.provider.ainvoke(
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un fact-checker y investigador periodístico. Usa búsquedas web para verificar y enriquecer información. Responde SIEMPRE con JSON puro, sin decoración markdown."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                config={
                    'temperature': 0.0,
                    'tracking': {
                        'organization_id': organization_id,
                        'operation': f'enrich_{enrich_type}',
                        'client_id': client_id,
                        'context_unit_id': context_unit_id,
                        'web_search_cost': 0.0065,  # Average: basic ($0.005) + advanced ($0.008) / 2
                        'metadata': {
                            'enrich_type': enrich_type,
                            'query': query,
                            'age_days': age_days
                        }
                    }
                }
            )

            # Parse response
            content = response.choices[0].message.content

            # Log raw response for debugging
            logger.debug("enrichment_raw_response",
                context_unit_id=context_unit_id,
                enrich_type=enrich_type,
                content_length=len(content) if content else 0,
                content_preview=content[:200] if content else "NONE"
            )

            # Validate content exists
            if not content:
                logger.error("enrichment_empty_response",
                    context_unit_id=context_unit_id,
                    enrich_type=enrich_type,
                    full_response=str(response)[:500]
                )
                return {
                    "error": "Empty response from LLM",
                    "details": "The model returned an empty response"
                }

            # Clean markdown if present
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            # Validate content after cleaning
            if not content:
                logger.error("enrichment_empty_after_cleaning",
                    context_unit_id=context_unit_id,
                    enrich_type=enrich_type,
                    raw_content=response.choices[0].message.content
                )
                return {
                    "error": "Empty response after cleaning",
                    "details": "The response was empty after removing markdown"
                }

            result = json.loads(content)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info("enrich_context_unit_completed",
                context_unit_id=context_unit_id,
                enrich_type=enrich_type,
                has_result=bool(result),
                duration_ms=duration_ms
            )

            return result

        except json.JSONDecodeError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error("enrichment_json_parse_error",
                context_unit_id=context_unit_id,
                enrich_type=enrich_type,
                error=str(e),
                duration_ms=duration_ms,
                content_preview=content[:500] if 'content' in locals() else "",
                content_length=len(content) if 'content' in locals() else 0,
                raw_response=response.choices[0].message.content[:1000] if response and response.choices else "no response"
            )
            return {
                "error": "Failed to parse response",
                "details": str(e),
                "content_preview": content[:200] if 'content' in locals() else ""
            }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error("enrichment_error",
                context_unit_id=context_unit_id,
                enrich_type=enrich_type,
                error=str(e),
                duration_ms=duration_ms,
                error_type=type(e).__name__
            )
            return {
                "error": "Enrichment failed",
                "details": str(e)
            }


# Global service instance
_enrichment_service = None


def get_enrichment_service() -> EnrichmentService:
    """Get or create enrichment service singleton.

    Returns:
        EnrichmentService instance
    """
    global _enrichment_service
    if _enrichment_service is None:
        _enrichment_service = EnrichmentService()
    return _enrichment_service
