# SEMANTIKA - Árbol de Llamadas de Funciones (News Processing)

## Flujo Principal del Scheduler

```
scheduler.py::main()
│
├─► schedule_sources()
│   └─► execute_source_task(source)
│       │
│       ├─► [source_type="scraping"]
│       │   └─► scraper_workflow.scrape_url(company_id, source_id, url, url_type)
│       │       │
│       │       ├─► LangGraph Workflow (8 nodes):
│       │       │   │
│       │       │   ├─► 1. fetch_url(state)
│       │       │   │   └─► aiohttp.ClientSession.get()
│       │       │   │
│       │       │   ├─► 2. parse_content(state)
│       │       │   │   ├─► [url_type="article"]
│       │       │   │   │   ├─► parse_article(state, soup)
│       │       │   │   │   │   ├─► BeautifulSoup parsing
│       │       │   │   │   │   └─► [multi-noticia detected: 3+ valid blocks]
│       │       │   │   │   │       └─► parse_multi_noticia(state, news_blocks, soup)
│       │       │   │   │   │           └─► FOR EACH block:
│       │       │   │   │   │               └─► unified_content_enricher.enrich_content()
│       │       │   │   │   │                   └─► llm_client.analyze_atomic()
│       │       │   │   │   │                       └─► Groq Llama 3.3 70B
│       │       │   │   │   │
│       │       │   │   │   └─► [single article]
│       │       │   │   │       └─► parse_single_article(state, page_title, content)
│       │       │   │   │           └─► unified_content_enricher.enrich_content()
│       │       │   │   │               └─► llm_client.analyze_atomic()
│       │       │   │   │
│       │       │   │   └─► [url_type="index"]
│       │       │   │       └─► parse_index(state, soup)
│       │       │   │           ├─► llm_client.extract_news_links(html, base_url)
│       │       │   │           │   └─► Groq Llama 3.3 70B
│       │       │   │           │
│       │       │   │           └─► scrape_articles_from_index(articles, company_id)
│       │       │   │               └─► FOR EACH article (max 3 concurrent):
│       │       │   │                   ├─► aiohttp.ClientSession.get(article_url)
│       │       │   │                   └─► unified_content_enricher.enrich_content()
│       │       │   │
│       │       │   ├─► 3. detect_changes(state)
│       │       │   │   └─► change_detector.detect_change()
│       │       │   │       ├─► Tier 1: content_hash (MD5)
│       │       │   │       ├─► Tier 2: simhash (semantic)
│       │       │   │       └─► Tier 3: embedding similarity
│       │       │   │           └─► embedding_generator.generate_embedding()
│       │       │   │               └─► FastEmbed multilingual (768d)
│       │       │   │
│       │       │   ├─► 4. extract_date(state)
│       │       │   │   └─► date_extractor.extract_publication_date()
│       │       │   │       ├─► extract_from_meta_tags()
│       │       │   │       ├─► extract_from_jsonld()
│       │       │   │       ├─► extract_from_url()
│       │       │   │       ├─► extract_from_css_selectors()
│       │       │   │       └─► extract_from_llm()
│       │       │   │
│       │       │   ├─► 5. filter_content(state)
│       │       │   ├─► 6. save_monitored_url(state)
│       │       │   ├─► 7. save_url_content(state)
│       │       │   │   └─► FOR EACH content_item:
│       │       │   │       ├─► embedding_generator.generate_embedding()
│       │       │   │       └─► supabase.table("url_content_units").upsert()
│       │       │   │
│       │       │   └─► 8. ingest_to_context(state)
│       │       │       └─► context_unit_saver.save_from_scraping()
│       │       │           └─► context_unit_saver.save_context_unit()
│       │       │               ├─► embedding_generator.generate_embedding()
│       │       │               ├─► check_for_duplicates()
│       │       │               │   └─► supabase.rpc('match_context_units')
│       │       │               └─► supabase.table("press_context_units").insert()
│       │       │
│       │       └─► supabase.log_execution()
│       │
│       ├─► [source_type="api" + connector="perplexity_news"]
│       │   └─► perplexity_news_connector.execute_perplexity_news_task(source)
│       │       │
│       │       ├─► PerplexityNewsConnector.fetch_news(location, news_count)
│       │       │   ├─► aiohttp.post(perplexity_api_url)
│       │       │   │   └─► model: "sonar"
│       │       │   └─► JSON parsing (robust 3-tier)
│       │       │
│       │       └─► FOR EACH news_item:
│       │           │
│       │           ├─► Phase 1: unified_context_verifier.verify_novelty()
│       │           │   └─► [source_type="api"] → Check title in 24h
│       │           │
│       │           ├─► Phase 2: unified_content_enricher.enrich_content()
│       │           │   └─► llm_client.analyze_atomic()
│       │           │       └─► Groq Llama 3.3 70B
│       │           │
│       │           └─► Phase 3: unified_context_ingester.ingest_context_unit()
│       │               ├─► normalize_atomic_statements()
│       │               ├─► embedding_generator.generate_embedding()
│       │               ├─► Check semantic duplicates (threshold 0.98)
│       │               └─► supabase.table("press_context_units").insert()
│       │
│       ├─► [source_type="api" + connector="dfa_subsidies"]
│       │   └─► dfa_subsidies_monitor.check_for_updates(source, company)
│       │       ├─► fetch_page(target_url)
│       │       ├─► content_hasher.compare_content()
│       │       │   ├─► Tier 1: content_hash (MD5)
│       │       │   └─► Tier 2: simhash
│       │       │
│       │       └─► [changes detected]
│       │           └─► unified_context_ingester.ingest_web_context_unit()
│       │               ├─► Generate missing fields with LLM
│       │               ├─► embedding_generator.generate_embedding()
│       │               └─► supabase.table("web_context_units").upsert()
│       │
│       └─► [source_type="webhook"]
│           └─► (Triggered externally)
│
├─► run_multi_company_email_monitor()
│   └─► MultiCompanyEmailMonitor.start()
│       └─► Loop: check_inbox() every 60s
│           └─► FOR EACH unread email:
│               │
│               ├─► _get_routing_and_source(to_address)
│               │
│               ├─► Collect content parts:
│               │   ├─► Email subject
│               │   ├─► Email body
│               │   ├─► FOR EACH text attachment → decode
│               │   └─► FOR EACH audio attachment:
│               │       └─► AudioTranscriber.transcribe_file()
│               │           └─► Whisper model ("base")
│               │
│               └─► _process_combined_content_with_workflow()
│                   ├─► Phase 1: unified_context_verifier.verify_novelty()
│                   │   └─► [source_type="email"] → Check Message-ID
│                   │
│                   └─► Phase 2: unified_context_ingester.ingest_context_unit()
│                       ├─► llm_client.generate_context_unit()
│                       │   └─► GPT-4o-mini
│                       ├─► normalize_atomic_statements()
│                       ├─► embedding_generator.generate_embedding()
│                       └─► supabase.table("press_context_units").insert()
│
└─► cleanup_old_data()
    └─► CronTrigger(hour=3, minute=0)
        └─► qdrant.delete_old_points(cutoff_timestamp)
```

## Utilidades Compartidas (Shared Utilities)

### unified_content_enricher.enrich_content()
```
├─► llm_client.analyze_atomic(text)
│   └─► Groq Llama 3.3 70B
│       └─► Returns: {title, summary, tags, category, atomic_facts}
└─► Output: {enrichment_cost_usd, enrichment_model, ...}
```

### unified_context_verifier.verify_novelty()
```
├─► [scraping] → change_detector.detect_change()
├─► [email] → Check Message-ID
├─► [api] → Check title + date in 24h
└─► [manual] → Always novel
```

### unified_context_ingester.ingest_context_unit()
```
├─► Generate missing fields (GPT-4o-mini if needed)
├─► normalize_atomic_statements()
├─► embedding_generator.generate_embedding()
│   ├─► Primary: FastEmbed multilingual (768d)
│   └─► Fallback: OpenAI (384d)
├─► Check semantic duplicates (threshold 0.98)
└─► supabase.table("press_context_units").insert()
```

### embedding_generator.generate_embedding()
```
├─► [force_openai=false] (default)
│   ├─► Try: FastEmbed TextEmbedding (768d)
│   └─► Fallback: OpenRouter OpenAI (384d)
└─► Returns: List[float]
```

### llm_client.analyze_atomic()
```
├─► Groq Llama 3.3 70B Versatile
└─► Returns: {title, summary, tags, category, atomic_facts[]}
```

### llm_client.generate_context_unit()
```
├─► GPT-4o-mini via OpenRouter
└─► Returns: {title, summary, tags, category, atomic_statements}
```

## Flujos Principales (Main Flows)

### 1. SCRAPING FLOW (Web Articles)
```
scheduler → scrape_url → LangGraph (8 nodes) → enrich → embed → save
```

**Detalles**:
- **Entrada**: URL de artículo o índice
- **Proceso**: LangGraph state machine con 8 nodos
- **Enriquecimiento**: Groq Llama 3.3 70B (analyze_atomic)
- **Embedding**: FastEmbed multilingual 768d
- **Deduplicación**: Multi-tier (hash → simhash → embedding)
- **Salida**: `press_context_units` + `url_content_units`

### 2. PERPLEXITY NEWS FLOW (API News)
```
scheduler → fetch_news → verify_novelty → enrich → ingest → embed → save
```

**Detalles**:
- **Entrada**: Location (e.g., "Bilbao, Bizkaia") + news_count (e.g., 5)
- **API**: Perplexity "sonar" model
- **Verificación**: Title matching en últimas 24h
- **Enriquecimiento**: Groq Llama 3.3 70B
- **Embedding**: FastEmbed multilingual 768d
- **Salida**: `press_context_units`

### 3. EMAIL FLOW (Email + Audio)
```
monitor → check_inbox → transcribe → verify → ingest → embed → save
```

**Detalles**:
- **Entrada**: Email unread vía IMAP
- **Routing**: Por dirección email (p.{company}@ekimen.ai)
- **Transcripción**: Whisper "base" para audios adjuntos
- **Verificación**: Message-ID duplicado
- **Enriquecimiento**: GPT-4o-mini (generate_context_unit)
- **Embedding**: FastEmbed multilingual 768d
- **Salida**: `press_context_units`

### 4. DFA SUBSIDIES FLOW (Government Forms)
```
scheduler → check_updates → detect_changes → ingest → save
```

**Detalles**:
- **Entrada**: URL de página de subvenciones DFA
- **Detección**: Multi-tier change detection (hash → simhash)
- **Workflow**: SubsidyExtractionWorkflow (custom)
- **Embedding**: FastEmbed multilingual 768d
- **Salida**: `web_context_units`

## Modelos LLM Utilizados

### 1. Groq Llama 3.3 70B Versatile (FREE)
**Uso**:
- `analyze_atomic()` → Extract facts/tags/summary from scraped content
- `extract_news_links()` → Parse index pages for article URLs

**Características**:
- **Provider**: Groq (free tier)
- **Costo**: $0.00/request
- **Velocidad**: ~2-3 segundos/request
- **Contexto**: 8K tokens
- **Output**: JSON estructurado

### 2. GPT-4o-mini via OpenRouter (PAID)
**Uso**:
- `generate_context_unit()` → Generate missing fields (title, summary, tags)
- Universal fallback cuando Groq no disponible

**Características**:
- **Provider**: OpenRouter
- **Costo**: ~$0.15 per 1M input tokens + $0.60 per 1M output tokens
- **Velocidad**: ~3-5 segundos/request
- **Contexto**: 128K tokens
- **Output**: JSON estructurado

### 3. FastEmbed Multilingual (LOCAL)
**Uso**:
- Generación de embeddings 768d para Spanish/Basque
- Duplicate detection + semantic search

**Características**:
- **Modelo**: `paraphrase-multilingual-mpnet-base-v2`
- **Dimensiones**: 768
- **Idiomas**: 50+ incluyendo español y euskera
- **Costo**: $0.00 (local inference)
- **Velocidad**: ~100-200ms/embedding

### 4. OpenAI text-embedding-3-small (FALLBACK)
**Uso**:
- Fallback cuando FastEmbed falla
- Legacy embeddings (384d truncated from 1536d)

**Características**:
- **Provider**: OpenRouter/OpenAI
- **Dimensiones**: 384 (truncado de 1536)
- **Costo**: ~$0.02 per 1M tokens
- **Velocidad**: ~500ms/embedding

## Puntos Clave de Arquitectura

✅ **Convergencia unificada**: Todos los flujos convergen en `unified_context_ingester`

✅ **Verificación de novedad**: `verify_novelty()` antes de procesamiento LLM (ahorra costos)

✅ **Enriquecimiento unificado**: `enrich_content()` para todos los source types

✅ **Embeddings locales**: FastEmbed 768d con fallback a OpenAI 384d

✅ **Deduplicación semántica**: pgvector cosine similarity (threshold 0.98)

✅ **Groq para scraping**: Free, fast, JSON parsing confiable

✅ **GPT-4o-mini para fallback**: Paid, mejor contexto, universal

✅ **LangGraph para scraping**: State machine de 8 nodos con detección multi-tier

✅ **Normalización de atomic_statements**: Groq string[] → GPT dict[] unificado

✅ **Multi-tier change detection**: hash → simhash → embedding (evita reingesta)

## Tablas de Base de Datos

### press_context_units (Principal)
**Contenido**: Context units enriquecidos de todas las fuentes

**Campos clave**:
- `id`: UUID
- `company_id`: Multi-tenancy
- `source_type`: email, api, scraping, webhook, manual, file
- `source_id`: Referencia a `sources` table
- `title`, `summary`, `tags`, `category`
- `atomic_statements`: JSONB array de hechos atómicos
- `embedding`: vector(768) para búsqueda semántica
- `raw_text`: Texto original sin procesar

### url_content_units
**Contenido**: Unidades extraídas de URLs (multi-noticia)

**Campos clave**:
- `monitored_url_id`: Referencia a `monitored_urls`
- `content_position`: Orden en página multi-noticia
- `embedding`: vector(768)
- `published_at`: Fecha de publicación extraída
- `ingested_to_context_unit_id`: Referencia a `press_context_units`

### monitored_urls
**Contenido**: URLs monitorizadas con historial de cambios

**Campos clave**:
- `url`, `url_type`: article o index
- `content_hash`, `simhash`: Para change detection
- `published_at`: Fecha extraída
- `last_scraped_at`, `last_modified_at`

### web_context_units
**Contenido**: Context units de web (DFA subsidies, custom scrapers)

**Campos clave**:
- `source_type`: dfa_subsidies, web_monitoring, custom_scraper
- `version`: Versionado de contenido
- `replaced_by_id`: Para tracking de actualizaciones
- `is_latest`: Boolean flag

### sources
**Contenido**: Configuración de fuentes de información

**Campos clave**:
- `source_type`: email, scraping, api, webhook, etc.
- `config`: JSONB con configuración específica
- `schedule_config`: JSONB con cron/interval
- `workflow_code`: Workflow a usar para procesamiento

## Validaciones Implementadas

### Future Date Validation (date_extractor.py)
**Problema**: Fechas futuras en contenido (deadlines, eventos) detectadas como fecha de publicación

**Solución**: 
```python
if dt and dt <= datetime.now():
    dates.append((dt, source, confidence))
elif dt and dt > now:
    logger.warn("future_date_ignored", date=dt.isoformat())
```

**Aplicado en**:
- `extract_from_meta_tags()`
- `extract_from_jsonld()`
- `extract_from_css_selectors()`
- `extract_from_url()`
- `extract_from_llm()`

### Source Type Validation
**Problema**: Constraint `source_type_valid` en `press_context_units`

**Valores permitidos**: `email`, `api`, `file`, `webhook`, `manual`, `scraping`

**Solución**: Perplexity usa `source_type='api'` con `connector_type='perplexity_news'` en metadata

## Configuración de Horarios (Zonas Horarias)

**Sistema**: UTC siempre

**España**: 
- Invierno (CET): UTC+1
- Verano (CEST): UTC+2

**Conversión**:
- España 13:00 (invierno) = UTC 12:00
- España 14:00 (verano) = UTC 12:00

**Scheduler auto-reload**: Cada 5 minutos recarga sources desde BD

**No reiniciar scheduler** después de cambios en BD - esperar hasta 5min para que recargue automáticamente
