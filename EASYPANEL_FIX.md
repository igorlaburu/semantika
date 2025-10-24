# 🔧 Solución a Errores de EasyPanel

## 🔴 Problemas Detectados

Has encontrado estos errores:

1. ❌ **Variables de entorno vacías** - No configuraste las variables en EasyPanel
2. ⚠️ **`container_name` causa conflictos** - EasyPanel maneja los nombres automáticamente
3. ⚠️ **`ports` puede causar conflictos** - EasyPanel expone puertos automáticamente
4. ⚠️ **`version` está obsoleto** - Docker Compose ya no lo usa
5. ❌ **Archivo incorrecto** - Estás usando `docker-compose.yml` en vez del correcto

---

## ✅ SOLUCIÓN COMPLETA

### Paso 1: Usa el Archivo Correcto

He creado un nuevo archivo optimizado para EasyPanel: **`docker-compose.easypanel.yml`**

**Cambios realizados:**
- ❌ Eliminado `version: '3.8'` (obsoleto)
- ❌ Eliminado `container_name` (EasyPanel lo gestiona)
- ❌ Eliminado `ports` → Cambiado a `expose` (EasyPanel expone automáticamente)
- ✅ Eliminado filtro `DOZZLE_FILTER` (verás todos los containers)
- ✅ Mantenido todo lo demás igual

**En EasyPanel, cambia:**
```
Archivo: docker-compose.yml          ❌ INCORRECTO
          ↓
Archivo: docker-compose.easypanel.yml  ✅ CORRECTO
```

---

### Paso 2: Configurar Variables de Entorno en EasyPanel

**IMPORTANTE**: Debes configurar estas variables en la interfaz de EasyPanel.

#### 📍 Dónde configurarlas:

1. Ve a tu proyecto en EasyPanel
2. Busca la sección **"Environment Variables"** o **"Variables de Entorno"**
3. Añade TODAS estas variables:

#### 🔑 Variables REQUERIDAS (obligatorias):

```bash
SUPABASE_URL=https://vasuydxhaldvpphkkarh.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZhc3V5ZHhoYWxkdnBwaGtrYXJoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MTA0NjMyOCwiZXhwIjoyMDc2NjIyMzI4fQ.tZu-Qr_sJ4vxU1JnLTxZJrNQOZd461yXnq_SKckdSMc

QDRANT_URL=https://badc88ac-b9fd-4632-af9b-637acd47a3da.eu-central-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.2tbbm2yFz317zB2LeScaq6yEHGhFDhN7wdLFG9VxAVY

OPENROUTER_API_KEY=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
```

⚠️ **ESTAS SON TUS CREDENCIALES REALES** (las leí de tu `.env` local)

#### ⚙️ Variables OPCIONALES (con defaults):

```bash
QDRANT_COLLECTION_NAME=semantika_prod
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_FAST_MODEL=openai/gpt-4o-mini

CHUNK_SIZE=1000
CHUNK_OVERLAP=200
SIMILARITY_THRESHOLD=0.98
DATA_TTL_DAYS=30
LOG_LEVEL=INFO

FILE_MONITOR_ENABLED=false
EMAIL_MONITOR_ENABLED=false
```

Si no las pones, usarán los valores por defecto.

---

### Paso 3: Configuración Visual en EasyPanel

#### **Opción A: Interfaz Gráfica**

Si EasyPanel tiene una UI para variables de entorno:

1. **Ve a:** Proyecto → Settings → Environment Variables
2. **Añade cada variable** una por una:
   ```
   Nombre: SUPABASE_URL
   Valor: https://vasuydxhaldvpphkkarh.supabase.co

   [Añadir Variable]

   Nombre: SUPABASE_KEY
   Valor: eyJhbGciOiJIUzI...

   [Añadir Variable]

   ... (continúa con todas)
   ```

3. **Guarda los cambios**

#### **Opción B: Archivo .env**

Si EasyPanel permite subir un archivo `.env`:

1. **Crea un archivo llamado `.env`** con este contenido:

```bash
# Copia exactamente esto en tu .env

SUPABASE_URL=https://vasuydxhaldvpphkkarh.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZhc3V5ZHhoYWxkdnBwaGtrYXJoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MTA0NjMyOCwiZXhwIjoyMDc2NjIyMzI4fQ.tZu-Qr_sJ4vxU1JnLTxZJrNQOZd461yXnq_SKckdSMc

QDRANT_URL=https://badc88ac-b9fd-4632-af9b-637acd47a3da.eu-central-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.2tbbm2yFz317zB2LeScaq6yEHGhFDhN7wdLFG9VxAVY
QDRANT_COLLECTION_NAME=semantika_prod

OPENROUTER_API_KEY=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
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_FAST_MODEL=openai/gpt-4o-mini

CHUNK_SIZE=1000
CHUNK_OVERLAP=200
SIMILARITY_THRESHOLD=0.98
DATA_TTL_DAYS=30
LOG_LEVEL=INFO

FILE_MONITOR_ENABLED=false
EMAIL_MONITOR_ENABLED=false
```

2. **Súbelo a EasyPanel** (si hay opción de "Upload .env file")

#### **Opción C: Variable de entorno múltiple**

Algunos paneles permiten pegar todas las variables a la vez:

```bash
SUPABASE_URL=https://vasuydxhaldvpphkkarh.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZhc3V5ZHhoYWxkdnBwaGtrYXJoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MTA0NjMyOCwiZXhwIjoyMDc2NjIyMzI4fQ.tZu-Qr_sJ4vxU1JnLTxZJrNQOZd461yXnq_SKckdSMc
QDRANT_URL=https://badc88ac-b9fd-4632-af9b-637acd47a3da.eu-central-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.2tbbm2yFz317zB2LeScaq6yEHGhFDhN7wdLFG9VxAVY
OPENROUTER_API_KEY=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
```

---

### Paso 4: Re-deploy

1. **Guarda** todas las variables de entorno
2. **Cambia** el archivo Docker Compose a `docker-compose.easypanel.yml`
3. **Re-deploy** el servicio (botón "Deploy" o "Restart")

---

## 🔍 Verificar que Funciona

Después del re-deploy, verifica:

### 1. **Revisa los logs** (ya no deberían aparecer warnings):

✅ **Antes** (con errores):
```
level=warning msg="The \"SUPABASE_URL\" variable is not set"
level=warning msg="container_name is used in semantika-api"
```

✅ **Después** (sin errores):
```
{"level": "INFO", "action": "server_starting", "port": 8000}
{"level": "INFO", "action": "supabase_connected", "url": "https://vasuydxhaldvpphkkarh.supabase.co"}
{"level": "INFO", "action": "scheduler_starting"}
```

### 2. **Test health check**:
```bash
curl https://tu-dominio.easypanel.app/health
```

Debería responder:
```json
{
  "status": "ok",
  "timestamp": "2025-10-24T...",
  "service": "semantika-api",
  "version": "0.1.0"
}
```

---

## 📊 Configuración de Puertos en EasyPanel

Una vez desplegado, configura los dominios:

### **semantika-api**
```
Puerto interno: 8000
Dominio público: api.semantika.tudominio.com
```

### **dozzle**
```
Puerto interno: 8080
Dominio público: logs.semantika.tudominio.com
```

### **semantika-scheduler**
```
Sin puerto público (solo interno)
```

---

## 🐛 Troubleshooting

### Error: "Variables still not set"

**Causa**: Las variables no se aplicaron correctamente

**Solución**:
1. Ve a EasyPanel → Tu servicio → Environment
2. Verifica que TODAS las variables están ahí
3. Click "Save" o "Apply"
4. **Importante**: Haz un **"Restart"** (no solo re-deploy)

### Error: "Cannot connect to Supabase/Qdrant"

**Causa**: Variables con espacios o caracteres extra

**Solución**:
1. Copia las variables **sin espacios** ni saltos de línea
2. No incluyas comillas extras
3. Ejemplo correcto:
   ```
   SUPABASE_URL=https://...
   ```
   No:
   ```
   SUPABASE_URL="https://..."  ← Mal (comillas extra)
   SUPABASE_URL= https://...   ← Mal (espacio extra)
   ```

### Dozzle no muestra logs

**Causa**: Volumen de Docker socket no montado

**Solución**:
1. Verifica que en EasyPanel el servicio `dozzle` tiene el volumen:
   ```
   /var/run/docker.sock:/var/run/docker.sock:ro
   ```
2. Si no está, añádelo manualmente en la configuración del servicio

---

## 📝 Resumen de Cambios

| Problema | Antes | Después |
|----------|-------|---------|
| **Archivo** | `docker-compose.yml` | `docker-compose.easypanel.yml` |
| **Version** | `version: '3.8'` | (eliminado) |
| **Container name** | `container_name: semantika-api` | (eliminado) |
| **Ports** | `ports: - "8000:8000"` | `expose: - "8000"` |
| **Variables** | No configuradas | Todas configuradas en EasyPanel |

---

## ✅ Checklist Final

- [ ] Cambiar archivo a `docker-compose.easypanel.yml`
- [ ] Configurar todas las variables de entorno en EasyPanel
- [ ] Eliminar el servicio anterior (opcional)
- [ ] Hacer nuevo deploy
- [ ] Verificar logs (sin warnings)
- [ ] Test health check
- [ ] Configurar dominios públicos
- [ ] Crear primer cliente de prueba

---

## 🚀 Siguiente Paso

Una vez que veas logs sin errores:

```bash
# En la Console de EasyPanel (servicio semantika-api)
python cli.py add-client --name "Test" --email "test@example.com"
```

Esto creará tu primer cliente y te dará un API Key para probar.

---

¿Necesitas ayuda configurando las variables en EasyPanel? Dime qué interfaz ves y te guío paso a paso. 👍
