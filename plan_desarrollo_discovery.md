# Plan de Desarrollo: Sistema Discovery de Fuentes

**Fecha:** 2 Diciembre 2024  
**Proyecto:** Semantika - Content Discovery Engine  
**Objetivo:** Sistema auto-evolutivo de descubrimiento y gestión de fuentes de contenido original

---

## 📋 Resumen Ejecutivo

### Concepto
Crear un sistema que **descubre automáticamente** nuevas fuentes de contenido original (ayuntamientos, empresas, fundaciones, asociaciones) a partir de noticias publicadas en grandes medios, evalúa su relevancia basándose en uso real, frecuencia y calidad, y optimiza recursos eliminando fuentes que decaen.

### Beneficios
- ✅ Acceso a **contenido original** antes que los medios
- ✅ Escala automáticamente sin intervención manual
- ✅ Se auto-optimiza eliminando fuentes irrelevantes
- ✅ Proporciona datos de contacto al periodista para verificación directa
- ✅ Diversifica fuentes evitando dependencia de agregadores

### Costos Estimados
- **Discovery diario:** $1.50/mes
- **Quality evaluations:** $0.60/mes
- **Contact extraction:** $0.90/mes
- **Total:** ~$3/mes

---

## 🎯 Estrategia de Relevancia

### Tres Pilares Simples

**1. Uso del Cliente (40% peso)**
- El periodista publica artículos usando contenido de esa fuente
- Métrica: `articles_published_count`
- Fórmula: `min(articles_count / 10, 1.0) * 0.4`

**2. Frecuencia de Contenido (30% peso)**
- La fuente publica contenido nuevo regularmente
- Métricas: `avg_content_frequency_days`, `last_content_date`
- Scoring:
  - ≤7 días: 1.0 (semanal o más)
  - ≤30 días: 0.6 (mensual)
  - >30 días: 0.3 (irregular)
- Penalizaciones:
  - Sin contenido >60 días: × 0.3
  - Sin contenido >30 días: × 0.7

**3. Calidad del Contenido (30% peso)**
- LLM evalúa riqueza informativa del contenido
- Métrica: `avg_content_quality_score` (0-1)
- Fórmula: `avg_quality_score * 0.3`

### Fórmula Final
```python
relevance_score = (
    min(articles_published / 10, 1.0) * 0.4 +
    frequency_score * frequency_penalty * 0.3 +
    avg_quality_score * 0.3
)
```

---

## 🗄️ Estructura de Base de Datos

### Tabla: `discovered_sources`

```sql
CREATE TABLE discovered_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id),
  
  -- Identidad de la fuente
  url TEXT NOT NULL,
  domain TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_type TEXT, -- ayuntamiento, empresa, fundacion, asociacion, medio_local
  
  -- Contacto (para el periodista)
  contact_name TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  contact_address TEXT,
  
  -- Estado del ciclo de vida
  status TEXT DEFAULT 'trial', -- trial, active, inactive, archived
  
  -- Métricas de relevancia (auto-calculadas)
  relevance_score FLOAT DEFAULT 0.5,
  
  -- Factor 1: Uso por clientes
  articles_published_count INT DEFAULT 0,
  last_article_published_at TIMESTAMPTZ,
  
  -- Factor 2: Frecuencia de contenido
  content_items_scraped INT DEFAULT 0,
  last_content_date TIMESTAMPTZ,
  avg_content_frequency_days FLOAT,
  
  -- Factor 3: Calidad del contenido
  avg_content_quality_score FLOAT,
  quality_evaluations_count INT DEFAULT 0,
  
  -- Metadatos de descubrimiento
  discovered_from TEXT, -- perplexity, google_news, manual
  discovered_at TIMESTAMPTZ DEFAULT NOW(),
  first_seen_headline TEXT,
  
  -- Scraping config
  scraping_frequency TEXT DEFAULT 'daily', -- daily, weekly, monthly
  last_scraped_at TIMESTAMPTZ,
  
  -- Lifecycle
  trial_ends_at TIMESTAMPTZ,
  archived_at TIMESTAMPTZ,
  archived_reason TEXT,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  UNIQUE(company_id, url)
);

-- Índices
CREATE INDEX idx_discovered_sources_status ON discovered_sources(status);
CREATE INDEX idx_discovered_sources_relevance ON discovered_sources(relevance_score DESC);
CREATE INDEX idx_discovered_sources_company ON discovered_sources(company_id);
CREATE INDEX idx_discovered_sources_last_content ON discovered_sources(last_content_date);
```

---

## 🏗️ Arquitectura del Sistema

### Fase 1: Discovery Pipeline (Job Diario - 6:00 UTC)

```
┌─────────────────────────────────────────────────────────┐
│ 1. EXTRACCIÓN DE TITULARES (10-20 noticias)            │
│    - Perplexity API (noticias de Euskadi/Álava)        │
│    - Google News scraping (opcional)                   │
│    - Portadas de medios (El Correo, Deia...)          │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ 2. BÚSQUEDA DE FUENTE ORIGINAL                         │
│    - Google Search: "título" + site:.eus/.es           │
│    - Identificar URL original (no medios conocidos)    │
│    - Extraer dominio raíz                              │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ 3. VALIDACIÓN DE FUENTE (inline, no se guarda en BD)   │
│    - ✅ Verificar robots.txt allow                     │
│    - ✅ Detectar copyright restrictivo                 │
│    - ✅ Detectar sala de prensa/noticias (heurística)  │
│    - ❌ Si falla → descartar fuente                    │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ 4. EXTRACCIÓN DE CONTACTO (LLM)                        │
│    - source_name: Nombre oficial organización          │
│    - contact_email: Email prensa/contacto              │
│    - contact_phone: Teléfono                           │
│    - contact_address: Dirección física                 │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ 5. EVALUACIÓN INICIAL DE CALIDAD (LLM)                 │
│    - Analizar primer contenido encontrado              │
│    - Score 0-1 de riqueza informativa                  │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ 6. CREAR discovered_source                             │
│    - status: trial                                     │
│    - relevance_score: 0.5 (inicial)                    │
│    - trial_ends_at: NOW() + 30 días                    │
│    - Crear source en tabla sources (para scraping)     │
└─────────────────────────────────────────────────────────┘
```

### Fase 2: Quality Evaluation (Durante Scraping)

```python
# Cada vez que se scrapea contenido nuevo de una discovered_source:

async def on_content_scraped(discovered_source_id, content_unit):
    """
    Callback cuando se scrapea contenido de una discovered source.
    """
    # 1. Evaluar calidad con LLM
    quality_score = await evaluate_content_quality(content_unit)
    
    # 2. Actualizar métricas
    await update_source_metrics(
        discovered_source_id,
        new_quality_score=quality_score,
        content_date=content_unit.created_at
    )
    
    # 3. Recalcular relevance_score
    await recalculate_relevance(discovered_source_id)
    
    # 4. Ajustar frecuencia de scraping si es necesario
    await adjust_scraping_frequency(discovered_source_id)
```

### Fase 3: Usage Tracking (Al Publicar Artículo)

```python
# Cuando el periodista publica un artículo usando context_units:

async def on_article_published(article_id):
    """
    Callback cuando se publica un artículo.
    """
    # 1. Identificar discovered_sources usadas
    sources_used = await get_sources_from_article(article_id)
    
    # 2. Incrementar articles_published_count
    for source_id in sources_used:
        await increment_usage_count(source_id)
        
    # 3. Recalcular relevance_score
    for source_id in sources_used:
        await recalculate_relevance(source_id)
```

### Fase 4: Lifecycle Management (Job Semanal - Lunes 3:00 UTC)

```python
async def evaluate_source_lifecycle():
    """
    Evalúa todas las fuentes y ajusta su estado.
    
    Estados del ciclo de vida:
    - trial: Periodo de prueba (30 días)
    - active: Fuente productiva y relevante (score > 0.5)
    - inactive: Sin contenido reciente (score < 0.5)
    - archived: Eliminada del scraping (score < 0.3 por >60 días)
    """
    
    # 1. Promocionar trial → active
    # Si trial_ends_at < NOW() y score > 0.5
    await promote_trials_to_active()
    
    # 2. Degradar active → inactive
    # Si no hay contenido nuevo en 60 días
    await demote_active_to_inactive()
    
    # 3. Archivar inactive → archived
    # Si llevan >90 días sin contenido y score < 0.3
    await archive_inactive_sources()
    
    # 4. Ajustar frecuencia de scraping
    # active con score alto → daily
    # active con score medio → weekly
    # inactive → monthly (última oportunidad)
    await adjust_all_scraping_frequencies()
```

---

## 💻 Componentes de Código

### 1. Discovery Connector
**Archivo:** `sources/discovery_connector.py`

```python
class DiscoveryConnector:
    """
    Descubre nuevas fuentes diariamente analizando noticias seed.
    """
    
    async def discover_from_perplexity(
        self, 
        location: str = "Euskadi, País Vasco", 
        count: int = 10
    ) -> List[str]:
        """
        Obtiene titulares seed desde Perplexity.
        
        Returns:
            Lista de titulares con snippets
        """
        pass
    
    async def find_original_source(
        self, 
        headline: str, 
        snippet: str
    ) -> Optional[str]:
        """
        Busca la fuente original con Google Custom Search.
        
        Args:
            headline: Titular de la noticia
            snippet: Extracto de la noticia
            
        Returns:
            URL de la fuente original (no medios conocidos)
        """
        pass
    
    async def validate_source(self, url: str) -> bool:
        """
        Valida que la fuente sea scrapeble y sin copyright.
        
        Checks:
        - robots.txt permite scraping
        - No tiene copyright restrictivo
        - Es una sala de prensa/noticias corporativa
        
        Returns:
            True si pasa todas las validaciones
        """
        pass
    
    async def extract_contact_info(
        self, 
        url: str, 
        html: str
    ) -> Dict[str, str]:
        """
        Extrae información de contacto con LLM.
        
        Returns:
            {
                "source_name": "...",
                "contact_name": "...",
                "contact_email": "...",
                "contact_phone": "...",
                "contact_address": "..."
            }
        """
        pass
    
    async def evaluate_initial_quality(
        self, 
        content: str
    ) -> float:
        """
        Evalúa calidad inicial del contenido con LLM.
        
        Returns:
            Score 0-1 de riqueza informativa
        """
        pass
    
    async def create_discovered_source(
        self,
        company_id: str,
        url: str,
        contact_info: Dict,
        initial_quality: float,
        discovered_from: str,
        headline: str
    ) -> str:
        """
        Crea discovered_source en BD y source para scraping.
        
        Returns:
            discovered_source_id
        """
        pass
```

### 2. Source Relevance Calculator
**Archivo:** `utils/source_relevance.py`

```python
class SourceRelevanceCalculator:
    """
    Calcula y actualiza scores de relevancia.
    """
    
    def calculate_relevance_score(self, source: Dict) -> float:
        """
        Calcula score de 0 a 1 basado en 3 factores.
        
        Factor 1: Uso del cliente (40%)
        Factor 2: Frecuencia de contenido (30%)
        Factor 3: Calidad del contenido (30%)
        """
        # Factor 1: Uso del cliente
        articles_score = min(source["articles_published_count"] / 10, 1.0)
        usage_score = articles_score * 0.4
        
        # Factor 2: Frecuencia de contenido
        frequency_score = self._calculate_frequency_score(source)
        frequency_score *= 0.3
        
        # Factor 3: Calidad del contenido
        quality_score = (source["avg_content_quality_score"] or 0.5) * 0.3
        
        return round(usage_score + frequency_score + quality_score, 2)
    
    def _calculate_frequency_score(self, source: Dict) -> float:
        """Calcula score de frecuencia con penalizaciones."""
        if not source["avg_content_frequency_days"]:
            return 0.5
        
        days = source["avg_content_frequency_days"]
        
        if days <= 7:
            base_score = 1.0
        elif days <= 30:
            base_score = 0.6
        else:
            base_score = 0.3
        
        # Penalizar si no hay contenido reciente
        if source["last_content_date"]:
            days_since = (datetime.now() - source["last_content_date"]).days
            if days_since > 60:
                base_score *= 0.3
            elif days_since > 30:
                base_score *= 0.7
        
        return base_score
    
    async def evaluate_content_quality(
        self, 
        content_unit: Dict
    ) -> float:
        """
        Evalúa calidad de un content_unit con LLM.
        
        Criterios:
        - Riqueza de información (datos, cifras, nombres)
        - Número de atomic_statements
        - Presencia de quotes
        - Novedad/relevancia temporal
        
        Returns:
            Score 0-1
        """
        pass
    
    async def update_source_metrics(
        self,
        discovered_source_id: str,
        new_quality_score: float,
        content_date: datetime
    ):
        """
        Actualiza métricas tras scrapear contenido nuevo.
        """
        pass
    
    async def recalculate_relevance(
        self, 
        discovered_source_id: str
    ):
        """
        Recalcula y actualiza relevance_score en BD.
        """
        pass
```

### 3. Source Lifecycle Manager
**Archivo:** `utils/source_lifecycle.py`

```python
class SourceLifecycleManager:
    """
    Gestiona el ciclo de vida de discovered_sources.
    """
    
    async def promote_trials_to_active(self):
        """
        Promociona sources en trial que superan periodo de prueba.
        
        Condición: trial_ends_at < NOW() AND score > 0.5
        """
        pass
    
    async def demote_active_to_inactive(self):
        """
        Degrada sources activas sin contenido reciente.
        
        Condición: last_content_date < NOW() - 60 días
        """
        pass
    
    async def archive_inactive_sources(self):
        """
        Archiva sources inactivas sin recuperación.
        
        Condición: 
        - status = inactive
        - last_content_date < NOW() - 90 días
        - score < 0.3
        """
        pass
    
    async def adjust_scraping_frequency(
        self, 
        discovered_source_id: str
    ):
        """
        Ajusta frecuencia de scraping según relevancia.
        
        Rules:
        - score > 0.7 → daily
        - score 0.5-0.7 → daily
        - score 0.3-0.5 → weekly
        - score < 0.3 → monthly
        """
        pass
    
    async def adjust_all_scraping_frequencies(self):
        """
        Evalúa y ajusta frecuencias de todas las sources.
        """
        pass
```

### 4. Usage Tracker
**Archivo:** `utils/discovery_usage_tracker.py`

```python
class DiscoveryUsageTracker:
    """
    Trackea uso de discovered_sources al publicar artículos.
    """
    
    async def track_article_publication(self, article_id: str):
        """
        Incrementa articles_published_count de sources usadas.
        
        Identifica discovered_sources a partir de:
        - press_articles.news_ids → press_context_units
        - press_context_units.source_metadata.url → discovered_sources
        """
        pass
    
    async def get_sources_from_article(
        self, 
        article_id: str
    ) -> List[str]:
        """
        Extrae discovered_source_ids usadas en un artículo.
        """
        pass
    
    async def increment_usage_count(
        self, 
        discovered_source_id: str
    ):
        """
        Incrementa articles_published_count y actualiza timestamp.
        """
        pass
```

---

## 📅 Plan de Implementación

### Sprint 1: Core Discovery (3-4 días)

**Objetivo:** Sistema básico de descubrimiento funcionando

**Tareas:**
1. ✅ Crear tabla `discovered_sources` (migración SQL)
2. ✅ Implementar `DiscoveryConnector`:
   - `discover_from_perplexity()`
   - `find_original_source()` con Google Custom Search
   - `validate_source()` (robots.txt, copyright)
   - `extract_contact_info()` (LLM)
   - `evaluate_initial_quality()` (LLM)
   - `create_discovered_source()`
3. ✅ Añadir job diario al scheduler (`6:00 UTC`)
4. ✅ Testing: Descubrir 3-5 fuentes manualmente
5. ✅ Logging completo de discovery pipeline

**Entregables:**
- Migración SQL: `sql/migrations/add_discovered_sources.sql`
- Código: `sources/discovery_connector.py`
- Job scheduler actualizado: `scheduler.py`
- CLI test: `python cli.py run-discovery`

---

### Sprint 2: Relevance Engine (2-3 días)

**Objetivo:** Sistema de scoring y evaluación de calidad

**Tareas:**
1. ✅ Implementar `SourceRelevanceCalculator`:
   - `calculate_relevance_score()`
   - `evaluate_content_quality()` (LLM)
   - `update_source_metrics()`
   - `recalculate_relevance()`
2. ✅ Hook en scraper workflow:
   - Callback `on_content_scraped()`
   - Actualizar métricas tras cada scraping
3. ✅ Implementar `SourceLifecycleManager`:
   - `promote_trials_to_active()`
   - `demote_active_to_inactive()`
   - `archive_inactive_sources()`
   - `adjust_scraping_frequency()`
4. ✅ Añadir job semanal al scheduler (`Lunes 3:00 UTC`)
5. ✅ Testing: Evaluar ciclo completo con fuentes de prueba

**Entregables:**
- Código: `utils/source_relevance.py`
- Código: `utils/source_lifecycle.py`
- Hook integrado en: `sources/scraper_workflow.py`
- Job scheduler actualizado: `scheduler.py`

---

### Sprint 3: Usage Tracking & UI (2-3 días)

**Objetivo:** Trackear uso real y exponer en API/Frontend

**Tareas:**
1. ✅ Implementar `DiscoveryUsageTracker`:
   - `track_article_publication()`
   - `get_sources_from_article()`
   - `increment_usage_count()`
2. ✅ Hook en artículos:
   - Callback al crear/publicar `press_articles`
   - Identificar sources usadas
3. ✅ API endpoints:
   - `GET /api/v1/discovered-sources` (listing con filtros)
   - `GET /api/v1/discovered-sources/{id}` (detalle)
   - `PATCH /api/v1/discovered-sources/{id}` (editar contacto)
   - `POST /api/v1/discovered-sources/{id}/pause` (pausar scraping)
4. ✅ CLI admin:
   - `python cli.py list-discovered --sort-by relevance`
   - `python cli.py source-stats {id}`
5. ✅ Testing end-to-end

**Entregables:**
- Código: `utils/discovery_usage_tracker.py`
- API endpoints en: `server.py`
- CLI commands en: `cli.py`
- Documentación API: actualizar `/docs`

---

### Sprint 4 (Opcional): Frontend UI (3-4 días)

**Objetivo:** Interfaz para gestionar discovered sources

**Tareas:**
1. ✅ Página "Fuentes Descubiertas"
2. ✅ Listado con filtros (status, relevancia, tipo)
3. ✅ Cards con info de contacto y métricas
4. ✅ Acciones: Ver noticias, Editar contacto, Pausar
5. ✅ Indicadores visuales de score y frecuencia

**Entregables:**
- Frontend integrado
- UX testeada con periodistas

---

## 🎪 Ejemplo de Flujo Completo

```
┌─────────────────────────────────────────────────────────┐
│ DÍA 1: DISCOVERY                                        │
├─────────────────────────────────────────────────────────┤
│ 06:00 - Job Discovery ejecuta                          │
│ ├─ Perplexity: "Ayuntamiento Laudio biblioteca"        │
│ ├─ Google: https://laudio.eus/noticias/biblioteca-2024 │
│ ├─ Validación: ✅ robots.txt, ✅ copyright             │
│ ├─ Contacto: "Ayuntamiento Laudio", email, teléfono   │
│ ├─ Calidad LLM: 0.7                                    │
│ └─ Crea discovered_source:                             │
│    - status: trial                                     │
│    - relevance_score: 0.5 (inicial)                    │
│    - contact info completo                             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ DÍA 2-30: TRIAL PERIOD                                 │
├─────────────────────────────────────────────────────────┤
│ - Scraping diario de laudio.eus/noticias               │
│ - 8 noticias scrapeadas                                │
│ - Calidad promedio: 0.75                               │
│ - Frecuencia: 1 cada 3.7 días                          │
│ - Score: 0.43 (0 + 0.30*0.9 + 0.30*0.75)              │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ DÍA 31: EVALUACIÓN LIFECYCLE                            │
├─────────────────────────────────────────────────────────┤
│ - Lunes 03:00 - Job Lifecycle ejecuta                  │
│ - Periodista publicó 2 artículos usando esta fuente    │
│ - Score recalculado: 0.08 + 0.27 + 0.23 = 0.58        │
│ - Promoción: trial → active ✅                         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ DÍA 90: FUENTE CONSOLIDADA                             │
├─────────────────────────────────────────────────────────┤
│ - 5 artículos publicados por periodista                │
│ - 30 noticias scrapeadas                               │
│ - Calidad promedio: 0.80                               │
│ - Frecuencia: cada 3 días                              │
│ - Score: 0.20 + 0.30 + 0.24 = 0.74                     │
│ - ⭐ FUENTE PRIORITARIA (scraping daily)               │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ DÍA 150: DECAIMIENTO                                    │
├─────────────────────────────────────────────────────────┤
│ - 0 contenido nuevo en 60 días                         │
│ - Score recalculado: 0.20 + 0.09 + 0.24 = 0.53        │
│ - Degradación: scraping daily → weekly                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ DÍA 200: INACTIVACIÓN                                   │
├─────────────────────────────────────────────────────────┤
│ - 0 contenido nuevo en 110 días                        │
│ - Score: 0.20 + 0.03 + 0.24 = 0.47                     │
│ - Estado: active → inactive                            │
│ - Scraping: weekly → monthly (última oportunidad)      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ DÍA 250: ARCHIVO                                        │
├─────────────────────────────────────────────────────────┤
│ - 0 contenido nuevo en 160 días                        │
│ - Score: 0.20 + 0.01 + 0.24 = 0.45 → 0.27             │
│ - Score < 0.3 y >90 días inactivo                      │
│ - Estado: inactive → archived ⚰️                       │
│ - Scraping: DETENIDO                                    │
└─────────────────────────────────────────────────────────┘
```

---

## 🔍 Casos de Uso

### Caso 1: Ayuntamiento Activo
**Fuente:** Ayuntamiento de Vitoria-Gasteiz  
**Resultado Esperado:** Score alto (0.7-0.9), scraping diario

- Publican 2-3 noticias/semana
- Periodista usa frecuentemente (8 artículos publicados)
- Contenido de calidad alta (ruedas de prensa, datos oficiales)
- **Score:** 0.32 + 0.30 + 0.27 = **0.89** ⭐⭐⭐⭐⭐

### Caso 2: Empresa con Sala de Prensa Regular
**Fuente:** Tubacex  
**Resultado Esperado:** Score medio-alto (0.6-0.8), scraping diario/semanal

- Publican 1 noticia/semana
- Periodista usa ocasionalmente (5 artículos)
- Contenido corporativo de calidad media-alta
- **Score:** 0.20 + 0.27 + 0.25 = **0.72** ⭐⭐⭐⭐

### Caso 3: Fundación Irregular
**Fuente:** Fundación BBK  
**Resultado Esperado:** Score medio (0.4-0.6), scraping semanal

- Publican 1-2 noticias/mes
- Periodista no ha usado aún (0 artículos)
- Contenido de calidad media
- **Score:** 0.00 + 0.18 + 0.18 = **0.36** ⭐⭐

### Caso 4: Ayuntamiento Inactivo
**Fuente:** Ayuntamiento pequeño sin actividad  
**Resultado Esperado:** Score bajo (0.2-0.4), archivado

- Última noticia hace 4 meses
- Periodista no usa (0 artículos)
- Contenido escaso
- **Score:** 0.00 + 0.03 + 0.15 = **0.18** → **ARCHIVED**

---

## 📊 Métricas de Éxito

### KPIs del Sistema

1. **Tasa de Descubrimiento**
   - Target: 3-5 fuentes nuevas/día
   - Métrica: `discovered_sources` creadas por día

2. **Tasa de Activación**
   - Target: >40% de trials → active
   - Métrica: Ratio trials promovidas / trials creadas

3. **Tasa de Uso**
   - Target: >30% de fuentes usadas en artículos
   - Métrica: Fuentes con `articles_published_count > 0` / total activas

4. **Cobertura de Contactos**
   - Target: >80% de fuentes con email contacto
   - Métrica: Fuentes con `contact_email != NULL` / total

5. **Eficiencia de Scraping**
   - Target: >60% de fuentes activas con contenido nuevo mensual
   - Métrica: Fuentes con `last_content_date` < 30 días / total activas

---

## 🚨 Consideraciones y Riesgos

### Riesgos Técnicos

1. **Falsos Positivos en Discovery**
   - Riesgo: Descubrir páginas que no son salas de prensa
   - Mitigación: Validación estricta con heurísticas + LLM

2. **Sobrecarga de Scraping**
   - Riesgo: Acumular 100s de fuentes → costos altos
   - Mitigación: Lifecycle automático, archivado agresivo

3. **Extracción de Contacto Incorrecta**
   - Riesgo: LLM extrae datos erróneos
   - Mitigación: UI permite edición manual + validación email

### Riesgos Legales

1. **Copyright Infringement**
   - Riesgo: Scrapear contenido con copyright restrictivo
   - Mitigación: Validación inline pre-ingesta, disclaimer en UI

2. **Robots.txt Violations**
   - Riesgo: Scrapear sitios que prohiben bots
   - Mitigación: Verificación obligatoria pre-ingesta

3. **GDPR - Datos de Contacto**
   - Riesgo: Almacenar datos personales sin consentimiento
   - Mitigación: Solo datos públicos de organizaciones (no personas físicas)

### Riesgos de Producto

1. **Baja Adopción por Periodistas**
   - Riesgo: Periodistas no usan fuentes descubiertas
   - Mitigación: UI intuitiva, destacar fuentes relevantes, notificaciones

2. **Calidad Baja de Fuentes**
   - Riesgo: Descubrir fuentes poco relevantes
   - Mitigación: Scoring estricto, threshold alto para promotion

---

## 📚 Referencias Técnicas

### APIs Externas

1. **Perplexity API**
   - Endpoint: `https://api.perplexity.ai/chat/completions`
   - Modelo: `sonar`
   - Costo: ~$0.001/request

2. **Google Custom Search API**
   - Endpoint: `https://www.googleapis.com/customsearch/v1`
   - Límite: 100 queries/día (free tier)
   - Costo: $5/1000 queries (paid tier)

3. **Groq LLM**
   - Modelo: `llama-3.3-70b-versatile`
   - Uso: Contact extraction, quality evaluation
   - Costo: Free (rate limited)

### Librerías Python

- `beautifulsoup4`: HTML parsing
- `urllib.robotparser`: robots.txt checking
- `langchain`: LLM orchestration
- `aiohttp`: Async HTTP requests
- `apscheduler`: Job scheduling

---

## 🎯 Próximos Pasos

### Inmediatos (Esta Semana)
1. Revisar y aprobar este plan
2. Crear migración SQL `discovered_sources`
3. Implementar `DiscoveryConnector` básico
4. Testing manual con 5 fuentes

### Corto Plazo (Próximas 2 Semanas)
1. Completar Sprint 1 (Core Discovery)
2. Completar Sprint 2 (Relevance Engine)
3. Monitoring de primeras 20-30 fuentes descubiertas

### Medio Plazo (Próximo Mes)
1. Completar Sprint 3 (Usage Tracking & API)
2. Analizar métricas de éxito
3. Ajustar algoritmo de scoring según feedback

### Largo Plazo (Próximos 3 Meses)
1. Sprint 4 opcional (Frontend UI)
2. Escalar a 100+ fuentes activas
3. Evaluar expansión geográfica (Gipuzkoa, Bizkaia)

---

**Documento preparado por:** Claude Code  
**Fecha:** 2 Diciembre 2024  
**Versión:** 1.0
