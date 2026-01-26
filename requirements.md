# Documento de Arquitectura: semantika

**Versión:** 3.0
**Fecha:** 26 de enero de 2026

---

## 1. Visión General del Proyecto

`semantika` es un pipeline de datos semánticos *multi-tenant* diseñado para operar como servicio headless. Su propósito es agregar, procesar y unificar información de múltiples fuentes en PostgreSQL+pgvector para búsquedas semánticas híbridas, alertas y agregación.

**Arquitectura unificada:**
- **PostgreSQL + pgvector**: BD única para config + vectores 768d con RLS multi-tenant
- **FastEmbed local**: Embeddings multilingües sin coste API
- **Búsqueda híbrida**: Semantic (0.7) + Keyword (0.3) con re-ranking

El sistema se despliega en **EasyPanel** (VPS) con contenedores Docker. La gestión multi-tenant se implementa vía **Supabase** (PostgreSQL + Auth) con Row-Level Security.

---

## 2. Funcionalidad Detallada

### 2.1. Ingesta Multi-Fuente

El sistema es capaz de ingerir datos de las siguientes fuentes, asociando cada dato a un `client_id`:

* **Scrapers Web (con LLM):** Ingiere el contenido de una URL y utiliza un LLM (OpenRouter) para extraer *múltiples* unidades de información (noticias, eventos) de una sola página.
* **APIs de Agencias:** Conectores específicos para APIs de noticias (ej. Reuters, EFE), configurables por cliente.
* **Twitter (scraper.tech):** Ingiere tuits o resultados de búsqueda de la API de `scraper.tech`.
* **Audio (Whisper):** Transcribe archivos de audio a texto usando un modelo local de Whisper.
* **Entrada Manual (API):** Permite a los usuarios añadir texto plano directamente a su base de conocimiento.
* **Bases de Datos (WordPress/API):** Ingiere contenido de APIs de BD externas (ej. un WordPress) y lo marca como "información especial" para eximirlo del borrado automático.

### 2.2. Procesamiento y Almacenamiento

**Sistema actual (PostgreSQL + pgvector):**
* **Vectorización:** FastEmbed local (`paraphrase-multilingual-mpnet-base-v2`, 768d) genera embeddings sin coste API
* **Almacenamiento:** Tabla `press_context_units` con columna `embedding vector(768)`
* **Metadatos:**
    * `company_id`: Separación multi-tenant (UUID)
    * `source_id`: Trazabilidad de fuente
    * `title`, `summary`, `raw_text`: Contenido procesado
    * `category`, `tags`: Clasificación LLM
    * `atomic_statements`: Hechos extraídos estructurados
    * `created_at`: Timestamp de ingesta
* **Desduplicación:** Búsqueda semántica pre-insert con threshold 0.98
* **Búsqueda Híbrida:** 
    * Semantic: pgvector cosine similarity (threshold 0.18)
    * Keyword: PostgreSQL full-text search (Spanish config)
    * Re-ranking: 0.7 * semantic + 0.3 * keyword

**Características actuales:**
* **Embeddings 768d**: FastEmbed local multilingual (50+ idiomas)
* **Deduplicación**: Similarity > 0.98 pre-insert
* **Quality gate**: atomic_statements >= 2 para pasar filtro
* **Imágenes destacadas**: Extracción automática (og:image, twitter:image, JSON-LD, content)

### 2.3. Recuperación y Agregación (Retrieval)

* **Búsqueda Parametrizada:** La API permite búsquedas semánticas (`query`) combinadas con filtros estrictos por metadatos (ej. `client_id`, `source`, `loaded_at > "fecha"`).
* **Alertas de Novedades:** Un caso de uso clave es la búsqueda parametrizada filtrando por `loaded_at` en la última hora/día.
* **Agregación ("Zumbar"):** La API ofrece un endpoint que:
    1.  Recibe una consulta (`query`) y un umbral de similitud.
    2.  Recupera los `k` documentos más relevantes.
    3.  Filtra los que superan el umbral.
    4.  Concatena sus textos y utiliza un LLM (OpenRouter) para generar un resumen coherente o una unidad de texto agregada.

### 2.4. Orquestación y Multi-Tenancy

* **Orquestación Dual:**
    1.  **Programada (Cron):** Un servicio `scheduler` lee una tabla `tasks` en Supabase y ejecuta trabajos de ingesta periódicos (scrapers, APIs) para cada cliente.
    2.  **Bajo Demanda (Webhook):** Un servidor `api` escucha peticiones HTTP para ingesta en tiempo real (audio, texto manual) y para todas las consultas.
* **Multi-Tenancy (Separación de Clientes):**
    1.  **Configuración (Supabase):** Las tablas `companies`, `sources` y `api_keys` gestionan qué cliente puede hacer qué.
    2.  **Datos (PostgreSQL):** Todos los vectores coexisten en tablas con `company_id` como columna de partición.
    3.  **Seguridad:** Row-Level Security (RLS) en Supabase filtra automáticamente por `company_id` según el JWT del usuario.

---

## 3. Arquitectura del Sistema

### 3.1. Pila Tecnológica (Stack)

**Backend:**
* **Lenguaje:** Python 3.10+
* **Framework API:** FastAPI, Uvicorn
* **Planificador:** APScheduler (cron jobs)
* **Deployment:** EasyPanel + Docker Compose
* **CI/CD:** GitHub Actions (auto-deploy a VPS)

**Bases de Datos:**
* **PostgreSQL + pgvector:** Supabase (config + vectores 768d)
* **Cliente Supabase:** `supabase-py`
* **Tablas principales:** `press_context_units`, `press_articles`, `sources`, `companies`

**Embeddings y LLM:**
* **Embeddings:** FastEmbed local (`paraphrase-multilingual-mpnet-base-v2`, 768d)
* **LLM Enriquecimiento:** OpenRouter (Claude 3.5 Sonnet)
* **LLM Análisis Rápido:** Groq (Llama 3.3 70B - gratis)
* **Librería:** LangChain

**Otros:**
* **Query Expansion:** Cache (1h) + diccionario local + Groq
* **Transcripción:** `openai-whisper` (opcional, pesado)

### 3.2. Sistemas Externos y Dependencias

**Críticos:**
* **Supabase:** PostgreSQL + Auth + RLS policies (config + vectores)
* **OpenRouter:** Claude 3.5 Sonnet para enriquecimiento LLM
* **Groq:** Llama 3.3 70B para análisis rápido (gratis)

**Opcionales:**
* **GNews API:** Discovery automático de fuentes pool
* **ScraperTech:** Twitter scraping (si configurado por cliente)
* **Playwright:** Scraping de sitios SPA (Single Page Applications)

---

## 4. Componentes y Ejecutables (Docker Compose)

El sistema se despliega como un conjunto de servicios gestionados por `docker-compose`.

### 4.1. `semantika-api` (Servidor FastAPI)

* **Descripción:** El punto de entrada principal del sistema. Es un demonio que escucha peticiones HTTP.
* **Funciones:**
    * **Autenticación:** Valida las `API Key` (X-API-Key) contra la tabla `clients` de Supabase.
    * **Ingesta (POST):** Recibe peticiones de ingesta bajo demanda (manual, audio, webhooks genéricos) y las pasa al `core_ingest`.
    * **Recuperación (GET):** Expone los endpoints de búsqueda híbrida que consultan PostgreSQL+pgvector (filtrado por RLS).
* **Ejecutable (interno):** `uvicorn server:app --host 0.0.0.0 --port 8000`

### 4.2. `semantika-scheduler` (Planificador APScheduler)

* **Descripción:** El motor de ingesta periódica. Es un demonio que gestiona su propio cron interno.
* **Funciones:**
    1.  Al arrancar, se conecta a Supabase y lee la tabla `tasks`.
    2.  Añade un *job* en memoria por cada tarea activa (ej. "scrapear X cada 15 min").
    3.  A intervalos definidos, ejecuta los *jobs*, llamando al `core_ingest` con el `client_id` y `task_id` correspondientes.
    4.  Ejecuta una tarea diaria de limpieza (TTL).
* **Ejecutable (interno):** `python scheduler.py`

### 4.3. PostgreSQL + pgvector (Base de Datos Vectorial)

* **Descripción:** Extensión pgvector en Supabase PostgreSQL.
* **Función:** Almacena los vectores y sus *payloads*. Expone su API en el puerto `6333` (solo a la red interna de Docker).

### 4.4. OpenRouter (Servicio LLM Externo)

* **Función:** Servicio cloud que proporciona acceso a múltiples modelos LLM (Claude 3.5 Sonnet, GPT-4o-mini) para `semantika-api` (resúmenes) y `semantika-scheduler` (extracción web).
* **Nota:** Se utiliza OpenRouter en lugar de Ollama local para reducir requisitos de hardware del VPS.

### 4.5. `dozzle` (Visor de Logs)

* **Descripción:** Contenedor ligero para monitorización.
* **Función:** Proporciona una interfaz web simple (en el puerto `8081`) que se conecta al socket de Docker y muestra los logs (`stdout`) en tiempo real de todos los contenedores (`api`, `scheduler`), permitiendo la depuración desde fuera del servidor.

---

## 5. Gestión de Datos

### 5.1. Modelo de Datos Relacional (Supabase)

Supabase actúa como la base de datos de "configuración".

* **`clients`**:
    * `client_id` (uuid, PK): ID único del cliente.
    * `client_name` (text): Nombre del cliente.
    * `api_key` (text, unique): Clave secreta para la API.
* **`tasks`**:
    * `task_id` (uuid, PK): ID único de la tarea.
    * `client_id` (uuid, FK a `clients`): A qué cliente pertenece.
    * `source_type` (text): "web_llm", "twitter", "api_efe", "api_reuters", "api_wordpress".
    * `target` (text): La URL, término de búsqueda, o endpoint de API.
    * `frequency_min` (integer): Frecuencia de ejecución en minutos.
* **`api_credentials`**:
    * `credential_id` (uuid, PK)
    * `client_id` (uuid, FK a `clients`)
    * `service_name` (text): "scraper_tech", "api_efe", etc.
    * `credentials` (jsonb): Objeto JSON con las claves de API del cliente.

### 5.2. Modelo de Datos Vectorial (PostgreSQL + pgvector)

Una única colección (`semantika_prod`) almacena los vectores.

* **Vector:** Generado por `fastembed` a partir del `text`.
* **Payload (Metadatos):**
    * `client_id` (string): UUID del cliente (para filtrado).
    * `source` (string): "web", "audio", "twitter", "manual", "api_db".
    * `source_id` (string): URL, ID del tuit, ID de la API (para trazabilidad).
    * `title` (string): Título o texto corto (para desduplicación).
    * `text` (string): El contenido textual completo del chunk.
    * `event_time` (timestamp): Cuándo ocurrió el evento.
    * `loaded_at` (timestamp): Cuándo se cargó en la BD.
    * `special_info` (boolean): `false` (borrado a 30 días) o `true` (permanente, ej. WordPress).

---

## 6. Flujos de Proceso Críticos

### 6.1. Flujo de Ingesta Programada (`scheduler.py`)

1.  El *job* de APScheduler se activa (ej. `task_id = 'uuid-task-efe'`).
2.  `scheduler.py` consulta a Supabase por `task_id` y `client_id`.
3.  Obtiene las credenciales de `api_credentials`.
4.  Llama a `core_ingest.py` (el motor de ingesta).
5.  **`core_ingest`:**
    * a. Llama a la API (ej. EFE) y obtiene los datos.
    * b. Normaliza los datos a `Document` de LangChain.
    * c. Divide el texto (`RecursiveCharacterTextSplitter`).
    * d. **Guardrail (PII):** Pasa el texto por una cadena LLM/regex. Si detecta PII, lo anonimiza (`[REDACTED]`) y loguea el hallazgo.
    * e. **Guardrail (Copyright):** Pasa el texto por una cadena LLM. Si detecta copyright estricto, descarta el documento y loguea el rechazo. 
    * f. **Desduplicación:** Para cada chunk, busca en PostgreSQL por `company_id` y similitud de embedding > 0.98. Si es duplicado, lo descarta y loguea.
    * g. **Carga:** Inserta los chunks únicos en `press_context_units` con `company_id`.
    * h. Loguea los IDs de los documentos añadidos.

### 6.2. Flujo de Recuperación (API)

1.  Petición `GET /search?query=IA` llega a `semantika-api` con `X-API-Key: "sk-cliente-A"`.
2.  `server.py` valida la API Key contra la tabla `clients` de Supabase y obtiene `client_id = 'uuid-A'`.
3.  RLS (Row-Level Security) filtra automáticamente por `company_id` según el JWT.
4.  Realiza la búsqueda híbrida (semántica pgvector + keyword full-text) con el `query`.
5.  Devuelve los resultados (los *payloads* de los documentos) como JSON.

---

## 7. Guardrails y Ciclo de Vida de Datos

### 7.1. Guardrails: Detección de Copyright y PII

Integrados en el `core_ingest.py`, se ejecutan antes de la desduplicación.

* **Detección de PII (Datos Personales):** Se implementa una cadena de LangChain que utiliza un LLM (OpenRouter) con un prompt de *few-shot* para detectar DNI, teléfonos, emails privados, etc.
    * **Acción:** Anonimización. El texto se modifica (`[EMAIL_REDACTED]`) antes de la vectorización.
    * **Log:** Se registra un `WARN` con `action: "pii_anonymized"`.
* **Detección de Copyright:** Una cadena LLM busca patrones de copyright explícitos ("Todos los derechos reservados", "Copyright © 2025...").
    * **Acción:** Rechazo. El documento no se procesa.
    * **Log:** Se registra un `INFO` con `action: "copyright_rejected"`.

    EL SCRAPPER DEBE BUSCAR TAMBIEN ROBOTS TXT Y EVITAR SCRAPEAR PAGINAS QUE NO PERMITAN SCRAPPEO. 
    TAMBIÉN EXISTIRÁ UNA LISTA NEGRA Y UNA BLANCA DE SITES ADECUADOS, O DE TIPOS DE SITES A VALORAR MEDIANTE LLMS

### 7.2. Ciclo de Vida de Datos (TTL)

La información genérica (noticias, tuits) caduca para mantener la base de datos relevante y de tamaño controlado.

* **Lógica:** La información se borra si tiene más de 30 días Y `special_info` es `false`.
* **Implementación:** Se añade un *job* diario al `semantika-scheduler`.
* **Función de Limpieza:**
    1.  Calcula `timestamp_limite = now() - 30 days`.
    2.  Ejecuta query SQL:
        ```sql
        DELETE FROM press_context_units
        WHERE created_at < timestamp_limite
        AND special_info = false
        ```
    3.  Loguea el resultado (`action: "ttl_cleanup", deleted_count: ...`).

---

## 8. Logging y Monitorización

* **Estrategia:** Todos los servicios (`semantika-api`, `semantika-scheduler`) loguean a `stdout` en formato **JSON estructurado**.
* **Accesibilidad Externa:** Se utiliza el contenedor `dozzle`. Se conecta al socket de Docker y expone una **interfaz web en el puerto 8081** (configurable) del VPS, permitiendo ver y filtrar los logs de todos los contenedores en tiempo real.
* **Detalle de Logs (Ejemplos):**

    ```json
    {"level": "INFO", "timestamp": "...", "service": "scheduler", "action": "ingest_start", "task_id": "uuid-task-efe"}
    {"level": "WARN", "timestamp": "...", "service": "core_ingest", "action": "pii_anonymized", "source_id": "..."}
    {"level": "INFO", "timestamp": "...", "service": "core_ingest", "action": "copyright_rejected", "source_id": "..."}
    {"level": "DEBUG", "timestamp": "...", "service": "core_ingest", "action": "llm_extraction_result", "source_id": "...", "output_units": 3}
    {"level": "ERROR", "timestamp": "...", "service": "core_ingest", "action": "llm_extraction_error", "error": "JSON parse error"}
    {"level": "INFO", "timestamp": "...", "service": "core_ingest", "action": "document_added", "context_unit_id": "uuid-1", "company_id": "uuid-A"}
    {"level": "INFO", "timestamp": "...", "service": "scheduler", "action": "ttl_cleanup", "deleted_count": 150}
    {"level": "INFO", "timestamp": "...", "service": "api", "action": "search_request", "client_id": "uuid-A", "query": "IA"}
    ```

---

## 9. Despliegue e Instalación

### 9.1. Prerrequisitos

#### Desarrollo Local (MacBook Air M1)
* **Docker Desktop** para Mac (con soporte Apple Silicon)
* **Git** instalado
* Mínimo 8GB RAM (16GB recomendado)
* ~5GB espacio en disco

#### Producción (VPS)
* Un VPS (Linux) con **Docker** y **Docker Compose** instalados
* Acceso SSH con clave pública configurada
* Un proyecto creado en **Supabase** (anotar URL y Service Key)
* (Opcional) Cuentas en APIs externas (scraper.tech, EFE...)
* GitHub configurado con secretos para CI/CD

### 9.2. Estructura de Ficheros

```
/semantika/
├── .env                  # Fichero de secretos (Supabase, OpenRouter, APIs)
├── .env.example          # Plantilla de variables de entorno
├── docker-compose.yml    # Orquestador de todos los servicios
├── Dockerfile            # Define la imagen de la aplicación semantika
├── requirements.txt      # Dependencias de Python
├── server.py             # Demonio API (FastAPI)
├── scheduler.py          # Demonio Cron (APScheduler)
├── core_ingest.py        # Lógica de ingesta (Guardrails, Dedupe, Carga)
├── cli.py                # Herramienta de admin (crear clientes/tareas en Supabase)
├── /endpoints/           # Módulos de API (articles.py, context_units.py, etc.)
├── /workflows/           # Flujos de procesamiento (discovery, ingestion)
└── .gitignore            # Excluir .env y directorios de datos
```

### 9.3. Ficheros de Configuración

#### `Dockerfile`

```dockerfile
# Usa una imagen base ligera de Python
FROM python:3.10-slim

# Instala dependencias del sistema (para Whisper)
RUN apt-get update && apt-get install -y ffmpeg

WORKDIR /app
COPY requirements.txt .

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# (CMD se define en docker-compose)
```

#### `requirements.txt`

```txt
fastapi
uvicorn
apscheduler
supabase
fastembed
langchain
langchain-openai
openai
requests
beautifulsoup4
python-dotenv
pydantic
pydantic-settings
aiohttp
playwright  # Para sitios SPA
```

#### `docker-compose.yml`

```yaml
version: '3.8'

services:
  semantika-api:
    build: .
    container_name: semantika-api
    command: "uvicorn server:app --host 0.0.0.0 --port 8000"
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - qdrant
    restart: always

  semantika-scheduler:
    build: .
    container_name: semantika-scheduler
    command: "python scheduler.py"
    env_file:
      - .env
    depends_on:
      - qdrant
    restart: always

  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    ports:
      - "6333:6333"
    volumes:
      - ./qdrant_storage:/qdrant/storage # Persistencia de datos
    restart: always

  dozzle:
    image: amir20/dozzle:latest
    container_name: dozzle
    ports:
      - "8081:8080" # Accede a los logs en http://IP_DEL_VPS:8081
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock # Acceso al socket de Docker
    restart: always
```

### 9.4. Proceso de Instalación

1.  **Preparar Supabase:**
      * Crea tu proyecto en Supabase.
      * Ve al "Table Editor" y crea las 3 tablas: `clients`, `tasks`, `api_credentials`.
2.  **Preparar VPS:**
      * Instalar `docker` y `docker-compose`.
      * Clonar este repositorio: `git clone ...`
      * `cd semantika`
3.  **Configurar Entorno:**
      * Copiar el archivo de ejemplo: `cp .env.example .env`
      * Editar `.env` y configurar tus claves:
        ```env
        SUPABASE_URL="https://tu-proyecto.supabase.co"
        SUPABASE_KEY="tu-supabase-service-role-key"
        OPENROUTER_API_KEY="sk-or-v1-tu-clave-aqui"
        SCRAPERTECH_API_KEY="tu-clave-scrapertech-aqui"
        ```
4.  **Lanzar Servicios:**
      * Ejecutar: `docker-compose up -d --build`
5.  **Configurar Clientes y Tareas:**
      * Ejecutar el CLI dentro del contenedor para añadir tu primer cliente:
        ```bash
        docker exec -it semantika-api python cli.py add-client --name "Mi Primer Cliente"
        ```
      * (El CLI te devolverá la API Key).
      * Añadir una tarea de prueba:
        ```bash
        docker exec -it semantika-api python cli.py add-task --client-id "uuid-del-cliente" --type "web_llm" --target "https://un-blog.com" --freq 60
        ```
7.  **Monitorizar:**
      * Acceder al visor de logs en `http://[IP_DEL_VPS]:8081` para ver el sistema en funcionamiento.

### 9.5. Despliegue Continuo (CI/CD)

El proyecto utiliza **GitHub Actions** para despliegue automático al VPS de producción.

#### Configuración Inicial

1.  **Generar clave SSH en el VPS** (si no existe):
    ```bash
    ssh-keygen -t ed25519 -C "github-actions"
    cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
    ```

2.  **Configurar GitHub Secrets** (Settings → Secrets → Actions):
    * `VPS_HOST`: IP o dominio del VPS
    * `VPS_USER`: Usuario SSH (ej. `root` o `deploy`)
    * `VPS_SSH_KEY`: Contenido de `~/.ssh/id_ed25519` (clave privada)
    * `VPS_PORT`: Puerto SSH (por defecto `22`)

3.  **Copiar `.env` al VPS**:
    ```bash
    scp .env usuario@VPS:/ruta/semantika/.env
    ```

#### Workflow de Despliegue

El archivo `.github/workflows/deploy.yml` automatiza:

1.  **Trigger:** Al hacer `git push` a la rama `main`
2.  **Acciones:**
    * Conecta al VPS por SSH
    * Hace `git pull` del repositorio
    * Ejecuta `docker-compose down` (detiene servicios)
    * Ejecuta `docker-compose up -d --build` (reconstruye y despliega)
    * Verifica que los servicios estén corriendo
3.  **Tiempo:** ~2-3 minutos
4.  **Rollback:** Si falla, mantiene la versión anterior corriendo

#### Uso

```bash
# Desde tu Mac
git add .
git commit -m "Update feature X"
git push  # ← Esto dispara el despliegue automático
```

Monitoriza el despliegue en: `https://github.com/igorlaburu/semantika/actions`

#### Despliegue Manual (Alternativo)

Si necesitas desplegar manualmente sin GitHub Actions:

```bash
# Conectar al VPS
ssh usuario@VPS

# Actualizar código
cd /ruta/semantika
git pull

# Reconstruir y desplegar
docker-compose down
docker-compose up -d --build

# Verificar logs
docker-compose logs -f
```