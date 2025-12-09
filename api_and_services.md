# Documentación API y Servicios - Sistema Ekimen

**Versión**: 0.2.2
**Última actualización**: 2024-12-09
**Base URL**: `https://api.ekimen.ai`

---

## Tabla de Contenidos

1. [Arquitectura del Sistema](#arquitectura-del-sistema)
2. [Autenticación](#autenticación)
3. [Gestión de Usuarios y Clientes](#gestión-de-usuarios-y-clientes)
4. [Endpoints de API](#endpoints-de-api)
5. [Servicios de Procesamiento](#servicios-de-procesamiento)
6. [Workflows y Tareas Programadas](#workflows-y-tareas-programadas)
7. [Monitores Automáticos](#monitores-automáticos)
8. [Crear Workflows Personalizados](#crear-workflows-personalizados)
9. [Configuración del Sistema](#configuración-del-sistema)
10. [Uso y Facturación](#uso-y-facturación)
11. [Sistema Pool (Discovery Automático)](#sistema-pool-discovery-automático)

---

## Arquitectura del Sistema

El sistema **ekimen** es una plataforma multi-tenant para procesamiento semántico de datos, compuesta por:

### Componentes Principales

```
┌─────────────────────────────────────────────────────────────┐
│                        FRONTEND                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Kazet (Cliente Web)                     │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS + X-API-Key
┌──────────────────────────┴──────────────────────────────────┐
│                        BACKEND                               │
│  ┌─────────────────┐  ┌──────────────────┐                 │
│  │ semantika-api   │  │ semantika-       │                 │
│  │ (FastAPI)       │  │ scheduler        │                 │
│  │ Puerto 8000     │  │ (APScheduler)    │                 │
│  └────────┬────────┘  └────────┬─────────┘                 │
│           │                     │                            │
└───────────┼─────────────────────┼────────────────────────────┘
            │                     │
    ┌───────┴───────┬─────────────┴──────┬───────────────┐
    │               │                    │               │
┌───▼────┐   ┌──────▼──────┐   ┌────────▼──────┐   ┌───▼────┐
│Supabase│   │   Qdrant    │   │  OpenRouter   │   │External│
│(Config)│   │  (Vectores) │   │    (LLMs)     │   │ APIs   │
└────────┘   └─────────────┘   └───────────────┘   └────────┘
```

### Servicios Docker

1. **semantika-api**: API REST principal (FastAPI + Uvicorn)
2. **semantika-scheduler**: Daemon para tareas programadas (APScheduler)

### Stack Tecnológico

- **Backend**: Python 3.10+, FastAPI, APScheduler
- **Base de Datos**: Supabase (PostgreSQL + pgvector)
- **Vector Store**: Qdrant Cloud
- **LLM**: OpenRouter (Claude 3.5 Sonnet, GPT-4o-mini, Groq Llama 3.3 70B)
- **Embeddings**: FastEmbed (integrado en Qdrant)
- **TTS**: Piper (es_ES-carlfm-x_low, 28MB)
- **STT**: Whisper (OpenAI)
- **Deployment**: Docker + GitHub Actions

### Arquitectura de Sources: Manual Source

**Concepto clave**: Cada company tiene una **source "Manual"** con un diseño especial:

```
source.id = company.id  // 🔑 KEY INSIGHT
```

**Propósito**:
- Unifica todo contenido manual de la company:
  - POST /context-units (texto manual)
  - POST /context-units/from-url (scraping manual)  
  - Emails procesados
  - Archivos subidos
  
**Creación**:
1. ✅ CLI onboarding - Método principal (`python cli.py create-company`)
2. ✅ Migración SQL - Backfill para companies existentes

**Ventajas**:
- No requiere búsquedas (solo usar `company_id`)
- 1 source por company (predecible)
- Simplifica lógica de endpoints

**Ver**: `sql/migrations/002_create_manual_sources.sql`

---

## Autenticación

### API Key Authentication

Todos los endpoints requieren autenticación mediante **X-API-Key** en el header:

```bash
curl -X POST https://api.semantika.es/search \
  -H "X-API-Key: sk-xxxxxxxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"query": "noticias sobre tecnología"}'
```

### Obtener tu API Key

1. **Via CLI** (administradores):
   ```bash
   docker exec -it semantika-api python cli.py add-client --name "Mi Cliente" --email "cliente@example.com"
   ```

2. **Via API** (no implementado todavía - requiere super-admin token)

### Endpoints Públicos (sin autenticación)

- `GET /health` - Health check del sistema
- `GET /` - Información básica del API
- `GET /docs` - Documentación Swagger interactiva
- `GET /redoc` - Documentación ReDoc

### Verificar tu Cliente Actual

```bash
GET /me
```

**Respuesta**:
```json
{
  "client_id": "123e4567-e89b-12d3-a456-426614174000",
  "client_name": "Mi Cliente",
  "is_active": true,
  "created_at": "2025-11-01T10:00:00Z"
}
```

---

## Gestión de Usuarios y Clientes

### CLI de Administración

El sistema incluye un CLI completo para administración. Ubicación: `cli.py`

#### 🏢 Onboarding de Company (Recomendado para admins)

**Crear company completa** con un solo comando:

```bash
python cli.py create-company \
  --name "Acme Corp" \
  --cif "B12345678" \
  --tier "pro"
```

**Qué crea automáticamente:**
1. ✅ Company record en BD
2. ✅ Client con API key (para integración API)
3. ✅ Source "Manual" (source.id = company.id) 
4. ✅ Organization por defecto

**Output:**
```
🎉 Company Onboarding Complete!
============================================================

📋 Company Details:
   ID: 00000000-0000-0000-0000-000000000001
   Name: Acme Corp
   CIF: B12345678
   Tier: pro

🔑 API Credentials:
   Client ID: abc-123-def-456
   API Key: sk-xxxxxxxxxxxxxxxxxxxxx
   ⚠️  SAVE THIS KEY - won't be shown again!

🏗️  Default Resources:
   Manual Source ID: 00000000-0000-0000-0000-000000000001
   Organization Slug: b12345678

📝 Next Steps:
   1. Create auth users: python cli.py create-auth-user ...
   2. Add sources: Use Supabase UI or API
   3. Share API key with client
```

#### 👤 Crear Usuarios Auth

**Después de crear la company**, crea usuarios para el frontend:

```bash
python cli.py create-auth-user \
  --email "usuario@acme.com" \
  --password "SecurePass123!" \
  --company-id "00000000-0000-0000-0000-000000000001" \
  --name "Usuario Acme"
```

**Output:**
```
🎉 User Created Successfully!
============================================================

📋 User Details:
   User ID: user-uuid-here
   Email: usuario@acme.com
   Password: SecurePass123!
   Company: Acme Corp

📝 Login Credentials (share with user):
   Email: usuario@acme.com
   Password: SecurePass123!
   URL: https://press.ekimen.ai
```

#### 📊 Listar Clients (Legacy)

```bash
python cli.py list-clients
```

**Output**:
```
✅ Client created successfully!
Client ID: 123e4567-e89b-12d3-a456-426614174000
Name: Nombre del Cliente
API Key: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

⚠️  Save this API key - it won't be shown again!
```

#### Listar Clientes

```bash
docker exec -it semantika-api python cli.py list-clients
```

**Output**:
```
📋 3 client(s) found:

ID                                   Name                           Active   Created
----------------------------------------------------------------------------------------------------
123e4567-e89b-12d3-a456-426614174000 Cliente A                      ✅       2025-11-01
456e7890-e89b-12d3-a456-426614174001 Cliente B                      ✅       2025-11-05
789e0123-e89b-12d3-a456-426614174002 Cliente C                      ❌       2025-11-10
```

#### Modificar Cliente (via SQL directo en Supabase)

Para modificar clientes, usar SQL en Supabase:

```sql
-- Cambiar nombre
UPDATE clients
SET client_name = 'Nuevo Nombre'
WHERE client_id = '123e4567-e89b-12d3-a456-426614174000';

-- Desactivar cliente
UPDATE clients
SET is_active = false
WHERE client_id = '123e4567-e89b-12d3-a456-426614174000';

-- Regenerar API Key (requiere hash bcrypt)
UPDATE clients
SET api_key = 'sk-nuevo-key-aqui',
    api_key_hash = crypt('sk-nuevo-key-aqui', gen_salt('bf'))
WHERE client_id = '123e4567-e89b-12d3-a456-426614174000';
```

---

## Endpoints de API

### 📊 Sistema y Estado

#### `GET /health`

Health check del sistema.

**Sin autenticación requerida**

**Respuesta**:
```json
{
  "status": "healthy",
  "service": "semantika-api",
  "version": "0.1.2",
  "timestamp": "2025-11-11T10:00:00Z"
}
```

---

#### `GET /me`

Información del cliente autenticado.

**Headers**: `X-API-Key`

**Respuesta**:
```json
{
  "client_id": "123e4567-e89b-12d3-a456-426614174000",
  "client_name": "Mi Cliente",
  "is_active": true,
  "created_at": "2025-11-01T10:00:00Z"
}
```

---

### 📥 Ingesta de Contenido

#### `POST /ingest/text`

Ingestar texto directamente al vector store.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "text": "El contenido del documento a ingestar...",
  "title": "Título del documento",
  "metadata": {
    "source": "manual",
    "category": "news"
  },
  "skip_guardrails": false
}
```

**Respuesta**:
```json
{
  "status": "success",
  "qdrant_ids": ["uuid-1", "uuid-2"],
  "chunks_created": 2
}
```

**Notas**:
- `skip_guardrails`: Si es `true`, omite validación de PII y copyright
- El texto se divide en chunks automáticamente
- Se realiza deduplicación (similitud > 0.98)

---

#### `POST /ingest/url`

Ingestar contenido desde una URL.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "url": "https://example.com/noticia",
  "extract_multiple": false,
  "skip_guardrails": false
}
```

**Parámetros**:
- `extract_multiple`: Si es `true`, extrae múltiples noticias de una página índice
- `skip_guardrails`: Omitir validación de guardrails

**Respuesta**:
```json
{
  "status": "success",
  "context_units_created": 1,
  "context_units": [
    {
      "context_unit_id": "uuid-123",
      "title": "Título extraído",
      "summary": "Resumen del contenido..."
    }
  ]
}
```

---

### 🔍 Búsqueda y Agregación

#### `GET /search`

Búsqueda semántica en el vector store.

**Headers**: `X-API-Key`

**Query Params**:
- `query` (string, requerido): Texto de búsqueda
- `limit` (int, default=5): Número de resultados
- `filters` (JSON string, opcional): Filtros adicionales

**Ejemplo**:
```bash
GET /search?query=noticias%20sobre%20IA&limit=10
```

**Respuesta**:
```json
{
  "results": [
    {
      "id": "uuid-1",
      "text": "Contenido del chunk...",
      "metadata": {
        "title": "Título del documento",
        "source": "web"
      },
      "score": 0.92
    }
  ],
  "count": 10
}
```

---

#### `GET /aggregate`

Búsqueda semántica + agregación con LLM.

**Headers**: `X-API-Key`

**Query Params**:
- `query` (string, requerido): Pregunta o tema
- `limit` (int, default=10): Chunks a recuperar
- `threshold` (float, default=0.7): Umbral de similitud

**Ejemplo**:
```bash
GET /aggregate?query=¿Cuáles%20son%20las%20últimas%20noticias%20sobre%20IA?&limit=15
```

**Respuesta**:
```json
{
  "query": "¿Cuáles son las últimas noticias sobre IA?",
  "aggregated_response": "Basándome en los documentos encontrados, las principales noticias sobre IA son...",
  "sources": [
    {
      "id": "uuid-1",
      "title": "Avances en IA generativa",
      "score": 0.89
    }
  ],
  "count": 15
}
```

---

### 📝 Context Units (Unidades de Contexto)

Las **context units** son documentos estructurados con análisis semántico completo.

#### `GET /context-units`

Listar context units del cliente.

**Headers**: `X-API-Key`

**Query Params**:
- `limit` (int, default=20): Resultados por página
- `offset` (int, default=0): Paginación

**Respuesta**:
```json
{
  "context_units": [
    {
      "context_unit_id": "uuid-123",
      "title": "Título del documento",
      "summary": "Resumen corto...",
      "content": "Contenido completo...",
      "atomic_statements": [
        {
          "text": "La Gran Recogida se celebrará el 7 y 8 de noviembre",
          "type": "fact",
          "order": 1,
          "speaker": null
        },
        {
          "text": "Necesitamos un radar móvil",
          "type": "quote",
          "order": 2,
          "speaker": "Asociación vecinal"
        }
      ],
      "enriched_statements": [
        {
          "text": "5.000 voluntarios participarán en la Gran Recogida",
          "type": "fact",
          "order": 16,
          "speaker": null
        }
      ],
      "loaded_at": "2025-11-11T10:00:00Z",
      "metadata": {}
    }
  ],
  "total": 45
}
```

**Formato Unificado de Statements**:

Tanto `atomic_statements` como `enriched_statements` usan el mismo formato JSONB:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `text` | string | Contenido del statement |
| `type` | string | `"fact"`, `"quote"`, `"context"` |
| `order` | number | Orden de aparición (secuencial) |
| `speaker` | string\|null | Atribución (para quotes) |

**Atomic vs Enriched**:
- **Atomic**: Extraídos del contenido original durante ingesta
- **Enriched**: Añadidos posteriormente via `/enrich` con búsqueda web

---

#### `POST /context-units`

Crear context unit desde texto.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "text": "Contenido del documento...",
  "title": "Título opcional"
}
```

**Respuesta**:
```json
{
  "context_unit_id": "uuid-123",
  "title": "Título generado o proporcionado",
  "summary": "Resumen generado por LLM",
  "atomic_statements": ["Statement 1", "Statement 2"],
  "loaded_at": "2025-11-11T10:00:00Z"
}
```

---

#### `POST /context-units/from-url`

Crear context unit desde URL (con workflow inteligente).

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "url": "https://prentsa.araba.eus/indice",
  "title": "Título opcional"
}
```

**Respuesta**:
```json
{
  "status": "success",
  "context_units_created": 3,
  "context_units": [
    {
      "context_unit_id": "uuid-1",
      "title": "Noticia 1",
      "summary": "Resumen..."
    }
  ]
}
```

**Nota**: Este endpoint usa el workflow de scraping inteligente que:
1. Detecta si es página índice o noticia individual
2. Extrae múltiples noticias si es índice
3. Genera análisis semántico completo

---

#### `POST /api/v1/context-units/{context_unit_id}/enrich`

Enriquecer context unit con información adicional usando búsqueda web en tiempo real.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**URL Params**: `context_unit_id` (UUID)

**Body**:
```json
{
  "enrich_type": "background"
}
```

**Tipos de enriquecimiento**:
- `"update"`: Actualizar con información reciente (busca novedades, desarrollos)
- `"background"`: Agregar contexto histórico (busca antecedentes, historia previa)
- `"verify"`: Verificar hechos con fuentes externas (valida vigencia)

**Respuesta**:
```json
{
  "success": true,
  "context_unit_id": "uuid-123",
  "context_unit_title": "Título del Context Unit",
  "enrich_type": "background",
  "age_days": 5,
  "result": {
    "background_facts": ["antecedente1", "antecedente2"],
    "historical_context": "explicación breve del contexto",
    "sources": ["url1", "url2"],
    "suggestion": "cómo añadir contexto al artículo"
  },
  "timestamp": "2025-11-11T10:00:00Z"
}
```

**Importante**: Los enriched statements se guardan automáticamente en la BD en formato JSONB:
```json
{
  "text": "El statement enriquecido",
  "type": "fact",
  "order": 16,
  "speaker": null
}
```

Los `order` se calculan automáticamente después del último `atomic_statement`.

**Notas**:
- Usa Groq Compound con web search automática
- Los statements enriquecidos se **acumulan** (no reemplazan los anteriores)
- Se factura como operación "simple" (microedición)
- Compatible con formato legacy (migración automática)

---

### 📰 Articles (Artículos Publicables)

Los **articles** son contenido redactado listo para publicación, generados desde context units.

#### `GET /api/v1/articles`

Listar artículos del cliente.

**Headers**: `X-API-Key` o `Authorization: Bearer {JWT}`

**Query Params**:
- `status` (string, default="all"): Filtrar por estado (`"publicado"`, `"borrador"`, `"all"`)
- `category` (string, default="all"): Filtrar por categoría
- `limit` (int, default=20): Resultados por página
- `offset` (int, default=0): Paginación

**Respuesta**:
```json
{
  "articles": [
    {
      "id": "uuid-123",
      "titulo": "Título del artículo",
      "slug": "titulo-del-articulo-123456",
      "excerpt": "Resumen breve del artículo...",
      "contenido": "<p>HTML del artículo...</p>",
      "autor": "Sistema",
      "tags": ["política", "gobierno"],
      "estado": "publicado",
      "category": "política",
      "fecha_publicacion": "2025-11-23T10:00:00Z",
      "created_at": "2025-11-23T09:00:00Z"
    }
  ],
  "total": 45,
  "limit": 20,
  "offset": 0
}
```

---

#### `GET /api/v1/articles/{article_id}`

Obtener artículo por ID.

**Headers**: `X-API-Key` o `Authorization: Bearer {JWT}`

**URL Params**: `article_id` (UUID)

**Respuesta**:
```json
{
  "id": "uuid-123",
  "titulo": "Título del artículo",
  "slug": "titulo-del-articulo-123456",
  "excerpt": "Resumen breve...",
  "contenido": "<p>Contenido HTML completo...</p>",
  "imagen_url": "https://...",
  "autor": "Sistema",
  "tags": ["política", "economía"],
  "estado": "publicado",
  "working_json": {
    "article": {
      "titulo": "...",
      "excerpt": "...",
      "contenido_markdown": "<p>...</p>"
    },
    "fuentes": {
      "news_ids": ["uuid-1", "uuid-2"],
      "context_unit_ids": ["uuid-3"],
      "statements": {
        "stmt_0_0": {
          "text": "Statement usado",
          "type": "fact",
          "order": 1,
          "speaker": null,
          "context_unit_id": "uuid-3"
        }
      }
    },
    "metadata": {
      "estado": "publicado",
      "version": 2,
      "style_id": "uuid-style"
    }
  },
  "fecha_publicacion": "2025-11-23T10:00:00Z",
  "created_at": "2025-11-23T09:00:00Z",
  "updated_at": "2025-11-23T10:30:00Z",
  "company_id": "uuid-company",
  "category": "política"
}
```

---

#### `GET /api/v1/articles/by-slug/{slug}`

Obtener artículo por slug (URL-friendly).

**Headers**: `X-API-Key` o `Authorization: Bearer {JWT}`

**URL Params**: `slug` (string)

**Ejemplo**:
```bash
GET /api/v1/articles/by-slug/alcaldesa-de-vitoria-advierte-sobre-el-peligro-del-hielo-en-las-calles-1763857107193
```

**Respuesta**: Igual que `GET /api/v1/articles/{article_id}`

---

#### `POST /api/v1/articles`

Crear o actualizar artículo (upsert). **Endpoint principal para guardar artículos**.

**Headers**: `X-API-Key` o `Authorization: Bearer {JWT}`, `Content-Type: application/json`

**Body**: JSON con los campos del artículo
```json
{
  "id": "uuid-generado-por-frontend",
  "titulo": "Título del artículo",
  "slug": "titulo-del-articulo-123456",
  "excerpt": "Resumen breve...",
  "contenido": "<p>Contenido HTML...</p>",
  "autor": "Sistema",
  "tags": ["política", "gobierno"],
  "estado": "borrador",
  "working_json": { /* ... */ }
}
```

**Respuesta**: El artículo guardado con todos sus campos

**Casos de uso**:

1. **Primera vez (crear)**:
```json
{
  "id": "uuid-nuevo",
  "titulo": "Título nuevo",
  "slug": "titulo-nuevo-123",
  "estado": "borrador",
  ...
}
```

2. **Actualización posterior**:
```json
{
  "id": "uuid-existente",
  "titulo": "Título actualizado",
  "estado": "publicado",
  ...
}
```

**Notas**:
- Si el artículo no existe, lo crea (INSERT)
- Si el artículo existe (mismo `id`), lo actualiza (UPDATE)
- `company_id` se añade automáticamente
- `updated_at` se actualiza automáticamente
- Valores `null` o `undefined` se ignoran

**Ejemplo curl**:
```bash
# Guardar artículo (crea o actualiza)
curl -X POST "https://api.ekimen.ai/api/v1/articles" \
  -H "X-API-Key: sk-your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "uuid-123",
    "titulo": "Mi artículo",
    "estado": "publicado"
  }'
```

---

#### `PATCH /api/v1/articles/{article_id}`

**Alias de POST** - Hace exactamente lo mismo (upsert). Mantenido por compatibilidad.

Usa `POST /api/v1/articles` en su lugar

---

### ⚙️ Procesamiento Stateless

Endpoints para procesamiento sin persistir en BD.

#### `POST /process/analyze`

Analizar texto y extraer información estructurada.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "text": "Texto a analizar...",
  "action": "extract_entities",
  "params": {
    "entity_types": ["person", "organization", "location"]
  }
}
```

**Respuesta**:
```json
{
  "analysis": {
    "entities": [
      {"text": "Madrid", "type": "location"},
      {"text": "Apple", "type": "organization"}
    ]
  }
}
```

---

#### `POST /process/analyze-atomic`

Extraer atomic statements (afirmaciones atómicas).

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "text": "El artículo sobre IA...",
  "action": "atomic",
  "params": {}
}
```

**Respuesta**:
```json
{
  "atomic_statements": [
    "La IA generativa ha revolucionado el sector",
    "OpenAI lanzó GPT-4 en marzo de 2023"
  ]
}
```

---

#### `POST /process/redact-news`

Redactar noticia desde context units (formato simple).

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "text": "[ID:uuid-1] [ID:uuid-2]",
  "action": "redact",
  "params": {
    "style": "periodístico",
    "length": "medium"
  }
}
```

**Respuesta**:
```json
{
  "draft": "Noticia redactada basándose en los context units...",
  "word_count": 450
}
```

---

#### `POST /process/redact-news-rich`

Redactar noticia enriquecida con metadata (formato Kazet).

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "context_unit_ids": ["uuid-1", "uuid-2", "uuid-3"],
  "title": "Título sugerido (opcional)",
  "instructions": "Enfócate en el aspecto económico",
  "style_guide": "Estilo formal, evitar sensacionalismo"
}
```

**Respuesta**:
```json
{
  "draft_id": "draft-uuid",
  "title": "Título generado",
  "draft": "Contenido completo de la noticia...",
  "metadata": {
    "word_count": 520,
    "sources_used": 3,
    "model": "claude-3.5-sonnet",
    "created_at": "2025-11-11T10:00:00Z"
  }
}
```

---

#### `POST /process/micro-edit`

Micro-edición de texto con comandos simples.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "text": "El texto a editar...",
  "command": "hacer más conciso",
  "context": "Es un párrafo introductorio",
  "params": {
    "max_length": 100
  }
}
```

**Comandos disponibles**:
- `"hacer más conciso"`
- `"expandir"`
- `"cambiar tono a formal"`
- `"cambiar tono a informal"`
- `"corregir gramática"`
- `"simplificar"`

**Respuesta**:
```json
{
  "edited_text": "Texto editado según el comando...",
  "changes_made": ["Reducido 30%", "Eliminadas redundancias"],
  "usage_type": "simple"
}
```

**Nota**: Se factura como operación "simple" (microedición).

---

#### `POST /process/url`

Procesar URL sin persistir.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "url": "https://example.com/article",
  "action": "extract",
  "params": {
    "extract_images": true
  }
}
```

**Respuesta**:
```json
{
  "title": "Título extraído",
  "content": "Contenido del artículo...",
  "metadata": {
    "author": "Nombre Autor",
    "publish_date": "2025-11-10"
  }
}
```

---

#### `POST /styles/generate`

Generar guía de estilo basada en ejemplos.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "style_name": "Estilo Editorial X",
  "urls": [
    "https://example.com/article1",
    "https://example.com/article2",
    "https://example.com/article3"
  ]
}
```

**Respuesta**:
```json
{
  "style_guide": {
    "name": "Estilo Editorial X",
    "tone": "formal, objetivo",
    "structure": "pirámide invertida",
    "language": {
      "vocabulary": "técnico pero accesible",
      "sentence_length": "media (15-20 palabras)"
    },
    "examples": [
      "Ejemplo de párrafo tipo..."
    ]
  }
}
```

---

### 🗓️ Tareas y Workflows

#### `GET /tasks`

Listar tareas del cliente.

**Headers**: `X-API-Key`

**Respuesta**:
```json
{
  "tasks": [
    {
      "task_id": "uuid-task-1",
      "source_type": "web_llm",
      "target": "https://example.com",
      "frequency_min": 60,
      "is_active": true,
      "last_run": "2025-11-11T09:00:00Z"
    }
  ]
}
```

---

#### `POST /tasks`

Crear nueva tarea programada.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "source_type": "web_llm",
  "target": "https://prentsa.araba.eus/indice",
  "frequency_min": 60,
  "config": {
    "extract_multiple": true,
    "notification_email": "alerts@example.com"
  }
}
```

**Tipos de source_type**:
- `"web_llm"`: Scraping web con LLM
- `"twitter"`: Twitter scraping
- `"api"`: Conectores API externos
- `"email"`: Monitor de correo
- `"file"`: Monitor de archivos

**Respuesta**:
```json
{
  "task_id": "uuid-task-new",
  "status": "created",
  "next_run": "2025-11-11T11:00:00Z"
}
```

---

#### `PUT /sources/{source_id}`

Actualizar configuración de tarea (source).

**Headers**: `X-API-Key`, `Content-Type: application/json`

**URL Params**: `source_id` (UUID)

**Body**:
```json
{
  "is_active": true,
  "schedule_config": {
    "cron": "09:00"
  },
  "config": {
    "notification_enabled": true
  }
}
```

**schedule_config opciones**:
```json
// Intervalo en minutos
{"interval_minutes": 60}

// Cron diario (hora UTC)
{"cron": "09:00"}

// Cron con día de semana
{"cron": "MON,WED,FRI 14:30"}
```

**Respuesta**:
```json
{
  "source_id": "uuid-source-1",
  "status": "updated",
  "next_run": "2025-11-12T09:00:00Z"
}
```

---

#### `DELETE /tasks/{task_id}`

Eliminar tarea.

**Headers**: `X-API-Key`

**URL Params**: `task_id` (UUID)

**Respuesta**:
```json
{
  "status": "deleted",
  "task_id": "uuid-task-1"
}
```

---

#### `GET /executions`

Ver historial de ejecuciones.

**Headers**: `X-API-Key`

**Query Params**:
- `limit` (int, default=50)
- `offset` (int, default=0)
- `task_id` (UUID, opcional): Filtrar por tarea

**Respuesta**:
```json
{
  "executions": [
    {
      "execution_id": "uuid-exec-1",
      "task_id": "uuid-task-1",
      "status": "completed",
      "started_at": "2025-11-11T10:00:00Z",
      "completed_at": "2025-11-11T10:02:15Z",
      "result": {
        "context_units_created": 3,
        "errors": []
      }
    }
  ],
  "total": 127
}
```

---

### 🎤 Text-to-Speech (TTS)

#### `GET /tts/health`

Health check del servicio TTS.

**Headers**: `X-API-Key`

**Respuesta**:
```json
{
  "status": "ok",
  "service": "semantika-tts",
  "version": "1.0.0",
  "model": "es_ES-carlfm-x_low",
  "quality": "x_low (3-4x faster, 28MB)",
  "integrated": true,
  "client_id": "uuid-client"
}
```

---

#### `POST /tts/synthesize`

Sintetizar voz desde texto.

**Headers**: `X-API-Key`, `Content-Type: application/json`

**Body**:
```json
{
  "text": "El texto a convertir en voz. Máximo 3000 caracteres.",
  "rate": 1.3
}
```

**Parámetros**:
- `text`: Texto a sintetizar (1-3000 chars)
- `rate`: Velocidad de habla (0.5-2.0)
  - `0.5`: 50% más lento
  - `1.0`: Velocidad normal
  - `1.3`: 30% más rápido (default)
  - `2.0`: 2x más rápido

**Respuesta**: Audio WAV stream

**Headers de respuesta**:
```
Content-Type: audio/wav
Content-Disposition: attachment; filename=speech.wav
Content-Length: [bytes]
Cache-Control: public, max-age=3600
```

**Ejemplo con curl**:
```bash
curl -X POST https://api.semantika.es/tts/synthesize \
  -H "X-API-Key: sk-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hola, este es un test de síntesis de voz.", "rate": 1.3}' \
  --output speech.wav
```

**Ejemplo con JavaScript (chunks)**:
```javascript
async function synthesizeInChunks(text, apiKey) {
  const chunks = splitTextIntoChunks(text, 800);

  for (const chunk of chunks) {
    const response = await fetch('https://api.semantika.es/tts/synthesize', {
      method: 'POST',
      headers: {
        'X-API-Key': apiKey,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ text: chunk, rate: 1.3 })
    });

    const audioBlob = await response.blob();
    await playAudio(audioBlob);
  }
}
```

**Rendimiento esperado**:
- Chunks de 500-800 chars: ~3-4 segundos
- Textos de 2000 chars: ~8-10 segundos
- Textos de 3000 chars: ~12-15 segundos

**Notas**:
- Timeout: 15 segundos
- Modelo: Piper es_ES-carlfm-x_low (voz masculina española)
- Se factura como operación "simple" (microedición)
- Recomendado: Dividir textos largos en chunks de 800 chars

---

### 🎙️ Speech-to-Text (STT)

**Nota**: El servicio STT usa Whisper de OpenAI pero no está expuesto como endpoint público.

Para usar STT:

1. **Via audio_transcriber.py** (interno):
   ```python
   from sources.audio_transcriber import AudioTranscriber

   transcriber = AudioTranscriber()
   result = await transcriber.transcribe_audio("path/to/audio.mp3")
   ```

2. **Modelos disponibles**:
   - `base`: Rápido, menos preciso
   - `small`: Balance velocidad/precisión (default)
   - `medium`: Más preciso, más lento

---

## Servicios de Procesamiento

### 🧠 Procesamiento con LLM

El sistema usa **OpenRouter** para acceso a múltiples modelos LLM:

#### Modelos Disponibles

| Modelo | Uso | Velocidad | Costo |
|--------|-----|-----------|-------|
| `anthropic/claude-3.5-sonnet` | Análisis complejo, redacción | Media | Alto |
| `openai/gpt-4o-mini` | Tareas rápidas, extracciones | Rápida | Bajo |
| `groq/llama-3.3-70b` | Scraping, análisis web | Muy rápida | Medio |

#### Operaciones LLM

**Análisis Semántico**:
- Extracción de entidades
- Generación de resúmenes
- Atomic statements
- Clasificación de contenido

**Redacción**:
- Noticias desde context units
- Micro-ediciones
- Expansión/condensación de texto

**Scraping Inteligente**:
- Detección de estructura de página
- Extracción de múltiples artículos
- Limpieza y normalización de HTML

---

### 🔍 Búsqueda Semántica (Qdrant)

Vector store para búsquedas semánticas multi-tenant.

#### Características

- **Embeddings**: FastEmbed (integrado en Qdrant)
- **Modelo**: `sentence-transformers/all-MiniLM-L6-v2`
- **Dimensiones**: 384
- **Similitud**: Cosine similarity

#### Filtrado Multi-tenant

Todos los queries incluyen filtro automático por `client_id`:

```python
search_results = qdrant.search(
    collection_name="semantika_prod",
    query_vector=embedding,
    query_filter={
        "must": [
            {"key": "client_id", "match": {"value": client_id}}
        ]
    },
    limit=10
)
```

#### Deduplicación

Antes de insertar nuevo contenido:
1. Calcular embedding del título o primeros 200 chars
2. Buscar similitud > 0.98 en Qdrant
3. Si existe duplicado → Descartar y loguear
4. Si no existe → Insertar

---

### 🛡️ Guardrails

Sistema de validación antes de ingesta.

#### 1. Detección de PII

Detecta y anonimiza información personal:
- Nombres completos
- DNI/NIE
- Números de teléfono
- Emails
- Direcciones

**Ejemplo**:
```
Input: "Juan Pérez (DNI 12345678X) llamó al 600123456"
Output: "[NOMBRE] ([DNI]) llamó al [TELÉFONO]"
```

#### 2. Copyright Detection

Detecta contenido con copyright:
- © symbols
- "All rights reserved"
- "Prohibida reproducción"

Si detectado → Rechazar ingesta

#### 3. Robots.txt Compliance

Antes de scrapear:
1. Fetch robots.txt del dominio
2. Verificar si la ruta está permitida
3. Si prohibido → Bloquear scraping

**Bypass**: `skip_guardrails: true` (solo para administradores)

---

## Workflows y Tareas Programadas

### Scheduler (APScheduler)

El componente `semantika-scheduler` ejecuta tareas programadas usando **APScheduler**.

#### Tipos de Triggers

**1. IntervalTrigger** (cada X minutos):
```json
{
  "frequency_min": 60
}
```

**2. CronTrigger** (hora específica):
```json
{
  "schedule_config": {
    "cron": "09:00"
  }
}
```

**3. Cron con días de semana**:
```json
{
  "schedule_config": {
    "cron": "MON,WED,FRI 14:30"
  }
}
```

#### Flujo de Ejecución

```
1. Scheduler carga tareas activas desde Supabase
2. Crea APScheduler jobs
3. En cada ejecución:
   ├─ Marca execution como "running"
   ├─ Ejecuta source connector
   ├─ Procesa resultados
   ├─ Marca execution como "completed" o "failed"
   └─ Loguea resultado
4. Recarga configuración cada 5 minutos
```

#### Reload Dinámico

El scheduler recarga las tareas cada 5 minutos para capturar cambios en configuración sin reiniciar el servicio.

**Nota importante**: Solo actualiza jobs si detecta cambios reales (frecuencia, activación/desactivación) para no resetear timers.

---

### Source Connectors

Conectores para diferentes fuentes de datos.

#### 1. Web Scraper (web_llm)

**Archivo**: `sources/scraper_workflow.py`

**Características**:
- Usa LangGraph workflow con Groq Llama 3.3 70B
- Detecta automáticamente:
  - Página índice → Extrae múltiples artículos
  - Noticia individual → Extrae contenido
- Genera atomic statements
- Crea context units completas

**Configuración**:
```json
{
  "source_type": "web_llm",
  "target": "https://prentsa.araba.eus/indice",
  "schedule_config": {"cron": "09:00"},
  "config": {
    "extract_multiple": true,
    "max_articles": 10
  }
}
```

---

#### 2. Twitter Scraper

**Archivo**: `sources/twitter_scraper.py`

**Características**:
- Usa ScraperTech API
- Extrae tweets por usuario o hashtag
- Filtra por fecha

**Configuración**:
```json
{
  "source_type": "twitter",
  "target": "@username",
  "frequency_min": 120,
  "config": {
    "max_tweets": 50,
    "include_replies": false
  }
}
```

---

#### 3. API Connectors

**Archivo**: `sources/api_connectors.py`

Conectores para:
- **Agencia EFE** (noticias)
- **Reuters** (noticias)
- **WordPress** (blogs)

**Configuración EFE**:
```json
{
  "source_type": "api",
  "target": "efe",
  "frequency_min": 60,
  "config": {
    "api_key": "tu-clave-efe",
    "category": "tecnologia"
  }
}
```

---

#### 4. Perplexity News Connector

**Archivo**: `sources/perplexity_news_connector.py`

Usa Perplexity API para buscar noticias recientes sobre un tema.

**Configuración**:
```json
{
  "source_type": "perplexity",
  "target": "inteligencia artificial España",
  "frequency_min": 180,
  "config": {
    "max_results": 10,
    "recency_days": 7
  }
}
```

---

## Monitores Automáticos

### Email Monitor

**Archivo**: `sources/email_monitor.py`

Monitorea buzón IMAP y extrae contenido de emails.

#### Configuración (.env)

```bash
EMAIL_MONITOR_ENABLED=true
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_IMAP_PORT=993
EMAIL_ADDRESS=tu-email@gmail.com
EMAIL_PASSWORD=app-password-aqui
EMAIL_MONITOR_INTERVAL=60
```

#### Gmail Setup

1. Activar 2FA en tu cuenta Google
2. Generar "App Password" en https://myaccount.google.com/apppasswords
3. Usar ese password en `EMAIL_PASSWORD`

#### Funcionamiento

```
1. Conecta a IMAP cada X minutos
2. Busca emails no leídos
3. Extrae:
   ├─ Subject → title
   ├─ Body (text/html) → content
   └─ Attachments (PDF, DOCX) → extraer texto
4. Crea context unit
5. Marca email como leído
```

#### Multi-empresa

**Archivo**: `sources/multi_company_email_monitor.py`

Permite monitorear múltiples cuentas de email (una por cliente).

**Configuración en Supabase**:
```sql
INSERT INTO email_accounts (client_id, email_address, imap_server, imap_port, password_encrypted)
VALUES ('uuid-client', 'cliente@example.com', 'imap.gmail.com', 993, encrypt('password'));
```

---

### File Monitor

**Archivo**: `sources/file_monitor.py`

Monitorea directorio y procesa archivos nuevos.

#### Configuración (.env)

```bash
FILE_MONITOR_ENABLED=true
FILE_MONITOR_WATCH_DIR=/app/data/watch
FILE_MONITOR_PROCESSED_DIR=/app/data/processed
FILE_MONITOR_INTERVAL=30
```

#### Formatos Soportados

- **Texto**: `.txt`, `.md`
- **Documentos**: `.pdf`, `.docx`, `.odt`
- **Web**: `.html`, `.htm`

#### Funcionamiento

```
1. Escanea FILE_MONITOR_WATCH_DIR cada X segundos
2. Para cada archivo nuevo:
   ├─ Extrae texto según formato
   ├─ Crea context unit
   └─ Mueve a FILE_MONITOR_PROCESSED_DIR
3. Loguea resultado
```

---

## Crear Workflows Personalizados

### Estructura de un Source Connector

Todos los conectores heredan de `BaseSource`:

```python
# sources/mi_conector.py

from sources.base_source import BaseSource
from utils.logger import get_logger

logger = get_logger("mi_conector")

class MiConector(BaseSource):
    """Descripción del conector."""

    async def fetch_data(self) -> List[Dict[str, Any]]:
        """
        Obtener datos de la fuente externa.

        Returns:
            Lista de documentos con formato:
            [
                {
                    "title": "Título",
                    "content": "Contenido",
                    "metadata": {"source": "mi_api"}
                }
            ]
        """
        logger.info("mi_conector_fetch", target=self.target)

        # Tu lógica aquí
        data = await self._call_external_api()

        return [
            {
                "title": item["name"],
                "content": item["description"],
                "metadata": {
                    "source": "mi_api",
                    "id": item["id"]
                }
            }
            for item in data
        ]

    async def _call_external_api(self):
        """Lógica específica de tu API."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.example.com/data",
                headers={"Authorization": f"Bearer {self.config.get('api_key')}"}
            ) as response:
                return await response.json()
```

---

### Registrar el Conector

1. **Importar en scheduler.py**:

```python
# scheduler.py

from sources.mi_conector import MiConector

# En la función get_source_connector():
def get_source_connector(source):
    source_type = source["source_type"]

    if source_type == "mi_conector":
        return MiConector(
            source_id=source["source_id"],
            client_id=source["client_id"],
            target=source["target"],
            config=source.get("config", {})
        )
    # ... otros conectores
```

2. **Crear tarea con el nuevo tipo**:

```bash
docker exec -it semantika-api python cli.py add-task \
  --client-id "uuid-cliente" \
  --type "mi_conector" \
  --target "https://api.example.com" \
  --freq 120
```

O via API:
```bash
POST /tasks
{
  "source_type": "mi_conector",
  "target": "https://api.example.com",
  "frequency_min": 120,
  "config": {
    "api_key": "mi-clave-api"
  }
}
```

---

### Librerías Comunes para Workflows

#### 1. HTTP Requests

```python
import aiohttp

async with aiohttp.ClientSession() as session:
    async with session.get(url) as response:
        data = await response.json()
```

#### 2. HTML Parsing

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(html, 'html.parser')
title = soup.find('h1').text
content = soup.find('article').get_text()
```

#### 3. LLM Processing

```python
from utils.llm_client import get_llm_client

llm_client = get_llm_client()

result = await llm_client.extract_atomic_statements(
    text=content,
    client_id=client_id
)
```

#### 4. Supabase

```python
from utils.supabase_client import get_supabase_client

supabase = get_supabase_client()

await supabase.create_context_unit(
    client_id=client_id,
    title=title,
    content=content,
    atomic_statements=statements
)
```

#### 5. Qdrant

```python
from utils.qdrant_client import get_qdrant_client

qdrant = get_qdrant_client()

await qdrant.upsert(
    collection_name="semantika_prod",
    points=[
        {
            "id": str(uuid.uuid4()),
            "vector": embedding,
            "payload": {
                "client_id": client_id,
                "text": content,
                "metadata": metadata
            }
        }
    ]
)
```

---

### Ejemplos de Workflows

#### Ejemplo 1: RSS Feed Connector

```python
# sources/rss_connector.py

import feedparser
from sources.base_source import BaseSource

class RSSConnector(BaseSource):
    """Conector para feeds RSS."""

    async def fetch_data(self):
        feed = feedparser.parse(self.target)

        return [
            {
                "title": entry.title,
                "content": entry.description,
                "metadata": {
                    "source": "rss",
                    "published": entry.published,
                    "link": entry.link
                }
            }
            for entry in feed.entries[:10]
        ]
```

#### Ejemplo 2: GitHub Issues Monitor

```python
# sources/github_issues.py

import aiohttp
from sources.base_source import BaseSource

class GitHubIssuesMonitor(BaseSource):
    """Monitor de issues de GitHub."""

    async def fetch_data(self):
        # self.target = "owner/repo"
        owner, repo = self.target.split('/')

        url = f"https://api.github.com/repos/{owner}/{repo}/issues"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"Authorization": f"token {self.config['github_token']}"}
            ) as response:
                issues = await response.json()

        return [
            {
                "title": f"Issue #{issue['number']}: {issue['title']}",
                "content": issue['body'] or "",
                "metadata": {
                    "source": "github",
                    "issue_number": issue['number'],
                    "state": issue['state'],
                    "url": issue['html_url']
                }
            }
            for issue in issues
            if issue['state'] == 'open'
        ]
```

---

## Configuración del Sistema

### Variables de Entorno

Archivo `.env` en la raíz del proyecto:

```bash
# Supabase (Base de datos de configuración)
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu-supabase-service-role-key

# Qdrant (Vector store)
QDRANT_URL=https://cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=tu-qdrant-api-key
QDRANT_COLLECTION_NAME=semantika_prod

# OpenRouter (LLMs)
OPENROUTER_API_KEY=sk-or-v1-tu-clave
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_FAST_MODEL=openai/gpt-4o-mini

# Groq (Scraping rápido)
GROQ_API_KEY=tu-groq-api-key

# ScraperTech (Twitter)
SCRAPERTECH_API_KEY=tu-scrapertech-key
SCRAPERTECH_BASE_URL=https://api.scraper.tech

# Perplexity (Noticias)
PERPLEXITY_API_KEY=pplx-tu-clave

# Procesamiento de texto
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
SIMILARITY_THRESHOLD=0.98

# TTL (días antes de borrar datos no especiales)
DATA_TTL_DAYS=30

# Servidor
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO

# File Monitor
FILE_MONITOR_ENABLED=false
FILE_MONITOR_WATCH_DIR=/app/data/watch
FILE_MONITOR_PROCESSED_DIR=/app/data/processed
FILE_MONITOR_INTERVAL=30

# Email Monitor
EMAIL_MONITOR_ENABLED=false
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_IMAP_PORT=993
EMAIL_ADDRESS=tu-email@example.com
EMAIL_PASSWORD=tu-app-password
EMAIL_MONITOR_INTERVAL=60
```

---

### Docker Compose

```yaml
version: '3.8'

services:
  semantika-api:
    build: .
    container_name: semantika-api
    command: "uvicorn server:app --host 0.0.0.0 --port 8000 --reload"
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - .:/app  # Hot-reload en desarrollo
    restart: unless-stopped
    networks:
      - semantika-network

  semantika-scheduler:
    build: .
    container_name: semantika-scheduler
    command: "python scheduler.py"
    env_file:
      - .env
    volumes:
      - .:/app
    restart: unless-stopped
    networks:
      - semantika-network

networks:
  semantika-network:
    driver: bridge
```

---

### Deployment (Easypanel)

El sistema se despliega automáticamente via GitHub Actions cuando se hace push a `main`.

**Workflow**:
1. Push a GitHub → Trigger GitHub Action
2. GitHub Action → SSH a servidor
3. Servidor ejecuta:
   ```bash
   cd /path/to/semantika
   git pull
   docker-compose up -d --build
   ```
4. Easypanel detecta cambios y reconstruye contenedores

**Tiempo de rebuild**: ~10 minutos (por descarga de modelo Piper TTS)

---

## Uso y Facturación

### Tipos de Operaciones

El sistema trackea uso para facturación:

| Tipo | Descripción | Coste Relativo |
|------|-------------|----------------|
| `simple` | Microediciones, TTS | 1x |
| `standard` | Búsquedas, análisis básico | 5x |
| `complex` | Redacción completa, workflows LLM | 20x |

### Tracking de Uso

Tabla `usage_logs` en Supabase:

```sql
CREATE TABLE usage_logs (
  usage_id UUID PRIMARY KEY,
  organization_id UUID,
  client_id UUID,
  model VARCHAR(100),
  operation VARCHAR(100),
  input_tokens INT,
  output_tokens INT,
  metadata JSONB,
  created_at TIMESTAMP
);
```

### Consultar Uso

**Via SQL en Supabase**:
```sql
-- Uso por cliente en el último mes
SELECT
  client_id,
  COUNT(*) as total_operations,
  SUM(input_tokens) as total_input_tokens,
  SUM(output_tokens) as total_output_tokens
FROM usage_logs
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY client_id;

-- Desglose por tipo de operación
SELECT
  operation,
  metadata->>'usage_type' as usage_type,
  COUNT(*) as count,
  AVG(input_tokens + output_tokens) as avg_tokens
FROM usage_logs
WHERE client_id = 'uuid-cliente'
  AND created_at > NOW() - INTERVAL '30 days'
GROUP BY operation, usage_type;
```

**Via API** (futuro):
```bash
GET /usage/report?start_date=2025-11-01&end_date=2025-11-30
```

---

## Límites y Consideraciones

### Rate Limits

- **TTS**: 15 segundos timeout por request
- **LLM (Groq)**: 12,000 tokens por request
- **Búsqueda Qdrant**: 100 resultados máximo por query

### Tamaño de Datos

- **Ingesta de texto**: 50,000 caracteres máximo
- **TTS**: 3,000 caracteres máximo (recomendado: chunks de 800)
- **Context units**: Sin límite (pero se aplica TTL de 30 días si `special_info=false`)

### TTL (Time to Live)

Datos con `special_info=false` se borran automáticamente después de 30 días (configurable con `DATA_TTL_DAYS`).

Para marcar datos como especiales:
```sql
UPDATE context_units
SET special_info = true
WHERE context_unit_id = 'uuid-importante';
```

---

## Troubleshooting

### Logs

**Ver logs del API**:
```bash
docker logs -f semantika-api
```

**Ver logs del scheduler**:
```bash
docker logs -f semantika-scheduler
```

**Formato de logs** (JSON):
```json
{
  "level": "INFO",
  "timestamp": "2025-11-11T10:00:00.123Z",
  "service": "api",
  "action": "search_completed",
  "client_id": "uuid-123",
  "duration_ms": 234.5
}
```

### Errores Comunes

#### 401 Unauthorized
**Causa**: API Key inválida o faltante
**Solución**: Verificar header `X-API-Key`

#### 403 Forbidden
**Causa**: API Key válida pero cliente inactivo
**Solución**: Activar cliente en Supabase

#### 429 Rate Limit
**Causa**: Demasiadas requests (rate limit de OpenRouter/Groq)
**Solución**: Esperar 1 minuto, reducir frecuencia de tareas

#### 500 Internal Server Error
**Causa**: Error en procesamiento (LLM, Qdrant, Supabase)
**Solución**: Revisar logs para detalles específicos

### Health Checks

```bash
# API health
curl https://api.semantika.es/health

# TTS health (requiere API key)
curl https://api.semantika.es/tts/health \
  -H "X-API-Key: sk-xxxxx"

# Qdrant health (directo)
curl https://cluster.cloud.qdrant.io:6333/health
```

---

## Soporte y Contacto

- **Documentación**: Este archivo + `/docs` en API
- **Logs**: Ver sección Troubleshooting
- **Issues**: GitHub Issues (repositorio privado)

---

## Sistema Pool (Discovery Automático)

El **Sistema Pool** es un componente que descubre automáticamente fuentes de contenido institucional (salas de prensa, comunicados de ayuntamientos, etc.) y las ingesta a una colección compartida en Qdrant.

### Arquitectura Pool vs Company

```
┌────────────────────────────────────────────────────────────┐
│ COMPANIES (Clientes periodistas - Privado)                 │
├────────────────────────────────────────────────────────────┤
│ sources (tabla) → scraper_workflow.py                      │
│   ↓                                                         │
│ monitored_urls (tracking URLs)                             │
│   ↓                                                         │
│ url_content_units (contenido scrapeado)                    │
│   ↓                                                         │
│ pgvector en Supabase (embeddings 768d)                     │
│   - Búsquedas privadas por company_id                      │
│   - RLS habilitado                                         │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ POOL (Sistema compartido - Público)                        │
├────────────────────────────────────────────────────────────┤
│ pool_discovery_config (tabla) → Filtros geográficos        │
│   ↓                                                         │
│ workflows/discovery_flow.py (cada 3 días)                  │
│   - GNews API → Headlines geográficos                      │
│   - Groq Compound → Búsqueda fuente original               │
│   - extract_index_url() → Encuentra página índice          │
│   - analyze_press_room() → Valida institutional source     │
│   ↓                                                         │
│ discovered_sources (tabla) → Fuentes encontradas           │
│   ↓                                                         │
│ workflows/ingestion_flow.py (cada hora)                    │
│   - Scrape con WebScraper                                  │
│   - Enrich con LLM (category, atomic facts, quality)       │
│   - Quality gate: >= 0.4                                   │
│   ↓                                                         │
│ Qdrant Pool collection (company_id="pool")                 │
│   - Embeddings 768d (FastEmbed multilingual)               │
│   - Deduplicación automática (similarity > 0.98)           │
│   - Todas las companies pueden consultar                   │
└────────────────────────────────────────────────────────────┘
```

### Componentes del Sistema Pool

#### 1. Discovery Flow (Cada 3 días)

**Propósito**: Descubrir automáticamente nuevas fuentes institucionales.

**Flujo**:
1. Lee configuraciones activas de `pool_discovery_config` (filtros geográficos: Álava, Bizkaia, etc.)
2. Por cada config:
   - Busca noticias en GNews API (últimas 24h)
   - Sample 5% de artículos
   - Por cada headline:
     - Busca fuente original con Groq Compound (web search)
     - Extrae URL de índice (de artículo específico → página /news)
     - Analiza si es sala de prensa institucional
     - Guarda en `discovered_sources`

**Scheduling**: Cada 3 días a las 8:00 UTC

**Archivos**:
- `workflows/discovery_flow.py`: Orquestador principal
- `sources/discovery_connector.py`: Análisis LLM (extract_index_url, analyze_press_room)
- `sources/gnews_client.py`: GNews API wrapper

#### 2. Ingestion Flow (Cada hora)

**Propósito**: Scrapear fuentes descubiertas e ingestar a Qdrant Pool.

**Flujo**:
1. Obtiene sources activas de `discovered_sources` (status='trial' o 'active')
2. Por cada source:
   - Scrape URL con WebScraper
   - Enriquece contenido con LLM
   - Quality gate: rechaza si quality_score < 0.4
   - Ingesta a Qdrant Pool collection
   - Actualiza stats de la source

**Scheduling**: Cada hora

**Archivos**:
- `workflows/ingestion_flow.py`: Flow principal
- `utils/pool_client.py`: Cliente Qdrant para Pool operations

### Endpoints Pool

#### `POST /pool/search`

Búsqueda semántica en Pool collection.

**Headers**: `X-API-Key`

**Body**:
```json
{
  "query": "Vitoria inversión industrial",
  "limit": 10,
  "filters": {
    "category": "economía",
    "date_from": "2024-01-01"
  },
  "score_threshold": 0.7
}
```

**Respuesta**:
```json
{
  "results": [
    {
      "id": "uuid-1",
      "title": "Inversión en polígono industrial",
      "content": "Contenido...",
      "quality_score": 0.85,
      "source_name": "Gobierno Vasco",
      "category": "economía",
      "published_at": "2024-12-01T10:00:00Z"
    }
  ],
  "total": 5,
  "query_time_ms": 89.9
}
```

---

#### `GET /pool/context/{context_id}`

Obtener context unit del Pool por ID.

**Headers**: `X-API-Key`

**Respuesta**:
```json
{
  "id": "uuid-1",
  "title": "Título del contenido",
  "content": "Contenido completo...",
  "category": "política",
  "tags": ["gobierno", "infraestructura"],
  "quality_score": 0.75,
  "atomic_statements": [
    {
      "text": "Statement 1",
      "type": "fact",
      "order": 1
    }
  ],
  "source_name": "Gobierno Vasco",
  "source_code": "www_irekia_euskadi_eus",
  "published_at": "2024-12-08T10:00:00Z",
  "ingested_at": "2024-12-08T11:00:00Z"
}
```

---

#### `GET /pool/sources`

Listar fuentes descubiertas.

**Headers**: `X-API-Key`

**Query Params**:
- `status`: Filtrar por status (trial, active, inactive, archived)
- `limit`: Número de resultados (default: 20)

**Respuesta**:
```json
{
  "sources": [
    {
      "source_id": "uuid-1",
      "source_name": "Gobierno Vasco",
      "url": "https://irekia.euskadi.eus/es/events",
      "status": "trial",
      "relevance_score": 0.8,
      "avg_quality_score": 0.7,
      "content_count_7d": 5,
      "discovered_at": "2024-12-08T10:00:00Z",
      "last_scraped_at": "2024-12-09T09:00:00Z",
      "config": {
        "geographic_area": "Álava",
        "discovery_config_id": "uuid-config"
      }
    }
  ],
  "total": 1
}
```

---

#### `POST /pool/adopt`

Copiar content unit del Pool al espacio privado de la company.

**Headers**: `Authorization: Bearer {JWT}` (user token)

**Body**:
```json
{
  "context_id": "uuid-pool-content",
  "target_organization_id": "uuid-user-org"
}
```

**Respuesta**:
```json
{
  "success": true,
  "context_unit_id": "uuid-new-copy",
  "message": "Content adopted from pool"
}
```

---

#### `GET /pool/system/health`

Health check del sistema Pool (solo admin).

**Headers**: `X-System-Key`

**Respuesta**:
```json
{
  "status": "healthy",
  "pool_stats": {
    "total_context_units": 15,
    "collection_name": "pool",
    "total_sources": 1,
    "sources_by_status": {
      "trial": 1
    }
  }
}
```

---

#### `GET /pool/system/stats`

Estadísticas del Pool (solo admin).

**Headers**: `X-System-Key`

**Respuesta**:
```json
{
  "total_context_units": 15,
  "collection_name": "pool",
  "avg_source_relevance": 0.8,
  "avg_source_quality": 0.7,
  "total_sources": 1
}
```

### Configuración Geographic Discovery

La tabla `pool_discovery_config` permite configurar búsquedas por área geográfica:

```sql
-- Ejemplo: Añadir config para Bizkaia
INSERT INTO pool_discovery_config (
  geographic_area,
  search_query,
  sample_rate,
  target_source_types,
  created_by
)
VALUES (
  'Bizkaia',
  'Bilbao',
  0.05,  -- 5% sampling
  ARRAY['press_room', 'institutional'],
  (SELECT id FROM organizations WHERE slug = 'system')
);
```

### Características Técnicas

- **Embeddings**: 768d multilingual (paraphrase-multilingual-mpnet-base-v2)
- **Deduplicación**: Automática por similitud > 0.98
- **Quality Threshold**: Solo ingesta content con quality_score >= 0.4
- **Rate Limiting**: 5% sampling + discovery cada 3 días para evitar límites de Groq
- **Company UUID Pool**: `00000000-0000-0000-0000-000000000999`

### Documentación Completa

Ver `POOL_SYSTEM_STATUS.md` para documentación detallada del estado actual del sistema Pool.

---

## Changelog

### v0.2.2 (2024-12-09)
- ✅ Sistema Pool completo (discovery + ingestion)
- ✅ Discovery flow con extract_index_url (LLM-based)
- ✅ Pool endpoints: search, sources, adopt, system/health, system/stats
- ✅ Geographic filtering via pool_discovery_config
- ✅ Quality gates y deduplicación automática

### v0.1.2 (2024-11-11)
- ✅ Añadido servicio TTS con Piper (modelo x_low)
- ✅ Workflow de scraping inteligente con Groq
- ✅ Fix scheduler: no resetear timers innecesariamente
- ✅ Context units enriquecidas con atomic statements
- ✅ Tracking de uso mejorado (simple/standard/complex)

### v0.1.1 (2025-11-08)
- ✅ Email monitor multi-empresa
- ✅ Perplexity news connector
- ✅ Micro-ediciones con comandos simples
- ✅ Generación de guías de estilo

### v0.1.0 (2025-11-01)
- ✅ Release inicial
- ✅ API REST completo
- ✅ Scheduler con APScheduler
- ✅ Web scraper, Twitter, API connectors
- ✅ Qdrant + Supabase integration

---

**Fin de la documentación**
