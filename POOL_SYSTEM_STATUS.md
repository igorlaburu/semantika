# Pool System - Estado de Implementación

**Fecha actualización:** 8 Diciembre 2024  
**Status:** ✅ Funcional (Discovery + Ingestion + Endpoints)

---

## 🎯 Arquitectura Implementada

### Separación Companies vs Pool

```
┌────────────────────────────────────────────────────────────┐
│ COMPANIES (Clientes periodistas - Privado)                 │
├────────────────────────────────────────────────────────────┤
│ sources (tabla) → scraper_workflow.py                      │
│   ↓                                                         │
│ monitored_urls (tracking URLs)                             │
│   ↓                                                         │
│ url_content_units (contenido scrapeado)                    │
│   ↓                                                         │
│ pgvector en Supabase (embeddings 768d)                     │
│   - Búsquedas privadas por company_id                      │
│   - RLS habilitado                                         │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ POOL (Sistema compartido - Público)                        │
├────────────────────────────────────────────────────────────┤
│ pool_discovery_config (tabla) → Filtros geográficos        │
│   ↓                                                         │
│ workflows/discovery_flow.py (cada 3 días)                  │
│   - GNews API → Headlines geográficos                      │
│   - Groq Compound → Búsqueda fuente original               │
│   - extract_index_url() → Encuentra página índice          │
│   - analyze_press_room() → Valida institutional source     │
│   ↓                                                         │
│ discovered_sources (tabla) → Fuentes encontradas           │
│   - Status: trial → active → inactive → archived           │
│   - Métricas: quality_score, content_count_7d              │
│   ↓                                                         │
│ workflows/ingestion_flow.py (cada hora)                    │
│   - Scrape con WebScraper (sin tabla sources)              │
│   - Enrich con LLM (category, atomic facts, quality)       │
│   - Quality gate: >= 0.4                                   │
│   ↓                                                         │
│ Qdrant Pool collection (company_id="pool")                 │
│   - Embeddings 768d (FastEmbed multilingual)               │
│   - Deduplicación automática (similarity > 0.98)           │
│   - Todas las companies pueden consultar                   │
└────────────────────────────────────────────────────────────┘
```

---

## 📊 Componentes Implementados

### 1. Discovery System ✅

**Archivos:**
- `workflows/discovery_flow.py` - Orquestador principal
- `sources/discovery_connector.py` - LLM analysis + URL extraction
- `sources/gnews_client.py` - GNews API wrapper

**Funciones clave:**

#### `discovery_flow.py::execute_discovery_job()`
```python
# FLUJO:
# 1. Lee configs activas (pool_discovery_config)
# 2. Por cada config (Álava, Bizkaia...):
#    - Busca noticias en GNews (query geográfico)
#    - Sample 5% de artículos
#    - Por cada headline:
#      a. Groq Compound → Busca fuente original
#      b. extract_index_url() → Encuentra índice (/news, /sala-prensa)
#      c. analyze_press_room() → Valida + metadata
#      d. Guarda en discovered_sources

# Scheduling: Cada 3 días a las 8:00 UTC
# Job: pool_discovery_job() en scheduler.py
```

#### `discovery_connector.py::extract_index_url()` ✅ NUEVO
```python
# PROPÓSITO:
# Convertir URL de artículo específico → URL del índice de noticias
# 
# INPUT: https://irekia.eus/es/events/106714-titulo-largo
# OUTPUT: https://irekia.eus/es/events
#
# MÉTODO:
# 1. Fetch HTML completo (sin filtros)
# 2. Envía HTML al LLM (groq_fast)
# 3. LLM analiza breadcrumbs, navigation, URL structure
# 4. LLM extrae href del índice o infiere quitando slug
# 
# RETURN: {
#   "index_url": "https://...",
#   "confidence": 0.9,
#   "method": "breadcrumb_link" | "navigation_link" | "url_inference"
# }
```

#### `discovery_connector.py::analyze_press_room()` ✅
```python
# PROPÓSITO:
# Validar que una URL es sala de prensa institucional
#
# INPUT: URL del índice (NO artículo específico)
# OUTPUT: {
#   "is_press_room": true,
#   "confidence": 0.8,
#   "org_name": "Gobierno Vasco",
#   "contact_email": "prensa@euskadi.eus",
#   "estimated_quality": 0.7,
#   "notes": "Sala de prensa activa con comunicados regulares"
# }
#
# TRACKING: SYSTEM organization (88044361-8529-46c8-8196-d1345ca7bbe8)
```

**Tablas DB:**

#### `pool_discovery_config`
```sql
CREATE TABLE pool_discovery_config (
    config_id UUID PRIMARY KEY,
    geographic_area TEXT NOT NULL,           -- "Álava", "Bizkaia"
    search_query TEXT NOT NULL,              -- "Vitoria"
    gnews_lang TEXT DEFAULT 'es',
    gnews_country TEXT DEFAULT 'es',
    max_articles INT DEFAULT 100,
    sample_rate FLOAT DEFAULT 0.05,          -- 5%
    excluded_domains TEXT[] DEFAULT '{}',
    target_source_types TEXT[] DEFAULT ARRAY['press_room', 'institutional'],
    is_active BOOLEAN DEFAULT true,
    priority INT DEFAULT 1,
    created_by UUID REFERENCES organizations(id)  -- SYSTEM org
);

-- Estado actual: 1 config activo (Álava)
```

#### `discovered_sources`
```sql
-- Fuentes encontradas automáticamente
{
  "source_id": "uuid",
  "source_name": "Gobierno Vasco",
  "url": "https://irekia.euskadi.eus/es/events",  -- URL ÍNDICE (no artículo)
  "status": "trial",  -- trial → active → inactive → archived
  "relevance_score": 0.8,
  "avg_quality_score": 0.7,
  "content_count_7d": 0,
  "company_id": "00000000-0000-0000-0000-000000000999",  -- Pool UUID
  "config": {
    "original_source_url": "https://.../106714-...",  -- Artículo original
    "index_url": "https://.../events",                 -- Índice extraído
    "index_extraction_method": "breadcrumb_link",
    "index_extraction_confidence": 0.9,
    "discovery_config_id": "uuid",
    "geographic_area": "Álava"
  }
}

-- Estado actual: 1 source descubierta (Irekia Gobierno Vasco)
```

---

### 2. Ingestion System ✅

**Archivos:**
- `workflows/ingestion_flow.py` - Scraping + enrichment + Qdrant
- `sources/web_scraper.py` - HTML scraping (usado por Pool)
- `utils/pool_client.py` - Qdrant Pool operations

**Funciones clave:**

#### `ingestion_flow.py::execute_ingestion_job()`
```python
# FLUJO:
# 1. Get active sources (discovered_sources WHERE status IN ('trial', 'active'))
# 2. Por cada source:
#    a. Scrape con WebScraper (NO usa tabla sources)
#    b. Enrich con LLM (title, summary, category, atomic_facts, quality_score)
#    c. Quality gate: quality_score >= 0.4
#    d. Ingest a Qdrant via pool_client.ingest_to_pool()
#    e. Update stats en discovered_sources

# Scheduling: Cada hora
# Job: pool_ingestion_job() en scheduler.py
```

#### `pool_client.py::ingest_to_pool()` ✅
```python
# PROPÓSITO:
# Ingerir contenido enriquecido a Qdrant Pool collection
#
# FEATURES:
# - Genera embedding 768d (FastEmbed multilingual)
# - Deduplicación automática (similarity > 0.98)
# - Quality threshold: >= 0.4
# - Collection: 'pool' (company_id="pool")
#
# PAYLOAD Qdrant:
# {
#   "company_id": "pool",
#   "source_id": "uuid",
#   "title": "...",
#   "content": "...",  # Truncado 5000 chars
#   "category": "economía",
#   "tags": [...],
#   "quality_score": 0.75,
#   "atomic_statements": [...],  # Máx 20
#   "published_at": "2024-12-08T...",
#   "ingested_at": "2024-12-08T...",
#   "source_name": "Gobierno Vasco",
#   "source_code": "www_irekia_euskadi_eus"
# }
```

#### `pool_client.py::search()` ✅
```python
# Búsqueda semántica en Pool con filtros:
# - categories: ["economía", "política"]
# - date_from / date_to
# - min_quality: 0.6
# - tags: ["subvenciones"]
# - score_threshold: 0.7
```

**Tablas DB:**

#### `companies` (Pool company)
```sql
-- UUID especial para Pool
{
  "id": "00000000-0000-0000-0000-000000000999",
  "company_code": "pool",
  "company_name": "Pool (Sistema compartido)",
  "tier": "unlimited",
  "settings": {
    "unlimited_usage": true,
    "store_in_qdrant": true
  }
}
```

#### `organizations` (SYSTEM org)
```sql
-- Para tracking LLM del sistema Pool
{
  "id": "88044361-8529-46c8-8196-d1345ca7bbe8",
  "slug": "system",
  "name": "System Pool Operations",
  "company_id": null,
  "is_active": true
}
```

---

### 3. API Endpoints ✅

#### Discovery & Management

**`GET /pool/system/health`** ✅
```
Auth: X-System-Key
Returns: {
  "status": "healthy",
  "pool_stats": {
    "total_context_units": 0,
    "collection_name": "pool",
    "total_sources": 1,
    "sources_by_status": {"trial": 1}
  }
}
```

**`GET /pool/system/stats`** ✅
```
Auth: X-System-Key
Returns: {
  "total_context_units": 0,
  "collection_name": "pool",
  "avg_source_relevance": 0.8,
  "avg_source_quality": 0.7
}
```

**`GET /pool/sources`** ✅
```
Auth: X-API-Key
Params: status, limit
Returns: {
  "sources": [{
    "source_id": "uuid",
    "source_name": "Gobierno Vasco",
    "url": "https://irekia.euskadi.eus/es/events",
    "status": "trial",
    "relevance_score": 0.8,
    "avg_quality_score": 0.7,
    "config": {...}
  }]
}
```

#### Search & Context

**`POST /pool/search`** ✅
```
Auth: X-API-Key
Body: {
  "query": "Vitoria inversión industrial",
  "limit": 10,
  "filters": {
    "category": "economía",
    "date_from": "2024-01-01"
  },
  "score_threshold": 0.7
}
Returns: {
  "results": [...],
  "total": 0,
  "query_time_ms": 89.9
}
```

**`GET /pool/context/{context_id}`** ✅
```
Auth: X-API-Key
Returns: {
  "id": "uuid",
  "title": "...",
  "content": "...",
  "category": "economía",
  "tags": [...],
  "quality_score": 0.75,
  "atomic_statements": [...],
  "source_name": "Gobierno Vasco"
}
```

**`POST /pool/adopt`** ✅
```
Auth: JWT (user token)
Body: {
  "context_id": "uuid",
  "target_organization_id": "user-org-uuid"
}
Purpose: Copiar context unit del Pool a espacio privado del usuario
```

#### ❌ Endpoint Faltante

**`GET /pool/context-units`** (listar con filtros)
```
# TODO: Implementar endpoint de listado
# Similar a /pool/search pero sin query text
# Filtros: category, date_from, date_to, min_quality, limit, offset
```

---

## 🔄 Scheduling (scheduler.py)

```python
# Pool discovery job - Cada 3 días a las 8:00 UTC
scheduler.add_job(
    pool_discovery_job,
    trigger=CronTrigger(hour=8, minute=0, day='*/3'),
    id="pool_discovery"
)

# Pool ingestion job - Cada hora
scheduler.add_job(
    pool_ingestion_job,
    trigger=IntervalTrigger(hours=1),
    id="pool_ingestion"
)
```

---

## 📈 Estado Actual (8 Dic 2024)

### Discovered Sources
| Source | URL | Status | Quality | Last Scraped |
|--------|-----|--------|---------|-------------|
| Gobierno Vasco (Irekia) | `irekia.euskadi.eus/es/events` | trial | 0.7 | Nunca |

### Qdrant Pool Collection
- **Total points:** 0 (vacía)
- **Vector size:** 768d
- **Collection name:** `pool`

### Next Steps
1. ✅ Discovery encontró 1 fuente (Irekia)
2. ⏳ Ingestion debe scrapear e ingestar (próxima hora)
3. ⏳ Validar que aparece contenido en `/pool/search`

---

## 🐛 Problemas Conocidos

### 1. extract_index_url() - Sin probar aún
- ✅ Implementado
- ⏳ Pendiente: Probar con más URLs reales
- **Próximo test:** Próxima ejecución discovery (cada 3 días)

### 2. Ingestion flow - Error en enrich_content
- ✅ Fixed: Removido `organization_id` parameter
- ⏳ Pendiente: Validar ingestion completa (próxima hora)

### 3. WebScraper - Puede no extraer contenido
- **Síntoma:** `scrape_url()` devuelve lista vacía
- **Causa:** Página compleja (mucho JS, anti-scraping)
- **Solución futura:** Usar scraping service (ScraperAPI, etc.)

---

## 📝 Mejoras Futuras

### Corto Plazo (1-2 semanas)
1. [ ] Implementar `GET /pool/context-units` (listing endpoint)
2. [ ] Añadir más configs geográficos (Bizkaia, Gipuzkoa)
3. [ ] Lifecycle management (trial → active → archived)
4. [ ] Metrics dashboard (/pool/system/metrics)

### Medio Plazo (1 mes)
1. [ ] Relevance scoring automático
2. [ ] Source quality evaluation (histórico)
3. [ ] Deduplicación cross-source
4. [ ] Notification system (nuevas fuentes high-quality)

### Largo Plazo (3 meses)
1. [ ] Frontend UI para discovered sources
2. [ ] Manual approval workflow (humano valida sources)
3. [ ] A/B testing discovery strategies
4. [ ] Export discovered sources to JSON/CSV

---

## 📚 Documentación Relacionada

- `plan_desarrollo_discovery.md` - Plan original (obsoleto parcialmente)
- `reflexiones_sobre_pgvector_y_qdrant_fuentes-propias-y-pool.md` - Arquitectura Pool
- `CLAUDE.md` - Guía desarrollo general

---

**Última actualización:** 8 Diciembre 2024  
**Autor:** Claude Code + Igor  
**Status:** ✅ Sistema funcional, esperando primera ingestion
