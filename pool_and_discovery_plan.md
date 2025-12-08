# Plan de Implementación: Discovery e Ingesta Pool v2.1

**Fecha:** 8 Diciembre 2025  
**Objetivo:** Implementar motor de Discovery + Pool Común de Noticias en Qdrant

---

## 📋 Análisis del Código Existente

### ✅ Componentes Reutilizables (Ya Existen)

| Componente | Archivo | Estado | Uso en Discovery/Pool |
|:-----------|:--------|:-------|:---------------------|
| **Qdrant Client** | `utils/qdrant_client.py` | ✅ Completo | Inserción en Pool con `company_id="pool"` |
| **Scraper Workflow** | `sources/scraper_workflow.py` | ✅ Completo | Extracción de contenido Index/Multi-noticia |
| **Multi-noticia Detection** | `scraper_workflow.py:211-248` | ✅ Completo | Detecta 3+ bloques válidos con heading+link |
| **Content Enricher** | `utils/unified_content_enricher.py` | ✅ Completo | Enriquecimiento LLM (Groq Llama 3.3 70B) |
| **Context Verifier** | `utils/unified_context_verifier.py` | ✅ Completo | Verificación de novedad por source_type |
| **Context Ingester** | `utils/unified_context_ingester.py` | ✅ Completo | Guardado en press_context_units |
| **Embedding Generator** | `utils/embedding_generator.py` | ✅ Completo | FastEmbed 768d + OpenAI fallback |
| **LLM Client** | `utils/llm_client.py` | ✅ Completo | Groq + GPT-4o-mini via OpenRouter |
| **Date Extractor** | `utils/date_extractor.py` | ✅ Completo | Multi-source date extraction |
| **Change Detector** | `utils/change_detector.py` | ✅ Completo | Hash → SimHash → Embedding |
| **Supabase Client** | `utils/supabase_client.py` | ✅ Completo | Gestión de sources, monitored_urls |
| **Scraper Helpers** | `utils/scraper_helpers.py` | ✅ Completo | CRUD de sources scraping |

### 🔴 Componentes Nuevos a Crear

| Componente | Prioridad | Descripción |
|:-----------|:----------|:------------|
| **GNews Client** | Alta | Wrapper para búsquedas con geo/topic/period=24h |
| **Discovery Connector** | Alta | Origin hunting + Press room detection |
| **Pool Ingester** | Alta | Adaptador para Qdrant con `company_id="pool"` |
| **Source Lifecycle Manager** | Media | Health check y scoring de fuentes |
| **Discovery Scheduler** | Media | Orquestador diario de Discovery flow |
| **Page Type Detector** | Baja | (Ya existe en scraper_workflow.py) |

---

## 🏗️ Arquitectura Propuesta

```
┌─────────────────────────────────────────────────────────────────┐
│                     SCHEDULER (Diario)                          │
│  - Discovery Flow (08:00 UTC)                                   │
│  - Ingestion Flow (cada hora para fuentes activas)             │
└────────┬────────────────────────────────────────────────────────┘
         │
         ├─► DISCOVERY FLOW (Flujo A)
         │   │
         │   ├─► 1. Health Check (SourceLifecycleManager)
         │   │      └─► Evaluar fuentes activas (uso/frecuencia/calidad)
         │   │
         │   ├─► 2. GNews Search (24h filter)
         │   │      ├─► Query: geo + topic (flexible)
         │   │      └─► 50 headlines → Sample 20% (10 noticias)
         │   │
         │   ├─► 3. Origin Hunting (DiscoveryConnector)
         │   │      ├─► find_original_source(headline)
         │   │      └─► detect_press_room_structure(url)
         │   │
         │   └─► 4. Create Trial Sources
         │          └─► DB.discovered_sources (status="trial")
         │
         └─► INGESTION FLOW (Flujo B)
             │
             ├─► 1. Get Active Sources
             │      └─► sources WHERE status IN ('active', 'trial')
             │
             ├─► 2. Scrape Content (scraper_workflow.py)
             │      ├─► Index pages → extract_article_links()
             │      └─► Multi-noticia → extract_blocks()
             │
             ├─► 3. Quality Gate (LLM)
             │      ├─► enrich_content() → Groq Llama 3.3 70B
             │      └─► Score threshold: 0.4
             │
             ├─► 4. Ingest to Pool (Qdrant)
             │      ├─► company_id: "pool" (FIJO)
             │      ├─► Embedding: FastEmbed 768d
             │      └─► Deduplicación: vector similarity
             │
             └─► 5. Update Source Metrics
                    └─► relevance_score = (Uso*0.4 + Freq*0.3 + Calidad*0.3)
```

---

## 📦 Fase 1: Discovery Engine (Motor de Búsqueda)

### 1.1. GNews Client (`sources/gnews_client.py`)

**Funcionalidad:**
- Búsquedas flexibles por `geo` y/o `topic`
- Filtro estricto `period="24h"`
- Muestreo estocástico 20%

**API a usar:** 
- Opción 1: GNews API (https://gnews.io/) - Free tier 100 requests/día
- Opción 2: Perplexity "sonar" (ya disponible) con query modificado
- Opción 3: NewsAPI (https://newsapi.org/) - Free tier 100 requests/día

**Implementación:**

```python
# sources/gnews_client.py

"""GNews client for discovery of news sources."""

import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from utils.logger import get_logger
from utils.config import settings

logger = get_logger("gnews_client")

class GNewsClient:
    """Client for fetching news headlines from GNews API."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://gnews.io/api/v4"
    
    async def search_headlines(
        self,
        geo: Optional[str] = None,
        topic: Optional[str] = None,
        period_hours: int = 24,
        limit: int = 50,
        language: str = "es"
    ) -> List[Dict[str, Any]]:
        """
        Buscar noticias recientes con filtros flexibles.
        
        Args:
            geo: Ubicación geográfica (ej. "Álava", "Bilbao")
            topic: Tema (ej. "Agricultura", "Tecnología")
            period_hours: Ventana temporal (default 24h)
            limit: Máximo de resultados
            language: Idioma (default español)
        
        Returns:
            Lista de headlines con url, title, snippet, publishedAt
        """
        # Construir query
        query_parts = []
        if geo:
            query_parts.append(geo)
        if topic:
            query_parts.append(topic)
        
        query = " ".join(query_parts) if query_parts else None
        
        if not query:
            logger.error("gnews_search_no_query")
            return []
        
        # Calcular desde cuándo buscar
        from_date = datetime.utcnow() - timedelta(hours=period_hours)
        from_str = from_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        logger.info("gnews_search_start",
            query=query,
            from_date=from_str,
            limit=limit
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "q": query,
                    "lang": language,
                    "country": "es",  # España
                    "max": limit,
                    "from": from_str,
                    "apikey": self.api_key
                }
                
                async with session.get(
                    f"{self.base_url}/search",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        logger.error("gnews_api_error",
                            status=response.status,
                            text=await response.text()
                        )
                        return []
                    
                    data = await response.json()
                    articles = data.get("articles", [])
                    
                    logger.info("gnews_search_completed",
                        query=query,
                        articles_found=len(articles)
                    )
                    
                    return articles
        
        except Exception as e:
            logger.error("gnews_search_error", error=str(e))
            return []
    
    def sample_headlines(
        self,
        headlines: List[Dict[str, Any]],
        sample_rate: float = 0.20
    ) -> List[Dict[str, Any]]:
        """
        Muestreo estocástico de headlines.
        
        Args:
            headlines: Lista completa de headlines
            sample_rate: Porcentaje a muestrear (default 20%)
        
        Returns:
            Subconjunto aleatorio
        """
        import random
        
        sample_size = max(1, int(len(headlines) * sample_rate))
        sampled = random.sample(headlines, min(sample_size, len(headlines)))
        
        logger.info("gnews_sampling",
            total=len(headlines),
            sample_size=len(sampled),
            rate=sample_rate
        )
        
        return sampled


def get_gnews_client() -> GNewsClient:
    """Get GNews client singleton."""
    return GNewsClient(api_key=settings.gnews_api_key)
```

**Config en `.env`:**
```bash
GNEWS_API_KEY=your_gnews_api_key
```

**Config en `utils/config.py`:**
```python
# Añadir en class Settings:
gnews_api_key: str = Field(default="", env="GNEWS_API_KEY")
```

---

### 1.2. Discovery Connector (`sources/discovery_connector.py`)

**Funcionalidad:**
- Origin Hunting: De medio → fuente original
- Press Room Detection: Validar estructura de sala de prensa
- Contact Extraction: Email, nombre contacto

**Implementación:**

```python
# sources/discovery_connector.py

"""Discovery connector for finding original news sources."""

import aiohttp
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from utils.logger import get_logger
from utils.llm_client import get_llm_client

logger = get_logger("discovery_connector")

# Medios conocidos a saltar (buscar fuente original)
KNOWN_MEDIA_DOMAINS = [
    "elcorreo.com", "deia.eus", "eldiario.es", "elpais.com",
    "abc.es", "elmundo.es", "lavanguardia.com", "20minutos.es",
    "europapress.es", "efe.com", "rtve.es"
]


class DiscoveryConnector:
    """Connector for discovering original news sources."""
    
    def __init__(self):
        self.llm_client = get_llm_client()
    
    async def find_original_source(
        self,
        headline: str,
        snippet: str,
        article_url: str
    ) -> Optional[str]:
        """
        Buscar la fuente original de una noticia.
        
        Estrategia:
        1. Verificar si URL es de medio conocido
        2. Buscar referencias en el snippet (ej. "según la Diputación Foral")
        3. Usar LLM para identificar entidad fuente
        4. Buscar URL oficial de la entidad
        
        Args:
            headline: Título de la noticia
            snippet: Resumen/extracto
            article_url: URL del artículo original
        
        Returns:
            URL de la fuente original o None
        """
        parsed = urlparse(article_url)
        domain = parsed.netloc.replace("www.", "")
        
        # Si no es medio conocido, es potencialmente una fuente directa
        if not any(known in domain for known in KNOWN_MEDIA_DOMAINS):
            logger.debug("direct_source_detected", domain=domain)
            return article_url
        
        logger.info("media_detected_hunting_origin",
            domain=domain,
            headline=headline[:50]
        )
        
        # Usar LLM para extraer entidad fuente del snippet
        prompt = f"""Analiza esta noticia y identifica la FUENTE ORIGINAL:

Título: {headline}
Extracto: {snippet}

¿Quién es la fuente original de esta información? (ej. "Diputación Foral de Álava", "Ayuntamiento de Bilbao", "Tubacex S.A.", etc.)

Responde SOLO con el nombre de la entidad, sin explicación.
Si no hay fuente clara, responde "MEDIO"."""

        try:
            # Usar GPT-4o-mini para inferencia rápida
            response = await self.llm_client.generate_context_unit(
                text=prompt,
                organization_id="pool",  # Discovery para pool
                client_id="system"
            )
            
            source_entity = response.get("title", "").strip()
            
            if not source_entity or source_entity == "MEDIO":
                logger.debug("no_original_source_found", headline=headline[:30])
                return None
            
            logger.info("source_entity_identified", entity=source_entity)
            
            # Buscar URL oficial de la entidad
            official_url = await self._search_entity_website(source_entity)
            
            return official_url
        
        except Exception as e:
            logger.error("find_original_source_error", error=str(e))
            return None
    
    async def _search_entity_website(self, entity_name: str) -> Optional[str]:
        """
        Buscar URL oficial de una entidad.
        
        Estrategia simple: Google "site oficial {entity_name}"
        O usar base de datos local de instituciones vascas.
        
        Args:
            entity_name: Nombre de la entidad
        
        Returns:
            URL oficial o None
        """
        # TODO: Implementar búsqueda web o DB lookup
        # Por ahora, retornar None (requiere Google Custom Search API)
        logger.warn("entity_website_search_not_implemented", entity=entity_name)
        return None
    
    async def detect_press_room_structure(self, url: str) -> bool:
        """
        Detectar si una URL tiene estructura de Sala de Prensa.
        
        Heurísticas:
        - Contiene sección "noticias", "prensa", "sala-de-prensa", "actualidad"
        - Tiene lista de artículos con fecha + título
        - No es blog personal (tiene estructura institucional)
        
        Args:
            url: URL a analizar
        
        Returns:
            True si parece Sala de Prensa
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=20),
                    headers={'User-Agent': 'SemantikaBotDiscovery/1.0'}
                ) as response:
                    if response.status != 200:
                        return False
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Buscar keywords en URL y contenido
                    press_keywords = [
                        'prensa', 'noticias', 'actualidad', 'sala-de-prensa',
                        'news', 'press-room', 'comunicados', 'notas-de-prensa'
                    ]
                    
                    url_lower = url.lower()
                    has_press_in_url = any(kw in url_lower for kw in press_keywords)
                    
                    # Buscar lista de artículos (heurística)
                    articles = soup.find_all(['article', 'div'], class_=lambda c: c and any(
                        kw in str(c).lower() for kw in ['noticia', 'news', 'post', 'item']
                    ))
                    
                    has_article_list = len(articles) >= 3
                    
                    # Buscar indicadores institucionales
                    footer = soup.find('footer')
                    has_institutional = False
                    if footer:
                        footer_text = footer.get_text().lower()
                        institutional_keywords = [
                            'diputación', 'ayuntamiento', 'gobierno', 'ministerio',
                            'instituto', 'fundación', 'consorcio'
                        ]
                        has_institutional = any(kw in footer_text for kw in institutional_keywords)
                    
                    is_press_room = (has_press_in_url or has_article_list) and has_institutional
                    
                    logger.info("press_room_detection",
                        url=url,
                        is_press_room=is_press_room,
                        has_press_in_url=has_press_in_url,
                        articles_found=len(articles),
                        has_institutional=has_institutional
                    )
                    
                    return is_press_room
        
        except Exception as e:
            logger.error("press_room_detection_error", url=url, error=str(e))
            return False
    
    async def extract_contact_info(self, url: str) -> Dict[str, Any]:
        """
        Extraer información de contacto de una página.
        
        Args:
            url: URL a analizar
        
        Returns:
            Dict con email, contact_name, phone (si disponibles)
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                    if response.status != 200:
                        return {}
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Buscar email con regex
                    import re
                    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                    emails = re.findall(email_pattern, html)
                    
                    # Filtrar emails genéricos de scripts
                    valid_emails = [
                        e for e in emails 
                        if not any(skip in e.lower() for skip in ['example.com', 'test', 'noreply'])
                    ]
                    
                    contact_info = {}
                    if valid_emails:
                        contact_info["email"] = valid_emails[0]
                    
                    logger.debug("contact_info_extracted", url=url, info=contact_info)
                    return contact_info
        
        except Exception as e:
            logger.error("extract_contact_error", url=url, error=str(e))
            return {}


def get_discovery_connector() -> DiscoveryConnector:
    """Get discovery connector singleton."""
    return DiscoveryConnector()
```

---

## 📦 Fase 2: Pool Ingestion (Ingesta a Pool)

### 2.1. Adaptador Qdrant Pool (`utils/pool_ingester.py`)

**Funcionalidad:**
- Wrapper sobre `QdrantClient` con `company_id="pool"` fijo
- Deduplicación por embedding similarity
- Scoring de calidad antes de insertar

**Implementación:**

```python
# utils/pool_ingester.py

"""Pool ingester for inserting content into Qdrant pool collection."""

import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime

from utils.qdrant_client import get_qdrant_client
from utils.embedding_generator import generate_embedding
from utils.logger import get_logger
from qdrant_client.models import PointStruct

logger = get_logger("pool_ingester")

POOL_COMPANY_ID = "pool"  # 🔒 CONSTANTE FIJA
QUALITY_THRESHOLD = 0.4   # Mínimo score para ingresar al pool


class PoolIngester:
    """Ingester for shared news pool in Qdrant."""
    
    def __init__(self):
        self.qdrant = get_qdrant_client()
    
    async def ingest_to_pool(
        self,
        title: str,
        content: str,
        url: str,
        source_id: str,
        quality_score: float,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        published_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ingerir contenido al Pool común de Qdrant.
        
        Args:
            title: Título del contenido
            content: Texto completo
            url: URL fuente
            source_id: UUID de la fuente (discovered_sources)
            quality_score: Score de calidad (0.0-1.0)
            category: Categoría opcional
            tags: Tags opcionales
            published_at: Fecha de publicación
            metadata: Metadata adicional
        
        Returns:
            Dict con success, point_id, duplicate info
        """
        # Validar calidad
        if quality_score < QUALITY_THRESHOLD:
            logger.warn("pool_ingest_rejected_low_quality",
                title=title[:50],
                quality_score=quality_score,
                threshold=QUALITY_THRESHOLD
            )
            return {
                "success": False,
                "reason": "quality_too_low",
                "quality_score": quality_score,
                "threshold": QUALITY_THRESHOLD
            }
        
        logger.info("pool_ingest_start",
            title=title[:50],
            source_id=source_id,
            quality_score=quality_score
        )
        
        try:
            # Generar embedding
            embedding = await generate_embedding(
                title=title,
                summary=content[:500],  # Primeros 500 chars como summary
                company_id=POOL_COMPANY_ID
            )
            
            # Check duplicates (similarity > 0.98)
            similar = await self._check_duplicates(embedding)
            
            if similar:
                logger.warn("pool_duplicate_found",
                    title=title[:50],
                    duplicate_id=similar["id"],
                    similarity=similar["score"]
                )
                return {
                    "success": False,
                    "reason": "duplicate",
                    "duplicate_id": similar["id"],
                    "similarity": similar["score"]
                }
            
            # Crear point ID determinista basado en URL
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))
            
            # Construir payload
            payload = {
                "company_id": POOL_COMPANY_ID,  # 🟢 FIJO
                "source_id": source_id,
                "title": title,
                "content": content[:2000],  # Limitar a 2K chars
                "url": url,
                "category": category or "general",
                "tags": tags or [],
                "quality_score": quality_score,
                "published_at": published_at or datetime.utcnow().isoformat(),
                "ingested_at": datetime.utcnow().isoformat(),
                "discovered_by": ["system_discovery"],
                **(metadata or {})
            }
            
            # Insert en Qdrant
            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload=payload
            )
            
            await self.qdrant.add_points([point])
            
            logger.info("pool_point_inserted",
                point_id=point_id,
                title=title[:50],
                quality_score=quality_score
            )
            
            return {
                "success": True,
                "point_id": point_id,
                "quality_score": quality_score,
                "duplicate": False
            }
        
        except Exception as e:
            logger.error("pool_ingest_error",
                title=title[:50],
                error=str(e)
            )
            return {
                "success": False,
                "reason": "error",
                "error": str(e)
            }
    
    async def _check_duplicates(self, embedding: List[float]) -> Optional[Dict[str, Any]]:
        """
        Buscar duplicados por similitud de embedding.
        
        Args:
            embedding: Vector a comparar
        
        Returns:
            Dict con id, score si hay duplicado, None si no
        """
        try:
            results = await self.qdrant.search(
                query_vector=embedding,
                limit=1,
                filter_dict={"company_id": POOL_COMPANY_ID}
            )
            
            if results and len(results) > 0:
                top_result = results[0]
                if top_result["score"] >= 0.98:  # Threshold de duplicado
                    return {
                        "id": top_result["id"],
                        "score": top_result["score"]
                    }
            
            return None
        
        except Exception as e:
            logger.error("duplicate_check_error", error=str(e))
            return None


def get_pool_ingester() -> PoolIngester:
    """Get pool ingester singleton."""
    return PoolIngester()
```

---

### 2.2. Source Lifecycle Manager (`utils/source_lifecycle_manager.py`)

**Funcionalidad:**
- Health Check de fuentes activas
- Cálculo de relevance score
- Transición de estados (trial → active → inactive → archived)

**Implementación:**

```python
# utils/source_lifecycle_manager.py

"""Source lifecycle manager for discovery sources."""

from typing import List, Dict, Any
from datetime import datetime, timedelta

from utils.supabase_client import get_supabase_client
from utils.logger import get_logger

logger = get_logger("source_lifecycle_manager")

# Scoring weights
WEIGHT_USAGE = 0.4
WEIGHT_FREQUENCY = 0.3
WEIGHT_QUALITY = 0.3

# Thresholds
ACTIVE_THRESHOLD = 0.6
TRIAL_PROMOTION_THRESHOLD = 0.7
INACTIVE_THRESHOLD = 0.3


class SourceLifecycleManager:
    """Manager for source health and lifecycle."""
    
    def __init__(self):
        self.supabase = get_supabase_client()
    
    async def evaluate_all_sources(self):
        """
        Evaluar todas las fuentes activas y trial.
        Actualizar scores y estados según métricas.
        """
        logger.info("source_health_check_start")
        
        try:
            # Obtener fuentes activas y trial
            result = self.supabase.client.table("discovered_sources").select(
                "*"
            ).in_("status", ["active", "trial"]).execute()
            
            sources = result.data or []
            
            logger.info("sources_to_evaluate", count=len(sources))
            
            for source in sources:
                await self._evaluate_source(source)
            
            logger.info("source_health_check_completed", sources_evaluated=len(sources))
        
        except Exception as e:
            logger.error("evaluate_all_sources_error", error=str(e))
    
    async def _evaluate_source(self, source: Dict[str, Any]):
        """
        Evaluar una fuente individual y actualizar su score/status.
        
        Args:
            source: Dict con datos de discovered_sources
        """
        source_id = source["source_id"]
        current_status = source["status"]
        
        logger.debug("evaluating_source", source_id=source_id, status=current_status)
        
        # Calcular métricas
        usage_score = await self._calculate_usage_score(source_id)
        frequency_score = await self._calculate_frequency_score(source_id)
        quality_score = source.get("avg_quality_score", 0.5)
        
        # Fórmula de relevancia
        relevance_score = (
            usage_score * WEIGHT_USAGE +
            frequency_score * WEIGHT_FREQUENCY +
            quality_score * WEIGHT_QUALITY
        )
        
        # Determinar nuevo estado
        new_status = current_status
        
        if current_status == "trial":
            if relevance_score >= TRIAL_PROMOTION_THRESHOLD:
                new_status = "active"
                logger.info("source_promoted_to_active", source_id=source_id, score=relevance_score)
            elif relevance_score < INACTIVE_THRESHOLD:
                new_status = "archived"
                logger.info("source_archived_from_trial", source_id=source_id, score=relevance_score)
        
        elif current_status == "active":
            if relevance_score < INACTIVE_THRESHOLD:
                new_status = "inactive"
                logger.info("source_deactivated", source_id=source_id, score=relevance_score)
        
        # Actualizar BD
        update_data = {
            "relevance_score": relevance_score,
            "last_evaluated_at": datetime.utcnow().isoformat()
        }
        
        if new_status != current_status:
            update_data["status"] = new_status
        
        self.supabase.client.table("discovered_sources").update(
            update_data
        ).eq("source_id", source_id).execute()
        
        logger.debug("source_evaluated",
            source_id=source_id,
            relevance_score=round(relevance_score, 2),
            status=new_status
        )
    
    async def _calculate_usage_score(self, source_id: str) -> float:
        """
        Calcular score de uso (cuántos usuarios adoptaron noticias de esta fuente).
        
        Args:
            source_id: UUID de la fuente
        
        Returns:
            Score 0.0-1.0
        """
        # TODO: Implementar conteo de adoptions en press_context_units
        # donde source_metadata contiene "pool_source_id": source_id
        # Por ahora retornar 0.5 (neutral)
        return 0.5
    
    async def _calculate_frequency_score(self, source_id: str) -> float:
        """
        Calcular score de frecuencia (cuánto contenido nuevo publica).
        
        Args:
            source_id: UUID de la fuente
        
        Returns:
            Score 0.0-1.0
        """
        try:
            # Contar noticias en últimos 7 días
            cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
            
            result = self.supabase.client.table("url_content_units").select(
                "id", count="exact"
            ).eq("source_id", source_id).gte("created_at", cutoff).execute()
            
            count = result.count or 0
            
            # Normalizar: 0-5 noticias/semana → 0.0-1.0
            # >10 noticias/semana → 1.0
            score = min(1.0, count / 10.0)
            
            logger.debug("frequency_score_calculated",
                source_id=source_id,
                count_7days=count,
                score=score
            )
            
            return score
        
        except Exception as e:
            logger.error("frequency_score_error", source_id=source_id, error=str(e))
            return 0.5


def get_source_lifecycle_manager() -> SourceLifecycleManager:
    """Get source lifecycle manager singleton."""
    return SourceLifecycleManager()
```

---

## 📦 Fase 3: Orchestration (Orquestación de Flujos)

### 3.1. Discovery Flow (`workflows/discovery_flow.py`)

```python
# workflows/discovery_flow.py

"""Discovery flow: Health check + GNews search + Origin hunting."""

import random
from typing import Dict, Any, List
from datetime import datetime
import uuid

from sources.gnews_client import get_gnews_client
from sources.discovery_connector import get_discovery_connector
from utils.source_lifecycle_manager import get_source_lifecycle_manager
from utils.supabase_client import get_supabase_client
from utils.logger import get_logger

logger = get_logger("discovery_flow")


async def run_discovery_flow(search_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ejecutar flujo de Discovery diario.
    
    Args:
        search_config: {
            "geo": "Álava",
            "topic": "Agricultura",
            "limit": 50,
            "sample_rate": 0.20
        }
    
    Returns:
        Dict con resultados del discovery
    """
    logger.info("discovery_flow_start", config=search_config)
    
    flow_start = datetime.utcnow()
    
    # --- PASO 1: Health Check ---
    logger.info("discovery_step_health_check")
    lifecycle_manager = get_source_lifecycle_manager()
    await lifecycle_manager.evaluate_all_sources()
    
    # --- PASO 2: GNews Search (24h) ---
    logger.info("discovery_step_gnews_search")
    gnews = get_gnews_client()
    
    headlines = await gnews.search_headlines(
        geo=search_config.get("geo"),
        topic=search_config.get("topic"),
        period_hours=24,
        limit=search_config.get("limit", 50)
    )
    
    if not headlines:
        logger.warn("discovery_no_headlines_found")
        return {
            "success": False,
            "reason": "no_headlines",
            "new_sources": 0
        }
    
    # --- PASO 3: Muestreo 20% ---
    sample_rate = search_config.get("sample_rate", 0.20)
    sampled = gnews.sample_headlines(headlines, sample_rate)
    
    logger.info("discovery_sampling_completed",
        total_headlines=len(headlines),
        sampled=len(sampled)
    )
    
    # --- PASO 4 & 5: Origin Hunting + Validación ---
    discovery_connector = get_discovery_connector()
    supabase = get_supabase_client()
    
    new_sources_found = []
    
    for item in sampled:
        title = item.get("title", "")
        description = item.get("description", "")
        url = item.get("url", "")
        
        if not url:
            continue
        
        # Origin hunting
        original_url = await discovery_connector.find_original_source(
            headline=title,
            snippet=description,
            article_url=url
        )
        
        if not original_url:
            continue
        
        # Validar si es Sala de Prensa
        is_press_room = await discovery_connector.detect_press_room_structure(original_url)
        
        if not is_press_room:
            logger.debug("not_press_room_skipping", url=original_url)
            continue
        
        # Extraer contacto
        contact_info = await discovery_connector.extract_contact_info(original_url)
        
        # Crear nueva fuente en estado "trial"
        source_id = str(uuid.uuid4())
        
        source_data = {
            "source_id": source_id,
            "source_name": f"Discovered: {title[:50]}",
            "source_type": "scraping",
            "source_code": f"discovered_{source_id[:8]}",
            "config": {
                "url": original_url,
                "url_type": "index"  # Asumir index por defecto
            },
            "schedule_config": {
                "frequency_minutes": 360  # 6 horas inicial
            },
            "status": "trial",
            "discovered_from": f"gnews:{search_config.get('geo')} {search_config.get('topic')}",
            "relevance_score": 0.5,
            "contact_email": contact_info.get("email"),
            "is_active": True,
            "created_at": datetime.utcnow().isoformat(),
            "company_id": "pool",  # Fuentes del pool
            "client_id": "system"
        }
        
        try:
            result = supabase.client.table("sources").insert(source_data).execute()
            
            if result.data:
                new_sources_found.append(source_id)
                logger.info("new_source_created",
                    source_id=source_id,
                    url=original_url,
                    status="trial"
                )
        
        except Exception as e:
            logger.error("source_creation_error",
                url=original_url,
                error=str(e)
            )
    
    # --- Resultado ---
    flow_end = datetime.utcnow()
    duration_seconds = (flow_end - flow_start).total_seconds()
    
    result = {
        "success": True,
        "headlines_searched": len(headlines),
        "headlines_sampled": len(sampled),
        "new_sources_found": len(new_sources_found),
        "source_ids": new_sources_found,
        "duration_seconds": duration_seconds
    }
    
    logger.info("discovery_flow_completed", **result)
    
    return result
```

---

### 3.2. Ingestion Flow (`workflows/ingestion_flow.py`)

```python
# workflows/ingestion_flow.py

"""Ingestion flow: Scrape active sources → Quality gate → Pool insert."""

from typing import Dict, Any, List
from datetime import datetime

from utils.supabase_client import get_supabase_client
from utils.pool_ingester import get_pool_ingester
from utils.unified_content_enricher import enrich_content
from utils.source_lifecycle_manager import get_source_lifecycle_manager
from sources.scraper_workflow import scrape_url
from utils.logger import get_logger

logger = get_logger("ingestion_flow")


async def run_ingestion_flow() -> Dict[str, Any]:
    """
    Ejecutar flujo de Ingesta para fuentes activas.
    
    Proceso:
    1. Get active/trial sources
    2. Scrape content
    3. Quality gate (LLM)
    4. Insert to Pool (Qdrant)
    5. Update source metrics
    
    Returns:
        Dict con resultados de la ingesta
    """
    logger.info("ingestion_flow_start")
    
    flow_start = datetime.utcnow()
    supabase = get_supabase_client()
    pool_ingester = get_pool_ingester()
    
    # --- PASO 1: Get Active Sources ---
    result = supabase.client.table("sources").select(
        "*"
    ).in_("status", ["active", "trial"]).eq("source_type", "scraping").execute()
    
    sources = result.data or []
    
    logger.info("ingestion_sources_loaded", count=len(sources))
    
    total_scraped = 0
    total_ingested = 0
    total_rejected_quality = 0
    total_duplicates = 0
    
    for source in sources:
        source_id = source["source_id"]
        company_id = source.get("company_id", "pool")
        config = source.get("config", {})
        
        url = config.get("url")
        url_type = config.get("url_type", "article")
        
        if not url:
            logger.warn("source_no_url", source_id=source_id)
            continue
        
        logger.info("scraping_source", source_id=source_id, url=url)
        
        try:
            # --- PASO 2: Scrape Content ---
            scrape_result = await scrape_url(
                company_id=company_id,
                source_id=source_id,
                url=url,
                url_type=url_type
            )
            
            if scrape_result.get("error"):
                logger.error("scrape_failed",
                    source_id=source_id,
                    error=scrape_result["error"]
                )
                continue
            
            content_items = scrape_result.get("content_items", [])
            total_scraped += len(content_items)
            
            source_quality_scores = []
            
            for item in content_items:
                title = item.get("title", "")
                raw_text = item.get("raw_text", "")
                item_url = item.get("url", url)
                
                # --- PASO 3: Quality Gate (Enrichment) ---
                enriched = await enrich_content(
                    raw_text=raw_text,
                    source_type="scraping",
                    company_id=company_id,
                    pre_filled={"title": title} if title else {}
                )
                
                # Score de calidad basado en:
                # - Longitud de raw_text
                # - Número de atomic_statements
                # - Category relevance
                quality_score = _calculate_quality_score(raw_text, enriched)
                
                source_quality_scores.append(quality_score)
                
                # --- PASO 4: Insert to Pool ---
                ingest_result = await pool_ingester.ingest_to_pool(
                    title=enriched.get("title", ""),
                    content=raw_text,
                    url=item_url,
                    source_id=source_id,
                    quality_score=quality_score,
                    category=enriched.get("category"),
                    tags=enriched.get("tags"),
                    published_at=item.get("published_at"),
                    metadata={
                        "enrichment_cost": enriched.get("enrichment_cost_usd", 0.0),
                        "enrichment_model": enriched.get("enrichment_model", "unknown")
                    }
                )
                
                if ingest_result["success"]:
                    total_ingested += 1
                    logger.info("content_ingested_to_pool",
                        source_id=source_id,
                        title=enriched["title"][:50],
                        quality_score=quality_score
                    )
                elif ingest_result.get("reason") == "quality_too_low":
                    total_rejected_quality += 1
                elif ingest_result.get("reason") == "duplicate":
                    total_duplicates += 1
            
            # --- PASO 5: Update Source Metrics ---
            if source_quality_scores:
                avg_quality = sum(source_quality_scores) / len(source_quality_scores)
                
                supabase.client.table("sources").update({
                    "avg_quality_score": avg_quality,
                    "last_scraped_at": datetime.utcnow().isoformat()
                }).eq("source_id", source_id).execute()
        
        except Exception as e:
            logger.error("source_ingestion_error",
                source_id=source_id,
                error=str(e)
            )
    
    # --- Resultado ---
    flow_end = datetime.utcnow()
    duration_seconds = (flow_end - flow_start).total_seconds()
    
    result = {
        "success": True,
        "sources_processed": len(sources),
        "items_scraped": total_scraped,
        "items_ingested": total_ingested,
        "items_rejected_quality": total_rejected_quality,
        "items_duplicates": total_duplicates,
        "duration_seconds": duration_seconds
    }
    
    logger.info("ingestion_flow_completed", **result)
    
    return result


def _calculate_quality_score(raw_text: str, enriched: Dict[str, Any]) -> float:
    """
    Calcular score de calidad de contenido.
    
    Args:
        raw_text: Texto raw extraído
        enriched: Resultado de enrich_content()
    
    Returns:
        Score 0.0-1.0
    """
    # Factores de calidad:
    # 1. Longitud del texto (300-3000 chars óptimo)
    # 2. Número de atomic_statements (2+ es bueno)
    # 3. Category no "general"
    
    text_length = len(raw_text)
    atomic_count = len(enriched.get("atomic_statements", []))
    category = enriched.get("category", "general")
    
    # Score de longitud (normalizado)
    if text_length < 300:
        length_score = text_length / 300.0
    elif text_length > 3000:
        length_score = 0.8  # Muy largo, ok pero no ideal
    else:
        length_score = 1.0
    
    # Score de atomic statements
    atomic_score = min(1.0, atomic_count / 5.0)  # 5+ statements → 1.0
    
    # Score de categoría
    category_score = 1.0 if category != "general" else 0.5
    
    # Promedio ponderado
    quality = (length_score * 0.3 + atomic_score * 0.4 + category_score * 0.3)
    
    return round(quality, 2)
```

---

### 3.3. Scheduler Integration (`scheduler.py`)

Añadir al scheduler existente:

```python
# En scheduler.py, añadir:

from workflows.discovery_flow import run_discovery_flow
from workflows.ingestion_flow import run_ingestion_flow

# ... (código existente)

async def schedule_discovery():
    """Schedule daily discovery flow."""
    try:
        logger.info("scheduled_discovery_start")
        
        # Configuración de búsqueda (puede venir de BD)
        search_config = {
            "geo": "Álava",
            "topic": None,  # Búsqueda general geográfica
            "limit": 50,
            "sample_rate": 0.20
        }
        
        result = await run_discovery_flow(search_config)
        
        logger.info("scheduled_discovery_completed", **result)
    
    except Exception as e:
        logger.error("scheduled_discovery_error", error=str(e))


async def schedule_ingestion():
    """Schedule hourly ingestion flow."""
    try:
        logger.info("scheduled_ingestion_start")
        
        result = await run_ingestion_flow()
        
        logger.info("scheduled_ingestion_completed", **result)
    
    except Exception as e:
        logger.error("scheduled_ingestion_error", error=str(e))


# En main(), añadir triggers:

# Discovery Flow: Diario a las 08:00 UTC
scheduler.add_job(
    schedule_discovery,
    CronTrigger(hour=8, minute=0),
    id="discovery_daily",
    name="Discovery Flow (Daily)",
    replace_existing=True
)

# Ingestion Flow: Cada hora
scheduler.add_job(
    schedule_ingestion,
    IntervalTrigger(hours=1),
    id="ingestion_hourly",
    name="Ingestion Flow (Hourly)",
    replace_existing=True
)
```

---

## 🗄️ Database Schema Changes

### Nueva tabla: `discovered_sources`

```sql
-- En Supabase, crear nueva tabla para fuentes descubiertas

CREATE TABLE IF NOT EXISTS discovered_sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'scraping',
    source_code TEXT UNIQUE NOT NULL,
    
    -- URL y configuración
    url TEXT NOT NULL,
    config JSONB DEFAULT '{}'::jsonb,
    schedule_config JSONB DEFAULT '{}'::jsonb,
    
    -- Estado de la fuente
    status TEXT NOT NULL DEFAULT 'trial' CHECK (status IN ('trial', 'active', 'inactive', 'archived')),
    
    -- Métricas
    relevance_score REAL DEFAULT 0.5,
    avg_quality_score REAL DEFAULT 0.5,
    
    -- Discovery metadata
    discovered_from TEXT,  -- Ej: "gnews:Álava Agricultura"
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    last_evaluated_at TIMESTAMPTZ,
    last_scraped_at TIMESTAMPTZ,
    
    -- Contacto
    contact_email TEXT,
    contact_name TEXT,
    contact_phone TEXT,
    
    -- Sistema
    company_id TEXT DEFAULT 'pool',
    client_id TEXT DEFAULT 'system',
    is_active BOOLEAN DEFAULT true,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices
CREATE INDEX idx_discovered_sources_status ON discovered_sources(status);
CREATE INDEX idx_discovered_sources_relevance ON discovered_sources(relevance_score DESC);
CREATE INDEX idx_discovered_sources_company ON discovered_sources(company_id);

-- Trigger para updated_at
CREATE TRIGGER update_discovered_sources_updated_at
    BEFORE UPDATE ON discovered_sources
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

### Modificar `sources` para link a discovered_sources (opcional)

```sql
-- Añadir columna opcional en sources para referenciar discovered_sources
ALTER TABLE sources ADD COLUMN IF NOT EXISTS discovered_source_id UUID REFERENCES discovered_sources(source_id);
```

---

## 📝 Testing Plan

### Unit Tests

```bash
# Test GNews Client
pytest tests/test_gnews_client.py -v

# Test Discovery Connector
pytest tests/test_discovery_connector.py -v

# Test Pool Ingester
pytest tests/test_pool_ingester.py -v

# Test Source Lifecycle Manager
pytest tests/test_source_lifecycle_manager.py -v
```

### Integration Tests

```bash
# Test Discovery Flow end-to-end
pytest tests/integration/test_discovery_flow.py -v

# Test Ingestion Flow end-to-end
pytest tests/integration/test_ingestion_flow.py -v
```

### Manual Testing

```bash
# 1. Ejecutar Discovery Flow manual
docker exec ekimen_semantika-semantika-api-1 python cli.py run-discovery \
  --geo "Bilbao" --topic "Tecnología" --limit 20

# 2. Ejecutar Ingestion Flow manual
docker exec ekimen_semantika-semantika-api-1 python cli.py run-ingestion

# 3. Verificar sources creadas
docker exec ekimen_semantika-semantika-api-1 python cli.py list-discovered-sources --status trial

# 4. Verificar contenido en Qdrant Pool
docker exec ekimen_semantika-semantika-api-1 python cli.py query-pool --query "tecnología Bilbao" --limit 5
```

---

## 📅 Timeline de Implementación

| Fase | Componentes | Duración | Prioridad |
|:-----|:------------|:---------|:----------|
| **Fase 1** | GNews Client + Discovery Connector | 3-4 días | Alta |
| **Fase 2** | Pool Ingester + Source Lifecycle Manager | 2-3 días | Alta |
| **Fase 3** | Discovery Flow + Ingestion Flow | 2-3 días | Alta |
| **Fase 4** | Scheduler Integration + Testing | 2 días | Alta |
| **Fase 5** | Database Schema + Migration | 1 día | Alta |
| **Fase 6** | CLI Commands + Documentation | 1-2 días | Media |
| **TOTAL** | - | **11-15 días** | - |

---

## 🎯 Próximos Pasos Inmediatos

1. **Crear `.env` con GNews API Key:**
   ```bash
   GNEWS_API_KEY=your_gnews_api_key
   ```

2. **Crear estructura de archivos:**
   ```bash
   touch sources/gnews_client.py
   touch sources/discovery_connector.py
   touch utils/pool_ingester.py
   touch utils/source_lifecycle_manager.py
   touch workflows/discovery_flow.py
   touch workflows/ingestion_flow.py
   ```

3. **Ejecutar migration SQL en Supabase**
   - Crear tabla `discovered_sources`
   - Añadir columna `discovered_source_id` a `sources`

4. **Implementar Fase 1 (GNews + Discovery)**
   - `gnews_client.py`: Búsqueda + Muestreo
   - `discovery_connector.py`: Origin Hunting + Press Room Detection

5. **Testing inicial:**
   ```bash
   # Test manual de GNews
   python -c "
   import asyncio
   from sources.gnews_client import get_gnews_client
   client = get_gnews_client()
   results = asyncio.run(client.search_headlines(geo='Bilbao', limit=10))
   print(f'Found {len(results)} headlines')
   "
   ```

---

## 🔗 Referencias

- **Documentación arquitectura**: `semantika-llamadas.md`
- **Utilidades existentes**: `utils/unified_*.py`
- **Scraper workflow**: `sources/scraper_workflow.py`
- **Qdrant client**: `utils/qdrant_client.py`
- **LLM client**: `utils/llm_client.py`

---

**Estado:** 📋 Plan listo para implementación  
**Próxima acción:** Crear archivos y comenzar Fase 1
