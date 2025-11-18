# Source Discovery - Auto-configuración de Fuentes

## Objetivo

Permitir a los usuarios configurar fuentes de información de forma automática proporcionando:
- Contexto geográfico (ej: "Álava", "País Vasco")
- Temática (ej: "política local", "cultura")
- Tipo de fuente (ej: "ayuntamientos", "medios oficiales")

El sistema debe descubrir fuentes públicas accesibles sin copyright automáticamente.

---

## Opción 1: LLM + Web Search Discovery (MÁS INTELIGENTE)

### Descripción
Usar LLM con capacidad de web search para descubrir fuentes en tiempo real.

### Flujo
```
Usuario: "Noticias de Álava"
↓
1. LLM genera keywords: "álava ayuntamientos sitios oficiales noticias"
2. Web search (Perplexity/Groq Compound) busca fuentes
3. LLM analiza resultados y filtra:
   ✅ Sitios oficiales (.eus, .gob.es, ayuntamientos)
   ✅ Medios locales conocidos
   ✅ RSS/Atom disponibles
   ❌ Descarta: paywalls, copyright, redes sociales
4. LLM detecta estructura (RSS, lista de noticias, etc.)
5. Propone fuentes con config autodetectada
```

### Implementación
```python
async def discover_with_llm(criteria: str) -> List[Dict]:
    """Discover sources using LLM with web search."""

    prompt = f"""
    Busca fuentes de noticias públicas para: {criteria}

    Criterios:
    - Solo sitios oficiales o medios verificados
    - Sin paywall ni copyright restrictivo
    - Preferir .eus, .gob.es, ayuntamientos, diputaciones
    - Indicar si tiene RSS/Atom

    Devuelve JSON:
    [
      {{
        "name": "Ayuntamiento de Vitoria",
        "url": "https://vitoria-gasteiz.org/noticias",
        "rss_url": "https://...",
        "type": "ayuntamiento",
        "tags": ["alava", "vitoria", "oficial"],
        "confidence": 0.95
      }}
    ]
    """

    # Use Groq Compound or Perplexity with web search
    response = await groq_compound.ainvoke(prompt)

    sources = parse_json_response(response)

    # Validate URLs (HEAD request)
    validated = await validate_sources(sources)

    return validated
```

### Ventajas
- ✅ Muy flexible, funciona para cualquier zona geográfica
- ✅ Descubre fuentes nuevas automáticamente
- ✅ Detecta estructura y tipo de scraping necesario

### Desventajas
- ❌ Coste LLM por búsqueda
- ❌ Puede encontrar fuentes inestables
- ❌ Requiere validación posterior

---

## Opción 2: Directorio Curado + Matching Semántico (MÁS FIABLE)

### Descripción
Mantener un catálogo pre-verificado de fuentes y usar búsqueda semántica para matching.

### Schema
```sql
CREATE TABLE source_catalog (
  id UUID PRIMARY KEY,
  name VARCHAR NOT NULL,
  url VARCHAR NOT NULL,
  source_type VARCHAR, -- 'scraping', 'rss', 'api'
  tags TEXT[], -- ["euskadi", "alava", "vitoria", "ayuntamiento"]
  geo_scope TEXT, -- "Vitoria-Gasteiz", "Álava", "Euskadi"
  topics TEXT[], -- ["política local", "urbanismo", "cultura"]
  verified BOOLEAN DEFAULT false,
  config_template JSONB, -- Pre-configuración probada
  embedding VECTOR(768), -- Para búsqueda semántica
  created_at TIMESTAMPTZ,
  last_validated TIMESTAMPTZ
);

-- Índices
CREATE INDEX idx_source_catalog_tags ON source_catalog USING GIN(tags);
CREATE INDEX idx_source_catalog_embedding ON source_catalog
  USING ivfflat (embedding vector_cosine_ops);
```

### Flujo
```
Usuario: "Política local en Vitoria"
↓
1. Generar embedding de la consulta
2. Búsqueda semántica en source_catalog
3. Filtro adicional por tags/geo_scope
4. Ranking por relevancia
5. Muestra top 10 fuentes sugeridas
6. Usuario selecciona → auto-configura con config_template
```

### Implementación
```python
async def search_catalog(criteria: str, limit: int = 10) -> List[Dict]:
    """Search curated source catalog."""

    # Generate embedding for query
    embedding = await get_embedding(criteria)

    # Semantic search + tag filtering
    results = supabase.client.rpc('search_sources', {
        'query_embedding': embedding,
        'match_count': limit,
        'filter_tags': extract_tags(criteria)  # ["alava", "vitoria"]
    }).execute()

    return results.data
```

### Catálogo Inicial (Euskadi)
```yaml
sources:
  - name: Diputación Foral de Álava
    url: https://prentsa.araba.eus/es/noticias
    tags: [alava, euskadi, diputacion, oficial]
    geo_scope: Álava
    verified: true

  - name: Ayuntamiento de Vitoria-Gasteiz
    url: https://www.vitoria-gasteiz.org/noticias
    tags: [alava, vitoria, ayuntamiento, oficial]
    geo_scope: Vitoria-Gasteiz
    verified: true

  - name: Ayuntamiento de Aiara
    url: https://www.aiaraldea.eus/noticias
    tags: [alava, aiara, ayuntamiento, oficial]
    geo_scope: Aiara
    verified: true

  # ... ~50-100 fuentes más
```

### Ventajas
- ✅ Fuentes verificadas y estables
- ✅ Configuración probada (config_template)
- ✅ Rápido (búsqueda local)
- ✅ Sin coste LLM por búsqueda

### Desventajas
- ❌ Requiere curaduría manual inicial
- ❌ No descubre fuentes nuevas automáticamente
- ❌ Limitado al catálogo existente

---

## Opción 3: Pattern Detection Automático (MÁS TÉCNICO)

### Descripción
Usuario provee URLs de ejemplo, el sistema detecta patrones y genera fuentes similares.

### Flujo
```
Usuario provee ejemplos:
- vitoria-gasteiz.org/noticias
- donostia.eus/actualidad
- bilbao.eus/prensa
↓
1. LLM detecta patrón: "{municipio}.{tld}/{seccion}"
2. Busca lista de municipios en OpenData Euskadi
3. Genera URLs candidatas automáticamente:
   - eibar.eus/actualidad
   - getxo.eus/noticias
   - barakaldo.eus/prensa
4. Verifica cada URL (HEAD request 200)
5. Test de scraping básico (detecta lista de noticias)
6. Propone batch de fuentes válidas
```

### Implementación
```python
async def discover_by_pattern(example_urls: List[str]) -> List[Dict]:
    """Discover sources by pattern detection."""

    # 1. Detect pattern with LLM
    pattern = await detect_url_pattern(example_urls)
    # → "{municipality}.eus/noticias"

    # 2. Get list of municipalities from OpenData
    municipalities = await fetch_opendata_euskadi(
        "https://opendata.euskadi.eus/api/datasets/municipios"
    )

    # 3. Generate candidate URLs
    candidates = []
    for muni in municipalities:
        url = pattern.format(
            municipality=muni['slug'],
            tld=muni.get('domain_tld', 'eus')
        )
        candidates.append({
            "name": f"Ayuntamiento de {muni['name']}",
            "url": url,
            "geo_scope": muni['comarca']
        })

    # 4. Validate URLs (parallel HEAD requests)
    valid_urls = await validate_urls_batch(candidates)

    # 5. Test scraping structure
    scrapeable = await test_scraping_batch(valid_urls, max_concurrent=10)

    return scrapeable
```

### Ventajas
- ✅ Escala bien para estructuras repetitivas
- ✅ Descubre muchas fuentes de golpe
- ✅ Útil para ayuntamientos con estructura común

### Desventajas
- ❌ Solo funciona si hay patrón común
- ❌ No todos los ayuntamientos siguen el patrón
- ❌ Requiere validación posterior

---

## Opción 4: Open Data + Institutional APIs (MÁS ESTRUCTURADO)

### Descripción
Usar APIs oficiales como fuente de metadatos para descubrir instituciones.

### Fuentes de Datos
```yaml
apis:
  - OpenData Euskadi:
      url: https://opendata.euskadi.eus/api
      datasets:
        - Ayuntamientos y municipios
        - Diputaciones forales
        - Organismos públicos
        - Boletines oficiales (BOPV)

  - Wikidata:
      url: https://query.wikidata.org/sparql
      queries:
        - Medios de comunicación vascos
        - Instituciones públicas Euskadi
        - Sitios web oficiales

  - Wikipedia:
      url: https://es.wikipedia.org/w/api.php
      content:
        - Lista de medios locales
        - Enlaces a sitios oficiales
```

### Flujo
```
Usuario: "Ayuntamientos de Bizkaia"
↓
1. Query a OpenData Euskadi API:
   GET /datasets/ayuntamientos?provincia=bizkaia

2. Para cada ayuntamiento:
   a) Construir URL probable: {nombre}.eus
   b) Verificar existencia (HEAD request)
   c) Crawl homepage para encontrar sección noticias
   d) Buscar RSS/Atom feeds

3. Extraer metadata:
   - Título de la web
   - Enlaces a secciones (noticias, actualidad, prensa)
   - Feeds disponibles

4. Proponer fuentes auto-configuradas
```

### Implementación
```python
async def discover_from_opendata(
    criteria: Dict[str, Any]
) -> List[Dict]:
    """Discover sources from OpenData Euskadi."""

    # Query OpenData API
    institutions = await fetch_opendata_euskadi(
        dataset="ayuntamientos",
        filters=criteria  # {"provincia": "bizkaia"}
    )

    sources = []
    for inst in institutions:
        # Try standard patterns
        base_urls = [
            f"https://{inst['slug']}.eus",
            f"https://{inst['slug']}.org",
            f"https://www.{inst['slug']}.eus"
        ]

        for base_url in base_urls:
            # Check if exists
            if await url_exists(base_url):
                # Crawl for news section
                news_urls = await find_news_section(base_url)

                # Check for RSS
                rss_urls = await find_rss_feeds(base_url)

                sources.append({
                    "name": inst['name'],
                    "url": news_urls[0] if news_urls else base_url,
                    "rss_url": rss_urls[0] if rss_urls else None,
                    "tags": [inst['provincia'].lower(), inst['comarca'].lower()],
                    "geo_scope": inst['comarca']
                })
                break

    return sources
```

### Ventajas
- ✅ Datos oficiales, alta calidad
- ✅ Coverage completo de instituciones
- ✅ Metadata estructurada

### Desventajas
- ❌ APIs limitadas (no todos tienen endpoint)
- ❌ No todos tienen web estructurada
- ❌ Requiere crawling adicional

---

## Opción 5: Hybrid - Catálogo + LLM Discovery (RECOMENDADO)

### Descripción
Combinar catálogo curado (rápido, fiable) con LLM discovery (flexible).

### Arquitectura en Capas

**Tier 1 - Catálogo Curado** (inmediato):
- 100-200 fuentes verificadas de Euskadi
- Config probada, alta calidad
- Búsqueda semántica instantánea

**Tier 2 - LLM Discovery** (bajo demanda):
- Si no hay suficientes matches en catálogo
- LLM busca + valida + propone
- Si funciona → añadir a catálogo

**Tier 3 - Community Sourced** (futuro):
- Usuarios pueden sugerir fuentes
- Review + validation automática
- Aprobación → promoción a Tier 1

### Flujo Completo
```
Usuario: "Noticias de economía en Gipuzkoa"
↓
1. Búsqueda en catálogo (Tier 1)
   → Encuentra 3 fuentes: Diputación Gipuzkoa, Bilbao Ekonomia, ...

2. Si <5 resultados → LLM Discovery (Tier 2)
   → Groq Compound busca más fuentes
   → Valida URLs y scraping
   → Añade 4 fuentes nuevas

3. Ranking combinado:
   - Tier 1: relevancia + verified=true → boost
   - Tier 2: relevancia + confidence score

4. Presenta top 10 al usuario

5. Usuario selecciona 5 fuentes
   → Auto-configuración con config_template
   → Fuentes Tier 2 exitosas → marcar para revisión (→ Tier 1)
```

### Implementación
```python
@app.post("/api/v1/sources/discover")
async def discover_sources(
    request: SourceDiscoveryRequest,
    user: Dict = Depends(get_current_user_from_jwt)
):
    """Hybrid source discovery: Catalog + LLM."""

    criteria = request.criteria  # "economía gipuzkoa"
    min_results = request.min_results or 10

    # 1. Search catalog (Tier 1)
    catalog_matches = await search_catalog(
        criteria=criteria,
        limit=min_results
    )

    logger.info("catalog_search_results", count=len(catalog_matches))

    # 2. If insufficient, use LLM discovery (Tier 2)
    if len(catalog_matches) < min_results:
        llm_discovered = await discover_with_llm(
            criteria=criteria,
            existing_urls=[s['url'] for s in catalog_matches]
        )

        # Validate discovered sources
        validated = await validate_discovered_sources(llm_discovered)

        # Add to results (lower ranking than catalog)
        catalog_matches.extend(validated)

        logger.info("llm_discovery_results",
            discovered=len(llm_discovered),
            validated=len(validated)
        )

    # 3. Rank and return
    ranked = rank_sources(catalog_matches, criteria)

    return {
        "sources": ranked[:min_results],
        "total": len(ranked),
        "catalog_count": len([s for s in ranked if s.get('verified')]),
        "discovered_count": len([s for s in ranked if not s.get('verified')])
    }
```

### Ventajas
- ✅ Mejor de ambos mundos
- ✅ Rápido para casos comunes (catálogo)
- ✅ Flexible para casos raros (LLM)
- ✅ El catálogo crece con el uso

### Desventajas
- ❌ Más complejo de implementar
- ❌ Requiere curaduría inicial del catálogo

---

## Implementación Recomendada (Roadmap)

### Fase 1: MVP - Catálogo Curado (2 semanas)

**Tareas:**
1. Crear tabla `source_catalog` en Supabase
2. Curar ~50 fuentes de Euskadi manualmente:
   - 3 Diputaciones
   - ~25 Ayuntamientos principales
   - ~10 Medios locales oficiales
   - ~10 Organismos (Euskalmet, universidades, etc.)
3. Implementar búsqueda por tags
4. Frontend: Wizard básico de selección

**Deliverable:**
```
POST /api/v1/sources/discover
Body: { "criteria": "ayuntamientos álava" }
Response: { "sources": [...], "total": 15 }
```

### Fase 2: LLM Discovery (2 semanas)

**Tareas:**
1. Integrar Groq Compound para web search
2. Implementar validación de URLs
3. Test de scraping automático
4. Hybrid search (catálogo + LLM)

**Deliverable:**
- Discovery funciona para cualquier criterio
- Valida URLs antes de proponer
- Auto-añade fuentes exitosas al catálogo

### Fase 3: Pattern Detection (opcional)

**Tareas:**
1. Integración con OpenData Euskadi
2. Pattern detection por ejemplos
3. Batch discovery de ayuntamientos

### Fase 4: Community & Auto-improvement

**Tareas:**
1. Usuarios pueden sugerir fuentes
2. Auto-validación periódica de catálogo
3. Machine learning para mejorar ranking

---

## UI/UX - Wizard de Discovery

### Paso 1: Criterios
```
┌─────────────────────────────────────────┐
│  Descubre Fuentes Automáticamente       │
├─────────────────────────────────────────┤
│                                         │
│  📍 Ubicación:                          │
│  [x] Álava  [ ] Bizkaia  [ ] Gipuzkoa  │
│                                         │
│  🏛️  Tipo de Fuente:                    │
│  [x] Ayuntamientos                      │
│  [x] Diputaciones                       │
│  [ ] Medios Locales                     │
│  [ ] Organismos Públicos                │
│                                         │
│  📰 Temas:                              │
│  [x] Política Local                     │
│  [ ] Cultura                            │
│  [ ] Deportes                           │
│  [ ] Economía                           │
│                                         │
│  🔍 Texto libre (opcional):             │
│  [________________________]             │
│                                         │
│          [Buscar Fuentes] →             │
└─────────────────────────────────────────┘
```

### Paso 2: Resultados
```
┌─────────────────────────────────────────┐
│  Encontradas 12 fuentes                 │
├─────────────────────────────────────────┤
│                                         │
│ ☑ Ayuntamiento de Vitoria-Gasteiz      │
│   🌐 vitoria-gasteiz.org/noticias       │
│   ✓ Verificada  📊 100 noticias/mes     │
│                                         │
│ ☑ Diputación Foral de Álava             │
│   🌐 prentsa.araba.eus                  │
│   ✓ Verificada  📊 50 noticias/mes      │
│                                         │
│ ☐ Ayuntamiento de Aiara                 │
│   🌐 aiaraldea.eus/noticias             │
│   ⚡ Descubierta  📊 ~20 noticias/mes    │
│                                         │
│ [Ver 9 más...]                          │
│                                         │
│     [Cancelar]  [Configurar 2 →]        │
└─────────────────────────────────────────┘
```

### Paso 3: Configuración
```
┌─────────────────────────────────────────┐
│  Configurar 2 fuentes seleccionadas     │
├─────────────────────────────────────────┤
│                                         │
│  ⏰ Frecuencia de actualización:         │
│  ○ Cada hora                            │
│  ● Cada 2 horas (recomendado)           │
│  ○ Cada 6 horas                         │
│  ○ Diaria                               │
│                                         │
│  🎯 Prioridad:                          │
│  ● Alta  ○ Media  ○ Baja               │
│                                         │
│  🏷️  Etiquetas adicionales:              │
│  [gobierno local] [+]                   │
│                                         │
│         [← Volver]  [Activar →]         │
└─────────────────────────────────────────┘
```

---

## Métricas de Éxito

**KPIs a trackear:**
1. Tiempo medio de configuración de fuentes: `<5 minutos` (vs ~30 min manual)
2. % fuentes válidas descubiertas: `>80%`
3. % fuentes que siguen activas a 30 días: `>90%`
4. Noticias capturadas por fuente/día: `>5`
5. Satisfacción del usuario: `>4/5`

---

## Próximos Pasos

1. **Decisión**: ¿Opción 2 (Catálogo) o Opción 5 (Hybrid)?
2. **Prototipo**: Implementar MVP de discovery endpoint
3. **Catálogo**: Curar primeras 50 fuentes de Euskadi
4. **Frontend**: Wizard básico de selección
5. **Testing**: Validar con usuarios beta
