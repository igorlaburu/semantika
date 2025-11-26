# Sistema de Monitoreo de Subvenciones DFA - Implementación Completa

**Fecha**: 2025-11-26  
**Usuario**: igor@gako.ai  
**URL Objetivo**: https://egoitza.araba.eus/es/-/tr-solicitar-ayudas-forestales  
**Schedule**: Diario a las 8:00 AM UTC

---

## ✅ Implementación Completada

**NOTA IMPORTANTE**: El source DFA usa `source_type='api'` con `config.connector_type='dfa_subsidies'` porque la tabla `sources` tiene un constraint que solo permite ciertos source_types predefinidos. El scheduler detecta el connector_type y enruta al monitor DFA correspondiente.

### 1. Base de Datos (SQL Migrations)

#### `sql/migrations/003_create_web_context_units.sql`
- **Tabla**: `web_context_units`
- **Estructura**: Similar a `press_context_units` pero para contenido web
- **Características**:
  - Embeddings 768d (FastEmbed multilingual)
  - Versioning (campo `version`, `replaced_by_id`, `is_latest`)
  - Change tracking (content_hash, simhash)
  - RLS multi-tenant
  - Función `match_web_context_units()` para búsqueda semántica

#### `sql/migrations/004_create_dfa_subsidies_source.sql`
- **Source**: Configurado para company `gako` (igor@gako.ai)
- **Config**:
  ```json
  {
    "target_url": "https://egoitza.araba.eus/es/-/tr-solicitar-ayudas-forestales",
    "change_detection": {
      "method": "simhash",
      "simhash_threshold": 0.90
    },
    "pdf_extraction": {
      "enabled": true,
      "max_file_size_mb": 10,
      "summarize_with_llm": true
    }
  }
  ```
- **Schedule**: Cron `0 8 * * *` (8:00 AM UTC)

---

### 2. Dependencias Añadidas

**requirements.txt**:
```
PyPDF2==3.0.1        # Extracción de texto de PDFs
pdfplumber==0.10.4   # Fallback para PDFs complejos
jinja2==3.1.3        # Templates de informes MD
simhash==2.1.2       # Ya estaba (detección de cambios)
```

---

### 3. Componentes Implementados

#### `utils/pdf_extractor.py`
**Funcionalidad**:
- Descarga PDFs con límite de tamaño (10MB) y timeout (30s)
- Extracción de texto multi-método:
  1. PyPDF2 (rápido, PDFs text-based)
  2. pdfplumber (fallback, layouts complejos)
- Resumen LLM (Llama 3.3 70B) en bullet points
- Procesamiento paralelo de múltiples PDFs

**Métodos clave**:
```python
async def download_pdf(url) -> (bytes, error)
def extract_text(pdf_bytes) -> (text, errors)
async def summarize_with_llm(text) -> List[str]  # Bullet points
async def process_pdf(url) -> Dict  # Pipeline completo
```

#### `utils/md_report_generator.py`
**Funcionalidad**:
- Templates Jinja2 para informes estructurados
- Formato consistente para subvenciones

**Template sections**:
```markdown
# Título
## 📅 Plazos de Presentación
## 📋 Metodología de Presentación
## 📄 Documentación a Presentar
  ### 1. Documento
  - Enlace
  - Resumen (bullets del PDF)
## 💰 Solicitudes de Pago
## 📌 Información Adicional
```

**Método clave**:
```python
def generate_subsidy_report(
    titulo, url, plazos, metodologia, 
    documentacion, solicitudes_pago
) -> str  # Markdown
```

#### `workflows/subsidy_extraction_workflow.py`
**Funcionalidad**:
- Workflow especializado para extracción de subvenciones
- Hereda de `BaseWorkflow`

**Pipeline**:
1. **LLM Extraction** → JSON estructurado con:
   - Título
   - Plazos (estado, fecha_inicio, fecha_fin)
   - Metodología (descripción)
   - Documentación (lista de {titulo, url, descripcion})
   - Solicitudes de pago
2. **PDF Processing** → Descarga y resume todos los PDFs en paralelo
3. **MD Report** → Genera informe Markdown con template
4. **Context Unit** → Prepara datos para `ingest_web_context_unit()`

**Método clave**:
```python
async def generate_context_unit(source_content) -> Dict
```

#### `sources/dfa_subsidies_monitor.py`
**Funcionalidad**:
- Monitor especializado para página DFA
- Detección de cambios con SimHash (threshold 0.90)

**Pipeline**:
1. **Fetch HTML** → Descarga página actual
2. **Compare SimHash** → Compara con snapshot anterior
   - `identical` / `trivial` → Skip
   - `minor_update` / `major_update` → Process
3. **Process Updates** → Ejecuta `SubsidyExtractionWorkflow`
4. **Save to DB** → Llama `ingest_web_context_unit()`
5. **Save Snapshot** → Guarda hashes para próxima comparación

**Métodos clave**:
```python
async def fetch_page(url) -> str
async def check_for_updates(source, company) -> bool
```

#### `utils/unified_context_ingester.py` (Actualizado)
**Funcionalidad añadida**:
- Nueva función `ingest_web_context_unit()` para `web_context_units`
- Lógica de versioning y reemplazo
- Genera content_hash y simhash automáticamente

**Método nuevo**:
```python
async def ingest_web_context_unit(
    raw_text: str,
    title=None, summary=None, tags=None,
    company_id, source_type, source_id,
    replace_previous=True  # Reemplaza versión anterior
) -> Dict
```

**Lógica de versioning**:
- Si `replace_previous=True`:
  - Busca registro existente con `is_latest=True`
  - Si existe → UPDATE (incrementa version)
  - Si no existe → INSERT
- Si `replace_previous=False`:
  - Siempre INSERT (nueva versión)

#### `scheduler.py` (Actualizado)
**Funcionalidad añadida**:
- Nuevo caso en `execute_source_task()` para `source_type="dfa_subsidies"`

**Lógica**:
```python
if source_type == "dfa_subsidies":
    monitor = get_dfa_subsidies_monitor()
    changes_detected = await monitor.check_for_updates(source, company)
    # Log execution
    # Update stats
```

**Integración**:
- El scheduler **ya lee dinámicamente** todas las sources activas
- Ejecuta cada source según su `schedule_config`
- No requiere hardcodear el job DFA

---

## 🔧 Configuración y Deployment

### Paso 1: Ejecutar Migraciones SQL ✅ COMPLETADO

```bash
# Migraciones ejecutadas vía MCP Supabase:
# ✅ Migration 003: create_web_context_units - Tabla creada
# ✅ Migration 004: create_dfa_subsidies_source - Source creado

# Source ID: 58b0f22e-ad7f-4dbe-9086-027307970070
# Source Type: api (connector_type: dfa_subsidies)
# Company: GAKO AI PRUEBAS (2cfa7d05-d754-4b78-a426-a117af1616d8)
```

### Paso 2: Instalar Dependencias

```bash
cd /Users/igor/Documents/semantika
pip install -r requirements.txt
```

### Paso 3: Verificar Source Configurado ✅ COMPLETADO

```sql
-- Verificar source DFA
SELECT 
    source_id, source_name, source_type, is_active,
    config->>'connector_type' as connector_type,
    config->>'target_url' as url,
    schedule_config->>'cron_expression' as cron
FROM sources
WHERE source_code = 'dfa_subsidies_monitor';

-- Resultado:
-- source_id: 58b0f22e-ad7f-4dbe-9086-027307970070
-- source_type: api
-- connector_type: dfa_subsidies
-- is_active: true
-- cron: 0 8 * * *
```

### Paso 4: Deploy a Producción

```bash
# Commit cambios
git add .
git commit -m "Add DFA subsidies monitoring system"
git push

# GitHub Actions desplegará automáticamente
```

---

## 📊 Flujo de Ejecución

### Ejecución Diaria (8:00 AM UTC)

```
1. Scheduler lee source con source_type='dfa_subsidies'
2. Ejecuta execute_source_task(source)
   ↓
3. DFASubsidiesMonitor.check_for_updates()
   ↓
4. Fetch HTML de https://egoitza.araba.eus/...
   ↓
5. Calcular SimHash y comparar con snapshot anterior
   ↓
6. SI cambios significativos (similarity < 0.90):
   ↓
   7. SubsidyExtractionWorkflow.process_content()
      ↓
      8. LLM extrae JSON estructurado
      9. Descarga y resume PDFs (paralelo)
      10. Genera informe Markdown
      ↓
   11. ingest_web_context_unit()
      - Genera embedding (768d)
      - Calcula content_hash y simhash
      - UPDATE registro existente (versioning)
      ↓
   12. Save snapshot (hashes para próxima comparación)
   
   RESULTADO: web_context_units actualizado
   
7. ELSE (sin cambios):
   - Log "Sin cambios significativos"
   - No procesa
```

---

## 🎯 Características Clave

### SimHash Change Detection
- **Inmune a cambios triviales**:
  - Timestamps actualizados
  - Banners/ads rotados
  - Cambios CSS/layout menores
- **Detecta cambios relevantes**:
  - Plazos modificados
  - Nuevos documentos añadidos
  - Estado cambiado (abierto/cerrado)

### PDF Processing Inteligente
- **Multi-método**: PyPDF2 → pdfplumber (fallback)
- **Parallel downloads**: Hasta 3 PDFs simultáneos
- **Size limit**: 10MB máximo
- **LLM summaries**: Bullet points concisos
- **Error handling**: Continúa si algún PDF falla

### Versioning System
- **is_latest flag**: Solo una versión activa por source
- **version number**: Incrementa en cada update
- **replaced_by_id**: Chain de versiones históricas
- **Queries**: Filtrar por `WHERE is_latest = TRUE`

### Multi-tenant Isolation
- **RLS policies**: Automático por company_id
- **Embeddings por company**: Deduplicación aislada
- **Logs separados**: Por client_id y company_id

---

## 🧪 Testing Manual

### Test 1: Verificar Source Configurado

```bash
# SSH al servidor
ssh usuario@api.ekimen.ai

# Ver source DFA
docker exec -it semantika-api python -c "
from utils.supabase_client import get_supabase_client
import asyncio

async def test():
    supabase = get_supabase_client()
    result = supabase.client.table('sources')\
        .select('*')\
        .eq('source_type', 'dfa_subsidies')\
        .execute()
    print(result.data)

asyncio.run(test())
"
```

### Test 2: Ejecutar Manualmente

```bash
# Ejecutar monitor una vez
docker exec -it semantika-api python -c "
from sources.dfa_subsidies_monitor import get_dfa_subsidies_monitor
from utils.supabase_client import get_supabase_client
import asyncio

async def test():
    supabase = get_supabase_client()
    
    # Get source
    source = supabase.client.table('sources')\
        .select('*')\
        .eq('source_type', 'dfa_subsidies')\
        .single()\
        .execute().data
    
    # Get company
    company = supabase.client.table('companies')\
        .select('*')\
        .eq('id', source['company_id'])\
        .single()\
        .execute().data
    
    # Run monitor
    monitor = get_dfa_subsidies_monitor()
    result = await monitor.check_for_updates(source, company)
    
    print(f'Changes detected: {result}')

asyncio.run(test())
"
```

### Test 3: Verificar web_context_units

```sql
-- Ver última versión guardada
SELECT 
    id, title, category, version, is_latest,
    created_at, updated_at,
    LENGTH(raw_text) as report_length,
    tags
FROM web_context_units
WHERE source_type = 'dfa_subsidies'
AND is_latest = TRUE
ORDER BY updated_at DESC
LIMIT 1;
```

---

## 📝 Próximos Pasos

### Pendiente

1. **Unit Tests** (`tests/test_dfa_subsidies_monitor.py`):
   - Test SimHash detection
   - Test PDF extraction
   - Test MD report generation
   - Mock LLM responses

2. **Integration Test** (`tests/integration/test_dfa_end_to_end.py`):
   - Test completo con HTML de ejemplo
   - Verificar base de datos
   - Verificar versioning

3. **Monitoring**:
   - Alertas si falla extracción
   - Dashboard con histórico de cambios
   - Notificaciones a igor@gako.ai cuando hay updates

### Mejoras Futuras

- **OCR para PDFs escaneados**: Tesseract si los PDFs son imágenes
- **Diff visualization**: Mostrar qué cambió exactamente
- **Email notifications**: Enviar informe cuando hay cambios
- **API endpoint**: GET /api/v1/subsidies/dfa/latest

---

## 🐛 Troubleshooting

### Error: "Company 'gako' not found"
```sql
-- Verificar si existe
SELECT * FROM companies WHERE company_code = 'gako';

-- Si no existe, crear primero:
INSERT INTO companies (company_name, company_code, is_active)
VALUES ('Gako', 'gako', TRUE);
```

### Error: "Table web_context_units does not exist"
```bash
# Ejecutar migración 003
# En Supabase SQL Editor, copiar contenido de:
# sql/migrations/003_create_web_context_units.sql
```

### Error: "PDF download timeout"
```python
# Ajustar timeout en source config:
UPDATE sources
SET config = jsonb_set(
    config,
    '{pdf_extraction,timeout_seconds}',
    '60'
)
WHERE source_type = 'dfa_subsidies';
```

### Error: "SimHash library not installed"
```bash
pip install simhash==2.1.2
```

---

## 📚 Referencias

- **SimHash**: `utils/content_hasher.py` - Multi-tier change detection
- **Workflow Factory**: `workflows/workflow_factory.py` - Registro de workflows
- **LLM Client**: `utils/llm_client.py` - OpenRouter integration
- **Embedding Generator**: `utils/embedding_generator.py` - 768d FastEmbed

---

**Estado**: ✅ Implementación completa  
**Próximo deploy**: Ejecutar migraciones SQL y push a producción
