# semantika

**Pipeline de datos semántico multi-tenant con guardrails LLM**

Pipeline inteligente para ingesta, procesamiento y búsqueda semántica de documentos con:
- 🔒 Aislamiento multi-tenant estricto
- 🛡️ Guardrails LLM (PII, copyright, deduplicación)
- 🔍 Búsqueda semántica vectorial
- 📊 Agregación inteligente con LLM
- ⏰ Scheduler para scraping automático
- 🌐 Web scraping + Email/File monitoring + Audio transcription

---

## 🚀 Quick Start (EasyPanel)

### 1. **Servicios Externos Requeridos**

Configura estos servicios antes de desplegar:

- **[Supabase](https://supabase.com)**: Base de datos PostgreSQL
- **[Qdrant Cloud](https://cloud.qdrant.io)**: Vector database
- **[OpenRouter](https://openrouter.ai)**: API de LLMs (Claude, GPT)

### 2. **Desplegar en EasyPanel**

Sigue la guía completa: **[DEPLOY_EASYPANEL.md](./DEPLOY_EASYPANEL.md)**

Pasos resumidos:
1. Crea proyecto en EasyPanel
2. Conecta este repo de GitHub
3. Configura variables de entorno (ver `.env.easypanel`)
4. Deploy con `docker-compose.prod.yml`
5. Verifica con `./verify-deployment.sh`

### 3. **Crear Primer Cliente**

```bash
# En EasyPanel Console (semantika-api)
python cli.py add-client --name "Mi Cliente" --email "cliente@example.com"

# Guarda el API Key generado: sk-xxxxx
```

### 4. **Probar API**

```bash
# Health check
curl https://tu-api.easypanel.app/health

# Autenticación
curl https://tu-api.easypanel.app/me \
  -H "X-API-Key: sk-xxxxx"

# Ingestar texto
curl -X POST https://tu-api.easypanel.app/ingest/text \
  -H "X-API-Key: sk-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Machine learning is transforming industries worldwide.",
    "title": "ML Revolution"
  }'

# Buscar
curl "https://tu-api.easypanel.app/search?query=machine%20learning&limit=5" \
  -H "X-API-Key: sk-xxxxx"
```

---

## 📚 Documentación

### Deployment
- **[Guía EasyPanel](./DEPLOY_EASYPANEL.md)** - Despliegue paso a paso
- **[Plan de Desarrollo](./PLAN.md)** - Arquitectura y fases
- **[Arquitectura Técnica](./requirements.md)** - Detalles completos

### API

- **[API Stateless](./API_STATELESS.md)** - Procesamiento sin almacenamiento (análisis, generación de artículos, guías de estilo)

### API Endpoints (con almacenamiento en Qdrant)

#### **POST /ingest/text**
Ingesta texto con guardrails automáticos.

```bash
curl -X POST https://api/ingest/text \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Contenido a ingestar...",
    "title": "Título del documento",
    "metadata": {"source": "manual", "author": "John"},
    "skip_guardrails": false
  }'
```

**Respuesta:**
```json
{
  "status": "ok",
  "documents_added": 1,
  "duplicates_skipped": 0,
  "pii_detected": false,
  "copyright_rejected": false
}
```

#### **POST /ingest/url**
Scraping web con extracción LLM.

```bash
curl -X POST https://api/ingest/url \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://techcrunch.com/ai",
    "extract_multiple": true
  }'
```

#### **GET /search**
Búsqueda semántica.

```bash
curl "https://api/search?query=artificial%20intelligence&limit=10&source=web" \
  -H "X-API-Key: sk-xxx"
```

**Respuesta:**
```json
{
  "results": [
    {
      "id": "uuid",
      "score": 0.89,
      "text": "...",
      "metadata": {"title": "...", "source": "web"}
    }
  ]
}
```

#### **GET /aggregate**
Agregación con resumen LLM.

```bash
curl "https://api/aggregate?query=machine%20learning&limit=20&threshold=0.7" \
  -H "X-API-Key: sk-xxx"
```

**Respuesta:**
```json
{
  "summary": "Resumen inteligente generado por LLM...",
  "sources_count": 15,
  "documents": [...]
}
```

---

## 🛠️ CLI Commands

Todos los comandos se ejecutan en la Console de EasyPanel (servicio `semantika-api`):

```bash
# Gestión de clientes
python cli.py add-client --name "Cliente" --email "email@example.com"
python cli.py list-clients

# Gestión de tareas
python cli.py add-task \
  --client-id "uuid" \
  --type web_llm \
  --target "https://news.site.com/tech" \
  --freq 60

python cli.py list-tasks
python cli.py list-tasks --client-id "uuid"
python cli.py delete-task --task-id "uuid"

# Información Qdrant
python cli.py qdrant-info
```

---

## 🏗️ Arquitectura

```
┌─────────────┐
│   Cliente   │
└──────┬──────┘
       │ X-API-Key
       ▼
┌─────────────────────────┐
│   semantika-api (8000)  │  ◄── FastAPI + Autenticación
│   - /ingest/text        │
│   - /ingest/url         │
│   - /search             │
│   - /aggregate          │
└───────┬─────────────────┘
        │
        ├──► Supabase (PostgreSQL)
        │    - clients, tasks, credentials
        │
        ├──► Qdrant Cloud (Vector DB)
        │    - Embeddings fastembed (384d)
        │    - Aislamiento por client_id
        │
        └──► OpenRouter (LLM)
             - Claude 3.5 Sonnet (guardrails)
             - GPT-4o-mini (fast tasks)

┌─────────────────────────┐
│ semantika-scheduler     │  ◄── APScheduler
│ - Ejecuta tareas        │
│ - TTL cleanup (03:00)   │
└─────────────────────────┘

┌─────────────────────────┐
│ dozzle (8081)           │  ◄── Log viewer
│ - JSON structured logs  │
└─────────────────────────┘
```

---

## 🔒 Seguridad

### Guardrails Implementados

1. **PII Detection & Anonymization**
   - Detecta: nombres, emails, teléfonos, DNI
   - Reemplaza con `[NAME]`, `[EMAIL]`, `[PHONE]`
   - Usa Claude 3.5 Sonnet

2. **Copyright Detection**
   - Detecta contenido protegido por copyright
   - Rechaza si confidence > 70%

3. **Semantic Deduplication**
   - Threshold: 0.98 similaridad coseno
   - Evita documentos duplicados

4. **Robots.txt Compliance**
   - Web scraper respeta robots.txt
   - User-agent: `semantika-bot/1.0`

### Multi-tenancy

- Aislamiento estricto por `client_id`
- API Keys únicos por cliente (64 chars hex)
- Filtros Qdrant con payload index
- Row-Level Security en Supabase (opcional)

---

## 📊 Monitoreo

### Logs
- **Dozzle**: `https://logs.tudominio.com` (puerto 8081)
- JSON structured logs
- Filtro por servicio: `name=semantika`

### Métricas
- **Supabase**: Dashboard de tablas
- **Qdrant Cloud**: Dashboard de cluster
  - Vectores almacenados
  - Queries/segundo
  - Storage usado
- **OpenRouter**: Dashboard de usage y costos

---

## 🧪 Testing

### Verificación Automática
```bash
./verify-deployment.sh https://tu-api.easypanel.app sk-xxxxx
```

### Tests Manuales
Ver **[PLAN.md](./PLAN.md)** secciones de validación de cada fase.

---

## 🔧 Configuración Avanzada

### Habilitar File Monitor

```bash
# En EasyPanel Environment Variables
FILE_MONITOR_ENABLED=true
FILE_MONITOR_WATCH_DIR=/app/data/watch
FILE_MONITOR_INTERVAL=30

# Los archivos deben nombrarse: {client_id}_filename.txt
# Ejemplo: a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11_report.pdf
```

### Habilitar Email Monitor

```bash
EMAIL_MONITOR_ENABLED=true
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_IMAP_PORT=993
EMAIL_ADDRESS=bot@tudominio.com
EMAIL_PASSWORD=app-password-aqui
EMAIL_MONITOR_INTERVAL=60

# Los emails deben incluir client_id en subject:
# Subject: [a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11] Monthly Report
```

### Ajustar TTL

```bash
DATA_TTL_DAYS=60  # Borrar datos > 60 días (default: 30)
```

---

## 🐛 Troubleshooting

### Error: "Invalid API Key"
- Verifica que el API Key existe en Supabase → `clients` table
- Comprueba que `is_active = true`
- Revisa el header: `X-API-Key: sk-xxxxx`

### Error: "Vector store unavailable"
- Verifica conectividad a Qdrant Cloud
- Comprueba `QDRANT_URL` y `QDRANT_API_KEY`
- Revisa logs: `docker logs semantika-api`

### Scheduler no ejecuta tareas
- Lista tareas: `python cli.py list-tasks`
- Verifica `is_active = true` en Supabase
- Revisa logs: `docker logs semantika-scheduler`
- Reinicia scheduler en EasyPanel

### OpenRouter timeout
- Verifica créditos en [openrouter.ai](https://openrouter.ai)
- Comprueba `OPENROUTER_API_KEY`
- Revisa rate limits del modelo

---

## 💰 Costos Estimados

- **Supabase**: Free tier (hasta 500MB, 2GB transferencia)
- **Qdrant Cloud**: $25/mes (1GB cluster)
- **OpenRouter**: Variable
  - Claude 3.5 Sonnet: ~$3 por 1M tokens input
  - GPT-4o-mini: ~$0.15 por 1M tokens input
  - Estimado: $10-50/mes uso medio
- **EasyPanel**: Según tu plan de hosting ($5-50/mes)

**Total**: $40-125/mes para uso medio

---

## 🚧 Roadmap

### Implementado (v1.0)
- ✅ Ingesta manual (texto, URL)
- ✅ Guardrails LLM (PII, copyright, dedup)
- ✅ Búsqueda semántica
- ✅ Agregación con LLM
- ✅ Scheduler de tareas
- ✅ TTL cleanup automático
- ✅ Web scraping
- ✅ File/Email monitoring
- ✅ Audio transcription (Whisper)

### Pendiente (v2.0+)
- [ ] Twitter scraping (scraper.tech)
- [ ] API connectors (EFE, Reuters, WordPress)
- [ ] Dashboard web UI
- [ ] Webhooks salientes
- [ ] Métricas (Prometheus + Grafana)
- [ ] Cache (Redis)
- [ ] Rate limiting por cliente
- [ ] Fine-tuning de embeddings

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
- **Documentación**: Ver archivos `*.md` en este repo
- **Logs**: Revisa Dozzle primero (`https://logs.tudominio.com`)

---

**Built with ❤️ using FastAPI, Qdrant, Supabase & Claude**
