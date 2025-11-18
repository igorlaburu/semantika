# Source Discovery - Auto-configuración de Fuentes

## Objetivo

Permitir a los usuarios **descubrir fuentes de información automáticamente** para cualquier:
- Temática (tecnología, política, deportes, etc.)
- Ubicación geográfica (cualquier ciudad, región, país)
- Tipo de organización (ayuntamientos, universidades, medios locales)

**Filosofía:** El sistema debe ser **global y escalable**, no limitado a un catálogo curado específico.

---

## Enfoque Principal: LLM Discovery con Web Search

### Modo de Uso

**CTA en UI:**
```
┌──────────────────────────────────────┐
│                                      │
│    🔍 Descubrir Nuevas Fuentes       │
│                                      │
│    Encuentra fuentes públicas de     │
│    noticias para cualquier tema      │
│    o ubicación                       │
│                                      │
│         [Comenzar Búsqueda]          │
│                                      │
└──────────────────────────────────────┘
```

### Flujo Completo

```
Usuario: "Ayuntamientos de Bizkaia"
↓
1. Groq Compound hace web search
2. LLM analiza resultados y filtra:
   ✅ Sitios públicos accesibles
   ✅ Sin paywall ni copyright restrictivo
   ✅ Estructura de noticias detectable
   ❌ Descarta: medios grandes, blogs personales, redes sociales
3. Sistema valida URLs (HEAD request 200)
4. Test de scraping básico (detecta lista de noticias)
5. Muestra top 10 fuentes validadas
6. Usuario selecciona → Auto-configura
```

### Criterios de Filtrado LLM

**El LLM debe proponer SOLO fuentes que cumplan:**
- ✅ **Públicas**: Sin login, sin paywall
- ✅ **Accesibles**: robots.txt permite crawling
- ✅ **Sin copyright restrictivo**: No medios grandes tipo El País, New York Times
- ✅ **Estructura clara**: Lista de noticias, artículos, comunicados
- ✅ **Relevantes**: Match con criterio del usuario

**Preferencias (en orden):**
1. Sitios oficiales (.gov, .gob, .eus para instituciones)
2. Medios locales pequeños
3. RSS/Atom feeds disponibles
4. Sitios con estructura HTML limpia

---

## Limitaciones y Control de Costes

### 1. Rate Limiting por Tier

```python
DISCOVERY_LIMITS = {
    "starter": {
        "searches_per_week": 5,
        "max_sources_per_search": 10
    },
    "pro": {
        "searches_per_week": 20,
        "max_sources_per_search": 15
    },
    "unlimited": {
        "searches_per_week": 100,
        "max_sources_per_search": 20
    }
}
```

**Tracking:**
```sql
CREATE TABLE discovery_usage (
  company_id UUID REFERENCES companies(id),
  week_start DATE,
  searches_count INT DEFAULT 0,
  PRIMARY KEY (company_id, week_start)
);
```

### 2. Caché de Resultados (Evita Duplicados)

```sql
CREATE TABLE discovery_cache (
  id UUID PRIMARY KEY,
  criteria_hash VARCHAR UNIQUE,  -- hash("ayuntamientos bizkaia")
  criteria_text TEXT,
  results JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ,  -- 7 días desde creación
  hit_count INT DEFAULT 1,
  last_hit_at TIMESTAMPTZ
);

CREATE INDEX idx_discovery_cache_hash ON discovery_cache(criteria_hash);
CREATE INDEX idx_discovery_cache_expires ON discovery_cache(expires_at);
```

**Lógica:**
- Si otro usuario buscó "ayuntamientos bizkaia" hace <7 días → reusar resultados
- Incrementar `hit_count` y `last_hit_at`
- **NO** consume cuota del usuario
- Permite "force_refresh" si el usuario quiere búsqueda nueva

### 3. Validación Obligatoria

```python
async def validate_source(url: str) -> Optional[Dict]:
    """Only propose sources that pass validation.

    Returns None if validation fails.
    """

    # 1. URL must exist and return 200
    try:
        response = await async_head(url, timeout=5)
        if response.status_code != 200:
            return None
    except Exception:
        return None

    # 2. Check robots.txt
    if not await is_crawlable(url):
        logger.info("source_validation_failed_robots", url=url)
        return None

    # 3. Basic scraping test
    try:
        html = await fetch_html(url, timeout=10)
        structure = detect_news_structure(html)

        if not structure.get("has_news_list"):
            logger.info("source_validation_failed_structure", url=url)
            return None

        return {
            "url": url,
            "validated": True,
            "structure_type": structure.get("type"),  # "rss", "list", "articles"
            "rss_url": structure.get("rss_url"),
            "article_selector": structure.get("article_selector")
        }

    except Exception as e:
        logger.error("source_validation_error", url=url, error=str(e))
        return None


async def validate_sources_batch(
    sources: List[Dict],
    max_concurrent: int = 10
) -> List[Dict]:
    """Validate sources in parallel."""

    import asyncio

    semaphore = asyncio.Semaphore(max_concurrent)

    async def validate_with_semaphore(source):
        async with semaphore:
            result = await validate_source(source["url"])
            if result:
                return {**source, **result}
            return None

    results = await asyncio.gather(*[
        validate_with_semaphore(s) for s in sources
    ])

    # Filter out None (failed validations)
    return [r for r in results if r is not None]
```

### 4. UI de Cuota

```
┌──────────────────────────────────────┐
│  Búsquedas restantes: 3/5 esta semana│
│  Se reinicia el lunes                │
│                                      │
│  [Upgrade a Pro] para 20/semana      │
└──────────────────────────────────────┘
```

---

## Implementación Backend

### Endpoint Principal

```python
@app.post("/api/v1/sources/discover")
async def discover_sources(
    request: DiscoveryRequest,
    user: Dict = Depends(get_current_user_from_jwt)
):
    """
    Discover sources with LLM + web search.

    Request:
    {
      "criteria": "ayuntamientos de bizkaia",
      "force_refresh": false  // optional
    }

    Response:
    {
      "sources": [...],
      "total_found": 15,
      "total_validated": 8,
      "cached": false,
      "usage": {
        "remaining": 3,
        "limit": 5,
        "resets_at": "2025-11-25T00:00:00Z"
      }
    }
    """

    company = user["company"]
    company_id = company["id"]
    tier = company["tier"]

    # 1. Check rate limit
    usage = await get_discovery_usage(company_id)
    limit = DISCOVERY_LIMITS[tier]["searches_per_week"]

    if usage >= limit and not request.force_refresh:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Límite de búsquedas alcanzado",
                "usage": usage,
                "limit": limit,
                "upgrade_url": "/pricing"
            }
        )

    # 2. Check cache (7 days)
    criteria_hash = hashlib.sha256(
        request.criteria.lower().strip().encode()
    ).hexdigest()

    if not request.force_refresh:
        cached = await get_cached_discovery(criteria_hash)
        if cached:
            logger.info("discovery_cache_hit",
                criteria=request.criteria,
                hit_count=cached["hit_count"]
            )
            await increment_cache_hits(criteria_hash)

            return {
                **cached["results"],
                "cached": True,
                "cached_at": cached["created_at"],
                "usage": await get_usage_info(company_id, tier)
            }

    # 3. LLM Discovery
    logger.info("discovery_llm_start",
        company_id=company_id,
        criteria=request.criteria
    )

    max_results = DISCOVERY_LIMITS[tier]["max_sources_per_search"]

    discovered = await discover_with_groq_compound(
        criteria=request.criteria,
        max_results=max_results * 2,  # Discover 2x, validate to 1x
        organization_id=user.get("organization_id"),
        client_id=company_id
    )

    logger.info("discovery_llm_completed",
        criteria=request.criteria,
        discovered_count=len(discovered)
    )

    # 4. Validate sources (parallel)
    validated = await validate_sources_batch(
        discovered,
        max_concurrent=10
    )

    logger.info("discovery_validation_completed",
        criteria=request.criteria,
        validated_count=len(validated)
    )

    # 5. Build response
    result = {
        "sources": validated[:max_results],
        "total_found": len(discovered),
        "total_validated": len(validated),
        "cached": False
    }

    # 6. Cache results (7 days)
    await cache_discovery(
        criteria_hash=criteria_hash,
        criteria_text=request.criteria,
        results=result,
        expires_days=7
    )

    # 7. Increment usage (only if not cached)
    await increment_discovery_usage(company_id)

    # 8. Return with usage info
    return {
        **result,
        "usage": await get_usage_info(company_id, tier)
    }
```

### LLM Discovery con Groq Compound

```python
async def discover_with_groq_compound(
    criteria: str,
    max_results: int = 20,
    organization_id: str = None,
    client_id: str = None
) -> List[Dict]:
    """Use Groq Compound (with web search) to discover sources."""

    from utils.llm_registry import get_llm_provider

    provider = get_llm_provider(
        provider_name="groq",
        model_name="llama-3.3-70b-versatile",
        organization_id=organization_id
    )

    prompt = f"""
Encuentra fuentes públicas de noticias para: {criteria}

CRITERIOS OBLIGATORIOS:
- Solo sitios públicos SIN paywall ni login
- Sin copyright restrictivo (NO medios grandes tipo El País, NYT)
- Preferir: sitios oficiales (.gov, .gob.es, .eus), medios locales, RSS
- URLs directas a secciones de noticias o comunicados

IMPORTANTE: Busca en la web para encontrar fuentes actuales y verificadas.

Devuelve EXACTAMENTE {max_results} fuentes en este formato JSON (sin markdown):
[
  {{
    "name": "Nombre completo del sitio",
    "url": "https://ejemplo.com/noticias",
    "rss_url": "https://ejemplo.com/feed",
    "type": "ayuntamiento|diputacion|universidad|medio_local|oficial",
    "tags": ["tag1", "tag2", "tag3"],
    "description": "1-2 frases: qué tipo de contenido publica",
    "why_relevant": "Por qué es relevante para '{criteria}'"
  }}
]

Si no hay RSS, pon rss_url: null.
"""

    response = await provider.ainvoke(
        messages=[
            {
                "role": "system",
                "content": "Eres un experto en encontrar fuentes públicas de información. Usa búsquedas web para encontrar fuentes actuales y verificadas. Responde SIEMPRE con JSON puro, sin decoración markdown."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        config={
            'tracking': {
                'organization_id': organization_id,
                'operation': 'source_discovery',
                'client_id': client_id,
                'web_search_cost': 0.0065,
                'metadata': {
                    'criteria': criteria,
                    'max_results': max_results
                }
            }
        }
    )

    # Parse response
    content = response.choices[0].message.content

    # Clean markdown if present
    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        sources = json.loads(content)

        if not isinstance(sources, list):
            logger.error("discovery_invalid_response_format",
                criteria=criteria,
                response_type=type(sources).__name__
            )
            return []

        return sources

    except json.JSONDecodeError as e:
        logger.error("discovery_json_parse_error",
            criteria=criteria,
            error=str(e),
            content_preview=content[:500]
        )
        return []
```

### Helper Functions

```python
async def get_discovery_usage(company_id: str) -> int:
    """Get current week's discovery usage count."""

    from datetime import datetime, timedelta

    # Get Monday of current week
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())

    result = supabase.client.table("discovery_usage")\
        .select("searches_count")\
        .eq("company_id", company_id)\
        .eq("week_start", week_start.isoformat())\
        .maybe_single()\
        .execute()

    if result.data:
        return result.data["searches_count"]
    return 0


async def increment_discovery_usage(company_id: str):
    """Increment discovery usage for current week."""

    from datetime import datetime, timedelta

    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())

    # Upsert
    supabase.client.table("discovery_usage")\
        .upsert({
            "company_id": company_id,
            "week_start": week_start.isoformat(),
            "searches_count": 1
        }, on_conflict="company_id,week_start")\
        .execute()


async def get_usage_info(company_id: str, tier: str) -> Dict:
    """Get usage info for response."""

    from datetime import datetime, timedelta

    usage = await get_discovery_usage(company_id)
    limit = DISCOVERY_LIMITS[tier]["searches_per_week"]

    # Next Monday
    today = datetime.utcnow().date()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + timedelta(days=days_until_monday)

    return {
        "used": usage,
        "limit": limit,
        "remaining": max(0, limit - usage),
        "resets_at": f"{next_monday}T00:00:00Z"
    }
```

---

## Catálogo Curado: Solo para Onboarding

**Uso limitado:** Pre-poblar fuentes obvias al crear cuenta.

### Templates por Contexto

```python
ONBOARDING_TEMPLATES = {
    "euskadi_alava": [
        {
            "name": "Diputación Foral de Álava",
            "url": "https://prentsa.araba.eus/es/noticias",
            "tags": ["alava", "diputacion", "oficial"]
        },
        {
            "name": "Ayuntamiento de Vitoria-Gasteiz",
            "url": "https://www.vitoria-gasteiz.org/noticias",
            "tags": ["alava", "vitoria", "ayuntamiento"]
        }
    ],
    "euskadi_bizkaia": [
        {
            "name": "Diputación Foral de Bizkaia",
            "url": "https://www.bizkaia.eus/actualidad",
            "tags": ["bizkaia", "diputacion", "oficial"]
        }
    ],
    "tech_spain": [
        {
            "name": "Xataka",
            "url": "https://www.xataka.com",
            "tags": ["tecnologia", "españa", "gadgets"]
        }
    ]
}


async def seed_sources_for_onboarding(
    company_id: str,
    template_key: str
):
    """Pre-populate sources during onboarding."""

    if template_key not in ONBOARDING_TEMPLATES:
        return

    seeds = ONBOARDING_TEMPLATES[template_key]

    for seed in seeds:
        # Create source in database
        await create_source(
            company_id=company_id,
            source_name=seed["name"],
            url=seed["url"],
            tags=seed["tags"],
            is_active=True
        )

    logger.info("onboarding_sources_seeded",
        company_id=company_id,
        template=template_key,
        count=len(seeds)
    )
```

**Cuándo usar:**
```python
@app.post("/auth/signup")
async def auth_signup(request: SignupRequest):
    # ... crear usuario y empresa ...

    # Opcional: Si el usuario indica ubicación en signup
    if request.location == "alava":
        await seed_sources_for_onboarding(
            company_id=company.id,
            template_key="euskadi_alava"
        )
```

---

## UI/UX - Wizard de Discovery

### Paso 1: Input de Criterios

```
┌──────────────────────────────────────────┐
│  🔍 Descubrir Fuentes                    │
├──────────────────────────────────────────┤
│                                          │
│  Describe qué tipo de fuentes buscas:    │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ Ayuntamientos de Bizkaia           │  │
│  └────────────────────────────────────┘  │
│                                          │
│  💡 Ejemplos:                            │
│  • "Noticias de tecnología en España"    │
│  • "Universidades del País Vasco"        │
│  • "Medios locales de Barcelona"         │
│  • "Ayuntamientos de Cataluña"           │
│                                          │
│  📊 Búsquedas restantes: 3/5 esta semana │
│                                          │
│              [Buscar Fuentes] →          │
│                                          │
└──────────────────────────────────────────┘
```

### Paso 2: Resultados (Loading 10-20 segundos)

```
┌──────────────────────────────────────────┐
│  🔍 Buscando fuentes...                  │
│                                          │
│  [████████░░░░░░░░░░░░] 40%              │
│                                          │
│  • Buscando en la web...                 │
│  • Validando URLs...                     │
│  • Detectando estructura...              │
│                                          │
└──────────────────────────────────────────┘

↓

┌──────────────────────────────────────────┐
│  ✓ Encontradas 8 fuentes válidas         │
├──────────────────────────────────────────┤
│                                          │
│  ☑ Ayuntamiento de Bilbao                │
│     🌐 bilbao.eus/noticias               │
│     ✓ Validada  📰 RSS disponible        │
│     "Comunicados oficiales del Ayto"     │
│                                          │
│  ☑ Diputación Foral de Bizkaia           │
│     🌐 bizkaia.eus/actualidad            │
│     ✓ Validada  🌐 Sin RSS               │
│     "Noticias institucionales"           │
│                                          │
│  ☐ Getxo Actualidad                      │
│     🌐 getxo.eus/noticias                │
│     ✓ Validada  📰 RSS disponible        │
│     "Portal de noticias del municipio"   │
│                                          │
│  ☐ Barakaldo Digital                     │
│     🌐 barakaldo.eus/prensa              │
│     ✓ Validada  🌐 Sin RSS               │
│                                          │
│  [Ver 4 más...]                          │
│                                          │
│  💾 Esta búsqueda se guardó en caché     │
│                                          │
│    [Nueva Búsqueda]  [Configurar 2 →]    │
└──────────────────────────────────────────┘
```

### Paso 3: Configuración

```
┌──────────────────────────────────────────┐
│  ⚙️ Configurar 2 fuentes seleccionadas    │
├──────────────────────────────────────────┤
│                                          │
│  ⏰ Frecuencia de actualización:          │
│  ○ Cada hora                             │
│  ● Cada 2 horas (recomendado)            │
│  ○ Cada 6 horas                          │
│  ○ Diaria                                │
│                                          │
│  🎯 Prioridad:                           │
│  ● Alta  ○ Media  ○ Baja                │
│                                          │
│  🏷️ Etiquetas adicionales:                │
│  [bizkaia] [institucional] [+]           │
│                                          │
│         [← Volver]  [Activar] →          │
└──────────────────────────────────────────┘

↓

┌──────────────────────────────────────────┐
│  ✓ 2 fuentes activadas correctamente     │
│                                          │
│  Las fuentes comenzarán a recopilar      │
│  noticias en las próximas 2 horas.       │
│                                          │
│          [Ir a Mis Fuentes]              │
└──────────────────────────────────────────┘
```

---

## Costes Estimados

### Por Búsqueda (LLM + Validación)

| Componente | Coste Unitario |
|------------|----------------|
| Groq Compound call (70B + web search) | $0.02 - $0.05 |
| Validación 20 URLs (HEAD requests) | Negligible |
| Test scraping 20 URLs | ~$0.001 |
| **Total por búsqueda** | **~$0.05** |

### Costes Mensuales por Tier

| Tier | Búsquedas/semana | Búsquedas/mes | Coste/mes |
|------|------------------|---------------|-----------|
| Starter | 5 | ~20 | ~$1 |
| Pro | 20 | ~80 | ~$4 |
| Unlimited | 100 | ~400 | ~$20 |

**Mitigación con caché:**
- Si 50% de búsquedas hit caché → costes reducidos a la mitad
- Búsquedas populares ("ayuntamientos bizkaia") se cachean automáticamente

---

## Schema de Base de Datos

```sql
-- Discovery usage tracking (rate limiting)
CREATE TABLE discovery_usage (
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  week_start DATE,
  searches_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (company_id, week_start)
);

CREATE INDEX idx_discovery_usage_week ON discovery_usage(week_start);

-- Discovery cache (avoid duplicate searches)
CREATE TABLE discovery_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  criteria_hash VARCHAR(64) UNIQUE NOT NULL,
  criteria_text TEXT NOT NULL,
  results JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  hit_count INT DEFAULT 1,
  last_hit_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_discovery_cache_hash ON discovery_cache(criteria_hash);
CREATE INDEX idx_discovery_cache_expires ON discovery_cache(expires_at);

-- Auto-cleanup expired cache (run daily)
CREATE OR REPLACE FUNCTION cleanup_expired_discovery_cache()
RETURNS void AS $$
BEGIN
  DELETE FROM discovery_cache WHERE expires_at < NOW();
END;
$$ LANGUAGE plpgsql;
```

---

## Métricas de Éxito

### KPIs a Trackear

1. **Tasa de éxito de discovery**: `validadas / propuestas > 40%`
2. **Hit rate de caché**: `cache_hits / total_searches > 30%`
3. **Fuentes activadas**: `activadas / descubiertas > 60%`
4. **Fuentes que capturan datos**: `con_datos_30d / activadas > 80%`
5. **Tiempo de discovery**: `< 20 segundos`
6. **Satisfacción del usuario**: `> 4/5`

### Logging para Análisis

```python
logger.info("discovery_completed",
    company_id=company_id,
    criteria=criteria,
    discovered_count=len(discovered),
    validated_count=len(validated),
    activated_count=len(activated),
    cached=False,
    duration_seconds=duration
)
```

---

## Roadmap de Implementación

### Fase 1: MVP (2 semanas)

**Backend:**
- [ ] Endpoint `/api/v1/sources/discover`
- [ ] Integración Groq Compound con web search
- [ ] Validación básica (HEAD request + robots.txt)
- [ ] Rate limiting por tier
- [ ] Caché simple (7 días)

**Frontend:**
- [ ] Modal de discovery con input
- [ ] Vista de resultados con checkboxes
- [ ] Configuración básica (frecuencia, prioridad)
- [ ] Indicador de cuota

**Testing:**
- [ ] Probar con 10 criterios diferentes
- [ ] Validar tasa de éxito > 40%
- [ ] Verificar rate limiting funciona

### Fase 2: Mejoras (1 semana)

**Backend:**
- [ ] Test de scraping avanzado (detecta estructura)
- [ ] Validación de RSS/Atom feeds
- [ ] Onboarding templates (Euskadi, Tech)

**Frontend:**
- [ ] Preview de fuentes (mini-scraping)
- [ ] Estadísticas de descubrimientos
- [ ] Historial de búsquedas

### Fase 3: Optimización (1 semana)

**Backend:**
- [ ] Caché distribuida (Redis)
- [ ] Auto-validación periódica de fuentes
- [ ] Machine learning para ranking

**Frontend:**
- [ ] Sugerencias de criterios
- [ ] Búsqueda por ejemplos (URLs)

---

## Próximos Pasos

1. **Decisión**: Aprobar enfoque LLM Discovery
2. **Prototipo**: Implementar endpoint básico
3. **Testing**: Validar con 20 búsquedas reales
4. **Frontend**: Wizard de 3 pasos
5. **Launch**: Beta con usuarios seleccionados
