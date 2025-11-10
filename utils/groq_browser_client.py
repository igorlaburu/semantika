"""Groq Browser Tool Client for real-time web enrichment.

Provides context unit enrichment capabilities using Groq's browser_search
and visit_website tools for fact-checking and contextualization.
"""

import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from groq import AsyncGroq

from .config import settings
from .logger import get_logger
from .usage_tracker import get_usage_tracker

logger = get_logger("groq_browser_client")


class GroqBrowserClient:
    """Client for Groq browser tool integration."""
    
    def __init__(self):
        """Initialize Groq client with web search capabilities."""
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY not configured")
        
        self.client = AsyncGroq(api_key=settings.groq_api_key)
        # Use groq/compound for automatic web search (no explicit tools needed)
        self.model = "groq/compound"
        
        logger.info("groq_browser_client_initialized", model=self.model)
    
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
            enrich_type: Type of enrichment
            organization_id: Organization UUID (for tracking)
            context_unit_id: Context unit UUID (for tracking)
            client_id: Client UUID (for tracking)
            
        Returns:
            Enrichment result with suggestions and sources
        """
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
                # Remove Z and handle microseconds padding
                created_at_clean = created_at.replace('Z', '+00:00')
                
                # Fix microseconds: Python expects 0 or 6 digits after decimal
                # Supabase sometimes returns 5 digits (e.g., .23697)
                if '.' in created_at_clean and '+' in created_at_clean:
                    parts = created_at_clean.split('.')
                    if len(parts) == 2:
                        microseconds = parts[1].split('+')[0]
                        # Pad to 6 digits
                        microseconds = microseconds.ljust(6, '0')
                        created_at_clean = f"{parts[0]}.{microseconds}+00:00"
                
                dt = datetime.fromisoformat(created_at_clean)
                age_days = (datetime.now(dt.tzinfo) - dt).days
            except Exception as e:
                logger.error("timestamp_parse_error", 
                    created_at=created_at, 
                    error=str(e)
                )
                # Fallback: assume 0 days if parsing fails
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
    "new_developments": ["desarrollo1", "desarrollo2"],
    "sources": ["url1", "url2"],
    "suggestion": "qué añadir al context unit"
}}""",
                
                "background": f"""Busca CONTEXTO HISTÓRICO Y ANTECEDENTES para este tema:

Título: {title}
Resumen: {summary}

¿Qué antecedentes explican este suceso? ¿Historia previa? ¿Datos de contexto?

Responde SOLO con JSON puro (sin markdown):
{{
    "background_facts": ["antecedente1", "antecedente2"],
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
    "issues": ["problema1 si existe"],
    "latest_info": "información más reciente encontrada",
    "sources": ["url1"],
    "suggestion": "usar sin cambios|actualizar|descartar"
}}"""
            }
            
            prompt = prompts.get(enrich_type, prompts["verify"])
            
            # Call Groq Compound (web search is automatic, no tools array needed)
            response = await self.client.chat.completions.create(
                model=self.model,
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
                temperature=0.0
            )
            
            # Parse response
            content = response.choices[0].message.content
            
            # Clean markdown if present
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            result = json.loads(content)
            
            # Groq Compound doesn't expose tool_calls in response
            # Assume 1 web search was performed for tracking
            tool_call_count = 1
            
            logger.info("enrich_context_unit_completed",
                context_unit_id=context_unit_id,
                enrich_type=enrich_type,
                tool_calls=tool_call_count,
                has_result=bool(result)
            )
            
            # Track usage as SIMPLE operation
            # Browser enrichment is quick fact-checking, not complex generation
            tracker = get_usage_tracker()
            await tracker.track(
                organization_id=organization_id,
                model=f"groq/{self.model}",
                operation=f"enrich_{enrich_type}",
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                client_id=client_id,
                context_unit_id=context_unit_id,
                metadata={
                    "enrich_type": enrich_type,
                    "tool_calls": tool_call_count,
                    "query": query,
                    "age_days": age_days,
                    "usage_type": "simple"  # Mark as simple operation
                }
            )
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error("groq_browser_json_parse_error",
                context_unit_id=context_unit_id,
                error=str(e),
                content=content[:500] if 'content' in locals() else ""
            )
            return {
                "error": "Failed to parse response",
                "details": str(e)
            }
        
        except Exception as e:
            logger.error("groq_browser_enrich_error",
                context_unit_id=context_unit_id,
                enrich_type=enrich_type,
                error=str(e)
            )
            return {
                "error": "Enrichment failed",
                "details": str(e)
            }


# Global client instance
_groq_browser_client: Optional[GroqBrowserClient] = None


def get_groq_browser_client() -> GroqBrowserClient:
    """Get or create Groq browser client singleton."""
    global _groq_browser_client
    if _groq_browser_client is None:
        _groq_browser_client = GroqBrowserClient()
    return _groq_browser_client
