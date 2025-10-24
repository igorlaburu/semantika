# 🚀 Auto-Deploy desde GitHub

Configura tu proyecto para que se despliegue automáticamente cuando hagas `git push origin main`.

---

## 🎯 Dos Opciones Disponibles

### **OPCIÓN 1: Auto-Deploy Nativo de EasyPanel** (Más Fácil) ⭐
- ✅ Sin configuración adicional
- ✅ Integrado en EasyPanel
- ✅ Funciona de inmediato

### **OPCIÓN 2: GitHub Actions** (Más Control)
- ✅ Control total del proceso
- ✅ Notificaciones personalizadas
- ✅ Deploy condicional (tests, etc.)

---

## OPCIÓN 1: Auto-Deploy Nativo (Recomendado)

### Paso 1: Habilitar en EasyPanel

1. **Abre tu proyecto** en EasyPanel

2. **Ve a la sección del servicio** `semantika`

3. **Busca una de estas secciones**:
   - **"Source"** o **"Git"**
   - **"Settings"** → **"Source"**
   - **"Deployment"** → **"Auto Deploy"**

4. **Busca la opción**:
   ```
   [ ] Auto Deploy
   [ ] Automatic Deployments
   [ ] Deploy on Push
   [ ] CI/CD
   ```

5. **Actívala** ✓

6. **Configura** (si hay opciones):
   ```
   Branch: main
   Auto Deploy: Enabled
   ```

7. **Guarda** los cambios

### Paso 2: Conectar GitHub (si no está conectado)

Si EasyPanel pide permisos:

1. Click **"Connect GitHub"** o **"Authorize"**
2. Autoriza a EasyPanel acceder a tu repo
3. Selecciona el repo: `igorlaburu/semantika`

### Paso 3: Probar

```bash
# Haz un cambio en el código
echo "# Test auto-deploy" >> README.md

# Commit y push
git add README.md
git commit -m "Test auto-deploy"
git push origin main

# Ve a EasyPanel → Logs
# Deberías ver: "Deployment started"
```

---

## OPCIÓN 2: GitHub Actions

Si EasyPanel NO tiene auto-deploy integrado, usa este método.

### Paso 1: Obtener Webhook URL de EasyPanel

**Método A: Buscar en EasyPanel**

1. Ve a tu servicio en EasyPanel
2. Busca sección **"Webhooks"** o **"Integrations"**
3. Copia el **"Deploy Webhook URL"**
   - Ejemplo: `https://easypanel.io/api/projects/xxxxx/deploy`

**Método B: Crear Webhook Manualmente**

Si no hay webhook visible:

1. Ve a **Settings** → **Webhooks**
2. Click **"Create Webhook"**
3. Tipo: **"Deploy"**
4. Copia la URL generada

### Paso 2: Configurar GitHub Secrets

1. **Ve a tu repo en GitHub**:
   ```
   https://github.com/igorlaburu/semantika
   ```

2. **Click**: Settings → Secrets and variables → Actions

3. **Click**: "New repository secret"

4. **Añade el secret**:
   ```
   Name: EASYPANEL_WEBHOOK_URL
   Value: https://easypanel.io/api/projects/xxxxx/deploy
   ```

5. **Click**: "Add secret"

### Paso 3: El Workflow Ya Está Creado

Ya he creado el archivo `.github/workflows/deploy-easypanel.yml` en tu repo.

Solo necesitas hacer commit y push:

```bash
git add .github/workflows/deploy-easypanel.yml
git commit -m "Add GitHub Actions auto-deploy"
git push origin main
```

### Paso 4: Verificar

1. **Ve a tu repo en GitHub**

2. **Click**: Actions

3. **Deberías ver**: "Deploy to EasyPanel" workflow running

4. **Logs** mostrarán:
   ```
   ✅ Deployment triggered successfully!
   ```

---

## 🔍 Comparación

| Característica | Opción 1 (Nativo) | Opción 2 (Actions) |
|----------------|-------------------|-------------------|
| **Facilidad** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Setup** | 2 clicks | 5 minutos |
| **Control** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Logs** | En EasyPanel | En GitHub + EasyPanel |
| **Tests pre-deploy** | ❌ | ✅ |
| **Notificaciones** | EasyPanel | Customizable |

---

## ✅ Verificar que Funciona

### Test Rápido:

```bash
# 1. Haz un cambio pequeño
echo "$(date)" >> test-autodeploy.txt

# 2. Commit
git add test-autodeploy.txt
git commit -m "Test auto-deploy at $(date +%H:%M)"

# 3. Push
git push origin main

# 4. Observa
# - Ve a GitHub Actions (si usas Opción 2)
# - Ve a EasyPanel Logs
# - Espera 2-3 minutos
# - Verifica que el servicio se reinició
```

### Qué Esperar:

**Opción 1 (Nativo):**
```
EasyPanel Logs:
→ "Received push from GitHub"
→ "Building image..."
→ "Deploying..."
→ "✅ Deployment successful"
```

**Opción 2 (Actions):**
```
GitHub Actions:
→ "Deploy to EasyPanel" workflow started
→ "Checkout code" ✓
→ "Deploy via webhook" ✓
→ "✅ Deployment triggered"

EasyPanel Logs:
→ "Deployment webhook received"
→ "Building..."
→ "Deploying..."
```

---

## 🔧 Configuración Avanzada (Opcional)

### Deploy Solo en Cambios Específicos

Si quieres deployar solo cuando cambien ciertos archivos:

**.github/workflows/deploy-easypanel.yml**:
```yaml
on:
  push:
    branches:
      - main
    paths:
      - 'src/**'
      - 'requirements.txt'
      - 'Dockerfile'
      - 'docker-compose.easypanel.yml'
```

### Deploy con Tests Previos

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: |
          python -m pytest tests/

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy
        # ... resto del workflow
```

### Notificaciones Slack/Discord

```yaml
- name: Notify Slack
  if: success()
  run: |
    curl -X POST "${{ secrets.SLACK_WEBHOOK }}" \
      -H 'Content-Type: application/json' \
      -d '{"text":"✅ semantika deployed successfully to EasyPanel!"}'
```

---

## 🐛 Troubleshooting

### "Auto-deploy no se dispara"

**Causa**: GitHub webhook no está configurado o EasyPanel no tiene acceso

**Solución**:
1. Ve a GitHub → Settings → Webhooks
2. Verifica que existe un webhook apuntando a EasyPanel
3. Si no existe, conéctalo desde EasyPanel
4. Test delivery: Click "Recent Deliveries" → "Redeliver"

### "Deployment falla inmediatamente"

**Causa**: Error en el código o Dockerfile

**Solución**:
1. Revisa logs en EasyPanel
2. Verifica que el build local funciona:
   ```bash
   docker compose -f docker-compose.easypanel.yml build
   ```
3. Arregla errores
4. Push de nuevo

### "Variables de entorno se pierden en deploy"

**Causa**: EasyPanel no persiste variables entre deploys

**Solución**:
1. Ve a EasyPanel → Environment
2. Verifica que TODAS las variables están configuradas
3. Las variables deben estar en el servicio, NO en el archivo compose
4. Re-deploy manualmente una vez para forzar actualización

### "GitHub Actions falla con 'Webhook not found'"

**Causa**: Secret `EASYPANEL_WEBHOOK_URL` incorrecto o no configurado

**Solución**:
1. Ve a GitHub → Settings → Secrets
2. Verifica que `EASYPANEL_WEBHOOK_URL` existe
3. Copia de nuevo el webhook URL desde EasyPanel
4. Actualiza el secret
5. Re-run workflow

---

## 📊 Workflow Completo

```
┌─────────────────────────────────────────────────┐
│  1. Developer                                   │
│     git commit -m "New feature"                 │
│     git push origin main                        │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  2. GitHub                                      │
│     • Recibe push                               │
│     • Dispara webhook a EasyPanel               │
│       O                                         │
│     • Ejecuta GitHub Actions workflow           │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  3. EasyPanel                                   │
│     • Recibe trigger                            │
│     • git pull del repo                         │
│     • docker compose build                      │
│     • docker compose up                         │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  4. Servicios Activos                           │
│     ✅ semantika-api (nuevo código)             │
│     ✅ semantika-scheduler (nuevo código)       │
│     ✅ dozzle (sin cambios)                     │
└─────────────────────────────────────────────────┘
```

---

## 🎯 Recomendación Final

**Para tu caso (semantika en EasyPanel):**

1. **Empieza con OPCIÓN 1** (Auto-Deploy Nativo)
   - Es más simple
   - Menos cosas que pueden fallar
   - Integración directa

2. **Si necesitas más control**, migra a OPCIÓN 2
   - Añade tests antes del deploy
   - Customiza notificaciones
   - Deploy condicional

---

## ✅ Checklist de Setup

### Opción 1:
- [ ] Abrir EasyPanel → Mi Servicio
- [ ] Buscar "Auto Deploy" o similar
- [ ] Activar toggle/checkbox
- [ ] Guardar cambios
- [ ] Test: hacer push y verificar logs

### Opción 2:
- [ ] Obtener webhook URL de EasyPanel
- [ ] Añadir secret `EASYPANEL_WEBHOOK_URL` en GitHub
- [ ] Commit del workflow `.github/workflows/deploy-easypanel.yml`
- [ ] Push a main
- [ ] Verificar en GitHub → Actions
- [ ] Verificar en EasyPanel → Logs

---

## 📞 ¿Necesitas Ayuda?

Si no encuentras la opción de Auto-Deploy en EasyPanel:

1. **Comparte una captura** de tu pantalla de configuración
2. Te diré **exactamente** dónde está
3. O te ayudo a configurar GitHub Actions

---

¡Con esto tendrás CI/CD automático! Cada `git push` desplegará automáticamente. 🚀
