# Guía de Desarrollo para Claude Code

Este documento contiene instrucciones específicas para Claude Code al trabajar en el proyecto **semantika**.

## Contexto del Proyecto

`semantika` es un pipeline de datos semánticos multi-tenant diseñado para operar como servicio headless. Agrega, procesa y unifica información de múltiples fuentes en Qdrant para búsquedas semánticas, alertas y agregación.

## Stack Tecnológico

- **Backend**: Python 3.10+, FastAPI, APScheduler
- **Base de Datos**: Supabase (config), Qdrant (vectores)
- **LLM**: OpenRouter (Claude 3.5 Sonnet, GPT-4o-mini)
- **Embeddings**: ⚠️ **OpenRouter/OpenAI** (temporal - ver migración pendiente)
- **Orquestación**: Docker Compose
- **Deployment**: GitHub Actions (CI/CD automático)

## ⚠️ MIGRACIÓN PENDIENTE: Embeddings Locales

### Estado Actual (Temporal)
**Usando OpenRouter API para embeddings**:
- Modelo: `openai/text-embedding-3-small` (1536d truncado a 384d)
- Costo: ~$0.02 por 1M tokens (~$1-5/mes estimado)
- Ubicación: `utils/embedding_generator.py` (fallback automático)
- Razón: VPS modesto sin GPU, múltiples clientes concurrentes

### Plan de Migración (Cuando escales)

**OBJETIVO**: Migrar a modelo local multilingual optimizado para español

**Modelo recomendado**: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
- Dimensiones: 768 (vs 384 actual)
- Idiomas: 50+ incluyendo español y euskera
- Rendimiento: Excelente para contenido en español

**Pasos de migración**:

1. **Preparar modelo local**:
   ```python
   # En utils/embedding_generator.py
   from fastembed import TextEmbedding
   model = TextEmbedding(
       model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
   )
   ```

2. **Migrar base de datos**:
   ```sql
   -- Aumentar dimensiones de 384 a 768
   ALTER TABLE press_context_units
   ALTER COLUMN embedding TYPE vector(768);

   ALTER TABLE url_content_units
   ALTER COLUMN embedding TYPE vector(768);
   ```

3. **Actualizar función de búsqueda**:
   ```sql
   -- En search_context_units_by_vector()
   -- Cambiar parámetro: p_query_embedding vector(768)
   ```

4. **Regenerar embeddings existentes**:
   - Script para procesar todos los context units (~30+ unidades)
   - Regenerar embedding con nuevo modelo
   - Actualizar BD con nuevos vectores de 768d

5. **Eliminar fallback de OpenRouter**:
   - Remover código de fallback a OpenAI
   - Usar solo modelo local

**Requisitos de recursos**:
- Disco: +90-120MB (modelo)
- RAM: +300MB (modelo cargado)
- CPU: 100-200ms por embedding (sin GPU)
- ⚠️ **Consideración**: Con múltiples clientes buscando simultáneamente, evaluar si VPS puede manejar la carga

**Cuándo migrar**:
- ✅ Cuando tengas servidor con >4 cores o GPU
- ✅ Cuando el costo de OpenRouter justifique infraestructura
- ✅ Cuando necesites embeddings offline
- ❌ NO migrar si el VPS actual se satura con búsquedas concurrentes

**Ver también**:
- `utils/embedding_generator.py` (TODO gigante línea ~183)
- Issues de FastEmbed: https://github.com/qdrant/fastembed

## Arquitectura

### Componentes Docker
1. **semantika-api**: FastAPI server (puerto 8000)
2. **semantika-scheduler**: APScheduler daemon
3. **qdrant**: Vector database (puerto 6333)

### Flujo de Datos
1. Ingesta → Guardrails (PII/Copyright) → Desduplicación → Qdrant
2. Búsqueda → Filtrado por client_id → Agregación (opcional con LLM)

## Reglas de Desarrollo

### 1. Logging
- **SIEMPRE** usar JSON estructurado en stdout
- Formato: `{"level": "INFO", "timestamp": "...", "service": "...", "action": "...", "client_id": "...", ...}`
- Niveles: DEBUG, INFO, WARN, ERROR

### 2. Multi-tenancy
- **NUNCA** permitir queries sin filtro `client_id`
- Validar API Key en **cada** request
- Aislar datos estrictamente por cliente

### 3. Seguridad
- **NO** commitear `.env`
- **NO** loguear API keys o credenciales
- Anonimizar PII antes de vectorizar
- Validar robots.txt antes de scrapear

### 4. Variables de Entorno
Usar `.env` para:
- `SUPABASE_URL`, `SUPABASE_KEY`
- `OPENROUTER_API_KEY`
- `SCRAPERTECH_API_KEY`
- `QDRANT_URL`, `QDRANT_COLLECTION_NAME`
- Configuraciones de procesamiento

### 5. Dependencias
Mantener `requirements.txt` sincronizado con:
- FastAPI, uvicorn
- supabase-py, qdrant-client
- langchain, langchain-openai
- openai-whisper (opcional, pesado)
- beautifulsoup4, requests

### 6. Guardrails
Implementar **antes** de la desduplicación:
1. **PII Detection**: LLM few-shot → Anonimizar → Log WARN
2. **Copyright**: LLM pattern match → Rechazar → Log INFO
3. **Robots.txt**: Verificar allow/disallow → Bloquear si prohibido

### 7. Desduplicación
- Calcular embedding del `title` o primeros 200 chars
- Buscar similitud > 0.98 en Qdrant (filtrado por `client_id`)
- Si duplicado → Descartar → Log DEBUG

### 8. TTL (Time-to-Live)
- Datos con `special_info=false`: Borrar después de 30 días
- Job diario en `scheduler.py`
- Filtro Qdrant: `loaded_at < (now - 30 days) AND special_info = false`

## Estructura de Archivos

```
/semantika/
├── .env                  # Secretos (NO commitear)
├── .env.example          # Plantilla
├── .gitignore
├── requirements.md       # Arquitectura completa
├── CLAUDE.md            # Este archivo
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── server.py            # FastAPI API
├── scheduler.py         # APScheduler cron
├── core_ingest.py       # Motor de ingesta
├── cli.py               # Admin CLI
├── /sources/            # Conectores (web, twitter, api, audio)
├── /utils/              # Logging, helpers
└── /sql/                # Scripts Supabase
```

## Tareas Pendientes

### Fase 1: Infraestructura
- [x] .env.example
- [x] .gitignore
- [x] requirements.md (actualizado con OpenRouter)
- [x] CLAUDE.md (este archivo)
- [ ] Dockerfile
- [ ] docker-compose.yml
- [ ] requirements.txt
- [ ] SQL schemas (Supabase)

### Fase 2: Core
- [ ] utils/logger.py (JSON logging)
- [ ] utils/config.py (Pydantic settings)
- [ ] core_ingest.py (guardrails, dedupe, carga)

### Fase 3: Conectores
- [ ] sources/web_scraper.py (BeautifulSoup + LLM)
- [ ] sources/twitter_scraper.py (scraper.tech API)
- [ ] sources/audio_transcriber.py (Whisper)
- [ ] sources/api_connectors.py (EFE, Reuters, WordPress)

### Fase 4: APIs
- [ ] server.py (FastAPI: /search, /aggregate, /ingest)
- [ ] scheduler.py (APScheduler: jobs + TTL cleanup)
- [ ] cli.py (add-client, add-task, list-*)

### Fase 5: CI/CD
- [ ] .github/workflows/deploy.yml (SSH → VPS → deploy)
- [ ] README.md (instrucciones de uso)
- [ ] Testing básico

## Comandos Útiles

### Desarrollo Local (Mac M1)
```bash
# Primera vez
cp .env.example .env
# Editar .env con tus claves

# Levantar servicios
docker-compose up -d --build

# Ver logs
docker-compose logs -f semantika-api
docker-compose logs -f semantika-scheduler

# Acceder al API
curl http://localhost:8000/health

# Parar todo
docker-compose down
```

### Producción (VPS)
```bash
# Deploy automático
git push  # GitHub Actions hace el resto

# Deploy manual
ssh usuario@VPS
cd /path/to/semantika
git pull
docker-compose up -d --build
```

### CLI Admin
```bash
# Añadir cliente
docker exec -it semantika-api python cli.py add-client --name "Cliente X"

# Añadir tarea
docker exec -it semantika-api python cli.py add-task \
  --client-id "uuid-X" \
  --type "web_llm" \
  --target "https://example.com" \
  --freq 60

# Listar clientes
docker exec -it semantika-api python cli.py list-clients
```

## Convenciones de Código

### Imports
```python
# Standard library
import os
from typing import List, Dict, Any
from datetime import datetime

# Third party
from fastapi import FastAPI, HTTPException
from qdrant_client import QdrantClient
from supabase import create_client

# Local
from utils.logger import get_logger
from utils.config import settings
```

### Logging
```python
import json
from datetime import datetime

def log(level: str, service: str, action: str, **kwargs):
    print(json.dumps({
        "level": level,
        "timestamp": datetime.utcnow().isoformat(),
        "service": service,
        "action": action,
        **kwargs
    }))

# Uso
log("INFO", "core_ingest", "document_added",
    client_id="uuid-A", qdrant_id="uuid-1", source="web")
```

### Manejo de Errores
```python
try:
    result = await ingest_document(...)
    log("INFO", "scheduler", "ingest_success", task_id=task_id)
except Exception as e:
    log("ERROR", "scheduler", "ingest_failed",
        task_id=task_id, error=str(e))
    # NO re-raise en scheduler (continuar con otros jobs)
```

## Notas Importantes

1. **OpenRouter vs Ollama**: Usamos OpenRouter para reducir requisitos de hardware del VPS. No hay contenedor Ollama.

2. **Whisper**: Es pesado. Considerar hacerlo opcional o usar API externa en producción.

3. **Qdrant Cloud**: Si el VPS es muy pequeño, considerar Qdrant Cloud en lugar de self-hosted.

4. **Supabase**: Es la única fuente de verdad para configuración. No cachear en memoria sin TTL.

5. **GitHub Actions**: Requiere configurar SSH keys en GitHub Secrets antes del primer deploy.

## Referencias

- Arquitectura completa: `requirements.md`
- Qdrant Docs: https://qdrant.tech/documentation/
- OpenRouter Models: https://openrouter.ai/models
- Supabase Docs: https://supabase.com/docs
- ScraperTech API: https://scraper.tech/docs
