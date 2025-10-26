# 🔒 Guía de Seguridad - semantika

## Estado Actual de Seguridad

### ✅ Implementado

- [x] Autenticación por API Key en todos los endpoints críticos
- [x] Multi-tenancy estricto (aislamiento por client_id)
- [x] Secrets en variables de entorno (no hardcoded)
- [x] HTTPS (manejado por EasyPanel)
- [x] Logs estructurados (JSON)
- [x] Health checks sin credenciales

### ⚠️ Vulnerabilidades Conocidas

- [ ] Swagger/Docs expuesto públicamente
- [ ] Sin rate limiting
- [ ] API keys en logs (primeros 10 chars)
- [ ] Sin CORS configurado
- [ ] Sin secrets rotation automática

---

## 🔴 Vulnerabilidades Críticas

### 1. Documentación API Expuesta

**Riesgo:** Information Disclosure
**Severidad:** MEDIO

**Problema:**
```
https://api.tudominio.com/docs  ← Accesible sin autenticación
```

Cualquiera puede ver:
- Todos los endpoints disponibles
- Parámetros requeridos
- Ejemplos de requests
- Estructura de respuestas

**Solución:**

Opción A: Deshabilitar completamente (producción):
```python
# server.py
app = FastAPI(
    docs_url=None,    # Deshabilita Swagger
    redoc_url=None    # Deshabilita ReDoc
)
```

Opción B: Proteger con autenticación:
```python
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi import Depends

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html(client: Dict = Depends(get_current_client)):
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="semantika API"
    )

app = FastAPI(docs_url=None)  # Deshabilita la ruta pública
```

**Recomendación:** Usa Opción A en producción, Opción B en desarrollo.

---

### 2. Sin Rate Limiting

**Riesgo:** DDoS, Abuse, Costos Excesivos
**Severidad:** ALTO

**Problema:**
```python
# Un atacante puede hacer requests ilimitados:
while True:
    requests.post("/ingest/text", data={"text": "spam"*10000})
```

Consecuencias:
- Sobrecarga del servidor
- Costos altos en OpenRouter ($$$)
- Llenado de Qdrant
- Consumo de créditos de Supabase

**Solución:**

Instalar slowapi:
```bash
pip install slowapi
```

Implementar rate limiting:
```python
# server.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Aplicar a endpoints:
@app.post("/ingest/text")
@limiter.limit("10/minute")  # Máximo 10 requests por minuto
async def ingest_text(...):
    ...

@app.get("/search")
@limiter.limit("60/minute")  # Máximo 60 búsquedas por minuto
async def search(...):
    ...
```

**Límites recomendados:**
- `/ingest/text`: 10/min por IP
- `/ingest/url`: 5/min por IP
- `/search`: 60/min por IP
- `/aggregate`: 10/min por IP

---

### 3. API Keys Parcialmente en Logs

**Riesgo:** Credential Leakage
**Severidad:** MEDIO

**Problema:**
```python
logger.warn("invalid_api_key", api_key_prefix=api_key[:10])
# Logea: sk-test-abc
```

Si un atacante:
1. Accede a logs (Dozzle sin auth, backups, etc.)
2. Ve patrones de API keys
3. Puede intentar brute-force

**Solución:**

No loguear NINGUNA parte del API key:
```python
# Antes:
logger.warn("invalid_api_key", api_key_prefix=api_key[:10])

# Después:
logger.warn("invalid_api_key", request_ip=request.client.host)
```

---

## 🟡 Mejoras Recomendadas

### 4. CORS No Configurado

**Riesgo:** Bajo (solo si agregas frontend)
**Severidad:** BAJO

**Problema:**
Si creas un frontend web, los navegadores bloquearán requests.

**Solución:**

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.tudominio.com",  # Tu frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**NO hagas esto en producción:**
```python
allow_origins=["*"]  # ❌ Permite cualquier dominio
```

---

### 5. Secrets Rotation

**Riesgo:** Bajo (pero buena práctica)
**Severidad:** BAJO

**Problema:**
Las API keys de clientes nunca expiran.

**Solución:**

Añadir campo `expires_at` a la tabla `clients`:
```sql
ALTER TABLE clients
ADD COLUMN expires_at TIMESTAMP WITH TIME ZONE;

-- Crear función para rotar keys
CREATE OR REPLACE FUNCTION rotate_api_key(client_uuid UUID)
RETURNS TEXT AS $$
DECLARE
    new_key TEXT;
BEGIN
    new_key := 'sk-' || encode(gen_random_bytes(32), 'hex');

    UPDATE clients
    SET api_key = new_key,
        updated_at = now()
    WHERE client_id = client_uuid;

    RETURN new_key;
END;
$$ LANGUAGE plpgsql;
```

CLI command:
```python
# cli.py
async def rotate_api_key(client_id: str):
    """Rotate API key for a client."""
    # Implementar rotación
```

---

### 6. IP Whitelisting

**Riesgo:** Bajo
**Severidad:** BAJO

**Uso:** Para clientes enterprise que quieren restringir acceso por IP.

**Solución:**

Añadir a tabla `clients`:
```sql
ALTER TABLE clients
ADD COLUMN allowed_ips JSONB DEFAULT '[]';

-- Ejemplo:
UPDATE clients
SET allowed_ips = '["192.168.1.100", "10.0.0.0/8"]'::jsonb
WHERE client_id = 'xxx';
```

Middleware:
```python
@app.middleware("http")
async def check_ip_whitelist(request: Request, call_next):
    # Verificar IP del cliente contra whitelist
    ...
```

---

## 🔐 Secrets Management

### Dónde están los secrets actualmente:

```
✅ NO en código (git)
✅ En variables de entorno (EasyPanel)
⚠️ En texto plano en EasyPanel UI
```

### Mejoras:

#### Opción A: Vault (Hashicorp)
- Secretos encriptados
- Rotación automática
- Auditoría completa

#### Opción B: AWS Secrets Manager
- Integración con AWS
- Rotación automática
- Pricing: $0.40/secret/mes

#### Opción C: Supabase Vault (Built-in)
```sql
-- Guardar secrets en Supabase Vault
SELECT vault.create_secret('openrouter-api-key', 'sk-or-v1-...');

-- Leer desde código
SELECT decrypted_secret
FROM vault.decrypted_secrets
WHERE name = 'openrouter-api-key';
```

**Recomendación:** Por ahora, variables de entorno está OK. Migra a Vault cuando escales.

---

## 📋 Checklist de Seguridad

### Pre-Producción

- [x] API Keys implementadas
- [x] Multi-tenancy funcional
- [x] HTTPS habilitado
- [ ] Rate limiting implementado
- [ ] Swagger/Docs deshabilitado en producción
- [ ] Logs sin secrets
- [ ] Secrets en EasyPanel (mínimo)
- [ ] Firewall configurado
- [ ] Backups automáticos

### Post-Producción

- [ ] Secrets rotation implementada
- [ ] Monitoring de intentos de auth fallidos
- [ ] IP whitelisting (opcional)
- [ ] WAF (Web Application Firewall)
- [ ] Penetration testing
- [ ] Security audits regulares

---

## 🚨 En Caso de Brecha de Seguridad

### Si un API Key se compromete:

1. **Revocar inmediatamente:**
```bash
docker exec semantika-api python cli.py delete-client --client-id xxx
```

2. **Revisar logs:**
```sql
SELECT * FROM audit_log
WHERE client_id = 'xxx'
AND created_at > now() - interval '24 hours';
```

3. **Generar nuevo API key:**
```bash
docker exec semantika-api python cli.py add-client --name "Cliente X (nuevo)"
```

### Si credenciales de servicios se comprometen:

1. **OpenRouter:**
   - Revoca key en openrouter.ai
   - Genera nueva
   - Actualiza `OPENROUTER_API_KEY` en EasyPanel
   - Restart servicios

2. **Qdrant:**
   - Regenera API key en Qdrant Cloud dashboard
   - Actualiza `QDRANT_API_KEY`
   - Restart servicios

3. **Supabase:**
   - Regenera service role key en Supabase dashboard
   - Actualiza `SUPABASE_KEY`
   - Restart servicios

---

## 📊 Nivel de Seguridad Actual

```
AUTENTICACIÓN:     ████████░░ 80%
AUTORIZACIÓN:      ██████████ 100% (multi-tenant)
SECRETS MGMT:      ██████░░░░ 60%
RATE LIMITING:     ░░░░░░░░░░ 0%
LOGGING:           ████████░░ 80%
NETWORK:           ████████░░ 80% (HTTPS)
MONITORING:        ██████░░░░ 60%

TOTAL:             ██████░░░░ 66%
```

**Objetivo Producción:** 85%+

---

## 📞 Reporte de Vulnerabilidades

Si encuentras una vulnerabilidad de seguridad:

1. **NO** la publiques en GitHub Issues
2. Envía email a: security@tudominio.com (configurar)
3. Include: descripción, steps to reproduce, impacto
4. Tiempo de respuesta: 48 horas

---

## 🔗 Referencias

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Supabase Security](https://supabase.com/docs/guides/platform/going-into-prod)
