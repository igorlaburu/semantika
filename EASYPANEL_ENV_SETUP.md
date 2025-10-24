# 🔧 Configurar Variables de Entorno en EasyPanel

## ❌ Problema Actual

Tus logs muestran:
```
time="2025-10-24T12:17:10Z" level=warning msg="The \"SUPABASE_URL\" variable is not set. Defaulting to a blank string."
```

Esto significa: **Las variables NO están configuradas en EasyPanel**.

---

## ✅ Solución Paso a Paso

### Paso 1: Localiza la Sección de Variables

En tu interfaz de EasyPanel, busca una de estas opciones:

- **"Environment"** o **"Environment Variables"**
- **"Env"** o **"Env Vars"**
- **"Configuration"** → **"Environment"**
- **"Settings"** → **"Environment Variables"**

📍 **Ubicación común**:
```
Tu Proyecto → semantika → Environment
```

---

### Paso 2: Método de Configuración

EasyPanel puede tener uno de estos 3 métodos:

#### **Método A: Formulario (campo por campo)**

Si ves algo como:
```
┌──────────────────────────────────┐
│ Add Environment Variable         │
├──────────────────────────────────┤
│ Name:  [___________________]     │
│ Value: [___________________]     │
│         [Add Variable]           │
└──────────────────────────────────┘
```

**HAZ ESTO** (copia/pega cada línea):

**Variable 1:**
```
Name:  SUPABASE_URL
Value: https://vasuydxhaldvpphkkarh.supabase.co
```
→ Click "Add Variable"

**Variable 2:**
```
Name:  SUPABASE_KEY
Value: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZhc3V5ZHhoYWxkdnBwaGtrYXJoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MTA0NjMyOCwiZXhwIjoyMDc2NjIyMzI4fQ.tZu-Qr_sJ4vxU1JnLTxZJrNQOZd461yXnq_SKckdSMc
```
→ Click "Add Variable"

**Variable 3:**
```
Name:  QDRANT_URL
Value: https://badc88ac-b9fd-4632-af9b-637acd47a3da.eu-central-1-0.aws.cloud.qdrant.io:6333
```
→ Click "Add Variable"

**Variable 4:**
```
Name:  QDRANT_API_KEY
Value: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.2tbbm2yFz317zB2LeScaq6yEHGhFDhN7wdLFG9VxAVY
```
→ Click "Add Variable"

**Variable 5:**
```
Name:  OPENROUTER_API_KEY
Value: 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
```
→ Click "Add Variable"

---

#### **Método B: Área de Texto (múltiples líneas)**

Si ves un cuadro grande de texto:
```
┌────────────────────────────────────┐
│ Environment Variables              │
├────────────────────────────────────┤
│                                    │
│ [____________________________]     │
│ [____________________________]     │
│ [____________________________]     │
│                                    │
│         [Save]                     │
└────────────────────────────────────┘
```

**COPIA Y PEGA TODO ESTO:**

```bash
SUPABASE_URL=https://vasuydxhaldvpphkkarh.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZhc3V5ZHhoYWxkdnBwaGtrYXJoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MTA0NjMyOCwiZXhwIjoyMDc2NjIyMzI4fQ.tZu-Qr_sJ4vxU1JnLTxZJrNQOZd461yXnq_SKckdSMc
QDRANT_URL=https://badc88ac-b9fd-4632-af9b-637acd47a3da.eu-central-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.2tbbm2yFz317zB2LeScaq6yEHGhFDhN7wdLFG9VxAVY
OPENROUTER_API_KEY=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
```

→ Click "Save" o "Apply"

---

#### **Método C: Archivo .env**

Si hay opción de subir archivo `.env`:

1. **Crea un archivo llamado `.env`** en tu computadora
2. **Pega este contenido**:

```bash
SUPABASE_URL=https://vasuydxhaldvpphkkarh.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZhc3V5ZHhoYWxkdnBwaGtrYXJoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MTA0NjMyOCwiZXhwIjoyMDc2NjIyMzI4fQ.tZu-Qr_sJ4vxU1JnLTxZJrNQOZd461yXnq_SKckdSMc
QDRANT_URL=https://badc88ac-b9fd-4632-af9b-637acd47a3da.eu-central-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.2tbbm2yFz317zB2LeScaq6yEHGhFDhN7wdLFG9VxAVY
OPENROUTER_API_KEY=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
```

3. **Sube el archivo** en EasyPanel (botón "Upload .env" o similar)

---

### Paso 3: Guardar y Aplicar

⚠️ **MUY IMPORTANTE**:

1. **Click "Save"** o **"Apply"** o **"Update"**
2. **NO** solo cierres la ventana
3. Busca confirmación: "Variables saved" o "Environment updated"

---

### Paso 4: Reiniciar el Servicio

Después de guardar las variables:

1. Ve a **Actions** o **Controls**
2. Click **"Restart"** o **"Redeploy"**
3. Espera 2-3 minutos

⚠️ **Nota**: Un simple "Deploy" puede no ser suficiente. Necesitas **"Restart"** para que tome las nuevas variables.

---

## ✅ Verificar que Funcionó

### 1. Revisa los Logs

Después del restart, los logs deberían verse así:

✅ **ANTES** (mal):
```
level=warning msg="The \"SUPABASE_URL\" variable is not set"
```

✅ **DESPUÉS** (bien):
```json
{"level": "INFO", "action": "supabase_connected", "url": "https://vasuydxhaldvpphkkarh.supabase.co"}
{"level": "INFO", "action": "server_starting", "port": 8000}
```

### 2. Test en Console

Si EasyPanel tiene una "Console" o "Shell" en el servicio:

```bash
echo $SUPABASE_URL
```

Debería mostrar:
```
https://vasuydxhaldvpphkkarh.supabase.co
```

Si muestra **nada** → las variables NO están aplicadas.

---

## 🐛 Troubleshooting

### Problema: "Variables guardadas pero logs siguen igual"

**Causa**: No reiniciaste el servicio

**Solución**:
1. Después de guardar variables
2. **Reinicia** (no solo re-deploy)
3. Espera a que arranque completamente

---

### Problema: "No encuentro dónde poner variables"

**Solución**:
1. Toma una captura de pantalla de tu interfaz EasyPanel
2. Compártela conmigo
3. Te diré exactamente dónde están

---

### Problema: "Al pegar da error de formato"

**Causa**: Caracteres invisibles o espacios extra

**Solución**:
1. Copia **solo el valor** (sin nombre de variable si ya está el campo)
2. Ejemplo:
   ```
   Name: SUPABASE_URL
   Value: https://vasuydxhaldvpphkkarh.supabase.co
   ```
   NO copies `SUPABASE_URL=` en el campo Value

---

## 📸 ¿Necesitas Ayuda Visual?

Si no encuentras dónde configurar las variables:

1. **Toma captura** de tu pantalla de EasyPanel
2. **Muéstramela**
3. Te diré **exactamente** dónde hacer click

---

## 🎯 Checklist

- [ ] Abre sección "Environment" en EasyPanel
- [ ] Añade las 5 variables obligatorias
- [ ] Click "Save" o "Apply"
- [ ] Ve confirmación de guardado
- [ ] Click "Restart" (no solo "Deploy")
- [ ] Espera 2-3 minutos
- [ ] Revisa logs → ya NO debe aparecer warning
- [ ] Ve mensaje: `{"level": "INFO", "action": "supabase_connected"}`

---

## ✅ Cuando Funcione

Verás logs como estos:

```json
{"level": "INFO", "timestamp": "2025-10-24T...", "service": "supabase_client", "action": "supabase_connected", "url": "https://vasuydxhaldvpphkkarh.supabase.co"}

{"level": "INFO", "timestamp": "2025-10-24T...", "service": "api", "action": "server_starting", "host": "0.0.0.0", "port": 8000, "log_level": "INFO"}

{"level": "INFO", "timestamp": "2025-10-24T...", "service": "scheduler", "action": "scheduler_starting"}

{"level": "INFO", "timestamp": "2025-10-24T...", "service": "scheduler", "action": "apscheduler_started"}
```

¡Sin warnings! 🎉

---

## 💡 Siguiente Paso

Una vez que veas logs limpios (sin warnings):

```bash
# En Console de semantika-api
python cli.py add-client --name "Test Client"
```

---

¿Necesitas que te guíe con capturas de pantalla de tu EasyPanel? ¡Compártelas! 📸
