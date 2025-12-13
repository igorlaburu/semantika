"""Query expansion con cache para búsqueda híbrida.

ESTRATEGIA:
1. Cache en memoria (TTL 1h) para queries repetidas
2. Expansión SOLO si query es corto (<4 palabras)
3. Sinónimos locales (diccionario estático) - PRIORIDAD
4. LLM call (Groq fast) solo para queries sin sinónimos locales

CONTABILIZACIÓN:
- Usa registry.track_usage() automáticamente via analyze_atomic()
- Modelo: fast (gpt-4o-mini on OpenRouter) - evita rate limits de Groq
- Se reutiliza analyze_atomic() para aprovechar logging existente

BENEFICIOS:
- Latencia baja: ~5ms con cache, ~100ms con Groq
- Costo: $0 (Groq gratis)
- Cache hit rate esperado: ~60-80% (queries repetitivas)
"""

from typing import List, Dict, Tuple
import hashlib
from datetime import datetime, timedelta

from .logger import get_logger

logger = get_logger("query_expander")


class QueryExpander:
    """Expansor de queries con cache y sinónimos locales."""
    
    def __init__(self):
        """Initialize query expander with cache and local synonyms."""
        # Cache: {query_hash: (expanded_terms, timestamp)}
        self._cache: Dict[str, Tuple[List[str], datetime]] = {}
        self._cache_ttl = timedelta(hours=1)
        self._cache_hits = 0
        self._cache_misses = 0
        
        # Diccionario local de sinónimos (español/euskera)
        # Términos comunes en prensa vasca
        self._local_synonyms = {
            # Instituciones
            "ayuntamiento": ["consistorio", "alcaldía", "municipio", "udala"],
            "udaletxea": ["udala", "ayuntamiento"],
            "diputación": ["foral", "aldundia"],
            "aldundia": ["diputación", "foral"],
            "gobierno vasco": ["eusko jaurlaritza", "ejecutivo vasco", "lehendakaritza"],
            "lehendakaritza": ["gobierno vasco", "ejecutivo vasco"],
            
            # Cargos
            "alcalde": ["regidor", "edil", "burgomaestre", "alkatea"],
            "alkatea": ["alcalde", "regidor"],
            "lehendakari": ["presidente", "lehendakaria"],
            "diputado": ["parlamentario", "legebiltzarkide"],
            
            # Lugares
            "bilbao": ["bilbo", "capital vizcaína"],
            "bilbo": ["bilbao"],
            "donostia": ["san sebastián", "capital guipuzcoana"],
            "gasteiz": ["vitoria", "capital alavesa"],
            
            # Temas comunes
            "educación": ["hezkuntza", "enseñanza", "formación"],
            "hezkuntza": ["educación", "enseñanza"],
            "salud": ["sanidad", "osasuna", "salud pública"],
            "osasuna": ["salud", "sanidad"],
            "vivienda": ["etxebizitza", "housing"],
            "transporte": ["garraio", "movilidad"],
            "presupuesto": ["aurrekontu", "cuentas públicas"],
            
            # Eventos
            "reunión": ["encuentro", "bilera", "cita"],
            "bilera": ["reunión", "encuentro"],
            "conferencia": ["hitzaldia", "charla"],
            "manifestación": ["protesta", "movilización"]
        }
        
        logger.info("query_expander_initialized",
            local_synonyms_count=len(self._local_synonyms)
        )
    
    def _get_cache_key(self, query: str) -> str:
        """Generate cache key from query."""
        normalized = query.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def _clean_cache(self):
        """Remove old cache entries (simple LRU)."""
        now = datetime.now()
        to_remove = []
        
        for key, (terms, cached_at) in self._cache.items():
            if now - cached_at > self._cache_ttl:
                to_remove.append(key)
        
        for key in to_remove:
            del self._cache[key]
        
        if to_remove:
            logger.debug("cache_cleaned", removed_count=len(to_remove))
    
    def _expand_with_local_synonyms(self, query: str) -> List[str]:
        """Expand query using local synonym dictionary (fast, no LLM)."""
        expanded = []
        words = query.lower().split()
        
        for word in words:
            if word in self._local_synonyms:
                expanded.extend(self._local_synonyms[word])
        
        return list(set(expanded))  # Deduplicate
    
    async def _expand_with_llm(self, query: str) -> List[str]:
        """Expand query using Groq LLM (fast, tracked via analyze_atomic)."""
        try:
            # IMPORTANTE: Reutilizamos analyze_atomic() que ya tiene tracking
            # Pero lo usamos de forma creativa para expansión de términos
            from .llm_client import get_llm_client
            llm = get_llm_client()
            
            # Construir un texto artificial que analyze_atomic procesará
            # para extraer sinónimos como "tags"
            prompt_text = f"""Genera sinónimos y términos relacionados para búsqueda semántica.

Query original: "{query}"

Por favor lista 3-5 términos relacionados o sinónimos que ayuden a encontrar contenido similar.
Solo términos clave, sin explicaciones."""
            
            # Llamar analyze_atomic (ya está tracked y contabilizado)
            result = await llm.analyze_atomic(
                text=prompt_text,
                organization_id="99999999-9999-9999-9999-999999999999"  # SYSTEM org
            )
            
            # Extraer "tags" como sinónimos expandidos
            tags = result.get("tags", [])
            
            logger.debug("llm_expansion_completed",
                query=query,
                expanded_count=len(tags)
            )
            
            return tags[:5]  # Max 5 términos adicionales
        
        except Exception as e:
            logger.error("llm_expansion_failed",
                query=query,
                error=str(e)
            )
            return []
    
    async def expand(self, query: str, use_llm: bool = True) -> List[str]:
        """Expand query with synonyms and related terms.
        
        Args:
            query: Original search query
            use_llm: Whether to use LLM if local synonyms not found
            
        Returns:
            List of expanded terms (includes original query)
        """
        # 1. Check cache first
        cache_key = self._get_cache_key(query)
        
        if cache_key in self._cache:
            cached_terms, cached_at = self._cache[cache_key]
            if datetime.now() - cached_at < self._cache_ttl:
                self._cache_hits += 1
                logger.debug("cache_hit",
                    query=query[:50],
                    cached_terms_count=len(cached_terms)
                )
                return cached_terms
        
        self._cache_misses += 1
        
        # 2. Always include original query
        expanded = [query]
        
        # 3. Try local synonyms first (fast, no cost)
        local_synonyms = self._expand_with_local_synonyms(query)
        
        if local_synonyms:
            expanded.extend(local_synonyms)
            logger.debug("local_synonyms_found",
                query=query[:50],
                synonyms_count=len(local_synonyms)
            )
        
        # 4. LLM expansion only if:
        # - Query is short (<4 words)
        # - No local synonyms found
        # - use_llm=True
        words = query.split()
        
        if use_llm and len(words) < 4 and len(local_synonyms) == 0:
            logger.debug("llm_expansion_triggered",
                query=query[:50],
                reason="short_query_no_local_synonyms"
            )
            
            llm_terms = await self._expand_with_llm(query)
            expanded.extend(llm_terms)
        
        # 5. Deduplicate and clean
        expanded = list(set([term.strip() for term in expanded if term.strip()]))
        
        # 6. Cache result
        self._cache[cache_key] = (expanded, datetime.now())
        
        # 7. Clean old cache entries periodically
        if len(self._cache) > 1000:
            self._clean_cache()
        
        logger.info("query_expanded",
            query=query[:50],
            expanded_count=len(expanded),
            cache_hit_rate=round(self._cache_hits / (self._cache_hits + self._cache_misses), 2) if self._cache_misses > 0 else 1.0
        )
        
        return expanded


# Singleton instance
_expander = None

def get_query_expander() -> QueryExpander:
    """Get singleton query expander instance."""
    global _expander
    if not _expander:
        _expander = QueryExpander()
    return _expander
