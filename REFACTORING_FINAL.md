# Refactoring Final: Arquitectura 2-Fases para Context Units

**Date**: 2025-11-20
**Status**: 🔴 PLAN DEFINITIVO
**Priority**: CRÍTICA

---

## Arquitectura Revisada: 2-FASES

### FASE 1: Verificación de Novedad (PRE-ingesta)
**Archivo**: `utils/unified_context_verifier.py` (NUEVO)

**Responsabilidad**: Determinar si el contenido es nuevo ANTES de procesar con LLM

```python
async def verify_novelty(
    source_type: str,
    content_data: Dict[str, Any],
    company_id: str
) -> Dict[str, Any]:
    """
    Verificar si el contenido es novedoso según el tipo de source.

    Args:
        source_type: "scraping", "email", "perplexity", "api", "manual"
        content_data: Datos específicos según source_type:
            - scraping: {"url": str, "html": str}
            - email: {"message_id": str, "subject": str, "date": datetime}
            - perplexity: {"title": str, "fecha": str}
            - api/manual: {} (siempre nuevo)
        company_id: Company UUID

    Returns:
        {
            "is_novel": bool,
            "reason": str,  # "new", "duplicate", "no_changes", "recent_duplicate"
            "duplicate_id": str | None,
            "similarity_score": float | None
        }
    """
```

**Implementaciones por source**:

1. **Scraping**: Reusar `change_detector.py` existente
   - Hash/simhash comparison con `monitored_urls` tabla
   - 3-tier detection: identical/trivial/minor/major
   - Multi-noticia: detectar títulos nuevos vs `url_content_units`

2. **Email**: Message-ID lookup
   ```python
   # Check si Message-ID ya existe
   existing = supabase.table("press_context_units")\
       .select("id")\
       .eq("source_type", "email")\
       .contains("source_metadata", {"message_id": message_id})\
       .execute()
   ```

3. **Perplexity**: Temporal + título similarity
   ```python
   # Buscar títulos similares en últimas 24h
   from datetime import datetime, timedelta
   yesterday = datetime.utcnow() - timedelta(days=1)

   existing = supabase.table("press_context_units")\
       .select("id, title")\
       .eq("source_type", "api")\
       .gte("created_at", yesterday.isoformat())\
       .execute()

   # Similarity check con títulos existentes
   for item in existing.data:
       if title_similarity(new_title, item["title"]) > 0.9:
           return {"is_novel": False, "reason": "recent_duplicate"}
   ```

4. **API/Manual**: Skip verification
   ```python
   return {"is_novel": True, "reason": "api_source"}
   ```

---

### FASE 2: Mega-Ingester Inteligente (POST-verificación)
**Archivo**: `utils/unified_context_ingester.py` (NUEVO)

**Responsabilidad**: Procesar contenido de forma flexible y guardar con embeddings

#### Firma del Mega-Ingester

```python
async def ingest_context_unit(
    # ============ INPUT FLEXIBLE ============
    # Contenido (al menos uno requerido)
    raw_text: Optional[str] = None,        # Texto crudo completo
    url: Optional[str] = None,              # URL a scrapear (si no hay raw_text)

    # Pre-procesados opcionales (si no, LLM los genera)
    title: Optional[str] = None,
    summary: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category: Optional[str] = None,
    atomic_statements: Optional[List[Dict]] = None,

    # ============ METADATA OBLIGATORIA ============
    company_id: str,
    organization_id: Optional[str] = None,
    source_type: str,                       # "email", "scraping", "api", etc.
    source_id: str,
    source_metadata: Optional[Dict] = None,  # Message-ID, URLs, etc.

    # ============ CONFIGURACIÓN ============
    workflow_code: str = "default",
    generate_embeddings: bool = True,
    check_semantic_duplicates: bool = True,
    llm_organization_id: Optional[str] = None,  # Para tracking
    llm_client_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    MEGA-INGESTER resiliente que acepta cualquier combinación de inputs.

    Flujo:
    1. Obtener raw_text (directo o scrapeando URL)
    2. Generar campos faltantes via LLM (título, resumen, tags, category, statements)
    3. Normalizar atomic_statements a formato estructurado
    4. Generar embedding
    5. Check duplicados semánticos (opcional)
    6. Guardar en BD

    Returns:
        {
            "success": bool,
            "context_unit_id": str,
            "duplicate_detected": bool,
            "duplicate_id": str | None,
            "similarity_score": float | None,
            "generated_fields": List[str],  # Qué campos generó el LLM
            "llm_usage": {...}
        }
    """
```

#### Lógica Interna del Ingester

```python
async def ingest_context_unit(...):
    logger.info("ingestion_start", source_type=source_type)

    # PASO 1: Obtener raw_text
    if not raw_text and url:
        # Scrapear URL
        scraper = WebScraper()
        documents = await scraper.scrape_url(url)
        raw_text = documents[0].get("text")

    if not raw_text:
        return {"success": False, "error": "No raw_text or URL provided"}

    # PASO 2: Determinar qué campos necesitan LLM
    needs_llm = False
    generated_fields = []

    if not title:
        needs_llm = True
        generated_fields.append("title")
    if not summary:
        needs_llm = True
        generated_fields.append("summary")
    if not tags:
        needs_llm = True
        generated_fields.append("tags")
    if not category:
        needs_llm = True
        generated_fields.append("category")
    if not atomic_statements:
        needs_llm = True
        generated_fields.append("atomic_statements")

    # PASO 3: Llamar LLM si necesario (GPT-4o-mini via OpenRouter)
    if needs_llm:
        llm_client = get_llm_client()

        llm_result = await llm_client.generate_context_unit(
            text=raw_text,
            organization_id=llm_organization_id,
            client_id=llm_client_id,
            context_unit_id=None,  # Se genera después
            # Pasar campos pre-generados para que LLM solo complete lo que falta
            existing_title=title,
            existing_summary=summary,
            existing_tags=tags,
            existing_category=category
        )

        # Rellenar campos faltantes
        title = title or llm_result.get("title")
        summary = summary or llm_result.get("summary")
        tags = tags or llm_result.get("tags", [])
        category = category or llm_result.get("category")
        atomic_statements = atomic_statements or llm_result.get("atomic_statements", [])

        logger.info("llm_generation_completed",
            generated_fields=generated_fields,
            llm_usage=llm_result.get("usage")
        )

    # PASO 4: Normalizar atomic_statements
    atomic_statements = normalize_atomic_statements(atomic_statements)

    # PASO 5: Guardar via context_unit_saver (maneja embeddings + dedup)
    save_result = await save_context_unit_universal(
        company_id=company_id,
        organization_id=organization_id,
        source_type=source_type,
        source_id=source_id,
        title=title,
        summary=summary,
        tags=tags,
        atomic_statements=atomic_statements,
        raw_text=raw_text,
        category=category,
        source_metadata=source_metadata,
        generate_embedding_flag=generate_embeddings,
        check_duplicates=check_semantic_duplicates
    )

    return {
        **save_result,
        "generated_fields": generated_fields
    }
```

---

## Entry Points Actuales que Crean Context Units

### CLIENTE WEB (UI manual)
1. `POST /context-units` - Texto plano desde UI
   - Source type: "manual"
   - Usa: workflow → direct DB insert ❌
   - **Debe migrar a**: `ingest_context_unit(raw_text=...)`

2. `POST /context-units/from-url` - URL desde UI
   - Source type: "scraping"
   - Usa: scraper → workflow → direct DB insert ❌
   - **Debe migrar a**: `ingest_context_unit(url=...)`

### API PROGRAMÁTICA (legacy/deprecated)
3. `POST /ingest/text` - API texto con guardrails
   - Source type: "manual"
   - Usa: IngestPipeline (deprecated)
   - **Debe migrar a**: `ingest_context_unit(raw_text=...)`

4. `POST /ingest/url` - API URL con guardrails
   - Source type: "scraping"
   - Usa: IngestPipeline (deprecated)
   - **Debe migrar a**: `ingest_context_unit(url=...)`

### BACKEND AUTOMÁTICO (procesos internos, NO endpoints)
5. **Email Monitor** (`multi_company_email_monitor.py`)
   - Source type: "email"
   - Usa: workflow → direct DB insert ❌ (3 veces)
   - **Debe migrar a**: `verify_novelty()` + `ingest_context_unit()`

6. **Perplexity Scheduler** (`perplexity_news_connector.py`)
   - Source type: "api"
   - Usa: workflow → direct DB insert ❌
   - **Debe migrar a**: `verify_novelty()` + `ingest_context_unit()`

7. **Scraping Scheduler** (`scraper_workflow.py`)
   - Source type: "scraping"
   - Usa: change_detector → LLM → `context_unit_saver` ✅
   - **Debe migrar a**: mantener change_detector + `ingest_context_unit()`

**TOTAL**: 7 entry points, 6 necesitan refactoring urgente

---

## Casos de Uso Reales

### 1. Email con Audio Transcrito

```python
# El email processor extrae todo y agrupa
combined_text = f"""
Asunto: {subject}
De: {from_email}
Fecha: {date}

Cuerpo del email:
{body_text}

--- Transcripción de audio adjunto ---
{audio_transcription}

--- Enlaces extraídos ---
{extracted_urls_text}
"""

# Llamar ingester con texto agregado
result = await ingest_context_unit(
    raw_text=combined_text,
    # Título pre-generado del asunto
    title=f"Email: {subject[:100]}",
    # Resto lo genera LLM
    company_id=company_id,
    source_type="email",
    source_id=email_id,
    source_metadata={
        "message_id": message_id,
        "from": from_email,
        "has_audio": True,
        "has_urls": True
    }
)
```

### 2. Perplexity con Datos Estructurados

```python
# Perplexity ya devuelve título + texto + fuente + fecha
for news_item in perplexity_news:
    result = await ingest_context_unit(
        raw_text=news_item["texto"],
        # Pre-generados por Perplexity
        title=news_item["titulo"],
        # LLM genera: summary, tags, category, atomic_statements
        company_id=company_id,
        source_type="api",
        source_id=f"perplexity_{date}_{i}",
        source_metadata={
            "fuente": news_item["fuente"],
            "fecha": news_item["fecha"],
            "connector": "perplexity"
        }
    )
```

### 3. Scraping (Ya Tiene Parse LLM)

```python
# Scraping ya hace LLM analysis con analyze_atomic
llm_result = await llm_client.analyze_atomic(text=semantic_content)

# Llamar ingester con todo pre-generado
result = await ingest_context_unit(
    raw_text=semantic_content,
    # Todo pre-generado por analyze_atomic
    title=llm_result["title"],
    summary=llm_result["summary"],
    tags=llm_result["tags"],
    category=llm_result["category"],
    atomic_statements=llm_result["atomic_facts"],  # Se normaliza automáticamente
    company_id=company_id,
    source_type="scraping",
    source_id=source_id,
    source_metadata={"url": url}
)
```

### 4. API Texto Directo (Sin Pre-proceso)

```python
# Usuario envía texto crudo via API
result = await ingest_context_unit(
    raw_text=user_submitted_text,
    # TODO lo genera LLM
    company_id=company_id,
    source_type="api",
    source_id=f"api_{timestamp}"
)
```

---

## Cambios por Connector

### Scraping (`scraper_workflow.py`)
**Cambio mínimo**: Solo en save

```python
# ANTES (líneas 899-914)
result = await save_from_scraping(...)

# DESPUÉS
result = await ingest_context_unit(
    raw_text=semantic_content,
    title=llm_result["title"],
    summary=llm_result["summary"],
    tags=llm_result["tags"],
    category=llm_result["category"],
    atomic_statements=llm_result["atomic_facts"],
    company_id=company_id,
    source_type="scraping",
    source_id=source_id,
    source_metadata={"url": url}
)
```

**NO TOCAR**: Change detection (Fase 1) mantener como está ✅

---

### Email (`multi_company_email_monitor.py`)
**Cambios**:

1. **Añadir verificación Message-ID** (Fase 1):
```python
# Antes de procesar
verification = await verify_novelty(
    source_type="email",
    content_data={
        "message_id": message_id,
        "subject": subject,
        "date": date
    },
    company_id=company_id
)

if not verification["is_novel"]:
    logger.info("email_duplicate_skipped", message_id=message_id)
    continue
```

2. **Reemplazar 3x direct inserts** con ingester:
```python
# Agregar todo el contenido
combined_text = f"""Asunto: {subject}\n..."""

result = await ingest_context_unit(
    raw_text=combined_text,
    title=f"Email: {subject[:100]}",
    company_id=company_id,
    source_type="email",
    source_id=message_id,
    source_metadata={"message_id": message_id, ...}
)
```

---

### Perplexity (`perplexity_news_connector.py`)
**Cambios**:

1. **Añadir verificación temporal** (Fase 1):
```python
# Antes de procesar cada noticia
verification = await verify_novelty(
    source_type="perplexity",
    content_data={
        "title": news_item["titulo"],
        "fecha": news_item["fecha"]
    },
    company_id=company_id
)

if not verification["is_novel"]:
    logger.info("perplexity_duplicate_skipped", title=news_item["titulo"][:50])
    continue
```

2. **Reemplazar direct insert** con ingester (líneas 234-270):
```python
result = await ingest_context_unit(
    raw_text=news_item["texto"],
    title=news_item["titulo"],  # Pre-generado por Perplexity
    # LLM genera resto
    company_id=company_id,
    source_type="api",
    source_id=f"perplexity_{date}_{i}",
    source_metadata={
        "fuente": news_item["fuente"],
        "fecha": news_item["fecha"]
    }
)
```

---

## Decisión LLM: GPT-4o-mini

**Modelo único**: `openai/gpt-4o-mini` via OpenRouter

**Por qué NO Groq**:
- `analyze_atomic` (Groq) devuelve formato simple (strings)
- `generate_context_unit` (GPT-4o-mini) devuelve formato estructurado
- GPT-4o-mini mejor para structured output
- Solo 3x más caro, pero mejor calidad

**Cambio en Scraping**:
```python
# ANTES
llm_result = await llm_client.analyze_atomic(text=...)  # Groq

# DESPUÉS
llm_result = await llm_client.generate_context_unit(text=...)  # GPT-4o-mini
```

**Routing centralizado**:
- TODO via `llm_client.py` → `openrouter_client.py`
- Tracking automático (organization_id + client_id)
- Compatibilidad con modelos futuros

---

## Plan de Implementación

### Semana 1: Crear Abstracciones (4h)

**Día 1**: Verifier
- [ ] Crear `utils/unified_context_verifier.py`
- [ ] Implementar `verify_novelty()` con 4 casos
- [ ] Tests unitarios

**Día 2**: Ingester
- [ ] Crear `utils/unified_context_ingester.py`
- [ ] Implementar `ingest_context_unit()` mega-flexible
- [ ] Implementar `normalize_atomic_statements()`
- [ ] Tests con diferentes combinaciones inputs

---

### Semana 2: Refactorizar Connectors (6h)

**Día 1**: Perplexity (URGENTE)
- [ ] Añadir `verify_novelty` temporal check
- [ ] Reemplazar direct insert con `ingest_context_unit`
- [ ] Test + deploy
- [ ] ✅ Verificar embeddings generados
- [ ] ✅ Verificar category presente

**Día 2**: Email
- [ ] Añadir `verify_novelty` Message-ID check
- [ ] Reemplazar 3x inserts con `ingest_context_unit`
- [ ] Test con emails reales
- [ ] Deploy

**Día 3**: Scraping
- [ ] Cambiar `analyze_atomic` → `generate_context_unit`
- [ ] Usar `ingest_context_unit` en save
- [ ] Test + deploy

---

### Semana 3: Backfill + Cleanup (3h)

**Día 1**: Backfill embeddings
- [ ] Regenerar 178 embeddings faltantes
- [ ] Verificar search funciona

**Día 2**: Deprecate código viejo
- [ ] Marcar `analyze_atomic` como deprecated
- [ ] Actualizar documentación

---

## Validación Final

### Checklist Pre-Deploy

**Perplexity**:
- [ ] Verificación temporal funciona
- [ ] Embeddings generados ✅
- [ ] Category presente ✅
- [ ] Búsqueda encuentra unidades ✅

**Email**:
- [ ] Message-ID no duplica
- [ ] Embeddings generados
- [ ] Audio transcriptions incluidas

**Scraping**:
- [ ] Change detection intacto
- [ ] GPT-4o-mini genera structured output
- [ ] Embeddings generados

---

## Métricas de Éxito

**ANTES**:
- 179 units, 1 con embedding (0.5%)
- Perplexity: sin embeddings, sin category
- Email: duplicados posibles
- Scraping: ✅ funciona bien

**DESPUÉS**:
- 100% units con embeddings
- 100% units con category
- 0 duplicados (Fase 1 + Fase 2)
- Search 100% funcional
- LLM único (GPT-4o-mini)
- Código -200 líneas

---

---

## Plan de Testing

### Tests Unitarios (`tests/test_unified_context.py`)

```python
import pytest
from utils.unified_context_verifier import verify_novelty
from utils.unified_context_ingester import ingest_context_unit, normalize_atomic_statements

class TestVerifier:
    """Tests para unified_context_verifier.py"""

    async def test_verify_novelty_email_new(self):
        """Email con Message-ID nuevo debe ser novel"""
        result = await verify_novelty(
            source_type="email",
            content_data={"message_id": "new-unique-id@example.com"},
            company_id="test-company-id"
        )
        assert result["is_novel"] == True
        assert result["reason"] == "new"

    async def test_verify_novelty_email_duplicate(self):
        """Email con Message-ID existente debe ser duplicate"""
        # Pre-insert email
        # ... setup ...
        result = await verify_novelty(
            source_type="email",
            content_data={"message_id": "existing-id@example.com"},
            company_id="test-company-id"
        )
        assert result["is_novel"] == False
        assert result["reason"] == "duplicate"

    async def test_verify_novelty_perplexity_recent(self):
        """Perplexity con título similar en 24h debe ser duplicate"""
        # Pre-insert similar title yesterday
        # ... setup ...
        result = await verify_novelty(
            source_type="perplexity",
            content_data={
                "title": "Aviso amarillo por nieve en Bizkaia",
                "fecha": "2025-11-20"
            },
            company_id="test-company-id"
        )
        assert result["is_novel"] == False
        assert result["reason"] == "recent_duplicate"

    async def test_verify_novelty_api_always_new(self):
        """API/manual siempre debe ser novel"""
        result = await verify_novelty(
            source_type="api",
            content_data={},
            company_id="test-company-id"
        )
        assert result["is_novel"] == True


class TestIngester:
    """Tests para unified_context_ingester.py"""

    async def test_ingest_raw_text_only(self):
        """Ingester con solo raw_text debe generar todo via LLM"""
        result = await ingest_context_unit(
            raw_text="El Gobierno Vasco aprueba nuevas medidas...",
            company_id="test-company-id",
            source_type="manual",
            source_id="test-1"
        )
        assert result["success"] == True
        assert "title" in result["generated_fields"]
        assert "summary" in result["generated_fields"]
        assert "category" in result["generated_fields"]

    async def test_ingest_with_pre_generated_title(self):
        """Ingester con título pre-generado NO debe regenerarlo"""
        result = await ingest_context_unit(
            raw_text="Texto completo...",
            title="Título pre-existente",
            company_id="test-company-id",
            source_type="manual",
            source_id="test-2"
        )
        assert result["success"] == True
        assert "title" not in result["generated_fields"]
        assert "summary" in result["generated_fields"]

    async def test_ingest_url_scraping(self):
        """Ingester con URL debe scrapear y procesar"""
        result = await ingest_context_unit(
            url="https://example.com/news/article",
            company_id="test-company-id",
            source_type="scraping",
            source_id="test-3"
        )
        assert result["success"] == True
        assert result["context_unit_id"]

    async def test_ingest_embeddings_generated(self):
        """Ingester debe generar embeddings por defecto"""
        result = await ingest_context_unit(
            raw_text="Contenido de prueba",
            company_id="test-company-id",
            source_type="manual",
            source_id="test-4"
        )
        # Verificar en BD que tiene embedding
        # ... DB check ...

    async def test_ingest_duplicate_detection(self):
        """Ingester debe detectar duplicados semánticos"""
        # Insert original
        await ingest_context_unit(
            raw_text="El Athletic gana 2-0 al Barcelona",
            title="Victoria del Athletic",
            company_id="test-company-id",
            source_type="manual",
            source_id="test-5a"
        )
        # Insert duplicate con texto ligeramente diferente
        result = await ingest_context_unit(
            raw_text="Athletic derrota 2-0 al Barça",
            title="Triunfo atlético",
            company_id="test-company-id",
            source_type="manual",
            source_id="test-5b"
        )
        assert result["duplicate_detected"] == True
        assert result["similarity_score"] > 0.95


class TestNormalizer:
    """Tests para normalize_atomic_statements"""

    def test_normalize_string_array(self):
        """String array debe convertirse a objetos estructurados"""
        input_statements = ["fact 1", "fact 2", "fact 3"]
        result = normalize_atomic_statements(input_statements)

        assert len(result) == 3
        assert result[0]["order"] == 1
        assert result[0]["type"] == "fact"
        assert result[0]["speaker"] is None
        assert result[0]["text"] == "fact 1"

    def test_normalize_structured_array(self):
        """Array estructurado debe validarse y mantenerse"""
        input_statements = [
            {"order": 1, "type": "quote", "speaker": "Juan", "text": "declaración"}
        ]
        result = normalize_atomic_statements(input_statements)
        assert result == input_statements

    def test_normalize_empty(self):
        """Empty/None debe retornar array vacío"""
        assert normalize_atomic_statements(None) == []
        assert normalize_atomic_statements([]) == []
```

---

### Tests de Integración (`tests/test_integration_context.py`)

```python
import pytest
from sources.perplexity_news_connector import execute_perplexity_news_task
from sources.multi_company_email_monitor import process_email

class TestPerplexityIntegration:
    """Tests end-to-end para Perplexity"""

    async def test_perplexity_creates_context_units_with_embeddings(self):
        """Perplexity debe crear units con embeddings y category"""
        # Setup mock source
        source = {
            "source_id": "test-perplexity-source",
            "company_id": "test-company-id",
            "config": {"location": "Bilbao", "news_count": 2}
        }

        result = await execute_perplexity_news_task(source)

        assert result["success"] == True
        assert result["items_processed"] == 2

        # Verificar en BD
        units = supabase.table("press_context_units")\
            .select("*")\
            .eq("source_type", "api")\
            .order("created_at", desc=True)\
            .limit(2)\
            .execute()

        for unit in units.data:
            assert unit["embedding"] is not None  # ✅ Tiene embedding
            assert unit["category"] is not None   # ✅ Tiene category
            assert unit["title"]
            assert unit["summary"]


    async def test_perplexity_skips_duplicates_24h(self):
        """Perplexity debe detectar duplicados en ventana 24h"""
        # Insert unit ayer
        # ... setup ...

        # Intentar insertar mismo título hoy
        result = await execute_perplexity_news_task(source)

        # Debe haber sido rechazado en verify_novelty
        assert result["items_processed"] < result["items_fetched"]


class TestEmailIntegration:
    """Tests end-to-end para Email"""

    async def test_email_creates_context_unit_with_embedding(self):
        """Email debe crear unit con embedding"""
        # Mock email data
        email_data = {
            "message_id": "test-email-123@example.com",
            "subject": "Nuevo aviso meteorológico",
            "body": "Se esperan nevadas..."
        }

        # Process
        await process_email(email_data)

        # Verificar
        unit = supabase.table("press_context_units")\
            .select("*")\
            .contains("source_metadata", {"message_id": email_data["message_id"]})\
            .single()\
            .execute()

        assert unit.data["embedding"] is not None
        assert unit.data["category"] is not None


    async def test_email_skips_duplicate_message_id(self):
        """Email con Message-ID duplicado debe ser rechazado"""
        # Insert email
        await process_email({"message_id": "dup@test.com", ...})

        # Intentar reinsertar
        result = await process_email({"message_id": "dup@test.com", ...})

        # Debe haber sido rechazado en verify_novelty
        assert result["duplicate_detected"] == True


class TestScrapingIntegration:
    """Tests end-to-end para Scraping"""

    async def test_scraping_uses_gpt4o_mini(self):
        """Scraping debe usar GPT-4o-mini después del refactor"""
        # Mock scraping task
        # Verificar que llama a generate_context_unit (GPT-4o-mini)
        # NO a analyze_atomic (Groq)
        pass


class TestAPIEndpoints:
    """Tests para endpoints públicos"""

    async def test_post_context_units_text(self):
        """POST /context-units debe usar ingester"""
        response = client.post(
            "/context-units",
            json={"text": "Contenido de prueba", "title": "Test"},
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        unit = response.json()
        assert unit["embedding"]  # ✅ Debe tener embedding


    async def test_post_context_units_from_url(self):
        """POST /context-units/from-url debe usar ingester"""
        response = client.post(
            "/context-units/from-url",
            json={"url": "https://example.com/article"},
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        unit = response.json()
        assert unit["embedding"]  # ✅ Debe tener embedding
```

---

### Tests de Búsqueda (`tests/test_search_after_refactor.py`)

```python
class TestSemanticSearch:
    """Verificar que búsqueda funciona después del refactor"""

    async def test_search_finds_all_sources(self):
        """Búsqueda debe encontrar units de TODAS las fuentes"""
        # Create units from different sources
        await ingest_context_unit(raw_text="Nieve en Bizkaia", source_type="api", ...)      # Perplexity
        await ingest_context_unit(raw_text="Nieve en Álava", source_type="email", ...)      # Email
        await ingest_context_unit(raw_text="Nieve en Gipuzkoa", source_type="scraping", ...) # Scraping

        # Search
        results = await semantic_search(query="nieve País Vasco", limit=10)

        # Debe encontrar los 3
        assert len(results) >= 3
        source_types = {r["source_type"] for r in results}
        assert "api" in source_types
        assert "email" in source_types
        assert "scraping" in source_types


    async def test_search_no_duplicates(self):
        """Búsqueda NO debe retornar duplicados"""
        # Insert duplicate content from different sources
        text = "El Athletic gana 2-0 al Barcelona en San Mamés"

        result1 = await ingest_context_unit(raw_text=text, source_type="api", ...)
        result2 = await ingest_context_unit(raw_text=text, source_type="email", ...)

        # El segundo debe ser rechazado como duplicate
        assert result2["duplicate_detected"] == True

        # Search debe retornar solo 1
        results = await semantic_search(query="Athletic Barcelona", limit=10)
        assert len(results) == 1
```

---

### Checklist de Validación Manual

**Antes de deploy a producción**:

1. **Perplexity (CRÍTICO)**
   - [ ] Ejecutar job Perplexity manualmente
   - [ ] Verificar 5 units creadas
   - [ ] Verificar TODAS tienen `embedding` (no NULL)
   - [ ] Verificar TODAS tienen `category` (no NULL)
   - [ ] Buscar una unit por título → debe encontrarla
   - [ ] Ejecutar job 2x seguidas → 2da debe rechazar duplicados

2. **Email**
   - [ ] Enviar email de prueba a monitor
   - [ ] Verificar unit creada con embedding
   - [ ] Enviar mismo email otra vez → debe ser rechazado

3. **Scraping**
   - [ ] Ejecutar scraping de URL conocida
   - [ ] Verificar usa GPT-4o-mini (no Groq)
   - [ ] Verificar unit tiene embedding
   - [ ] Re-scrapear misma URL sin cambios → debe ser rechazado

4. **API Endpoints**
   - [ ] POST /context-units con texto → verificar embedding
   - [ ] POST /context-units/from-url → verificar embedding
   - [ ] POST /ingest/text → verificar embedding
   - [ ] POST /ingest/url → verificar embedding

5. **Búsqueda**
   - [ ] Buscar "nieve Bizkaia" → debe encontrar units recientes
   - [ ] Buscar "mudanza religiosas" → debe encontrar unit test
   - [ ] Verificar score > 0.5 para matches relevantes

6. **Tracking LLM**
   - [ ] Verificar tabla `llm_usage` tiene registros nuevos
   - [ ] Verificar `model` = "openai/gpt-4o-mini"
   - [ ] Verificar `operation` correcta por source
   - [ ] Verificar costos calculados correctamente

---

**FIN DEL PLAN**
