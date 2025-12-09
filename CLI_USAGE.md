# 📘 Guía de Uso - semantika CLI & API

Esta guía contiene todos los comandos disponibles para gestionar clientes (CLI) y consumir la API (curl).

---

## 📋 Capítulo 1: Comandos CLI (Gestión de Clientes)

Estos comandos se ejecutan **dentro del contenedor** de `semantika-api` en el servidor.

### Acceso al CLI

**Opción A: Consola de EasyPanel**
```bash
# Directamente en la consola del servicio semantika-api
python cli.py <comando>
```

**Opción B: SSH al VPS**
```bash
# Desde tu terminal local
ssh root@tu-vps.com
docker exec -it semantika-api python cli.py <comando>
```

### Comandos Disponibles

#### 1. Listar Clientes
```bash
python cli.py list-clients
```
Muestra todos los clientes registrados con sus detalles.

#### 2. Añadir Cliente
```bash
python cli.py add-client --name "Nombre Cliente" --email "email@example.com"
```
Crea un nuevo cliente y genera una API Key única.

**Parámetros:**
- `--name`: Nombre del cliente (requerido)
- `--email`: Email del cliente (opcional pero recomendado)

**Salida:**
```
✅ Client created successfully!
   Client ID: 123e4567-e89b-12d3-a456-426614174000
   API Key: sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6
   Name: Nombre Cliente
```

#### 3. Eliminar Cliente
```bash
python cli.py delete-client --client-id <uuid>
```
Elimina un cliente y revoca su API Key.

**Parámetros:**
- `--client-id`: UUID del cliente (requerido)

**Advertencia:** Esta acción NO elimina los documentos del cliente en PostgreSQL. Solo revoca el acceso.

#### 4. Crear Company (Empresa/Organización)
```bash
python cli.py create-company --name "Nombre Empresa" --code "empresa-code" --tier "starter"
```
Crea una nueva company con su configuración inicial.

**Parámetros:**
- `--name`: Nombre de la company (requerido)
- `--code`: Código único identificador (requerido, alfanumérico con guiones)
- `--tier`: Nivel de plan (opcional, default: "starter", opciones: "starter", "pro", "unlimited")

**Salida:**
```
🏢 Company Created Successfully!
============================================================

📋 Company Details:
   Company ID: 00000000-0000-0000-0000-000000000001
   Name: Nombre Empresa
   Code: empresa-code
   Tier: starter
   Created: 2025-11-23

📝 Next Steps:
   1. Create auth users: python cli.py create-auth-user --email user@example.com --company-id 00000000-0000-0000-0000-000000000001
   2. Configure sources in Supabase
```

---

#### 5. Crear Usuario Autenticado
```bash
python cli.py create-auth-user \
  --email "usuario@empresa.com" \
  --password "SecurePass123!" \
  --company-id "00000000-0000-0000-0000-000000000001" \
  --name "Nombre Usuario"
```
Crea un usuario con autenticación JWT para acceso al frontend.

**Parámetros:**
- `--email`: Email del usuario (requerido)
- `--password`: Contraseña (requerido)
- `--company-id`: UUID de la company (requerido)
- `--name`: Nombre completo del usuario (opcional)

**Salida:**
```
🎉 User Created Successfully!
============================================================

📋 User Details:
   User ID: user-uuid-here
   Email: usuario@empresa.com
   Password: SecurePass123!
   Company: Nombre Empresa

📝 Login Credentials (share with user):
   Email: usuario@empresa.com
   Password: SecurePass123!
   URL: https://press.ekimen.ai
```

**Importante:** Este comando crea usuarios en Supabase Auth para login con JWT (frontend web). Para acceso API usar `add-client`.

---

#### 6. Verificar Conectividad
```bash
python cli.py test-connection
```
Verifica conexión con Supabase, Qdrant y OpenRouter.

**Salida:**
```json
{
  "supabase": "✅ Connected",
  "qdrant": "✅ Connected (collection: semantika_prod)",
  "openrouter": "✅ Connected (model: anthropic/claude-3.5-sonnet)"
}
```

---

## 🌐 Capítulo 2: Comandos API con curl

Estos comandos se ejecutan desde **cualquier aplicación externa** que quiera consumir la API.

### Requisitos Previos

1. **Obtener tu API Key**
```bash
# En el servidor (consola EasyPanel o SSH)
python cli.py add-client --name "Mi Aplicación" --email "app@example.com"
# Output: sk-xxxxxxxxxx
```

2. **Configurar variables de entorno** (recomendado)
```bash
export API_URL="https://tu-dominio.easypanel.app"
export API_KEY="sk-xxxxxxxxxx"
```

---

### 1. Health Check

**Sin autenticación** - Verifica que el servicio está disponible.

```bash
curl $API_URL/health
```

**Respuesta:**
```json
{
  "status": "ok",
  "timestamp": "2025-10-26T14:30:00Z",
  "service": "semantika-api",
  "version": "0.1.0"
}
```

---

### 2. Información del Cliente

**Requiere autenticación** - Muestra información del cliente autenticado.

```bash
curl -H "X-API-Key: $API_KEY" \
  $API_URL/me
```

**Respuesta:**
```json
{
  "client_id": "123e4567-e89b-12d3-a456-426614174000",
  "client_name": "Mi Aplicación",
  "email": "app@example.com",
  "is_active": true,
  "created_at": "2025-10-26T10:00:00Z"
}
```

---

### 3. Ingerir Texto

**Requiere autenticación** - Ingesta un documento de texto.

```bash
curl -X POST $API_URL/ingest/text \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Machine learning and artificial intelligence are revolutionizing the technology sector.",
    "title": "AI Revolution",
    "metadata": {
      "source": "manual",
      "category": "technology"
    },
    "skip_guardrails": false
  }'
```

**Parámetros:**
- `text` (requerido): Contenido del documento
- `title` (opcional): Título del documento
- `metadata` (opcional): Metadata personalizada (objeto JSON)
- `skip_guardrails` (opcional): Saltar detección de PII/Copyright (default: `false`)

**Respuesta:**
```json
{
  "success": true,
  "stats": {
    "chunks_created": 3,
    "chunks_ingested": 3,
    "chunks_deduplicated": 0,
    "pii_detections": 0,
    "copyright_violations": 0
  },
  "qdrant_ids": [
    "uuid-1",
    "uuid-2",
    "uuid-3"
  ],
  "message": "Text ingested successfully"
}
```

---

### 4. Ingerir URL (Web Scraping)

**Requiere autenticación** - Extrae y ingesta contenido de una URL.

```bash
curl -X POST $API_URL/ingest/url \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/article",
    "extract_multiple": false,
    "skip_guardrails": false
  }'
```

**Parámetros:**
- `url` (requerido): URL a extraer
- `extract_multiple` (opcional): Extraer múltiples artículos de la página (default: `false`)
- `skip_guardrails` (opcional): Saltar detección de PII/Copyright (default: `false`)

**Respuesta:**
```json
{
  "success": true,
  "url": "https://example.com/article",
  "articles_extracted": 1,
  "stats": {
    "chunks_created": 5,
    "chunks_ingested": 5,
    "chunks_deduplicated": 0,
    "pii_detections": 0,
    "copyright_violations": 0
  },
  "message": "URL scraped and ingested successfully"
}
```

---

### 5. Búsqueda Semántica

**Requiere autenticación** - Busca documentos similares a la consulta.

```bash
curl -G "$API_URL/search" \
  -H "X-API-Key: $API_KEY" \
  --data-urlencode "query=machine learning applications" \
  --data-urlencode "limit=5" \
  --data-urlencode "source=web"
```

**Parámetros:**
- `query` (requerido): Texto de búsqueda
- `limit` (opcional): Número máximo de resultados (default: `5`)
- `source` (opcional): Filtrar por fuente (`web`, `manual`, etc.)

**Respuesta:**
```json
[
  {
    "id": "uuid-1",
    "text": "Machine learning and artificial intelligence are revolutionizing...",
    "score": 0.92,
    "metadata": {
      "title": "AI Revolution",
      "source": "manual",
      "category": "technology",
      "created_at": "2025-10-26T14:30:00Z"
    }
  },
  {
    "id": "uuid-2",
    "text": "Applications of ML in healthcare include...",
    "score": 0.87,
    "metadata": {
      "title": "ML in Healthcare",
      "source": "web",
      "url": "https://example.com/ml-healthcare"
    }
  }
]
```

---

### 6. Agregación con Resumen LLM

**Requiere autenticación** - Busca documentos relevantes y genera un resumen con LLM.

```bash
curl -G "$API_URL/aggregate" \
  -H "X-API-Key: $API_KEY" \
  --data-urlencode "query=latest trends in artificial intelligence" \
  --data-urlencode "limit=10" \
  --data-urlencode "threshold=0.7"
```

**Parámetros:**
- `query` (requerido): Pregunta o tema para agregar
- `limit` (opcional): Número máximo de documentos a considerar (default: `10`)
- `threshold` (opcional): Umbral mínimo de similitud (0.0-1.0, default: `0.7`)

**Respuesta:**
```json
{
  "query": "latest trends in artificial intelligence",
  "summary": "Based on the analyzed documents, the latest trends in AI include:\n\n1. **Large Language Models (LLMs)**: Models like GPT-4 and Claude are enabling sophisticated natural language understanding...\n\n2. **Multimodal AI**: Integration of text, image, and audio processing...\n\n3. **AI Safety and Alignment**: Growing focus on responsible AI development...",
  "sources_used": 7,
  "sources": [
    {
      "id": "uuid-1",
      "text": "Large language models have achieved...",
      "score": 0.89,
      "metadata": {
        "title": "LLM Evolution",
        "source": "web",
        "url": "https://example.com/llm-trends"
      }
    },
    {
      "id": "uuid-2",
      "text": "Multimodal AI systems combine...",
      "score": 0.85,
      "metadata": {
        "title": "Multimodal AI",
        "source": "manual"
      }
    }
  ]
}
```

---

## 🔐 Autenticación

Todos los endpoints **excepto** `/health` y `/` requieren autenticación mediante API Key.

### Formato del Header

```bash
-H "X-API-Key: sk-xxxxxxxxxx"
```

### Códigos de Respuesta

- `200 OK`: Éxito
- `401 Unauthorized`: Falta el header `X-API-Key`
- `403 Forbidden`: API Key inválida o cliente desactivado
- `500 Internal Server Error`: Error del servidor

### Ejemplo de Error

```bash
# Sin API Key
curl $API_URL/search?query=test

# Respuesta:
{
  "detail": "Missing API Key"
}
```

```bash
# API Key inválida
curl -H "X-API-Key: sk-invalid" $API_URL/search?query=test

# Respuesta:
{
  "detail": "Invalid API Key"
}
```

---

## 🧪 Ejemplos Prácticos

### Workflow Completo

```bash
# 1. Crear cliente (en el servidor)
python cli.py add-client --name "Blog Analyzer" --email "blog@example.com"
# Output: sk-abc123...

# 2. Configurar variables (en tu aplicación local)
export API_URL="https://semantika.tu-dominio.com"
export API_KEY="sk-abc123..."

# 3. Verificar autenticación
curl -H "X-API-Key: $API_KEY" $API_URL/me

# 4. Ingestar varios artículos
curl -X POST $API_URL/ingest/url \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/ai-trends"}'

curl -X POST $API_URL/ingest/url \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/ml-applications"}'

# 5. Buscar contenido
curl -G "$API_URL/search" \
  -H "X-API-Key: $API_KEY" \
  --data-urlencode "query=machine learning" \
  --data-urlencode "limit=3"

# 6. Generar resumen
curl -G "$API_URL/aggregate" \
  -H "X-API-Key: $API_KEY" \
  --data-urlencode "query=what are the main AI trends?" \
  --data-urlencode "limit=5"
```

---

## 🐛 Troubleshooting

### Error: "Connection refused"

**Causa**: El servicio no está corriendo o la URL es incorrecta.

**Solución**:
```bash
# Verificar health check
curl $API_URL/health

# Si falla, revisar logs
docker logs semantika-api
```

---

### Error: "Invalid API Key"

**Causa**: API Key incorrecta o cliente desactivado.

**Solución**:
```bash
# Listar clientes activos (en el servidor)
python cli.py list-clients

# Verificar que el client_id existe y is_active=true
# Si no, crear nuevo cliente:
python cli.py add-client --name "New App"
```

---

### Error: "Text too long"

**Causa**: El texto excede el límite permitido.

**Solución**:
- Divide el texto en chunks más pequeños
- El límite recomendado es ~100,000 caracteres por request

---

### Error: "Quota exceeded" (OpenRouter)

**Causa**: Se agotaron los créditos de OpenRouter.

**Solución**:
1. Ve a https://openrouter.ai/credits
2. Añade créditos
3. Los requests volverán a funcionar automáticamente

---

## 📊 Límites y Recomendaciones

| Endpoint | Rate Limit (actual) | Recomendado |
|----------|---------------------|-------------|
| `/ingest/text` | Sin límite ⚠️ | 10/min |
| `/ingest/url` | Sin límite ⚠️ | 5/min |
| `/search` | Sin límite ⚠️ | 60/min |
| `/aggregate` | Sin límite ⚠️ | 10/min |

**Nota**: Actualmente NO hay rate limiting implementado. Ver `SECURITY.md` para añadirlo.

**Tamaños recomendados:**
- Texto por ingesta: < 100KB
- Documentos por búsqueda: 5-10
- Documentos por agregación: 10-20

---

## 🔗 Integración con Aplicaciones

### Python
```python
import requests

class SemantikaClient:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.headers = {"X-API-Key": api_key}

    def ingest_text(self, text: str, title: str = None):
        response = requests.post(
            f"{self.api_url}/ingest/text",
            headers=self.headers,
            json={"text": text, "title": title}
        )
        return response.json()

    def search(self, query: str, limit: int = 5):
        response = requests.get(
            f"{self.api_url}/search",
            headers=self.headers,
            params={"query": query, "limit": limit}
        )
        return response.json()

# Uso
client = SemantikaClient(
    api_url="https://semantika.tu-dominio.com",
    api_key="sk-xxx"
)

result = client.ingest_text("Document content", "Title")
print(result)
```

### JavaScript/Node.js
```javascript
class SemantikaClient {
  constructor(apiUrl, apiKey) {
    this.apiUrl = apiUrl;
    this.apiKey = apiKey;
  }

  async ingestText(text, title = null) {
    const response = await fetch(`${this.apiUrl}/ingest/text`, {
      method: 'POST',
      headers: {
        'X-API-Key': this.apiKey,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ text, title })
    });
    return response.json();
  }

  async search(query, limit = 5) {
    const params = new URLSearchParams({ query, limit });
    const response = await fetch(`${this.apiUrl}/search?${params}`, {
      headers: { 'X-API-Key': this.apiKey }
    });
    return response.json();
  }
}

// Uso
const client = new SemantikaClient(
  'https://semantika.tu-dominio.com',
  'sk-xxx'
);

const result = await client.ingestText('Document content', 'Title');
console.log(result);
```

---

## 📚 Referencias

- **API Docs**: `https://tu-dominio.easypanel.app/docs` (Swagger UI)
- **ReDoc**: `https://tu-dominio.easypanel.app/redoc` (Documentación alternativa)
- **Código fuente**: `server.py` - Todos los endpoints
- **Seguridad**: `SECURITY.md` - Mejores prácticas de seguridad

---

## ✅ Checklist de Inicio Rápido

- [ ] Desplegar en EasyPanel
- [ ] Configurar variables de entorno
- [ ] Crear primer cliente: `python cli.py add-client --name "Test"`
- [ ] Copiar API Key generada
- [ ] Test health check: `curl $API_URL/health`
- [ ] Test autenticación: `curl -H "X-API-Key: $API_KEY" $API_URL/me`
- [ ] Ingerir primer documento
- [ ] Hacer primera búsqueda
- [ ] Generar primer resumen con agregación

---

**¿Listo para empezar?** Ejecuta:
```bash
python cli.py add-client --name "Mi Primera App" --email "test@example.com"
```
