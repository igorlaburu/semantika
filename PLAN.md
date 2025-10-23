# Plan de Ejecución: semantika

## Resumen Ejecutivo

Desarrollo incremental en **5 fases** con validación al final de cada una. Cada fase produce un sistema funcional y desplegable.

**Duración estimada:** 3-4 semanas
**Validación:** Testing manual + deploy local antes de pasar a siguiente fase

---

## FASE 1: Infraestructura Base (Días 1-2)

### Objetivo
Sistema Docker funcional con logging y configuración centralizada.

### Tareas
1. ✅ `.env.example` - Variables de entorno
2. ✅ `.gitignore` - Exclusiones
3. ✅ `CLAUDE.md` - Guía de desarrollo
4. ✅ `requirements.md` - Arquitectura completa
5. [ ] `requirements.txt` - Dependencias Python
6. [ ] `Dockerfile` - Imagen base Python
7. [ ] `docker-compose.yml` - Orquestación servicios
8. [ ] `utils/logger.py` - Logger JSON estructurado
9. [ ] `utils/config.py` - Configuración Pydantic

### Entregables
- ✅ Docker Compose funcional (api + qdrant + dozzle)
- ✅ Logging JSON en stdout
- ✅ Configuración desde .env

### Validación FASE 1
```bash
# 1. Build exitoso
docker-compose build

# 2. Servicios arrancan
docker-compose up -d
docker-compose ps  # Todos "Up"

# 3. Logs visibles
curl http://localhost:8081  # Dozzle OK

# 4. API responde
curl http://localhost:8000/health
# Esperado: {"status": "ok", "timestamp": "..."}

# 5. Qdrant accesible
curl http://localhost:6333/collections
# Esperado: {"result": {"collections": []}}
```

**CRITERIO DE PASO:** Todos los servicios UP, API responde, logs visibles en Dozzle.

---

## FASE 2: Persistencia y Autenticación (Días 3-5)

### Objetivo
Conectar Supabase, crear esquemas SQL, implementar autenticación por API Key.

### Tareas
1. [ ] `sql/schema.sql` - Tablas: clients, tasks, api_credentials
2. [ ] `sql/seed.sql` - Datos de prueba (1 cliente, 2 tareas)
3. [ ] `utils/supabase_client.py` - Cliente Supabase
4. [ ] `utils/qdrant_client.py` - Cliente Qdrant + crear colección
5. [ ] `server.py` (v1) - FastAPI básico
   - Middleware autenticación (X-API-Key → client_id)
   - Endpoint `GET /health`
   - Endpoint `GET /me` (info del cliente)
6. [ ] `cli.py` (v1) - Comandos básicos
   - `add-client --name "X"`
   - `list-clients`
   - `generate-api-key --client-id "uuid"`

### Entregables
- ✅ Tablas Supabase creadas
- ✅ Cliente de prueba en DB
- ✅ API autentica por API Key
- ✅ CLI funcional

### Validación FASE 2
```bash
# 1. Crear cliente de prueba
docker exec semantika-api python cli.py add-client --name "Test Client"
# Esperado: Client created. API Key: sk-test-xxxxx

# 2. Probar autenticación
curl -H "X-API-Key: sk-test-xxxxx" http://localhost:8000/me
# Esperado: {"client_id": "uuid", "client_name": "Test Client"}

# 3. Sin API Key → 401
curl http://localhost:8000/me
# Esperado: {"detail": "Missing API Key"}

# 4. API Key inválida → 403
curl -H "X-API-Key: invalid" http://localhost:8000/me
# Esperado: {"detail": "Invalid API Key"}

# 5. Colección Qdrant creada
curl http://localhost:6333/collections/semantika_prod
# Esperado: {"result": {"name": "semantika_prod", ...}}
```

**CRITERIO DE PASO:** Autenticación funciona, cliente en DB, colección Qdrant existe.

---

## FASE 3: Ingesta Manual (Días 6-9)

### Objetivo
Implementar pipeline completo de ingesta con guardrails y desduplicación.

### Tareas
1. [ ] `utils/openrouter_client.py` - Cliente OpenRouter
2. [ ] `core_ingest.py` - Motor de ingesta
   - Guardrail PII (detección + anonimización)
   - Guardrail Copyright (detección + rechazo)
   - Desduplicación por similitud
   - Chunking (RecursiveCharacterTextSplitter)
   - Carga a Qdrant con metadatos
3. [ ] `server.py` (v2) - Añadir endpoints:
   - `POST /ingest/text` (ingesta manual)
   - `GET /search?query=X` (búsqueda semántica)
4. [ ] Tests manuales con datos de ejemplo

### Entregables
- ✅ Ingesta manual funcional
- ✅ Guardrails activos (PII + Copyright)
- ✅ Desduplicación por embedding
- ✅ Búsqueda semántica con filtro client_id

### Validación FASE 3
```bash
# 1. Ingerir texto manual
curl -X POST http://localhost:8000/ingest/text \
  -H "X-API-Key: sk-test-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "La inteligencia artificial está transformando la industria.",
    "title": "IA en la industria",
    "metadata": {"source": "manual", "category": "tech"}
  }'
# Esperado: {"status": "ok", "documents_added": 1}

# 2. Ingerir duplicado → rechazado
curl -X POST http://localhost:8000/ingest/text \
  -H "X-API-Key: sk-test-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "La inteligencia artificial está transformando la industria.",
    "title": "IA en la industria",
    "metadata": {"source": "manual"}
  }'
# Esperado: {"status": "ok", "documents_added": 0, "duplicates": 1}

# 3. Ingerir con PII → anonimizado
curl -X POST http://localhost:8000/ingest/text \
  -H "X-API-Key: sk-test-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Contacta a Juan Pérez en juan.perez@example.com o al 555-1234.",
    "title": "Contacto"
  }'
# Esperado: Log WARN con "pii_anonymized"
# Verificar en Qdrant que email y teléfono están redactados

# 4. Buscar
curl "http://localhost:8000/search?query=inteligencia+artificial&k=3" \
  -H "X-API-Key: sk-test-xxxxx"
# Esperado: Array con documentos, solo del client_id del test

# 5. Verificar aislamiento multi-tenant
# Crear segundo cliente, ingestar, buscar con API Key 1 → no ve datos de cliente 2
```

**CRITERIO DE PASO:** Ingesta funciona, guardrails activos, desduplicación OK, búsqueda aislada por cliente.

---

## FASE 4: Conectores de Fuentes (Días 10-14)

### Objetivo
Implementar scrapers web, Twitter, APIs externas y audio.

### Tareas
1. [ ] `sources/__init__.py`
2. [ ] `sources/web_scraper.py`
   - BeautifulSoup para parsear HTML
   - Verificar robots.txt
   - Extraer múltiples unidades con LLM
   - Lista negra/blanca de dominios
3. [ ] `sources/twitter_scraper.py`
   - Integración scraper.tech API
   - Buscar tweets por query
   - Normalizar a Document
4. [ ] `sources/api_connectors.py`
   - Conectores genéricos (EFE, Reuters, WordPress)
   - Configurables por cliente desde api_credentials
5. [ ] `sources/audio_transcriber.py`
   - Whisper local (opcional)
   - Transcribir → ingestar
6. [ ] `server.py` (v3) - Añadir endpoints:
   - `POST /ingest/url` (scrapear una URL)
   - `POST /ingest/twitter` (buscar tweets)
   - `POST /ingest/audio` (subir archivo de audio)

### Entregables
- ✅ Scraper web con LLM funcional
- ✅ Integración Twitter (scraper.tech)
- ✅ Conector API genérico
- ✅ Transcripción de audio (opcional)

### Validación FASE 4
```bash
# 1. Scrapear URL
curl -X POST http://localhost:8000/ingest/url \
  -H "X-API-Key: sk-test-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/blog/article",
    "extract_multiple": true
  }'
# Esperado: {"status": "ok", "documents_added": N}
# Verificar en logs: robots.txt checked, LLM extraction

# 2. Scrapear URL con robots.txt bloqueado → rechazado
curl -X POST http://localhost:8000/ingest/url \
  -H "X-API-Key: sk-test-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://blocked-site.com/page"}'
# Esperado: {"detail": "Robots.txt disallows scraping"}

# 3. Twitter search
curl -X POST http://localhost:8000/ingest/twitter \
  -H "X-API-Key: sk-test-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "inteligencia artificial",
    "max_results": 10
  }'
# Esperado: {"status": "ok", "documents_added": M}

# 4. Audio (si implementado)
curl -X POST http://localhost:8000/ingest/audio \
  -H "X-API-Key: sk-test-xxxxx" \
  -F "file=@test.mp3"
# Esperado: {"status": "ok", "transcription": "...", "documents_added": 1}

# 5. Buscar contenido de fuentes mixtas
curl "http://localhost:8000/search?query=IA&source=web" \
  -H "X-API-Key: sk-test-xxxxx"
# Esperado: Solo documentos source=web
```

**CRITERIO DE PASO:** Todos los conectores funcionan, robots.txt respetado, datos normalizados correctamente.

---

## FASE 5: Scheduler y Agregación (Días 15-18)

### Objetivo
Automatizar ingesta periódica y añadir endpoint de agregación con LLM.

### Tareas
1. [ ] `scheduler.py` - APScheduler
   - Leer tabla `tasks` de Supabase al arranque
   - Crear jobs dinámicos por cada tarea
   - Ejecutar ingesta según frecuencia
   - Job diario de limpieza TTL
2. [ ] `cli.py` (v2) - Añadir comandos:
   - `add-task --client-id X --type web_llm --target URL --freq 60`
   - `list-tasks --client-id X`
   - `delete-task --task-id X`
3. [ ] `server.py` (v4) - Añadir endpoint:
   - `GET /aggregate?query=X&threshold=0.7`
     - Buscar documentos
     - Filtrar por similitud
     - Concatenar textos
     - Generar resumen con LLM
4. [ ] Implementar TTL cleanup
5. [ ] Testing de scheduler (añadir tarea, esperar ejecución, verificar logs)

### Entregables
- ✅ Scheduler ejecutando tareas periódicas
- ✅ CLI para gestionar tareas
- ✅ Endpoint de agregación funcional
- ✅ Limpieza TTL automática

### Validación FASE 5
```bash
# 1. Añadir tarea programada
docker exec semantika-api python cli.py add-task \
  --client-id "uuid-test" \
  --type "web_llm" \
  --target "https://example.com/rss" \
  --freq 15
# Esperado: Task created: uuid-task-xxx

# 2. Verificar que scheduler la carga
docker-compose logs semantika-scheduler | grep "job_added"
# Esperado: {"action": "job_added", "task_id": "uuid-task-xxx", "frequency_min": 15}

# 3. Esperar 15 min, verificar ejecución
docker-compose logs semantika-scheduler | grep "ingest_start"
# Esperado: {"action": "ingest_start", "task_id": "uuid-task-xxx"}

# 4. Probar agregación
curl "http://localhost:8000/aggregate?query=inteligencia+artificial&threshold=0.7&k=10" \
  -H "X-API-Key: sk-test-xxxxx"
# Esperado: {"summary": "Texto agregado por LLM...", "sources_count": N}

# 5. Verificar TTL cleanup
# Insertar documento con loaded_at antiguo (simulado)
# Ejecutar manualmente: docker exec semantika-scheduler python -c "from scheduler import cleanup_ttl; cleanup_ttl()"
# Verificar en logs: {"action": "ttl_cleanup", "deleted_count": M}

# 6. Listar tareas
docker exec semantika-api python cli.py list-tasks --client-id "uuid-test"
# Esperado: Lista con tarea creada
```

**CRITERIO DE PASO:** Scheduler ejecuta tareas automáticamente, agregación genera resúmenes coherentes, TTL limpia datos antiguos.

---

## FASE 6: CI/CD y Documentación (Días 19-21)

### Objetivo
Automatizar despliegue y completar documentación.

### Tareas
1. [ ] `.github/workflows/deploy.yml` - GitHub Actions
   - Trigger en push a main
   - SSH al VPS
   - git pull + docker-compose up
2. [ ] `README.md` - Documentación usuario final
   - Quick start
   - Configuración
   - Endpoints API
   - Ejemplos de uso
3. [ ] Testing en VPS real
4. [ ] Configurar GitHub Secrets (VPS_HOST, VPS_SSH_KEY, etc.)
5. [ ] Primera deploy automática

### Entregables
- ✅ README.md completo
- ✅ GitHub Actions funcional
- ✅ Deploy automático al VPS

### Validación FASE 6
```bash
# 1. Push a main dispara workflow
git push origin main
# Ir a: https://github.com/igorlaburu/semantika/actions
# Esperado: Workflow "Deploy to VPS" running → success

# 2. Verificar en VPS
ssh usuario@VPS
docker ps  # semantika-api, scheduler, qdrant, dozzle UP
curl http://localhost:8000/health
# Esperado: {"status": "ok"}

# 3. Test desde exterior (si puerto expuesto)
curl http://VPS_IP:8000/health
# Esperado: {"status": "ok"}

# 4. README completo
# Verificar que contiene: instalación, ejemplos, troubleshooting

# 5. Rollback test
# Hacer un push que rompa algo
git push origin main
# Verificar que workflow falla pero servicios antiguos siguen UP
```

**CRITERIO DE PASO:** Deploy automático funciona, servicios UP en VPS, README claro.

---

## FASE 7: Testing y Refinamiento (Días 22-25)

### Objetivo
Testing exhaustivo, manejo de errores, optimizaciones.

### Tareas
1. [ ] Testing de casos límite:
   - Ingesta masiva (1000+ documentos)
   - API Key revocada
   - Supabase caído
   - Qdrant caído
   - LLM timeout
   - Documentos muy largos (>100KB)
2. [ ] Implementar rate limiting (opcional)
3. [ ] Optimizar embeddings (batch processing)
4. [ ] Documentar troubleshooting común
5. [ ] Crear colección de Postman/Insomnia para testing

### Entregables
- ✅ Sistema robusto ante fallos
- ✅ Manejo de errores completo
- ✅ Colección API para testing
- ✅ Guía de troubleshooting

### Validación FASE 7
```bash
# 1. Stress test
for i in {1..100}; do
  curl -X POST http://localhost:8000/ingest/text \
    -H "X-API-Key: sk-test-xxxxx" \
    -H "Content-Type: application/json" \
    -d "{\"text\": \"Test document $i\", \"title\": \"Doc $i\"}" &
done
wait
# Verificar: todos exitosos, sin errores en logs, Qdrant tiene 100 docs

# 2. Simular caída de Qdrant
docker stop qdrant
curl http://localhost:8000/search?query=test -H "X-API-Key: sk-test-xxxxx"
# Esperado: {"detail": "Vector store unavailable"}
docker start qdrant

# 3. API Key inválida después de borrar cliente
docker exec semantika-api python cli.py delete-client --client-id "uuid-test"
curl http://localhost:8000/me -H "X-API-Key: sk-test-xxxxx"
# Esperado: {"detail": "Invalid API Key"}

# 4. Documento muy largo
curl -X POST http://localhost:8000/ingest/text \
  -H "X-API-Key: sk-valid-xxx" \
  --data-binary "@large-doc.txt"  # 500KB
# Esperado: {"status": "ok", "documents_added": N, "chunks": M}

# 5. Verificar logs estructurados
docker-compose logs --tail=100 | jq .
# Esperado: Todos los logs son JSON válido
```

**CRITERIO DE PASO:** Sistema estable bajo carga, errores manejados gracefully, logs útiles.

---

## Resumen de Validaciones

| Fase | Validación Principal | Tiempo |
|------|---------------------|--------|
| 1 | Docker Compose UP, API /health responde | 1h |
| 2 | Autenticación funciona, cliente en DB | 2h |
| 3 | Ingesta + guardrails + búsqueda OK | 3h |
| 4 | Todos los conectores funcionan | 4h |
| 5 | Scheduler ejecuta, agregación OK | 3h |
| 6 | Deploy automático al VPS funciona | 2h |
| 7 | Stress test pasa, errores manejados | 4h |

**Total validación:** ~19 horas

---

## Checklist Final

Antes de considerar el proyecto "listo para producción":

### Funcionalidad
- [ ] Ingesta manual de texto
- [ ] Scraper web con LLM
- [ ] Scraper Twitter (scraper.tech)
- [ ] Conectores API (al menos 1)
- [ ] Transcripción audio (opcional)
- [ ] Búsqueda semántica
- [ ] Agregación con LLM
- [ ] Scheduler de tareas
- [ ] TTL cleanup automático

### Seguridad
- [ ] Autenticación por API Key
- [ ] Aislamiento multi-tenant estricto
- [ ] PII anonimizado
- [ ] Copyright detectado
- [ ] Robots.txt respetado
- [ ] .env no commiteado
- [ ] Credenciales en Supabase (no en código)

### Infraestructura
- [ ] Docker Compose funcional
- [ ] Qdrant persistente
- [ ] Logs JSON estructurados
- [ ] Dozzle accesible
- [ ] GitHub Actions deploy automático

### Documentación
- [ ] README.md completo
- [ ] CLAUDE.md actualizado
- [ ] requirements.md preciso
- [ ] .env.example completo
- [ ] Ejemplos de uso en docs

### Testing
- [ ] Ingesta manual validada
- [ ] Scrapers validados
- [ ] Búsqueda validada
- [ ] Scheduler validado
- [ ] Deploy automático validado
- [ ] Stress test pasado
- [ ] Manejo de errores validado

---

## Próximos Pasos (Post-MVP)

Funcionalidades para versiones futuras:

1. **Webhooks salientes**: Notificar a clientes cuando hay nuevos documentos relevantes
2. **Dashboard web**: UI para gestionar clientes/tareas sin CLI
3. **Métricas**: Prometheus + Grafana para monitoreo
4. **Cache**: Redis para búsquedas frecuentes
5. **Búsqueda híbrida avanzada**: Tuning de BM25 + dense vectors
6. **Conectores adicionales**: Google Drive, Dropbox, Slack
7. **Fine-tuning**: Embeddings customizados por cliente
8. **Multi-modelo**: Diferentes LLMs según tipo de tarea
9. **Backup automático**: Qdrant snapshots a S3
10. **Rate limiting**: Por cliente/endpoint

---

## Notas de Desarrollo

- **Prioridad 1**: Funcionalidad core (Fases 1-3)
- **Prioridad 2**: Conectores (Fase 4)
- **Prioridad 3**: Automatización (Fase 5)
- **Prioridad 4**: Deploy y docs (Fase 6-7)

- **Cada fase termina con commit + push**
- **No pasar a siguiente fase sin validación exitosa**
- **Documentar problemas encontrados en TROUBLESHOOTING.md**
- **Logging abundante durante desarrollo (DEBUG), reducir en producción (INFO)**
