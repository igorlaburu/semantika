````markdown
# Documento de Arquitectura: semantika

**Versión:** 1.0
**Fecha:** 24 de octubre de 2025

---

## 1. Visión General del Proyecto

`semantika` es un pipeline de datos semánticos *multi-cliente* (multi-tenant), diseñado para operar como un servicio de fondo (headless). Su propósito es agregar, procesar y unificar información de un conjunto diverso de fuentes en una base de datos vectorial (Qdrant) para permitir búsquedas semánticas avanzadas, alertas de novedades y agregación de información.

El sistema está diseñado para un despliegue de dependencias mínimas en un VPS, encapsulado en contenedores **Docker**. La gestión de clientes, tareas y credenciales se centraliza en **Supabase**, desacoplando la configuración de la lógica de negocio.

---

## 2. Funcionalidad Detallada

### 2.1. Ingesta Multi-Fuente

El sistema es capaz de ingerir datos de las siguientes fuentes, asociando cada dato a un `client_id`:

* **Scrapers Web (con LLM):** Ingiere el contenido de una URL y utiliza un LLM (Ollama) para extraer *múltiples* unidades de información (noticias, eventos) de una sola página.
* **APIs de Agencias:** Conectores específicos para APIs de noticias (ej. Reuters, EFE), configurables por cliente.
* **Twitter (scraper.tech):** Ingiere tuits o resultados de búsqueda de la API de `scraper.tech`.
* **Audio (Whisper):** Transcribe archivos de audio a texto usando un modelo local de Whisper.
* **Entrada Manual (API):** Permite a los usuarios añadir texto plano directamente a su base de conocimiento.
* **Bases de Datos (WordPress/API):** Ingiere contenido de APIs de BD externas (ej. un WordPress) y lo marca como "información especial" para eximirlo del borrado automático.

### 2.2. Procesamiento y Almacenamiento

* **Unificación:** Toda la información se normaliza al formato `Document` de LangChain.
* **Vectorización:** Utiliza `fastembed` (integrado con Qdrant) para generar embeddings *on-the-fly* durante la ingesta.
* **Metadatos:** Cada documento vectorial en Qdrant se almacena con un *payload* que incluye:
    * `client_id`: (Para separación de datos).
    * `source`, `source_id`: (Para trazabilidad).
    * `title`: (Para desduplicación).
    * `event_time`: (Timestamp del evento, si se conoce).
    * `loaded_at`: (Timestamp de la ingesta).
    * `special_info`: (Booleano para gestionar el TTL).
* **Desduplicación:** Antes de insertar un documento, el sistema calcula el embedding de su título/contenido y realiza una búsqueda de similitud. Si un documento con similitud > 0.98 (configurable) ya existe para ese `client_id`, se descarta.
* **Búsqueda Híbrida:** Qdrant se configura para utilizar *sparse vectors* (BM25, keywords) y *dense vectors* (semántica), permitiendo búsquedas híbridas.

### 2.3. Recuperación y Agregación (Retrieval)

* **Búsqueda Parametrizada:** La API permite búsquedas semánticas (`query`) combinadas con filtros estrictos por metadatos (ej. `client_id`, `source`, `loaded_at > "fecha"`).
* **Alertas de Novedades:** Un caso de uso clave es la búsqueda parametrizada filtrando por `loaded_at` en la última hora/día.
* **Agregación ("Zumbar"):** La API ofrece un endpoint que:
    1.  Recibe una consulta (`query`) y un umbral de similitud.
    2.  Recupera los `k` documentos más relevantes.
    3.  Filtra los que superan el umbral.
    4.  Concatena sus textos y utiliza un LLM (Ollama) para generar un resumen coherente o una unidad de texto agregada.

### 2.4. Orquestación y Multi-Tenancy

* **Orquestación Dual:**
    1.  **Programada (Cron):** Un servicio `scheduler` lee una tabla `tasks` en Supabase y ejecuta trabajos de ingesta periódicos (scrapers, APIs) para cada cliente.
    2.  **Bajo Demanda (Webhook):** Un servidor `api` escucha peticiones HTTP para ingesta en tiempo real (audio, texto manual) y para todas las consultas.
* **Multi-Tenancy (Separación de Clientes):**
    1.  **Configuración (Supabase):** Las tablas `clients`, `tasks` y `api_credentials` gestionan qué cliente puede hacer qué.
    2.  **Datos (Qdrant):** Todos los vectores de todos los clientes coexisten en una única colección, pero están estrictamente particionados por el `client_id` en el *payload*.
    3.  **Seguridad:** El servidor API **fuerza** la inclusión del `client_id` (verificado desde la API Key) en *todos* los filtros de búsqueda y escritura de Qdrant.

---

## 3. Arquitectura del Sistema

### 3.1. Pila Tecnológica (Stack)

* **Lenguaje:** Python 3.10+
* **Framework API:** FastAPI, Uvicorn
* **Planificador (Cron):** APScheduler
* **Base de Datos de Configuración:** Supabase (PostgreSQL Cloud)
* **Cliente de Supabase:** `supabase-py`
* **Base de Datos Vectorial:** Qdrant (Corriendo en Docker)
* **Cliente Vectorial:** `qdrant-client`
* **Modelo de Embeddings:** `fastembed` (Integrado en Qdrant)
* **Motor LLM:** Modelo a determinar, mediante Openrouter 
* **Librería de Flujo:** LangChain
* **Transcripción:** `openai-whisper` (modelo local)
* **Visor de Logs:** `dozzle`
* **Entorno de Ejecución:** Docker, Docker Compose

### 3.2. Sistemas Externos y Dependencias

* **Supabase Cloud:** (Crítico) Aloja la configuración de clientes, tareas y credenciales de APIs externas.
* **Qdrant:** (Crítico) El núcleo del almacenamiento. Se ejecuta como un contenedor Docker local o se conecta a Qdrant Cloud.
* **Modelos llm:** (Crítico) mediante Openrouter, en (`web_llm`) y resumen (`/aggregate`).
* **APIs de Terceros:** `scraper.tech`, `API EFE`, `API Reuters` (configuradas por cliente).

---

## 4. Componentes y Ejecutables (Docker Compose)

El sistema se despliega como un conjunto de servicios gestionados por `docker-compose`.

### 4.1. `semantika-api` (Servidor FastAPI)

* **Descripción:** El punto de entrada principal del sistema. Es un demonio que escucha peticiones HTTP.
* **Funciones:**
    * **Autenticación:** Valida las `API Key` (X-API-Key) contra la tabla `clients` de Supabase.
    * **Ingesta (POST):** Recibe peticiones de ingesta bajo demanda (manual, audio, webhooks genéricos) y las pasa al `core_ingest`.
    * **Recuperación (GET):** Expone los endpoints `GET /search` y `GET /aggregate` que consultan Qdrant (forzando el `client_id`).
* **Ejecutable (interno):** `uvicorn server:app --host 0.0.0.0 --port 8000`

### 4.2. `semantika-scheduler` (Planificador APScheduler)

* **Descripción:** El motor de ingesta periódica. Es un demonio que gestiona su propio cron interno.
* **Funciones:**
    1.  Al arrancar, se conecta a Supabase y lee la tabla `tasks`.
    2.  Añade un *job* en memoria por cada tarea activa (ej. "scrapear X cada 15 min").
    3.  A intervalos definidos, ejecuta los *jobs*, llamando al `core_ingest` con el `client_id` y `task_id` correspondientes.
    4.  Ejecuta una tarea diaria de limpieza (TTL).
* **Ejecutable (interno):** `python scheduler.py`

### 4.3. `qdrant` (Base de Datos Vectorial)

* **Descripción:** Contenedor oficial de Qdrant.
* **Función:** Almacena los vectores y sus *payloads*. Expone su API en el puerto `6333` (solo a la red interna de Docker).

### 4.4. `openrouter` (Motor LLM)

* **Función:** Sirve los modelos LLM (ej. `phi-3-mini`) para que `semantika-api` (resúmenes) y `semantika-scheduler` (extracción web) los consuman. POSIBILIDAD DE EJECUCIÓN DE MODELOS LOCALES CON OLLAMA

### 4.5. `dozzle` (Visor de Logs)

* **Descripción:** Contenedor ligero para monitorización.
* **Función:** Proporciona una interfaz web simple (en el puerto `8081`) que se conecta al socket de Docker y muestra los logs (`stdout`) en tiempo real de todos los contenedores (`api`, `scheduler`, `qdrant`), permitiendo la depuración desde fuera del servidor.

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

### 5.2. Modelo de Datos Vectorial (Qdrant)

Una única colección (`semantika_prod`) almacena los vectores.

* **Vector:** Generado por `fastembed` a partir del `text`.
* **Payload (Metadatos):**
    * `client_id` (string): UUID del cliente (para filtrado).
    * `source` (string): "web", "audio", "twitter", "manual", "api_db".
    * `source_id` (string): URL, ID del tuit, ID de la API (para trazabilidad).
    * `title` (string): Título o texto corto (para desduplicación).
    * `text` (string): El contenido textual completo del chunk.
    * `event_time` (timestamp): Cuándo ocurrió el evento.
    * `loaded_at` (timestamp): Cuándo se cargó en Qdrant.
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
    * f. **Desduplicación:** Para cada chunk, busca en Qdrant por `client_id` y similitud de `title`. Si es duplicado, lo descarta y loguea.
    * g. **Carga:** Inserta los chunks únicos en Qdrant con `client_id` y `special_info=false`.
    * h. Loguea los `qdrant_id` de los documentos añadidos.

### 6.2. Flujo de Recuperación (API)

1.  Petición `GET /search?query=IA` llega a `semantika-api` con `X-API-Key: "sk-cliente-A"`.
2.  `server.py` valida la API Key contra la tabla `clients` de Supabase y obtiene `client_id = 'uuid-A'`.
3.  Construye el filtro de Qdrant: `filter = must=[{"key": "client_id", "match": {"value": "uuid-A"}}]`.
4.  Realiza la búsqueda híbrida (semántica + keyword) con el `query` y el `filter`.
5.  Devuelve los resultados (los *payloads* de los documentos) como JSON.

---

## 7. Guardrails y Ciclo de Vida de Datos

### 7.1. Guardrails: Detección de Copyright y PII

Integrados en el `core_ingest.py`, se ejecutan antes de la desduplicación.

* **Detección de PII (Datos Personales):** Se implementa una cadena de LangChain que utiliza un LLM (Ollama) con un prompt de *few-shot* para detectar DNI, teléfonos, emails privados, etc.
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
    2.  Define un filtro de Qdrant:
        ```json
        {
          "filter": {
            "must": [
              { "key": "loaded_at", "range": { "lt": timestamp_limite } },
              { "key": "special_info", "match": { "value": false } }
            ]
          }
        }
        ```
    3.  Llama a `qdrant.delete(collection_name="semantika_prod", points_selector={"filter": filter})`.
    4.  Loguea el resultado (`action: "ttl_cleanup", deleted_count: ...`).

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
    {"level": "INFO", "timestamp": "...", "service": "core_ingest", "action": "document_added", "qdrant_id": "uuid-qdrant-1", "client_id": "uuid-A"}
    {"level": "INFO", "timestamp": "...", "service": "scheduler", "action": "ttl_cleanup", "deleted_count": 150}
    {"level": "INFO", "timestamp": "...", "service": "api", "action": "search_request", "client_id": "uuid-A", "query": "IA"}
    ```

---

## 9. Despliegue e Instalación (Docker)

### 9.1. Prerrequisitos

* Un VPS (Linux) con **Docker** y **Docker Compose** instalados.
* Un proyecto creado en **Supabase** (anotar URL y Service Key).
* (Opcional) Cuentas en APIs externas (scraper.tech, EFE...).

### 9.2. Estructura de Ficheros

````

/semantika/
├── .env                  \# Fichero de secretos (Supabase URL/Key)
├── docker-compose.yml    \# Orquestador de todos los servicios
├── Dockerfile            \# Define la imagen de la aplicación semantika
├── requirements.txt      \# Dependencias de Python
├── server.py             \# Demonio API (FastAPI)
├── scheduler.py          \# Demonio Cron (APScheduler)
├── core\_ingest.py        \# Lógica de ingesta (Guardrails, Dedupe, Carga)
├── cli.py                \# Herramienta de admin (crear clientes/tareas en Supabase)
├── /qdrant\_storage/      \# (Directorio para datos persistentes de Qdrant)
└── /ollama\_storage/      \# (Directorio para modelos persistentes de Ollama)

````

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
````

#### `requirements.txt`

```txt
fastapi
uvicorn
apscheduler
supabase-py
qdrant-client
fastembed
langchain
langchain-ollama
openai-whisper
requests
beautifulsoup4
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
    environment:
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
      - QDRANT_URL=http://qdrant:6333
      - OLLAMA_HOST=http://ollama:11434
    depends_on:
      - qdrant
      - ollama
    restart: always

  semantika-scheduler:
    build: .
    container_name: semantika-scheduler
    command: "python scheduler.py"
    environment:
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
      - QDRANT_URL=http://qdrant:6333
      - OLLAMA_HOST=http://ollama:11434
    depends_on:
      - qdrant
      - ollama
    restart: always

  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    ports:
      - "6333:6333"
    volumes:
      - ./qdrant_storage:/qdrant/storage # Persistencia de datos

  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    ports:
      - "11434:11434"
    volumes:
      - ./ollama_storage:/root/.ollama # Persistencia de modelos

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
      * Crear el fichero `.env`: `nano .env`
      * Añadir las claves:
        ```
        SUPABASE_URL="[https://tu-proyecto.supabase.co](https://tu-proyecto.supabase.co)"
        SUPABASE_KEY="tu-supabase-service-role-key"
        ```
4.  **Lanzar Servicios:**
      * Ejecutar: `docker-compose up -d --build`
5.  **Configuración Post-Instalación (Ollama):**
      * Descargar el modelo LLM que usará la aplicación (ej. `phi-3-mini`):
        ```bash
        docker exec -it ollama ollama pull phi-3-mini
        ```
6.  **Configurar Clientes y Tareas:**
      * Ejecutar el CLI dentro del contenedor para añadir tu primer cliente:
        ```bash
        docker exec -it semantika-api python cli.py add-client --name "Mi Primer Cliente"
        ```
      * (El CLI te devolverá la API Key).
      * Añadir una tarea de prueba:
        ```bash
        docker exec -it semantika-api python cli.py add-task --client-id "uuid-del-cliente" --type "web_llm" --target "[https://un-blog.com](https://un-blog.com)" --freq 60
        ```
7.  **Monitorizar:**
      * Acceder al visor de logs en `http://[IP_DEL_VPS]:8081` para ver el sistema en funcionamiento.

<!-- end list -->

```
```