# Despliegue en EasyPanel

Guía paso a paso para desplegar **semantika** en EasyPanel.

---

## 📋 Requisitos Previos

Antes de empezar, necesitas tener configurados estos servicios externos:

### 1. **Supabase** (Base de datos)
- Crea un proyecto en [supabase.com](https://supabase.com)
- Ejecuta el schema SQL (ver sección abajo)
- Copia:
  - **Project URL**: `https://tu-proyecto.supabase.co`
  - **Service Role Key**: desde Project Settings → API

### 2. **Qdrant Cloud** (Vector database)
- Crea un cluster en [cloud.qdrant.io](https://cloud.qdrant.io)
- Copia:
  - **Cluster URL**: `https://xxxxx.aws.cloud.qdrant.io:6333`
  - **API Key**: desde el dashboard del cluster

### 3. **OpenRouter** (LLM API)
- Crea cuenta en [openrouter.ai](https://openrouter.ai)
- Genera API Key: `sk-or-v1-xxxxx`
- Recarga créditos (mínimo $5)

---

## 🗄️ Configurar Supabase

1. Ve a tu proyecto Supabase → **SQL Editor**
2. Ejecuta este schema:

```sql
-- Tabla de clientes (tenants)
CREATE TABLE IF NOT EXISTS clients (
    client_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_name TEXT NOT NULL,
    email TEXT,
    api_key TEXT UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Tabla de tareas programadas
CREATE TABLE IF NOT EXISTS tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK (source_type IN ('web_llm', 'twitter', 'api_efe', 'api_reuters', 'api_wordpress', 'manual')),
    target TEXT NOT NULL,
    frequency_min INTEGER NOT NULL CHECK (frequency_min > 0),
    config JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    last_run TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Tabla de credenciales API (opcional)
CREATE TABLE IF NOT EXISTS api_credentials (
    credential_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    service_name TEXT NOT NULL,
    credentials JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    UNIQUE(client_id, service_name)
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_clients_api_key ON clients(api_key);
CREATE INDEX IF NOT EXISTS idx_tasks_client_id ON tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(is_active) WHERE is_active = true;

-- Función para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger para clients
DROP TRIGGER IF EXISTS update_clients_updated_at ON clients;
CREATE TRIGGER update_clients_updated_at
    BEFORE UPDATE ON clients
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

## 🚀 Despliegue en EasyPanel

### Paso 1: Crear Proyecto en EasyPanel

1. Accede a tu panel de EasyPanel
2. Click en **"Create Project"**
3. Nombre del proyecto: `semantika`
4. Selecciona tu servidor

### Paso 2: Conectar GitHub

1. En el proyecto, click **"Create Service"** → **"Git"**
2. Conecta tu cuenta de GitHub
3. Selecciona el repositorio: `igorlaburu/semantika`
4. Branch: `main`
5. Docker Compose file: `docker-compose.prod.yml`

### Paso 3: Configurar Variables de Entorno

En EasyPanel, ve a **Environment Variables** y añade:

```bash
# Supabase
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu-service-role-key-aqui

# Qdrant Cloud
QDRANT_URL=https://xxxxx.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=tu-qdrant-api-key
QDRANT_COLLECTION_NAME=semantika_prod

# OpenRouter
OPENROUTER_API_KEY=sk-or-v1-tu-clave-aqui
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_FAST_MODEL=openai/gpt-4o-mini

# Configuración (opcional - usa defaults)
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
SIMILARITY_THRESHOLD=0.98
DATA_TTL_DAYS=30
LOG_LEVEL=INFO

# Monitores (deshabilitados por defecto)
FILE_MONITOR_ENABLED=false
EMAIL_MONITOR_ENABLED=false
```

### Paso 4: Configurar Puertos y Dominios

1. **semantika-api**:
   - Puerto interno: `8000`
   - Configura dominio público: `api.semantika.tudominio.com` (o usa el dominio de EasyPanel)

2. **dozzle** (logs):
   - Puerto interno: `8080`
   - Configura dominio: `logs.semantika.tudominio.com`

3. **semantika-scheduler**:
   - No necesita puerto público (solo interno)

### Paso 5: Deploy

1. Click **"Deploy"**
2. EasyPanel construirá las imágenes y arrancará los servicios
3. Espera 2-3 minutos (primera vez tarda más)

---

## ✅ Verificar Deployment

### 1. Health Check
```bash
curl https://api.semantika.tudominio.com/health
```

Respuesta esperada:
```json
{
  "status": "ok",
  "timestamp": "2025-10-24T...",
  "service": "semantika-api",
  "version": "0.1.0"
}
```

### 2. Crear Cliente de Prueba

**Opción A: Via CLI en EasyPanel**

1. Ve a **semantika-api** → **Console**
2. Ejecuta:
```bash
python cli.py add-client --name "Test Client" --email "test@example.com"
```

3. Guarda el API Key generado: `sk-xxxxx`

**Opción B: Manualmente en Supabase**

1. Ve a Supabase → **Table Editor** → `clients`
2. Insert row:
   - `client_name`: "Test Client"
   - `email`: "test@example.com"
   - `api_key`: `sk-test-12345678901234567890` (o genera uno con `openssl rand -hex 32`)
   - `is_active`: `true`

### 3. Probar API

```bash
# Autenticación
curl https://api.semantika.tudominio.com/me \
  -H "X-API-Key: sk-xxxxx"

# Ingestar texto
curl -X POST https://api.semantika.tudominio.com/ingest/text \
  -H "X-API-Key: sk-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Machine learning está revolucionando la industria tecnológica.",
    "title": "Test Document",
    "metadata": {"source": "test"}
  }'

# Buscar
curl "https://api.semantika.tudominio.com/search?query=machine%20learning&limit=5" \
  -H "X-API-Key: sk-xxxxx"
```

### 4. Verificar Logs

1. Ve a `https://logs.semantika.tudominio.com` (Dozzle)
2. O en EasyPanel: **semantika-api** → **Logs**

Deberías ver:
```json
{"level": "INFO", "action": "server_starting", "host": "0.0.0.0", "port": 8000}
{"level": "INFO", "action": "scheduler_starting"}
{"level": "INFO", "action": "tasks_loaded", "count": 0}
```

---

## 🔧 Gestión via CLI

Todos los comandos se ejecutan en la **Console** de EasyPanel (servicio `semantika-api`):

```bash
# Listar clientes
python cli.py list-clients

# Crear tarea programada
python cli.py add-task \
  --client-id "uuid-del-cliente" \
  --type web_llm \
  --target "https://techcrunch.com/category/artificial-intelligence" \
  --freq 60

# Listar tareas
python cli.py list-tasks

# Borrar tarea
python cli.py delete-task --task-id "uuid-de-la-tarea"

# Info de Qdrant
python cli.py qdrant-info
```

---

## 🔄 Actualizaciones

EasyPanel puede configurarse para auto-deploy cuando haces push a GitHub:

1. Ve a tu proyecto → **Settings** → **Build Settings**
2. Habilita **Auto Deploy**
3. Cada push a `main` desplegará automáticamente

---

## 🐛 Troubleshooting

### Error: "Connection refused" al iniciar

**Causa**: Supabase/Qdrant no accesibles

**Solución**:
1. Verifica URLs y API Keys en Environment Variables
2. Prueba conectividad desde Console:
```bash
curl -I https://tu-proyecto.supabase.co
curl -I https://xxxxx.aws.cloud.qdrant.io:6333
```

### Error: "Module not found"

**Causa**: Build falló o incompleto

**Solución**:
1. Ve a **Logs** del build
2. Verifica que `requirements.txt` se instaló correctamente
3. Rebuild: **Actions** → **Rebuild**

### Scheduler no ejecuta tareas

**Causa**: No hay tareas activas o scheduler no arrancó

**Solución**:
1. Verifica logs de `semantika-scheduler`
2. Comprueba que hay tareas: `python cli.py list-tasks`
3. Reinicia scheduler: **Actions** → **Restart**

### API devuelve 500 en /ingest/text

**Causa**: OpenRouter API Key inválida o sin créditos

**Solución**:
1. Verifica API Key en [openrouter.ai](https://openrouter.ai)
2. Comprueba que tienes créditos disponibles
3. Revisa logs: busca `openrouter_error`

---

## 📊 Monitoreo

### Dozzle (Logs en tiempo real)
- URL: `https://logs.semantika.tudominio.com`
- Filtra por servicio (api/scheduler)
- JSON structured logs

### Supabase
- Monitorea tablas: clients, tasks
- SQL queries directas para analytics

### Qdrant
- Dashboard: tu cluster en cloud.qdrant.io
- Monitorea:
  - Número de vectores
  - Queries por segundo
  - Storage usado

---

## 🔒 Seguridad

### Recomendaciones:

1. **Rotar API Keys periódicamente**
   ```sql
   UPDATE clients
   SET api_key = 'sk-nuevo-key-aqui'
   WHERE client_id = 'uuid';
   ```

2. **Nunca expongas**:
   - `SUPABASE_KEY` (service role)
   - `QDRANT_API_KEY`
   - `OPENROUTER_API_KEY`

3. **HTTPS obligatorio**:
   - EasyPanel usa HTTPS automático vía Let's Encrypt
   - No expongas puertos HTTP directamente

4. **Firewall Qdrant**:
   - En Qdrant Cloud, restringe IPs permitidas (opcional)

---

## 💰 Costos Estimados

- **Supabase**: Free tier (hasta 500MB)
- **Qdrant Cloud**: $25/mes (1GB cluster)
- **OpenRouter**: Variable (~$0.01-0.10 por 1000 docs)
- **EasyPanel**: Según tu plan de hosting

**Total estimado**: $30-50/mes para uso medio

---

## 📞 Soporte

- **Issues**: [github.com/igorlaburu/semantika/issues](https://github.com/igorlaburu/semantika/issues)
- **Logs**: Revisa Dozzle primero
- **Status**: Verifica `/health` endpoint

---

¡Listo! Tu instancia de semantika debería estar funcionando en EasyPanel. 🚀
