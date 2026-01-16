# Plan de Refactorización: server.py → endpoints/

## Checkpoint de recuperación
```bash
git checkout checkpoint-before-refactor-20260116-194828
```

---

## Fase 0: Preparación

### 0.1 Crear estructura de directorios
```
endpoints/
├── __init__.py
├── auth.py
├── oauth_twitter.py
├── oauth_linkedin.py
├── oauth_facebook.py
├── legacy.py
├── process.py
├── context_units.py
├── articles.py
├── images.py
├── tts.py
├── companies.py
└── publication_targets.py

utils/
├── auth_dependencies.py (NUEVO)
└── helpers.py (NUEVO)
```

### 0.2 Extraer dependencias compartidas primero
1. `utils/auth_dependencies.py` - funciones de auth (get_auth_context, etc.)
2. `utils/helpers.py` - funciones helper (_generate_slug, _strip_markdown, etc.)

---

## Fase 1: Módulos sin dependencias externas (bajo riesgo)

### 1.1 `endpoints/tts.py` (2 endpoints, ~150 líneas)
- [ ] Extraer endpoints TTS
- [ ] Test local: `curl http://localhost:8000/tts/health`
- [ ] Verificar logs

### 1.2 `endpoints/companies.py` (4 endpoints, ~300 líneas)
- [ ] Extraer endpoints de company settings
- [ ] Test local: `curl http://localhost:8000/api/v1/companies/current/settings`

### 1.3 `endpoints/publication_targets.py` (6 endpoints, ~350 líneas)
- [ ] Extraer endpoints de publication targets
- [ ] Test local: `curl http://localhost:8000/api/v1/publication-targets`

---

## Fase 2: OAuth (módulos independientes)

### 2.1 `endpoints/oauth_twitter.py` (4 endpoints, ~400 líneas)
- [ ] Extraer OAuth Twitter
- [ ] Test local: `curl http://localhost:8000/oauth/twitter/status`

### 2.2 `endpoints/oauth_linkedin.py` (4 endpoints, ~400 líneas)
- [ ] Extraer OAuth LinkedIn
- [ ] Test local: `curl http://localhost:8000/oauth/linkedin/status`

### 2.3 `endpoints/oauth_facebook.py` (6 endpoints, ~550 líneas)
- [ ] Extraer OAuth Facebook
- [ ] Test local: `curl http://localhost:8000/oauth/facebook/status`

---

## Fase 3: Auth (dependencias de Supabase Auth)

### 3.1 `endpoints/auth.py` (7 endpoints, ~400 líneas)
- [ ] Extraer auth endpoints (signup, login, refresh, logout, forgot/reset password)
- [ ] Test local: `curl -X POST http://localhost:8000/auth/login -d '...'`

---

## Fase 4: Módulos de datos (medio riesgo)

### 4.1 `endpoints/images.py` (10 endpoints, ~700 líneas)
- [ ] Extraer todos los endpoints de imágenes
- [ ] Incluir `generate_placeholder_image()`
- [ ] Test local: `curl http://localhost:8000/api/v1/images/{uuid}`

### 4.2 `endpoints/context_units.py` (8 endpoints, ~800 líneas)
- [ ] Extraer endpoints de context units
- [ ] Test local: `curl http://localhost:8000/api/v1/context-units`

### 4.3 `endpoints/legacy.py` (12 endpoints, ~1000 líneas)
- [ ] Extraer endpoints legacy (ingest, search, tasks, sources)
- [ ] Marcar como deprecated en docstrings
- [ ] Test local: `curl http://localhost:8000/sources`

---

## Fase 5: Módulos complejos (mayor riesgo)

### 5.1 `endpoints/process.py` (7 endpoints, ~600 líneas)
- [ ] Extraer endpoints de procesamiento
- [ ] Test local: `curl -X POST http://localhost:8000/process/analyze`

### 5.2 `endpoints/articles.py` (10 endpoints + helpers, ~1300 líneas)
- [ ] Extraer endpoints de artículos
- [ ] **INCLUIR**: `publish_to_platforms()`, `_add_article_footer()`, `calculate_optimal_schedule_time()`
- [ ] Test local completo:
  - `curl http://localhost:8000/api/v1/articles`
  - `curl -X POST http://localhost:8000/api/v1/articles/{id}/publish`

---

## Fase 6: Limpieza final

### 6.1 server.py final (~200 líneas)
- [ ] Solo: imports, app creation, middleware, router includes
- [ ] Verificar que no queda código muerto

### 6.2 Tests de integración
- [ ] Test completo de flujo: crear artículo → publicar
- [ ] Test OAuth flows
- [ ] Test búsqueda semántica

---

## Plantilla de cada módulo

```python
"""Endpoints de [NOMBRE]."""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, Optional, List

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_auth_context, get_company_id_from_auth

logger = get_logger("api.[nombre]")
router = APIRouter(prefix="/api/v1/[nombre]", tags=["[nombre]"])


@router.get("/")
async def list_items(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """List items."""
    # ... código ...
```

---

## server.py final

```python
"""Semantika API Server."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils.logger import get_logger
from endpoints import (
    auth,
    oauth_twitter,
    oauth_linkedin,
    oauth_facebook,
    legacy,
    process,
    context_units,
    articles,
    images,
    tts,
    companies,
    publication_targets,
)

logger = get_logger("api")

app = FastAPI(
    title="Semantika API",
    description="Semantic data pipeline API",
    version="2.0.0"
)

# CORS
app.add_middleware(CORSMiddleware, ...)

# Include routers
app.include_router(auth.router)
app.include_router(oauth_twitter.router)
app.include_router(oauth_linkedin.router)
app.include_router(oauth_facebook.router)
app.include_router(legacy.router)
app.include_router(process.router)
app.include_router(context_units.router)
app.include_router(articles.router)
app.include_router(images.router)
app.include_router(tts.router)
app.include_router(companies.router)
app.include_router(publication_targets.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "Semantika API"}
```

---

## Comandos de test local

```bash
# Levantar servidor local
cd /Users/igor/Documents/semantika
python -m uvicorn server:app --reload --port 8000

# Test básico
curl http://localhost:8000/health

# Test con auth (usar API key de dev)
curl -H "X-API-Key: sk-xxx" http://localhost:8000/api/v1/articles
```

---

## Rollback

Si algo falla:
```bash
git checkout checkpoint-before-refactor-20260116-194828
git checkout -b main-recovered
git branch -D main
git branch -m main
git push -f origin main
```

---

## Orden de ejecución recomendado

1. ✅ Checkpoint creado
2. ⏳ Fase 0: Crear estructura + auth_dependencies + helpers
3. ⏳ Fase 1: TTS → Companies → Publication Targets
4. ⏳ Fase 2: OAuth (Twitter → LinkedIn → Facebook)
5. ⏳ Fase 3: Auth
6. ⏳ Fase 4: Images → Context Units → Legacy
7. ⏳ Fase 5: Process → Articles
8. ⏳ Fase 6: Limpieza + tests integración
9. ⏳ Deploy a producción

**Estimación**: ~2-3 horas de trabajo efectivo
