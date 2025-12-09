# Guía de Desarrollo para Claude Code

Este documento contiene instrucciones específicas para Claude Code al trabajar en el proyecto **semantika**.

## Contexto del Proyecto

`semantika` es un pipeline de datos semánticos multi-tenant diseñado para operar como servicio headless. Agrega, procesa y unifica información de múltiples fuentes en PostgreSQL/pgvector para búsquedas semánticas híbridas, alertas y agregación.

## Stack Tecnológico

- **Backend**: Python 3.10+, FastAPI, APScheduler
- **Base de Datos**: Supabase PostgreSQL + pgvector (embeddings 768d)
- **LLM**: OpenRouter (Claude 3.5 Sonnet), Groq (Llama 3.3 70B - gratis)
- **Embeddings**: ✅ **FastEmbed local** (`paraphrase-multilingual-mpnet-base-v2`, 768d)
- **Búsqueda**: Híbrida (semantic pgvector + keyword full-text)
- **Orquestación**: Docker Compose
- **Deployment**: GitHub Actions (CI/CD automático)

## Arquitectura de Datos

### Sistema Unificado PostgreSQL + pgvector

**Estado actual**: ✅ Migración completa de Qdrant → PostgreSQL (dic 2024)

**Ventajas**:
- ✅ Una sola BD (config + vectores) - simplicidad operacional
- ✅ RLS policies para multi-tenancy seguro
- ✅ Búsqueda híbrida (semantic + keyword en una query)
- ✅ Joins nativos (context_units + sources + companies)
- ✅ No necesita sincronización entre Qdrant y Supabase

**Colecciones**:
- `press_context_units`: Noticias de prensa (company-specific + pool)
- `web_context_units`: Monitoring web (subvenciones, formularios)

**Pool compartido**:
- UUID: `99999999-9999-9999-9999-999999999999`
- Contenido público accesible por todos los clientes
- Discovery automático vía GNews + LLM (cada 3 días)
- Ingesta horaria de fuentes descubiertas

### Embeddings FastEmbed (Local)

**Modelo**: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
- Dimensiones: 768
- Idiomas: 50+ (español, euskera, catalán, gallego, inglés...)
- Velocidad: ~100-200ms por embedding (CPU)
- Ubicación: `utils/embedding_generator.py`

**Performance**:
- Startup: Modelo precargado en `/app/startup` (~1-2 segundos)
- Inferencia: ~150ms por query en VPS modesto
- Costo: $0 (100% local)

### Búsqueda Híbrida (Semantic + Keyword)

**Endpoint**: `POST /api/v1/context-units/search-vector`

**3 técnicas combinadas**:
1. **Query expansion**: Cache (1h) + sinónimos locales + LLM Groq (gratis)
2. **Semantic search**: pgvector cosine similarity (threshold 0.18)
3. **Keyword search**: PostgreSQL full-text search (Spanish config)

**Re-ranking**: `0.7 * semantic_score + 0.3 * keyword_score`

**Performance**:
- Latencia: 150-200ms (con cache) / 300-400ms (sin cache)
- Costo: $0 (Groq gratis para expansión)
- Threshold: 0.18 (vs 0.25 anterior, +40% resultados)

## Arquitectura

### Componentes Docker
1. **semantika-api**: FastAPI server (puerto 8000)
2. **semantika-scheduler**: APScheduler daemon
   - **Auto-reload**: Recarga sources cada 5 minutos automáticamente
   - **NO reiniciar** después de cambiar schedules en BD - esperar hasta 5min
3. **qdrant**: Vector database (puerto 6333)

### Zonas Horarias
- **España**: UTC+1 (CET) en invierno, UTC+2 (CEST) en verano
- **Scheduler**: Usa **UTC** siempre
- **Conversión**: España 13:00 = UTC 12:00 (invierno)

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

### Pool Discovery & Ingestion
- [ ] **TODO**: Mover schedules de pool discovery/ingestion a BD (tabla pool_discovery_config)
  - Actualmente hardcoded en scheduler.py (discovery cada hora :30, ingestion cada hora :00)
  - Debería leer schedule_config desde pool_discovery_config por geographic_area
  - Permitir diferentes frecuencias por región (ej: Álava cada 2h, Bizkaia cada 6h)
- [ ] **TODO**: Mejorar validación de URLs en discovery_flow.py
  - Añadir post-validación después de extract_index_url()
  - Detectar y rechazar URLs con IDs numéricos largos o slugs específicos
  - Ejemplo rechazar: `/events/106714-titulo-largo` → Aceptar solo: `/events`
- [ ] **TODO**: Limpiar contenido HTML antes de generar embeddings
  - Actualmente el summary tiene mucho ruido (navegación, scripts, etc)
  - Afecta la calidad de los embeddings y scores de búsqueda
  - Mejorar extracción en web_scraper.py antes de enrichment

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

## Testing

### Ejecutar Tests Unitarios

**IMPORTANTE**: Todos los cambios nuevos DEBEN incluir unit tests.

```bash
# Ejecutar todos los tests
./run_tests.sh

# O manualmente con pytest
python3 -m pytest tests/ -v

# Ejecutar un test específico
python3 -m pytest tests/test_unified_content_enricher.py -v

# Ejecutar con coverage
python3 -m pytest tests/ --cov=utils --cov=sources --cov-report=html
```

### Estructura de Tests

```
/tests/
├── __init__.py
├── test_unified_content_enricher.py  # Content enrichment tests
├── test_llm_client.py                 # (TODO)
└── test_scraper_workflow.py           # (TODO)
```

### Escribir Tests

Usar `pytest` + `pytest-asyncio` para tests asíncronos:

```python
import pytest
from unittest.mock import Mock, AsyncMock, patch

@pytest.mark.asyncio
async def test_enrich_content():
    mock_llm = Mock()
    mock_llm.analyze_atomic = AsyncMock(return_value={...})
    
    with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm):
        result = await enrich_content(...)
    
    assert result["category"] == "política"
```

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

**Acceso SSH para Claude Code**:
```bash
# Configuración SSH (en ~/.ssh/config)
Host semantika-vps
    HostName api.ekimen.ai
    User ubuntu
    IdentityFile ~/.ssh/claude_vps_key

# Conectar (forma simple)
ssh semantika-vps

# O directamente
ssh -i ~/.ssh/claude_vps_key ubuntu@api.ekimen.ai

# Contenedores Docker (nombres completos)
# - ekimen_semantika-semantika-api-1 (FastAPI)
# - ekimen_semantika-semantika-scheduler-1 (APScheduler)
# - ekimen_semantika-qdrant-1 (Vector DB)
```

**Comandos útiles VPS**:
```bash
# Deploy automático
git push  # GitHub Actions hace el resto

# Deploy manual
ssh semantika-vps
cd ~/semantika  # o donde esté el proyecto
git pull
sudo docker-compose up -d --build

# Ver logs en tiempo real
ssh semantika-vps "sudo docker logs -f ekimen_semantika-semantika-api-1"

# Reiniciar contenedor API
ssh semantika-vps "sudo docker restart ekimen_semantika-semantika-api-1"

# Ejecutar CLI en VPS
ssh semantika-vps "sudo docker exec ekimen_semantika-semantika-api-1 python cli.py list-clients"
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
