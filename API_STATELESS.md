# API Stateless - Procesamiento sin Almacenamiento

Endpoints para procesamiento de documentos **sin almacenamiento en Qdrant**. Diseñados para aplicaciones web que necesitan análisis y generación de contenido sin persistencia.

---

## 📋 Índice

1. [Análisis de Contenido](#análisis-de-contenido)
2. [Generación de Artículos](#generación-de-artículos)
3. [Procesamiento de URLs](#procesamiento-de-urls)
4. [Generación de Guías de Estilo](#generación-de-guías-de-estilo)

---

## 🔍 Análisis de Contenido

### POST /process/analyze

Extrae título, resumen y tags de un texto.

**Request:**
```bash
curl -X POST https://api/process/analyze \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "La Diputación Foral de Álava inauguró ayer la exposición Geoteka en la Plaza de la Provincia. La muestra permanecerá abierta hasta finales de mes.",
    "action": "analyze"
  }'
```

**Response:**
```json
{
  "status": "ok",
  "action": "analyze",
  "result": {
    "title": "Inauguración de la Exposición Geoteka en Álava",
    "summary": "La Diputación Foral de Álava ha inaugurado la exposición Geoteka en la Plaza de la Provincia, que estará disponible hasta finales de mes.",
    "tags": ["exposición", "Álava", "Geoteka", "cultura", "Vitoria"]
  },
  "text_length": 150
}
```

---

### POST /process/analyze-atomic

Extrae título, resumen, tags **y hechos atómicos** (atomic facts).

Los **hechos atómicos** son afirmaciones independientes y verificables extraídas del texto.

**Request:**
```bash
curl -X POST https://api/process/analyze-atomic \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "La Diputación Foral de Álava inauguró ayer la exposición Geoteka en la Plaza de la Provincia. La muestra incluye 50 piezas geológicas de la región. Permanecerá abierta hasta el 30 de noviembre de forma gratuita.",
    "action": "analyze_atomic"
  }'
```

**Response:**
```json
{
  "status": "ok",
  "action": "analyze_atomic",
  "result": {
    "title": "Inauguración de la Exposición Geoteka en Álava",
    "summary": "La Diputación Foral de Álava inauguró la exposición Geoteka con 50 piezas geológicas en la Plaza de la Provincia. La exposición es gratuita y estará abierta hasta el 30 de noviembre.",
    "tags": ["exposición", "Álava", "geología", "cultura", "Geoteka"],
    "atomic_facts": [
      "La Diputación Foral de Álava inauguró la exposición Geoteka.",
      "La exposición Geoteka está ubicada en la Plaza de la Provincia.",
      "La muestra incluye 50 piezas geológicas de la región.",
      "La exposición permanecerá abierta hasta el 30 de noviembre.",
      "El acceso a la exposición es gratuito."
    ]
  },
  "text_length": 200
}
```

**Características de los hechos atómicos:**
- Cada hecho es una oración completa e independiente
- Contiene una sola afirmación verificable
- Es comprensible sin contexto adicional
- No contiene opiniones ni interpretaciones

---

## ✍️ Generación de Artículos

### POST /process/redact-news

Genera un artículo periodístico profesional a partir de texto o hechos atómicos.

Puede usar una **guía de estilo personalizada** en formato Markdown para seguir el estilo de un medio específico.

#### Sin guía de estilo (estilo periodístico genérico)

**Request:**
```bash
curl -X POST https://api/process/redact-news \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "La Diputación Foral de Álava inauguró ayer la exposición Geoteka en la Plaza de la Provincia. La muestra incluye 50 piezas geológicas de la región y permanecerá abierta hasta el 30 de noviembre de forma gratuita.",
    "action": "redact_news",
    "params": {
      "language": "es"
    }
  }'
```

**Response:**
```json
{
  "status": "ok",
  "action": "redact_news",
  "result": {
    "article": "La Diputación Foral de Álava inauguró ayer la exposición 'Geoteka' en la Plaza de la Provincia de Vitoria-Gasteiz. La muestra, que estará disponible hasta el 30 de noviembre, ofrece un recorrido por la riqueza geológica de la región a través de 50 piezas seleccionadas.\n\nLa exposición presenta formaciones rocosas, minerales y fósiles que ilustran millones de años de historia geológica alavesa. Según fuentes de la Diputación, el objetivo es acercar el patrimonio geológico local a la ciudadanía de forma divulgativa.\n\nEl acceso a 'Geoteka' es gratuito y está dirigido a todos los públicos. La muestra forma parte de las iniciativas culturales de la Diputación para la promoción del conocimiento científico en la provincia.",
    "title": "La Diputación de Álava inaugura la exposición geológica 'Geoteka'",
    "summary": "La muestra 'Geoteka' presenta 50 piezas geológicas de la región en la Plaza de la Provincia hasta el 30 de noviembre con entrada gratuita.",
    "tags": ["exposición", "Álava", "geología", "Diputación", "cultura"]
  },
  "text_length": 180
}
```

#### Con guía de estilo personalizada

**Request:**
```bash
curl -X POST https://api/process/redact-news \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "La Diputación Foral de Álava inauguró ayer la exposición Geoteka...",
    "action": "redact_news",
    "params": {
      "style_guide": "# Estilo Gasteiz Hoy\n\n## Titular\n- Longitud: 6-8 palabras\n- Voz activa, tiempo presente\n- Sin artículos al inicio\n\n## Lead\n- Máximo 30 palabras\n- Responde: qué, quién, dónde\n\n## Cuerpo\n- Párrafos cortos (2-3 oraciones)\n- Uso frecuente de citas directas\n- Tono informativo local",
      "language": "es"
    }
  }'
```

**Formato de la guía de estilo:**
- Markdown estructurado
- Secciones: Titular, Lead, Cuerpo, Cierre
- Ejemplos concretos del medio
- Características estadísticas (longitud párrafos, uso de citas, etc.)

---

## 🌐 Procesamiento de URLs

### POST /process/url

Scraping de URL + procesamiento stateless en un solo paso.

Soporta las mismas acciones que el procesamiento de texto:
- `analyze`
- `analyze_atomic`
- `redact_news`

**Request (analyze):**
```bash
curl -X POST https://api/process/url \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.gasteizhoy.com/trokoniz-quiere-que-la-linea-6-de-alavabus-vuelva-al-pueblo/",
    "action": "analyze"
  }'
```

**Request (redact_news con estilo):**
```bash
curl -X POST https://api/process/url \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.gasteizhoy.com/articulo-ejemplo/",
    "action": "redact_news",
    "params": {
      "style_guide": "# Estilo...",
      "language": "es"
    }
  }'
```

**Response (analyze):**
```json
{
  "status": "ok",
  "action": "analyze",
  "result": {
    "title": "Trokoniz solicita restablecer parada de Alavabus",
    "summary": "Los vecinos de Trokoniz piden a la Diputación que restablezca la parada de la línea 6 eliminada en abril.",
    "tags": ["Trokoniz", "Alavabus", "transporte", "Álava"]
  }
}
```

---

## 📚 Generación de Guías de Estilo

### POST /styles/generate

Genera una guía de estilo en Markdown analizando artículos de ejemplo de un medio.

**Proceso:**
1. Scraping de 1-10 URLs del medio
2. Análisis estructural de cada artículo (LLM)
3. Cálculo de estadísticas agregadas
4. Generación de guía Markdown con ejemplos reales

**Request:**
```bash
curl -X POST https://api/styles/generate \
  -H "X-API-Key: sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "style_name": "Gasteiz Hoy",
    "urls": [
      "https://www.gasteizhoy.com/trokoniz-quiere-que-la-linea-6-de-alavabus-vuelva-al-pueblo/",
      "https://www.gasteizhoy.com/la-extincion-del-incendio-de-elgea-fue-ejemplar/",
      "https://www.gasteizhoy.com/otro-articulo-ejemplo/"
    ]
  }'
```

**Restricciones:**
- **Mínimo:** 1 URL
- **Máximo:** 10 URLs
- Las URLs deben ser accesibles y tener contenido suficiente (>200 caracteres)

**Response:**
```json
{
  "status": "ok",
  "style_name": "Gasteiz Hoy",
  "style_guide_markdown": "# Estilo: Gasteiz Hoy\n\n## Características Generales\n- Extensión media: 8 párrafos por artículo\n- Tono informativo y directo\n- Perspectiva local centrada en Vitoria-Gasteiz\n\n## Estructura del Titular\n- Longitud: 6-8 palabras\n- Voz activa, tiempo presente\n- Sin artículos al inicio\n\nEjemplos reales:\n- \"Trokoniz quiere que la línea 6 de Alavabus vuelva al pueblo\"\n- \"La extinción del incendio de Elgea 'fue ejemplar'\"\n\n## Apertura / Lead\n- Primer párrafo breve (máximo 30 palabras)\n- Responde: qué, quién, dónde\n\nEjemplo real:\n\"Los vecinos de Trokoniz han solicitado a la Diputación Foral de Álava la reanudación de la parada de la línea regular 6 de Alavabus...\"\n\n...",
  "articles_analyzed": 3,
  "articles_with_structure": 3,
  "generated_at": "2025-10-27T12:00:00Z"
}
```

**Contenido de la guía generada:**
- Características generales (longitud, tono, perspectiva)
- Estructura del titular (longitud, voz, ejemplos reales)
- Apertura/Lead (estructura, ejemplos reales)
- Desarrollo del cuerpo (párrafos, uso de citas)
- Tratamiento de fuentes
- Uso de datos y cifras
- Cierre del artículo
- Vocabulario característico
- Ejemplo completo de artículo

**Uso posterior:**
La guía generada (campo `style_guide_markdown`) se puede usar directamente en `/process/redact-news`:

```bash
# 1. Generar guía
STYLE=$(curl -X POST https://api/styles/generate ...)

# 2. Extraer campo style_guide_markdown y usarlo
curl -X POST https://api/process/redact-news \
  -d '{
    "text": "...",
    "action": "redact_news",
    "params": {
      "style_guide": "'"$STYLE"'",
      "language": "es"
    }
  }'
```

---

## 🔐 Autenticación

Todos los endpoints requieren header `X-API-Key`:

```bash
-H "X-API-Key: sk-xxxxxxxxxxxxxxxx"
```

---

## ⚙️ Parámetros Comunes

### `action` (requerido)
Acción a realizar:
- `analyze` - Título + resumen + tags
- `analyze_atomic` - Título + resumen + tags + hechos atómicos
- `redact_news` - Generar artículo periodístico

### `params.language` (opcional)
Idioma del contenido generado. Default: `"es"`

### `params.style_guide` (opcional)
Guía de estilo en Markdown para generación de artículos.

---

## 🚀 Casos de Uso

### 1. Extracción de Hechos de Documentos PDF

```bash
# Usuario sube PDF → Aplicación extrae texto → API
curl -X POST https://api/process/analyze-atomic \
  -H "X-API-Key: sk-xxx" \
  -d '{"text": "'"$PDF_TEXT"'", "action": "analyze_atomic"}'
```

### 2. Generación de Artículos con Estilo de Marca

```bash
# 1. Generar guía de estilo una vez
curl -X POST https://api/styles/generate \
  -d '{"style_name": "Mi Blog", "urls": ["https://miblog.com/articulo1", ...]}'

# 2. Usar guía para generar artículos
curl -X POST https://api/process/redact-news \
  -d '{
    "text": "Hechos atómicos o fuente...",
    "action": "redact_news",
    "params": {"style_guide": "'"$STYLE_GUIDE"'"}
  }'
```

### 3. Análisis Rápido de URLs

```bash
# Scraping + análisis en un paso
curl -X POST https://api/process/url \
  -d '{
    "url": "https://ejemplo.com/noticia",
    "action": "analyze_atomic"
  }'
```

---

## 📊 Límites y Consideraciones

- **Límite de texto:** Máximo 8000 caracteres procesados
- **URLs de estilo:** Mínimo 1, máximo 10
- **Timeout:** 2 minutos por request
- **Sin almacenamiento:** Ningún dato se persiste en Qdrant
- **Stateless:** Sin memoria entre requests

---

## 🐛 Errores Comunes

### Error 400: "Missing required field: action"
```json
{"detail": "Field required"}
```
**Solución:** Añadir campo `"action"` en el body del request.

### Error 400: "At least 1 URL required"
```json
{"detail": "At least 1 URL required for style analysis"}
```
**Solución:** Enviar al menos 1 URL en el array `urls`.

### Error 400: "Maximum 10 URLs allowed"
```json
{"detail": "Maximum 10 URLs allowed"}
```
**Solución:** Reducir el número de URLs a 10 o menos.

### Error 500: "No content extracted from URL"
```json
{"detail": "No content extracted from URL"}
```
**Solución:** Verificar que la URL es accesible y contiene contenido textual suficiente.

---

## 📝 Notas Técnicas

- **LLM usado:** Claude 3.5 Sonnet (via OpenRouter)
- **Scraping:** BeautifulSoup + requests
- **Respeta robots.txt:** User-agent `semantika-bot/1.0`
- **Framework:** LangChain (chains con ChatPromptTemplate)
- **Sin caché:** Cada request es independiente

---

## 📚 Ver También

- [README.md](./README.md) - Documentación general
- [DEPLOY_EASYPANEL.md](./DEPLOY_EASYPANEL.md) - Despliegue
- [CLI_USAGE.md](./CLI_USAGE.md) - Comandos CLI
