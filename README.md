# semantika

**Pipeline semántico multi-tenant para agregación y análisis de noticias en español/euskera**

Sistema inteligente para ingesta, procesamiento y búsqueda híbrida de contenido con:
- 🔒 Multi-tenancy seguro con RLS (Row-Level Security)
- 🔍 Búsqueda híbrida (semantic + keyword) con query expansion
- 🌊 Pool compartido con discovery automático de fuentes
- 🤖 Enriquecimiento LLM (Claude 3.5 Sonnet, Groq Llama 3.3)
- 📊 Embeddings locales FastEmbed (768d multilingual)
- ⏰ Scheduler para scraping e ingesta automática
- 🌐 Web scraping + Perplexity + Email monitoring

---

## 🚀 Quick Start

### 1. **Servicios Externos Requeridos**

- **[Supabase](https://supabase.com)**: PostgreSQL + pgvector (embeddings)
- **[OpenRouter](https://openrouter.ai)**: Claude 3.5 Sonnet (enriquecimiento)
- **[Groq](https://console.groq.com)**: Llama 3.3 70B (gratis, análisis rápido)

### 2. **Deploy en VPS**

```bash
# Clonar repositorio
git clone https://github.com/igorlaburu/semantika.git
cd semantika

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales

# Levantar servicios
docker-compose up -d --build

# Verificar
curl http://localhost:8000/health
```

**Deploy automático**: Push a `main` → GitHub Actions despliega a VPS (ver [AUTO_DEPLOY_GUIDE.md](./AUTO_DEPLOY_GUIDE.md))

### 3. **Crear Primera Organización**

```bash
# Onboarding automático vía API
curl -X POST https://api.ekimen.ai/onboard/company \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "Mi Empresa",
    "company_cif": "B12345678",
    "email": "admin@miempresa.com",
    "password": "contraseña-segura",
    "full_name": "Admin Usuario"
  }'

# Respuesta incluye JWT token para autenticación
```

### 4. **Probar API**

```bash
# Health check
curl https://api.ekimen.ai/health

# Login
curl -X POST https://api.ekimen.ai/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@miempresa.com", "password": "contraseña-segura"}'

# Guardar JWT token
export JWT="eyJhbGc..."

# Buscar en contexto privado + pool
curl -X POST https://api.ekimen.ai/api/v1/context-units/search-vector \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "alcalde bilbao",
    "limit": 10,
    "threshold": 0.18,
    "filters": {"include_pool": true}
  }'
```

---

## 📚 Arquitectura

### Sistema Unificado PostgreSQL + pgvector

**Base de datos única** (Supabase):
- ✅ Config + vectores en una sola BD
- ✅ RLS policies para multi-tenancy seguro
- ✅ Búsqueda híbrida (semantic + keyword) en una query
- ✅ Joins nativos (context_units + sources + companies)

**Tablas principales**:
- `press_context_units`: Noticias procesadas (company-specific + pool)
- `web_context_units`: Monitoring web (subvenciones, formularios)
- `sources`: Configuración de fuentes de scraping
- `companies`, `users`, `organizations`: Multi-tenancy

### Pool Compartido

**UUID Pool**: `99999999-9999-9999-9999-999999999999`

**Flujo automático**:
1. **Discovery** (cada 3 días): GNews API → LLM Groq identifica fuentes originales → Extrae index URLs → Guarda en `discovered_sources`
2. **Ingesta** (cada hora): Scrape fuentes descubiertas → Enriquece con LLM → Guarda en `press_context_units` (pool)
3. **Acceso**: Todos los clientes buscan con `include_pool=true`

### Búsqueda Híbrida

**Endpoint**: `POST /api/v1/context-units/search-vector`

**3 capas**:
1. **Query expansion**: Cache (1h) + diccionario local (español/euskera) + LLM Groq (solo queries cortos)
2. **Semantic search**: pgvector cosine similarity (FastEmbed 768d, threshold 0.18)
3. **Keyword search**: PostgreSQL full-text search (Spanish config)

**Re-ranking**: `0.7 * semantic + 0.3 * keyword`

**Performance**:
- Latencia: 150-200ms (con cache) / 300-400ms (sin cache)
- Costo: $0 (Groq gratis, FastEmbed local)

### Embeddings FastEmbed

**Modelo**: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
- Dimensiones: 768
- Idiomas: 50+ (español, euskera, catalán, gallego, inglés...)
- Velocidad: ~150ms por query (CPU)
- Costo: $0 (100% local, sin API)

---

## 🔌 API Endpoints

### Autenticación

#### `POST /onboard/company`
Crear nueva organización + usuario admin.

```bash
curl -X POST https://api.ekimen.ai/onboard/company \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "Empresa SL",
    "company_cif": "B12345678",
    "email": "admin@empresa.com",
    "password": "pass",
    "full_name": "Admin User"
  }'
```

**Respuesta**: JWT token + company_id + user_id

#### `POST /auth/login`
Login con email + password.

```bash
curl -X POST https://api.ekimen.ai/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@empresa.com", "password": "pass"}'
```

**Respuesta**: JWT token (válido 7 días)

### Context Units (Noticias)

#### `GET /api/v1/context-units`
Listar context units con filtros.

```bash
curl "https://api.ekimen.ai/api/v1/context-units?limit=20&timePeriod=24h&include_pool=true" \
  -H "Authorization: Bearer $JWT"
```

**Parámetros**:
- `limit`: Max resultados (1-100, default 20)
- `offset`: Paginación (default 0)
- `timePeriod`: `24h`, `week`, `month`, `all`
- `category`: Filtro por categoría
- `include_pool`: Incluir contenido pool (default false)

#### `POST /api/v1/context-units/search-vector`
Búsqueda híbrida (semantic + keyword).

```bash
curl -X POST https://api.ekimen.ai/api/v1/context-units/search-vector \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "lehendakari reunión empresarios",
    "limit": 10,
    "threshold": 0.18,
    "filters": {"include_pool": true, "category": "política"}
  }'
```

**Respuesta**:
```json
{
  "query": "lehendakari reunión empresarios",
  "query_expansion": {
    "original": "lehendakari reunión empresarios",
    "expanded_terms": ["lehendakari", "presidente", "lehendakaritza", "reunión", "bilera", "empresarios"],
    "terms_count": 6
  },
  "results": [{
    "id": "uuid",
    "title": "El Lehendakari se reúne...",
    "summary": "...",
    "semantic_score": 0.82,
    "keyword_score": 0.15,
    "combined_score": 0.62,
    "category": "política",
    "created_at": "2025-12-09T..."
  }],
  "count": 10,
  "search_method": "hybrid_semantic_keyword",
  "query_time_ms": 187
}
```

#### `GET /api/v1/context-units/{id}`
Obtener context unit por ID.

### Sources (Fuentes)

#### `GET /api/v1/sources`
Listar fuentes configuradas.

#### `POST /api/v1/sources`
Crear nueva fuente de scraping.

```bash
curl -X POST https://api.ekimen.ai/api/v1/sources \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "source_name": "Noticias Empresa",
    "source_type": "scraping",
    "config": {
      "url": "https://empresa.com/noticias",
      "frequency_minutes": 60
    }
  }'
```

### Processing (Workflows)

#### `POST /process/micro-edit`
Micro-edición de texto con LLM.

```bash
curl -X POST https://api.ekimen.ai/process/micro-edit \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Texto original...",
    "command": "Corrige errores ortográficos",
    "params": {"temperature": 0.3}
  }'
```

#### `POST /process/redact-news-rich`
Redacción de noticia con estructura rich.

---

## 🏗️ Arquitectura Docker

```
┌─────────────────────────┐
│  semantika-api (8000)   │  ◄── FastAPI + Auth JWT
│  - /api/v1/*            │
│  - /process/*           │
│  - /auth/*              │
└───────┬─────────────────┘
        │
        ├──► Supabase PostgreSQL + pgvector
        │    - press_context_units (768d embeddings)
        │    - companies, users, sources
        │    - RLS policies multi-tenant
        │
        ├──► FastEmbed Local (768d)
        │    - paraphrase-multilingual-mpnet-base-v2
        │    - ~150ms per query
        │
        ├──► OpenRouter
        │    - Claude 3.5 Sonnet (enriquecimiento)
        │
        └──► Groq (gratis)
             - Llama 3.3 70B (análisis, query expansion)

┌─────────────────────────┐
│ semantika-scheduler     │  ◄── APScheduler
│ - Discovery (3 días)    │
│ - Ingesta Pool (1h)     │
│ - Scraping sources      │
└─────────────────────────┘
```

---

## 🔒 Seguridad

### Multi-tenancy con RLS

**Row-Level Security** en Supabase:
```sql
-- Context units: Solo acceso a propios + pool
CREATE POLICY select_own_company_context_units 
ON press_context_units FOR SELECT
USING (
  company_id = current_user_company_id() 
  OR company_id = '99999999-9999-9999-9999-999999999999'::uuid
);
```

### Guardrails de Contenido

1. **Quality gate**: Mínimo 2 atomic statements
2. **Deduplicación semántica**: Threshold 0.98
3. **Robots.txt**: Web scraper respeta directivas
4. **Título genérico**: LLM extrae título real si HTML es genérico

### Autenticación

- **JWT tokens** (Supabase Auth) - 7 días validez
- **Refresh tokens** - Rotación automática
- **RLS policies** - Aislamiento por company_id

---

## 📊 Monitoreo

### Logs
```bash
# Ver logs API
docker logs -f ekimen_semantika-semantika-api-1

# Ver logs Scheduler
docker logs -f ekimen_semantika-semantika-scheduler-1

# Logs JSON estructurados
{"level": "INFO", "timestamp": "...", "service": "hybrid_search", "query": "..."}
```

### Métricas

- **Supabase Dashboard**: Queries, storage, usuarios
- **OpenRouter Dashboard**: Usage LLM + costos
- **Groq Console**: Requests (gratis, sin coste)

---

## 💰 Costos Estimados

- **Supabase**: $25/mes (Pro plan para producción)
- **OpenRouter**: $10-30/mes (Claude 3.5 Sonnet uso medio)
- **Groq**: $0 (gratis, rate limits generosos)
- **FastEmbed**: $0 (local, sin API)
- **VPS**: $10-50/mes (según recursos)

**Total**: $45-105/mes para uso medio (~1000 búsquedas/día)

---

## 🧪 Testing

```bash
# Unit tests
./run_tests.sh

# O manualmente
python3 -m pytest tests/ -v

# Con coverage
python3 -m pytest tests/ --cov=utils --cov=sources --cov-report=html
```

---

## 📝 Documentación

- **[CLAUDE.md](./CLAUDE.md)** - Guía para Claude Code (desarrollo)
- **[AUTO_DEPLOY_GUIDE.md](./AUTO_DEPLOY_GUIDE.md)** - Deploy automático GitHub Actions
- **[CLI_USAGE.md](./CLI_USAGE.md)** - Comandos CLI
- **[SECURITY.md](./SECURITY.md)** - Guía de seguridad
- **[requirements.md](./requirements.md)** - Arquitectura técnica completa

---

## 🚧 Roadmap

### ✅ Implementado (v1.0)
- ✅ PostgreSQL + pgvector unificado
- ✅ Búsqueda híbrida (semantic + keyword)
- ✅ Query expansion con cache + Groq
- ✅ FastEmbed local 768d
- ✅ Pool compartido con discovery automático
- ✅ Multi-tenancy con RLS
- ✅ Web scraping + Perplexity
- ✅ Micro-edit + redacción noticias
- ✅ Auth JWT + onboarding

### 🔜 Próximamente (v2.0)
- [ ] Frontend Dashboard (React/Vue)
- [ ] Alertas personalizadas (email/webhooks)
- [ ] Analytics y reportes
- [ ] API connectors (EFE, Reuters, WordPress)
- [ ] Cache Redis para búsquedas
- [ ] Rate limiting por company

---

## 📄 Licencia

MIT License - ver [LICENSE](./LICENSE)

---

## 🤝 Contribuir

1. Fork el repo
2. Crea branch: `git checkout -b feature/nueva-feature`
3. Commit: `git commit -m 'Add nueva feature'`
4. Push: `git push origin feature/nueva-feature`
5. Abre Pull Request

---

## 📞 Soporte

- **Issues**: [github.com/igorlaburu/semantika/issues](https://github.com/igorlaburu/semantika/issues)
- **Documentación**: Ver `*.md` en raíz
- **Logs**: `docker logs -f ekimen_semantika-semantika-api-1`

---

**Built with ❤️  using FastAPI, PostgreSQL, pgvector, FastEmbed, Claude & Groq**
