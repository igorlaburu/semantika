# EasyPanel Setup: Dos Opciones

Dependiendo de las capacidades de tu EasyPanel, tienes 2 formas de desplegar semantika.

---

## 🔍 Identifica Tu Caso

Mira la interfaz de EasyPanel en "Build Configuration":

### ✅ CASO 1: Ves opción "Docker Compose"
Si en el campo "Tipo" o "Build Type" ves opciones como:
- [ ] Dockerfile
- [x] Docker Compose
- [ ] Buildpack

→ **Sigue la OPCIÓN A (Docker Compose)**

### ✅ CASO 2: Solo ves "Dockerfile"
Si solo puedes elegir Dockerfile y no hay opción Docker Compose:

→ **Sigue la OPCIÓN B (Servicios Individuales)**

---

## OPCIÓN A: Docker Compose (Recomendada)

### Ventajas
- ✅ Deploy de 3 servicios con 1 clic
- ✅ Configuración única de variables
- ✅ Networking automático entre servicios
- ✅ Más fácil de mantener

### Configuración

1. **Crear Servicio en EasyPanel**
   - Nombre: `semantika`
   - Tipo: **Git Repository**

2. **Source Configuration**
   ```
   Propietario: igorlaburu
   Repositorio: semantika
   Rama: main
   ```

3. **Build Configuration**
   ```
   Tipo: Docker Compose
   Archivo: docker-compose.prod.yml
   Ruta: /
   ```

4. **Environment Variables**

   Copia TODAS estas variables (mínimo requerido):

   ```bash
   # Supabase
   SUPABASE_URL=https://tu-proyecto.supabase.co
   SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

   # Qdrant Cloud
   QDRANT_URL=https://xxxxx.aws.cloud.qdrant.io:6333
   QDRANT_API_KEY=tu-api-key-aqui
   QDRANT_COLLECTION_NAME=semantika_prod

   # OpenRouter
   OPENROUTER_API_KEY=sk-or-v1-tu-clave-aqui
   OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
   OPENROUTER_DEFAULT_MODEL=anthropic/claude-3.5-sonnet
   OPENROUTER_FAST_MODEL=openai/gpt-4o-mini

   # Configuración
   CHUNK_SIZE=1000
   CHUNK_OVERLAP=200
   SIMILARITY_THRESHOLD=0.98
   DATA_TTL_DAYS=30
   LOG_LEVEL=INFO

   # Monitores (deshabilitados)
   FILE_MONITOR_ENABLED=false
   EMAIL_MONITOR_ENABLED=false
   ```

5. **Domain Configuration**

   Después del deploy, configura dominios para:
   - `semantika-api` → Puerto 8000 → `api.tudominio.com`
   - `dozzle` → Puerto 8081 → `logs.tudominio.com`

6. **Deploy**
   - Click "Deploy" o "Create Service"
   - Espera 2-3 minutos

### Resultado
Verás 3 containers corriendo:
```
✅ semantika-api (8000)
✅ semantika-scheduler (interno)
✅ dozzle (8081)
```

---

## OPCIÓN B: Servicios Individuales

### Ventajas
- ✅ Funciona en cualquier EasyPanel
- ✅ Control granular por servicio
- ✅ Puedes escalar cada uno independientemente

### Desventajas
- ⚠️ Más trabajo inicial (3 servicios)
- ⚠️ Variables duplicadas
- ⚠️ Networking manual entre servicios

### Configuración

Debes crear **3 servicios separados**:

---

#### **SERVICIO 1: semantika-api**

**1. Crear Servicio**
- Nombre: `semantika-api`
- Tipo: Git Repository

**2. Source**
```
Propietario: igorlaburu
Repositorio: semantika
Rama: main
Ruta de compilación: /
```

**3. Build**
```
Tipo: Dockerfile
Archivo: Dockerfile
```

**4. Deployment**
```
Comando: uvicorn server:app --host 0.0.0.0 --port 8000 --workers 2
Puerto: 8000
```

**5. Environment Variables**
```bash
# Todas las variables (mismo bloque que OPCIÓN A)
SUPABASE_URL=...
SUPABASE_KEY=...
QDRANT_URL=...
# ... etc
```

**6. Domain**
```
Puerto 8000 → api.tudominio.com
```

---

#### **SERVICIO 2: semantika-scheduler**

**1. Crear Servicio**
- Nombre: `semantika-scheduler`
- Tipo: Git Repository

**2. Source**
```
Propietario: igorlaburu
Repositorio: semantika
Rama: main
Ruta de compilación: /
```

**3. Build**
```
Tipo: Dockerfile
Archivo: Dockerfile
```

**4. Deployment**
```
Comando: python scheduler.py
Puerto: (ninguno - solo interno)
```

**5. Environment Variables**
```bash
# MISMAS variables que semantika-api
SUPABASE_URL=...
SUPABASE_KEY=...
QDRANT_URL=...
# ... etc
```

**6. Networking**
- Asegúrate que está en la misma red que `semantika-api`
- Algunos EasyPanel requieren configurar "Service Links" o "Internal Network"

---

#### **SERVICIO 3: dozzle (Logs)**

**1. Crear Servicio**
- Nombre: `dozzle`
- Tipo: **Docker Image** (NO Git!)

**2. Image**
```
Imagen: amir20/dozzle:latest
```

**3. Deployment**
```
Puerto: 8080 → exponer en 8081
```

**4. Volumes**
```
/var/run/docker.sock:/var/run/docker.sock:ro
```
⚠️ Esto permite a Dozzle leer logs de Docker

**5. Environment Variables**
```bash
DOZZLE_LEVEL=info
DOZZLE_TAILSIZE=300
DOZZLE_FILTER=name=semantika
```

**6. Domain**
```
Puerto 8081 → logs.tudominio.com
```

---

### Networking entre Servicios (OPCIÓN B)

Si creas servicios separados, necesitas que se comuniquen:

**En `semantika-scheduler`:**
- Debe poder conectarse a Supabase (externo - OK por defecto)
- Debe poder conectarse a Qdrant (externo - OK por defecto)

**En `dozzle`:**
- Necesita acceso a Docker socket
- Filtra containers por nombre "semantika"

EasyPanel automáticamente crea una red interna, así que deberían poder comunicarse.

---

## 🆚 Comparación Rápida

| Característica | OPCIÓN A (Compose) | OPCIÓN B (Individual) |
|---|---|---|
| **Facilidad setup** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Mantenimiento** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Flexibilidad** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Control granular** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Variables env** | 1 lugar | 3 lugares |
| **Deploy time** | 1 click | 3 clicks |

---

## ✅ Verificación Post-Deploy

Independientemente de la opción que uses:

**1. Health Check**
```bash
curl https://api.tudominio.com/health
```

**2. Verificar logs**
- Ve a `https://logs.tudominio.com` (Dozzle)
- O en EasyPanel: Ve a cada servicio → Logs

Deberías ver:
```json
{"level": "INFO", "action": "server_starting", "port": 8000}
{"level": "INFO", "action": "scheduler_starting"}
{"level": "INFO", "action": "tasks_loaded", "count": 0}
```

**3. Crear cliente de prueba**

En Console de `semantika-api`:
```bash
python cli.py add-client --name "Test" --email "test@example.com"
```

**4. Test completo**
```bash
./verify-deployment.sh https://api.tudominio.com sk-xxxxx
```

---

## 🐛 Troubleshooting

### Problema: "Service won't start"
**Causa**: Variables de entorno faltantes o incorrectas

**Solución**:
1. Ve a Logs del servicio
2. Busca error específico
3. Verifica variables:
   ```bash
   # En Console del servicio
   env | grep SUPABASE
   env | grep QDRANT
   env | grep OPENROUTER
   ```

### Problema: "Cannot connect to Qdrant"
**Causa**: URL o API Key incorrecta

**Solución**:
1. Verifica en Qdrant Cloud que el cluster está UP
2. Copia de nuevo la URL (incluye puerto `:6333`)
3. Verifica que el API Key es correcto
4. Prueba conectividad:
   ```bash
   curl -H "api-key: TU_KEY" https://tu-cluster.qdrant.io:6333/collections
   ```

### Problema: "Scheduler doesn't execute tasks"
**Causa**: No hay tareas activas O scheduler no arrancó

**Solución**:
1. Verifica que el servicio `semantika-scheduler` está corriendo
2. Revisa sus logs
3. Crea una tarea de prueba:
   ```bash
   python cli.py add-task \
     --client-id "uuid" \
     --type web_llm \
     --target "https://example.com" \
     --freq 1
   ```
4. Reinicia scheduler en EasyPanel

---

## 💡 Recomendación Final

**Si EasyPanel soporta Docker Compose → USA OPCIÓN A**

Es mucho más fácil, todo está en `docker-compose.prod.yml` y se mantiene automáticamente.

**Si solo soporta Dockerfile → USA OPCIÓN B**

Es más trabajo inicial pero funciona igual de bien.

---

## 📞 Siguiente Paso

1. **Identifica** qué opción aplica a tu EasyPanel
2. **Sigue** los pasos de esa opción
3. **Verifica** con el script de verificación
4. **Avísame** si tienes algún problema

¡Estoy aquí para ayudarte! 🚀
