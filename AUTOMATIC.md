# Sistema de Publicación Automática Inteligente

**Fecha**: 2025-12-23  
**Versión**: 1.0  
**Estado**: Diseño aprobado, pendiente implementación

---

## 📋 Índice

1. [Visión General](#visión-general)
2. [Arquitectura de Agentes](#arquitectura-de-agentes)
3. [Pipeline de Publicación](#pipeline-de-publicación)
4. [Esquema de Base de Datos](#esquema-de-base-de-datos)
5. [Configuración](#configuración)
6. [Roadmap de Implementación](#roadmap-de-implementación)
7. [APIs y Endpoints](#apis-y-endpoints)
8. [Seguridad y Control](#seguridad-y-control)

---

## Visión General

### Objetivo

Crear un **publicador automático inteligente** que:
- ✅ Evalúa y rankea noticias diariamente
- ✅ Selecciona las mejores para publicar según estrategia editorial
- ✅ Decide la mejor imagen (featured vs AI-generated)
- ✅ Publica automáticamente en horarios óptimos
- ✅ Mantiene diversidad temática y geográfica
- ✅ Aprende de métricas de engagement (futuro)

### Principios de Diseño

1. **Autonomía con supervisión**: Sistema 100% automático, pero con capacidad de override manual
2. **Trazabilidad total**: Cada decisión del LLM queda registrada con su razonamiento
3. **Configurabilidad**: Estrategia editorial ajustable por company
4. **Seguridad**: Quality gates antes de publicación
5. **Escalabilidad**: Diseñado para manejar 100+ context units/día

---

## Arquitectura de Agentes

### Agentes LLM Especializados

```
┌─────────────────────────────────────────────────────────────┐
│                    PIPELINE AUTOMÁTICO                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. CURATION AGENT (06:00 AM)                               │
│     ├─ Input: Context units del día anterior                │
│     ├─ Proceso: Rating 0-100 con criterios ponderados       │
│     └─ Output: daily_curation (ratings + reasoning)         │
│                                                              │
│  2. EDITORIAL AGENT (07:00 AM)                              │
│     ├─ Input: daily_curation + estrategia editorial         │
│     ├─ Proceso: Selección diversa y balanceada              │
│     └─ Output: publication_queue (cola priorizada)          │
│                                                              │
│  3. PRODUCTION AGENT (continuo)                             │
│     ├─ Input: publication_queue                             │
│     ├─ Proceso: Redacción + decisión de imagen              │
│     └─ Output: Artículo listo (estado: borrador)            │
│                                                              │
│  4. SCHEDULER AGENT (horarios configurados)                 │
│     ├─ Input: Artículos listos + slots de publicación       │
│     ├─ Proceso: Publicar en horarios óptimos                │
│     └─ Output: Artículo publicado + notificación            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Pipeline de Publicación

### Fase 1: Curación (Curation Agent)

**Frecuencia**: 1x/día a las 06:00 AM  
**LLM**: `fast` (GPT-4o-mini) - análisis batch eficiente  
**Costo estimado**: ~$0.05/día (100 context units)

#### Criterios de Rating (0-100)

| Criterio | Peso | Descripción |
|----------|------|-------------|
| **Relevancia geográfica** | 30% | Álava (100) > Euskadi (80) > España (60) > Internacional (40) |
| **Novedad** | 25% | ¿Información nueva o ya cubierta? |
| **Interés público** | 20% | Políticas públicas, economía > eventos menores |
| **Calidad de fuente** | 15% | Institucional > Prensa verificada > Otros |
| **Urgencia temporal** | 10% | ¿Caduca pronto? (convocatorias, eventos) |

#### Prompt del Curation Agent

```python
CURATION_PROMPT = """Eres un editor jefe que evalúa noticias para un medio local de Álava.

Context Units del día:
{context_units}

Criterios de evaluación (0-100):
1. Relevancia geográfica (30%): Álava > Euskadi > España > Internacional
2. Novedad (25%): ¿Es información nueva o redundante con noticias previas?
3. Interés público (20%): Impacto en políticas, economía, sociedad
4. Calidad de fuente (15%): Institucional/oficial > prensa > otros
5. Urgencia temporal (10%): ¿Tiene fecha límite o caduca pronto?

Para cada context unit, devuelve:
{{
  "context_unit_id": "uuid",
  "rating": 0-100,
  "relevance_score": 0-100,
  "novelty_score": 0-100,
  "public_interest_score": 0-100,
  "source_quality_score": 0-100,
  "urgency_score": 0-100,
  "recommended_for_publication": true/false,
  "recommended_category": "política|economía|sociedad|cultura|...",
  "reasoning": "Explicación de 2-3 líneas"
}}

IMPORTANTE: Sé estricto. Solo ratings >60 deberían publicarse.
"""
```

#### Output

```sql
INSERT INTO daily_curation VALUES (
  uuid,
  'e15d5b9e-fd0b-4211-8db9-5e36939aec53', -- context_unit_id
  '2025-12-23',
  85.0, -- rating
  90.0, -- relevance_score (Álava)
  80.0, -- novelty_score
  90.0, -- public_interest_score
  95.0, -- source_quality_score (Diputación)
  70.0, -- urgency_score
  'Noticia sobre Sábados Musicales: relevante local, fuente oficial, interés cultural alto',
  true,  -- recommended_for_publication
  'cultura',
  now()
);
```

---

### Fase 2: Selección Editorial (Editorial Agent)

**Frecuencia**: 1x/día a las 07:00 AM  
**LLM**: `fast` (GPT-4o-mini)  
**Costo estimado**: ~$0.02/día

#### Estrategia Editorial (Configurable)

```json
{
  "daily_quota": 5,
  "category_distribution": {
    "política": 0.30,
    "economía": 0.25,
    "sociedad": 0.20,
    "cultura": 0.15,
    "medio_ambiente": 0.10
  },
  "min_rating": 60,
  "avoid_duplicates_days": 7,
  "prefer_local": true,
  "prefer_exclusive": true,
  "geographic_balance": {
    "araba": 0.50,
    "bizkaia": 0.25,
    "gipuzkoa": 0.15,
    "euskadi": 0.10
  }
}
```

#### Criterios de Selección

1. **Diversidad temática**: Máximo 2 artículos de la misma categoría/día
2. **Balance temporal**: Priorizar urgentes primero (eventos próximos, convocatorias)
3. **Evitar redundancia**: No publicar si ya cubrimos tema similar en últimos 7 días
4. **Cobertura geográfica**: Al menos 1 noticia de cada provincia vasca/semana
5. **Exclusividad**: Preferir fuentes que solo nosotros tenemos (institucionales)

#### Prompt del Editorial Agent

```python
EDITORIAL_PROMPT = """Eres el director editorial. Selecciona qué noticias publicar HOY.

Context units rankeadas:
{curated_units}

Artículos publicados últimos 7 días:
{recent_articles}

Estrategia editorial:
- Quota diaria: {daily_quota} artículos
- Distribución por categoría: {category_distribution}
- Rating mínimo: {min_rating}
- Preferir noticias locales de Álava/Euskadi

Reglas:
1. Máximo 2 artículos de la misma categoría
2. No duplicar temas ya cubiertos (últimos 7 días)
3. Equilibrar urgencia vs relevancia
4. Priorizar fuentes exclusivas (institucionales)

Devuelve array de seleccionados:
[
  {{
    "context_unit_ids": ["uuid1", "uuid2"], // Puede fusionar múltiples
    "priority": 1-5,
    "category": "política",
    "image_strategy": "featured|ai_generate|none",
    "scheduled_slot": "morning|afternoon|evening",
    "reasoning": "Por qué seleccionaste esto"
  }}
]
"""
```

#### Output

```sql
INSERT INTO publication_queue VALUES (
  uuid,
  ARRAY['e15d5b9e-...', 'a3b2c1d4-...'], -- Fusionar 2 sources
  '2025-12-23 09:00:00+00', -- scheduled_for
  5, -- priority (1=low, 5=urgent)
  'cultura',
  'ai_generate', -- Fusión de múltiples → generar imagen
  'pending',
  'Cobertura cultural completa combinando anuncio oficial + análisis experto',
  now()
);
```

---

### Fase 3: Producción (Production Agent)

**Frecuencia**: Continuo (cada 5 minutos revisa cola)  
**LLM**: `haiku` (Claude Haiku 4.5) - redacción de calidad  
**Costo estimado**: ~$0.15/artículo

#### Decisión de Imagen

```python
def decide_image_strategy(context_units, queue_item):
    """
    Estrategia inteligente de selección de imagen.
    
    Prioridades:
    1. Si queue especifica 'featured' → usar imagen de primera context unit
    2. Si es multi-source → SIEMPRE generar con IA (evita sesgo)
    3. Si es single-source:
       - Con featured_image oficial → usar directamente
       - Sin featured_image → generar con IA
    """
    # Override manual del Editorial Agent
    if queue_item.image_strategy == 'featured':
        return use_featured_image(context_units[0])
    
    # Multi-source → siempre IA (evita favorecer una fuente)
    if len(context_units) > 1:
        return generate_ai_image(context_units)
    
    # Single-source con featured → usar
    cu = context_units[0]
    if cu.source_metadata.get('featured_image'):
        return use_featured_image(cu)
    
    # Single-source sin imagen → generar IA
    return generate_ai_image(context_units)


def use_featured_image(context_unit):
    """
    Copiar featured_image a cache con UUID único.
    
    Evita vincular imagen al article_id (permite regenerar).
    """
    featured = context_unit.source_metadata['featured_image']
    
    # Descargar imagen original
    image_bytes = download_image(featured['url'])
    
    # Guardar en cache con UUID único
    image_uuid = uuid.uuid4()
    cache_file = f"/app/cache/images/{image_uuid}.jpg"
    save_image(cache_file, image_bytes)
    
    return {
        "image_uuid": image_uuid,
        "image_url": f"/api/images/{image_uuid}",
        "source": "featured",
        "original_url": featured['url']
    }


def generate_ai_image(context_units):
    """
    Generar imagen con fal.ai FLUX.1 usando prompt del LLM.
    """
    # Ya existe en server.py - reutilizar
    result = await generate_image_from_prompt(
        context_unit_id=str(uuid.uuid4()),
        image_prompt=generate_image_prompt(context_units)
    )
    
    return {
        "image_uuid": result['image_uuid'],
        "image_url": f"/api/images/{result['image_uuid']}",
        "source": "ai_generated",
        "prompt": result['image_prompt']
    }
```

#### Flujo de Producción

```python
async def process_publication_queue():
    """
    Agente de producción que procesa cola continuamente.
    """
    # 1. Obtener siguiente item de la cola
    queue_item = get_next_pending_from_queue()
    
    if not queue_item:
        return  # Cola vacía
    
    # 2. Marcar como processing
    update_queue_status(queue_item.id, 'processing')
    
    try:
        # 3. Obtener context units
        context_units = get_context_units(queue_item.context_unit_ids)
        
        # 4. Generar artículo con redact_news_rich
        article = await llm_client.redact_news_rich(
            context_unit_ids=queue_item.context_unit_ids,
            title_suggestion=None,
            instructions=f"Enfoque: {queue_item.category}",
            style_guide=get_default_style_guide(),
            language="es",
            organization_id=POOL_ORG_ID,
            client_id=POOL_CLIENT_ID
        )
        
        # 5. Decidir y obtener imagen
        image_result = decide_image_strategy(context_units, queue_item)
        
        # 6. Crear artículo en BD (estado: borrador)
        article_id = create_article(
            titulo=article['title'],
            excerpt=article['summary'],
            contenido=article['article'],
            tags=article['tags'],
            categoria=queue_item.category,
            imagen_uuid=image_result['image_uuid'],
            imagen_url=image_result['image_url'],
            estado='borrador',  # NO publicar aún
            working_json={
                'article': article,
                'fuentes': {
                    'context_unit_ids': queue_item.context_unit_ids,
                    'statements_used': article.get('statements_used', {})
                },
                'metadata': {
                    'auto_generated': True,
                    'queue_id': queue_item.id,
                    'image_source': image_result['source'],
                    'scheduled_for': queue_item.scheduled_for
                }
            }
        )
        
        # 7. Actualizar cola
        update_queue_item(queue_item.id, {
            'status': 'ready',
            'article_id': article_id,
            'processed_at': datetime.utcnow()
        })
        
        logger.info("production_agent_success",
            queue_id=queue_item.id,
            article_id=article_id,
            image_source=image_result['source']
        )
        
    except Exception as e:
        update_queue_status(queue_item.id, 'failed', error=str(e))
        logger.error("production_agent_failed", queue_id=queue_item.id, error=str(e))
```

---

### Fase 4: Publicación (Scheduler Agent)

**Frecuencia**: Horarios configurados (ej: 09:00, 13:00, 18:00)  
**LLM**: No requiere (lógica determinista)  
**Costo**: $0

#### Slots de Publicación

```json
{
  "publication_slots": [
    {
      "time": "09:00",
      "priority_filter": [4, 5],
      "categories": ["política", "economía"],
      "max_articles": 2,
      "spacing_minutes": 15
    },
    {
      "time": "13:00",
      "priority_filter": [3, 4],
      "categories": ["sociedad", "cultura", "medio_ambiente"],
      "max_articles": 2,
      "spacing_minutes": 10
    },
    {
      "time": "18:00",
      "priority_filter": [1, 2, 3],
      "categories": ["all"],
      "max_articles": 1,
      "spacing_minutes": 0
    }
  ]
}
```

#### Flujo de Publicación

```python
async def publish_scheduled_articles(slot_config):
    """
    Publicar artículos en un slot específico.
    
    Args:
        slot_config: Configuración del slot (hora, categorías, etc.)
    """
    # 1. Obtener artículos listos para este slot
    articles = get_ready_articles_for_slot(
        scheduled_time=slot_config['time'],
        priorities=slot_config['priority_filter'],
        categories=slot_config['categories'],
        limit=slot_config['max_articles']
    )
    
    # 2. Quality gate antes de publicar
    for article in articles:
        checks = run_quality_checks(article)
        
        if not all(checks.values()):
            logger.warn("quality_gate_failed", 
                article_id=article.id,
                failed_checks=[k for k, v in checks.items() if not v]
            )
            notify_admin(f"Artículo {article.id} falló quality gate", checks)
            continue
        
        # 3. Publicar
        try:
            # Espaciado entre publicaciones
            if len(published_today) > 0:
                await asyncio.sleep(slot_config['spacing_minutes'] * 60)
            
            # Actualizar estado
            update_article(
                article_id=article.id,
                estado='publicado',
                fecha_publicacion=datetime.utcnow()
            )
            
            # Log
            log_publication(article.id, slot_config['time'])
            
            # Notificar (opcional)
            if config.notify_on_publication:
                send_notification(article)
            
            published_today.append(article.id)
            
        except Exception as e:
            logger.error("publication_failed", article_id=article.id, error=str(e))
            notify_admin(f"Error publicando {article.id}: {str(e)}")


def run_quality_checks(article) -> Dict[str, bool]:
    """
    Quality gate antes de publicación automática.
    
    Previene publicación de artículos defectuosos.
    """
    return {
        "has_category": article.category is not None,
        "has_image": article.imagen_uuid is not None,
        "min_length": len(article.contenido) >= 500,
        "has_title": len(article.titulo) >= 10,
        "has_excerpt": len(article.excerpt) >= 50,
        "no_duplicate": not has_duplicate_in_last_7_days(article),
        "passes_toxicity": not contains_toxic_content(article),
        "has_sources": len(article.news_ids) > 0
    }
```

---

## Esquema de Base de Datos

### Nuevas Tablas

```sql
-- ============================================================================
-- TABLA: daily_curation
-- Descripción: Ratings diarios de context units por el Curation Agent
-- ============================================================================
CREATE TABLE daily_curation (
  curation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  context_unit_id UUID NOT NULL REFERENCES press_context_units(id) ON DELETE CASCADE,
  curation_date DATE NOT NULL,
  
  -- Scores (0-100)
  rating FLOAT NOT NULL CHECK (rating >= 0 AND rating <= 100),
  relevance_score FLOAT CHECK (relevance_score >= 0 AND relevance_score <= 100),
  novelty_score FLOAT CHECK (novelty_score >= 0 AND novelty_score <= 100),
  public_interest_score FLOAT CHECK (public_interest_score >= 0 AND public_interest_score <= 100),
  source_quality_score FLOAT CHECK (source_quality_score >= 0 AND source_quality_score <= 100),
  urgency_score FLOAT CHECK (urgency_score >= 0 AND urgency_score <= 100),
  
  -- Recomendación
  recommended_for_publication BOOLEAN NOT NULL,
  recommended_category VARCHAR,
  reasoning TEXT,
  
  -- Metadata
  llm_model VARCHAR, -- Modelo usado para rating
  processing_time_ms INT,
  created_at TIMESTAMPTZ DEFAULT now(),
  
  -- Índices
  UNIQUE(context_unit_id, curation_date)
);

CREATE INDEX idx_daily_curation_date ON daily_curation(curation_date);
CREATE INDEX idx_daily_curation_rating ON daily_curation(rating DESC);
CREATE INDEX idx_daily_curation_recommended ON daily_curation(recommended_for_publication, rating DESC);


-- ============================================================================
-- TABLA: publication_queue
-- Descripción: Cola de artículos pendientes de publicación
-- ============================================================================
CREATE TABLE publication_queue (
  queue_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Referencias
  context_unit_ids UUID[] NOT NULL, -- Puede fusionar múltiples
  article_id UUID REFERENCES press_articles(id) ON DELETE SET NULL,
  
  -- Scheduling
  scheduled_for TIMESTAMPTZ NOT NULL,
  priority INT NOT NULL CHECK (priority BETWEEN 1 AND 5), -- 1=low, 5=urgent
  
  -- Editorial
  category VARCHAR NOT NULL,
  image_strategy VARCHAR NOT NULL CHECK (image_strategy IN ('featured', 'ai_generate', 'none')),
  editorial_reasoning TEXT,
  
  -- Status
  status VARCHAR NOT NULL DEFAULT 'pending' 
    CHECK (status IN ('pending', 'processing', 'ready', 'published', 'failed', 'cancelled')),
  error_message TEXT,
  
  -- Metadata
  created_at TIMESTAMPTZ DEFAULT now(),
  processed_at TIMESTAMPTZ,
  published_at TIMESTAMPTZ
);

CREATE INDEX idx_publication_queue_status ON publication_queue(status, scheduled_for);
CREATE INDEX idx_publication_queue_scheduled ON publication_queue(scheduled_for);


-- ============================================================================
-- TABLA: autopublish_config
-- Descripción: Configuración del sistema automático por company
-- ============================================================================
CREATE TABLE autopublish_config (
  company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
  
  -- Estado global
  is_enabled BOOLEAN DEFAULT false,
  
  -- Curation settings
  min_rating_threshold FLOAT DEFAULT 60.0,
  prefer_local BOOLEAN DEFAULT true,
  
  -- Editorial settings
  daily_quota INT DEFAULT 5,
  category_distribution JSONB DEFAULT '{
    "política": 0.30,
    "economía": 0.25,
    "sociedad": 0.20,
    "cultura": 0.15,
    "medio_ambiente": 0.10
  }'::jsonb,
  avoid_duplicates_days INT DEFAULT 7,
  prefer_exclusive BOOLEAN DEFAULT true,
  
  -- Image settings
  default_image_strategy VARCHAR DEFAULT 'ai_generate' 
    CHECK (default_image_strategy IN ('featured', 'ai_generate', 'smart')),
  always_generate_new BOOLEAN DEFAULT false,
  
  -- Scheduling settings
  publication_slots JSONB DEFAULT '[
    {"time": "09:00", "priority_filter": [4,5], "categories": ["política", "economía"], "max_articles": 2},
    {"time": "13:00", "priority_filter": [3,4], "categories": ["sociedad", "cultura"], "max_articles": 2},
    {"time": "18:00", "priority_filter": [1,2,3], "categories": ["all"], "max_articles": 1}
  ]'::jsonb,
  max_per_slot INT DEFAULT 2,
  spacing_minutes INT DEFAULT 15,
  
  -- Safety & Control
  require_human_approval BOOLEAN DEFAULT true,
  notify_on_publication BOOLEAN DEFAULT true,
  admin_email VARCHAR,
  
  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);


-- ============================================================================
-- TABLA: agent_executions
-- Descripción: Log de ejecuciones de agentes para monitoreo
-- ============================================================================
CREATE TABLE agent_executions (
  execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  
  -- Identificación del agente
  agent_name VARCHAR NOT NULL CHECK (agent_name IN ('curation', 'editorial', 'production', 'scheduler')),
  execution_date TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  -- Resultados
  items_processed INT DEFAULT 0,
  items_approved INT DEFAULT 0,
  items_rejected INT DEFAULT 0,
  avg_rating FLOAT,
  
  -- Metadata
  reasoning_summary TEXT,
  duration_ms INT,
  status VARCHAR NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'partial', 'failed')),
  error_message TEXT,
  metadata JSONB,
  
  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_agent_executions_agent ON agent_executions(agent_name, execution_date DESC);
CREATE INDEX idx_agent_executions_company ON agent_executions(company_id, execution_date DESC);
```

---

## Configuración

### Archivo de Configuración

```python
# agents/config.py

from pydantic import BaseModel, Field
from typing import List, Dict

class CurationConfig(BaseModel):
    """Configuración del Curation Agent."""
    min_rating_threshold: float = Field(default=60.0, ge=0, le=100)
    prefer_local: bool = True
    weights: Dict[str, float] = {
        "relevance": 0.30,
        "novelty": 0.25,
        "public_interest": 0.20,
        "source_quality": 0.15,
        "urgency": 0.10
    }
    llm_model: str = "fast"  # fast | haiku | sonnet_premium


class EditorialConfig(BaseModel):
    """Configuración del Editorial Agent."""
    daily_quota: int = Field(default=5, ge=1, le=20)
    category_distribution: Dict[str, float] = {
        "política": 0.30,
        "economía": 0.25,
        "sociedad": 0.20,
        "cultura": 0.15,
        "medio_ambiente": 0.10
    }
    max_per_category: int = 2
    avoid_duplicates_days: int = 7
    prefer_exclusive: bool = True
    llm_model: str = "fast"


class PublicationSlot(BaseModel):
    """Slot de publicación."""
    time: str  # "09:00"
    priority_filter: List[int] = [1, 2, 3, 4, 5]
    categories: List[str] = ["all"]
    max_articles: int = 2
    spacing_minutes: int = 15


class SchedulerConfig(BaseModel):
    """Configuración del Scheduler Agent."""
    publication_slots: List[PublicationSlot]
    require_human_approval: bool = True
    notify_on_publication: bool = True
    admin_email: str = "admin@example.com"


class AutopublishConfig(BaseModel):
    """Configuración global del sistema automático."""
    is_enabled: bool = False
    company_id: str
    curation: CurationConfig = CurationConfig()
    editorial: EditorialConfig = EditorialConfig()
    scheduler: SchedulerConfig
    
    @classmethod
    def load_from_db(cls, company_id: str):
        """Cargar configuración desde BD."""
        # Implementar lectura de autopublish_config table
        pass
```

### Variables de Entorno

Añadir a `.env`:

```bash
# Autopublish Configuration
AUTOPUBLISH_ENABLED=false
AUTOPUBLISH_CURATION_SCHEDULE="0 6 * * *"  # Daily at 6:00 AM
AUTOPUBLISH_EDITORIAL_SCHEDULE="0 7 * * *"  # Daily at 7:00 AM
AUTOPUBLISH_PRODUCTION_INTERVAL=300  # Every 5 minutes
AUTOPUBLISH_ADMIN_EMAIL=igor@gako.ai
AUTOPUBLISH_NOTIFY_ON_PUBLISH=true
```

---

## Roadmap de Implementación

### Sprint 1: Curation Agent (5 días)

**Objetivo**: Sistema de rating automático funcionando

- [ ] **Día 1-2**: Base de datos
  - [ ] Crear tabla `daily_curation`
  - [ ] Crear tabla `agent_executions`
  - [ ] Migrations para Supabase
  
- [ ] **Día 3-4**: Agente de curación
  - [ ] Implementar `agents/curation_agent.py`
  - [ ] Prompt engineering y testing
  - [ ] Integración con scheduler.py
  
- [ ] **Día 5**: API y testing
  - [ ] Endpoint `POST /api/v1/admin/run-curation`
  - [ ] Dashboard básico (lectura de `daily_curation`)
  - [ ] Testing con 100 context units reales

**Entregables**:
- ✅ `daily_curation` table poblada diariamente
- ✅ Endpoint manual para ejecutar curation
- ✅ Logs en `agent_executions`

---

### Sprint 2: Editorial Agent (5 días)

**Objetivo**: Selección inteligente de qué publicar

- [ ] **Día 1**: Base de datos
  - [ ] Crear tabla `publication_queue`
  - [ ] Crear tabla `autopublish_config`
  
- [ ] **Día 2-3**: Agente editorial
  - [ ] Implementar `agents/editorial_agent.py`
  - [ ] Lógica de diversidad y balance
  - [ ] Detección de duplicados
  
- [ ] **Día 4**: Configuración
  - [ ] UI para ajustar `autopublish_config`
  - [ ] Validación de estrategia editorial
  
- [ ] **Día 5**: API y testing
  - [ ] Endpoint `POST /api/v1/admin/run-editorial-selection`
  - [ ] Vista de `publication_queue`
  - [ ] Testing con diferentes estrategias

**Entregables**:
- ✅ `publication_queue` poblada con selección inteligente
- ✅ Configuración editable por company
- ✅ Dashboard de cola de publicación

---

### Sprint 3: Production Agent (7 días)

**Objetivo**: Generación automática de artículos listos

- [ ] **Día 1-2**: Lógica de imagen
  - [ ] Implementar `decide_image_strategy()`
  - [ ] Copiar featured images a cache con UUID único
  - [ ] Testing de ambas estrategias
  
- [ ] **Día 3-4**: Agente de producción
  - [ ] Implementar `agents/production_agent.py`
  - [ ] Integración con `redact_news_rich`
  - [ ] Procesamiento continuo de cola
  
- [ ] **Día 5-6**: Quality gates
  - [ ] Implementar `run_quality_checks()`
  - [ ] Sistema de retry en caso de fallo
  - [ ] Notificaciones de errores
  
- [ ] **Día 7**: Testing end-to-end
  - [ ] Pipeline completo: curation → editorial → production
  - [ ] Validar calidad de artículos generados
  - [ ] Ajustar prompts según resultados

**Entregables**:
- ✅ Artículos generados automáticamente (estado: borrador)
- ✅ Imágenes asignadas inteligentemente
- ✅ Quality checks funcionando

---

### Sprint 4: Scheduler Agent (3 días)

**Objetivo**: Publicación automática en horarios óptimos

- [ ] **Día 1**: Agente de publicación
  - [ ] Implementar `agents/scheduler_agent.py`
  - [ ] Lógica de slots y espaciado
  
- [ ] **Día 2**: Integración con scheduler
  - [ ] Cron jobs en `scheduler.py`
  - [ ] Sistema de notificaciones (email)
  - [ ] Webhook opcional
  
- [ ] **Día 3**: Safety y control
  - [ ] Modo "require_human_approval"
  - [ ] Override manual
  - [ ] Dashboard de publicaciones automáticas

**Entregables**:
- ✅ Sistema 100% automático funcionando
- ✅ Publicaciones en horarios configurados
- ✅ Modo manual override disponible

---

### Sprint 5: Monitoreo y Optimización (5 días)

**Objetivo**: Dashboards, métricas y mejora continua

- [ ] **Día 1-2**: Dashboard de agentes
  - [ ] Vista de ejecuciones (`agent_executions`)
  - [ ] Gráficas de ratings diarios
  - [ ] Métricas de publicación
  
- [ ] **Día 3-4**: Análisis de calidad
  - [ ] Tracking de engagement (vistas, tiempo lectura)
  - [ ] Correlación rating vs engagement
  - [ ] A/B testing de títulos
  
- [ ] **Día 5**: Optimización
  - [ ] Ajuste de pesos en curation
  - [ ] Refinamiento de prompts
  - [ ] Documentación final

**Entregables**:
- ✅ Dashboard completo de autopublish
- ✅ Métricas de calidad y engagement
- ✅ Sistema optimizado y documentado

---

## APIs y Endpoints

### Endpoints de Administración

```python
# ============================================================================
# CURATION AGENT
# ============================================================================

@app.post("/api/v1/admin/run-curation")
async def run_curation_agent(
    date: Optional[str] = None,  # YYYY-MM-DD, default: yesterday
    company_id: str = Depends(get_admin_company_id)
):
    """
    Ejecutar manualmente el Curation Agent.
    
    Evalúa y rankea todas las context units del día especificado.
    """
    # Implementar llamada a agents/curation_agent.py
    pass


@app.get("/api/v1/admin/daily-curation")
async def get_daily_curation(
    date: str,  # YYYY-MM-DD
    min_rating: Optional[float] = 0,
    company_id: str = Depends(get_admin_company_id)
):
    """
    Obtener ratings del día.
    
    Query params:
    - date: Fecha (YYYY-MM-DD)
    - min_rating: Filtrar por rating mínimo
    
    Response:
    {
      "date": "2025-12-23",
      "total_items": 47,
      "avg_rating": 72.5,
      "recommended_count": 12,
      "items": [...]
    }
    """
    pass


# ============================================================================
# EDITORIAL AGENT
# ============================================================================

@app.post("/api/v1/admin/run-editorial-selection")
async def run_editorial_selection(
    date: Optional[str] = None,  # YYYY-MM-DD, default: today
    company_id: str = Depends(get_admin_company_id)
):
    """
    Ejecutar manualmente el Editorial Agent.
    
    Selecciona qué context units publicar basándose en estrategia editorial.
    """
    pass


@app.get("/api/v1/admin/publication-queue")
async def get_publication_queue(
    status: Optional[str] = None,  # pending | processing | ready | published
    company_id: str = Depends(get_admin_company_id)
):
    """
    Ver cola de publicación.
    
    Response:
    {
      "total": 12,
      "pending": 5,
      "processing": 2,
      "ready": 3,
      "published": 2,
      "items": [...]
    }
    """
    pass


@app.delete("/api/v1/admin/publication-queue/{queue_id}")
async def cancel_queue_item(
    queue_id: str,
    company_id: str = Depends(get_admin_company_id)
):
    """
    Cancelar un item de la cola.
    """
    pass


# ============================================================================
# PRODUCTION AGENT
# ============================================================================

@app.post("/api/v1/admin/process-production-queue")
async def process_production_queue(
    limit: Optional[int] = 1,
    company_id: str = Depends(get_admin_company_id)
):
    """
    Procesar manualmente N items de la cola de producción.
    
    Útil para testing o procesamiento urgente.
    """
    pass


# ============================================================================
# SCHEDULER AGENT
# ============================================================================

@app.post("/api/v1/admin/publish-now")
async def publish_article_now(
    article_id: str,
    company_id: str = Depends(get_admin_company_id)
):
    """
    Publicar un artículo inmediatamente (override del scheduler).
    """
    pass


@app.get("/api/v1/admin/publication-schedule")
async def get_publication_schedule(
    date: Optional[str] = None,  # YYYY-MM-DD
    company_id: str = Depends(get_admin_company_id)
):
    """
    Ver qué artículos están programados para publicar.
    
    Response:
    {
      "date": "2025-12-23",
      "slots": [
        {
          "time": "09:00",
          "scheduled": 2,
          "published": 0,
          "articles": [...]
        }
      ]
    }
    """
    pass


# ============================================================================
# CONFIGURATION
# ============================================================================

@app.get("/api/v1/admin/autopublish-config")
async def get_autopublish_config(
    company_id: str = Depends(get_admin_company_id)
):
    """
    Obtener configuración actual del autopublish.
    """
    pass


@app.put("/api/v1/admin/autopublish-config")
async def update_autopublish_config(
    config: AutopublishConfigUpdate,
    company_id: str = Depends(get_admin_company_id)
):
    """
    Actualizar configuración del autopublish.
    
    Body:
    {
      "is_enabled": true,
      "daily_quota": 5,
      "category_distribution": {...},
      "publication_slots": [...]
    }
    """
    pass


# ============================================================================
# MONITORING
# ============================================================================

@app.get("/api/v1/admin/agent-executions")
async def get_agent_executions(
    agent_name: Optional[str] = None,  # curation | editorial | production | scheduler
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    company_id: str = Depends(get_admin_company_id)
):
    """
    Ver historial de ejecuciones de agentes.
    
    Response:
    {
      "executions": [
        {
          "execution_id": "...",
          "agent_name": "curation",
          "execution_date": "2025-12-23T06:00:00Z",
          "items_processed": 47,
          "items_approved": 12,
          "avg_rating": 72.5,
          "status": "success",
          "duration_ms": 15234
        }
      ]
    }
    """
    pass
```

---

## Seguridad y Control

### Modos de Operación

#### 1. Modo Manual (default)

```json
{
  "is_enabled": false,
  "require_human_approval": true
}
```

- ✅ Agentes generan recomendaciones
- ✅ Admin revisa y aprueba manualmente
- ✅ No se publica nada automáticamente

#### 2. Modo Semi-Automático

```json
{
  "is_enabled": true,
  "require_human_approval": true
}
```

- ✅ Pipeline completo hasta borrador
- ✅ Admin recibe notificación diaria
- ✅ Admin decide qué publicar con 1 click

#### 3. Modo Automático (recomendado tras 2 semanas de testing)

```json
{
  "is_enabled": true,
  "require_human_approval": false,
  "notify_on_publication": true
}
```

- ✅ Pipeline 100% automático
- ✅ Publicación en horarios configurados
- ✅ Admin recibe email post-publicación
- ✅ Override manual siempre disponible

---

### Quality Gates

Prevenir publicación de contenido defectuoso:

```python
QUALITY_CHECKS = {
    "has_category": "Artículo debe tener categoría asignada",
    "has_image": "Artículo debe tener imagen (featured o generada)",
    "min_length": "Artículo debe tener mínimo 500 caracteres",
    "has_title": "Título debe tener mínimo 10 caracteres",
    "has_excerpt": "Resumen debe tener mínimo 50 caracteres",
    "no_duplicate": "No debe haber artículo similar en últimos 7 días",
    "passes_toxicity": "No debe contener lenguaje tóxico o inapropiado",
    "has_sources": "Debe referenciar al menos 1 context unit"
}
```

Si algún check falla:
1. ❌ NO publicar artículo
2. 📧 Notificar admin con detalles del fallo
3. 📝 Marcar item de cola como `failed`
4. 🔄 Admin puede revisar y corregir manualmente

---

### Rollback y Recovery

#### Si el sistema genera contenido inadecuado

```python
# Endpoint de emergencia
@app.post("/api/v1/admin/emergency-stop")
async def emergency_stop(company_id: str):
    """
    Detener inmediatamente el sistema automático.
    
    - Desactiva autopublish
    - Cancela todos los items pendientes en cola
    - Notifica admin
    """
    update_autopublish_config(company_id, is_enabled=False)
    cancel_all_pending_queue_items(company_id)
    send_alert_email(f"Autopublish DETENIDO para {company_id}")
```

#### Si se publica contenido incorrecto

```python
# Despublicar y ocultar
@app.post("/api/v1/admin/unpublish/{article_id}")
async def unpublish_article(article_id: str):
    """
    Despublicar artículo y marcarlo como oculto.
    
    Útil si se detecta error post-publicación.
    """
    update_article(article_id, estado="oculto")
    log_unpublish_action(article_id, reason="error")
```

---

### Notificaciones

#### Email diario al admin

```
Subject: [Autopublish] Resumen diario - 2025-12-23

Curation Agent (06:00):
✅ 47 context units evaluadas
✅ 12 recomendadas para publicación
📊 Rating promedio: 72.5

Editorial Agent (07:00):
✅ 5 artículos seleccionados
📋 Categorías: política (2), economía (1), cultura (2)

Production Agent:
✅ 5 artículos generados (listos para publicar)
🖼️  Imágenes: 3 featured, 2 AI-generated

Scheduler Agent:
✅ 09:00 - 2 artículos publicados
✅ 13:00 - 2 artículos publicados
✅ 18:00 - 1 artículo publicado

Ver detalles: https://admin.ekimen.ai/autopublish
```

---

### Logging y Auditoría

Todas las decisiones del LLM quedan registradas:

```python
logger.info("curation_agent_decision",
    context_unit_id=cu_id,
    rating=85.0,
    recommended=True,
    reasoning="Noticia local de fuente oficial con alto interés público",
    llm_model="gpt-4o-mini",
    processing_time_ms=234
)

logger.info("editorial_agent_selection",
    selected_units=[cu1, cu2],
    category="política",
    priority=5,
    reasoning="Urgente: convocatoria con fecha límite próxima",
    image_strategy="ai_generate"
)

logger.info("production_agent_created",
    article_id=article_id,
    context_units_used=3,
    image_source="ai_generated",
    image_prompt="A modern city hall building...",
    quality_checks_passed=True
)

logger.info("scheduler_agent_published",
    article_id=article_id,
    scheduled_for="09:00",
    actual_time="09:00:03",
    slot_category="política",
    notification_sent=True
)
```

---

## Métricas de Éxito

### KPIs del Sistema

| Métrica | Target | Medición |
|---------|--------|----------|
| **Precisión de curation** | >80% de recomendaciones publicables | % de items con rating >60 que realmente se publican |
| **Diversidad temática** | ≤2 artículos misma categoría/día | Distribución real vs configurada |
| **Calidad de artículos** | 100% pasan quality gates | % de artículos que pasan todos los checks |
| **Engagement promedio** | >30 seg tiempo de lectura | Analytics del frontend |
| **Tasa de override manual** | <10% de publicaciones | % de artículos publicados manualmente vs automáticamente |

### Métricas de Eficiencia

| Métrica | Target |
|---------|--------|
| **Tiempo de procesamiento** | <5 min desde curation hasta borrador |
| **Costo por artículo** | <$0.20 (LLM + imagen) |
| **Artículos generados/día** | 5-10 (configurable) |
| **Tasa de error** | <5% fallos en producción |

---

## Próximos Pasos

### Fase Actual: Diseño ✅

- [x] Definir arquitectura de agentes
- [x] Diseñar esquema de BD
- [x] Documentar flujos y configuración

### Fase 1: Implementación MVP

**Sprint 1** (próxima semana):
- [ ] Implementar Curation Agent
- [ ] Crear tabla `daily_curation`
- [ ] Endpoint manual + dashboard básico

**Pregunta clave**: ¿Empezamos por el Curation Agent la próxima semana?

---

## Notas Finales

### Riesgos y Mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| LLM genera contenido inapropiado | Quality gates + toxicity check + modo approval |
| Publicación de duplicados | Detección semántica de similitud en últimos 7 días |
| Agotamiento de cuota LLM/fal.ai | Alertas de costos + circuit breaker |
| Error en imagen featured | Fallback a AI-generated si falla descarga |
| Horario de publicación subóptimo | A/B testing de slots + análisis de engagement |

### Dependencias Externas

- ✅ OpenRouter API (LLM)
- ✅ Fal.ai API (imagen)
- ✅ Supabase (BD)
- ✅ Scheduler (APScheduler)

### Coste Estimado

**Por día (5 artículos)**:
- Curation Agent: ~$0.05 (100 units × GPT-4o-mini)
- Editorial Agent: ~$0.02
- Production Agent: ~$0.75 (5 artículos × Haiku 4.5)
- Imágenes AI: ~$0.015 (5 × fal.ai FLUX)
- **Total**: ~$0.83/día (~$25/mes)

**ROI esperado**:
- Sin sistema: ~2h/día de trabajo manual editorial
- Con sistema: ~15min/día de supervisión
- **Ahorro**: ~1h45min/día = ~35h/mes = ~$1,400/mes (asumiendo $40/h)

---

**Última actualización**: 2025-12-23  
**Autor**: Claude (Anthropic) + Igor (Gako.ai)  
**Estado**: Pendiente aprobación para implementación
