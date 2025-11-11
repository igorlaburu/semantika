# Semantika TTS Service (Piper TTS)

Servicio de Text-to-Speech usando Piper TTS con voz en español para el proyecto Semantika.

## 🎯 Características

- ✅ Voz natural en español (modelo `es_ES-davefx-medium`)
- ✅ Latencia baja (~500ms para 1000 palabras)
- ✅ Sin costos de API (auto-hospedado)
- ✅ Control de velocidad (0.5x - 2.0x)
- ✅ CORS habilitado para integración con frontend

## 🏗️ Arquitectura

```
Kazet (Frontend Next.js)
    ↓
https://api.ekimen.ai/tts/synthesize
    ↓
Reverse Proxy (Easypanel)
    ↓
semantika-tts:5000 (Docker interno)
    ↓
Piper TTS Binary
    ↓
Audio WAV
```

## 📡 API Endpoints

### POST /synthesize

Genera audio a partir de texto.

**Request:**
```json
{
  "text": "Texto a sintetizar en español",
  "rate": 1.3
}
```

**Response:**
- Status: 200
- Content-Type: `audio/wav`
- Body: Binary audio data

**Ejemplo con curl:**
```bash
curl -X POST https://api.ekimen.ai/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Hola, esto es una prueba", "rate": 1.3}' \
  --output prueba.wav
```

### GET /health

Health check del servicio.

**Response:**
```json
{
  "status": "ok",
  "service": "semantika-tts",
  "version": "1.0.0",
  "model": "es_ES-davefx-medium"
}
```

### GET /

Información del servicio y endpoints disponibles.

## 🚀 Deployment en Easypanel

### 1. Build del servicio

El servicio se construye automáticamente con `docker-compose`:

```bash
docker-compose up -d --build semantika-tts
```

### 2. Configuración del Reverse Proxy

En Easypanel, configura el dominio `api.ekimen.ai` para enrutar a:

```
Path: /tts/*
Target: http://semantika-tts:5000
Strip Prefix: /tts
```

Esto permite:
- `https://api.ekimen.ai/tts/synthesize` → `http://semantika-tts:5000/synthesize`
- `https://api.ekimen.ai/tts/health` → `http://semantika-tts:5000/health`

### 3. Variables de entorno

En tu archivo `.env`:

```bash
# URL interna (comunicación entre servicios Docker)
TTS_SERVICE_URL=http://semantika-tts:5000

# URL externa (para frontend Kazet)
TTS_EXTERNAL_URL=https://api.ekimen.ai/tts
```

## 🧪 Testing

### Test local (dentro de Docker network)

```bash
# Dentro del contenedor semantika-api
curl http://semantika-tts:5000/health
```

### Test externo (desde Kazet)

```bash
curl https://api.ekimen.ai/tts/health
```

### Test de síntesis

```bash
curl -X POST https://api.ekimen.ai/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Bienvenido a Semantika", "rate": 1.0}' \
  --output welcome.wav

# Reproducir audio
afplay welcome.wav  # macOS
# aplay welcome.wav  # Linux
```

## 🔧 Integración con Kazet (Frontend)

En tu Next.js API route (`app/api/tts/route.ts`):

```typescript
export async function POST(request: Request) {
  const { text } = await request.json()

  const response = await fetch(
    `${process.env.TTS_EXTERNAL_URL}/synthesize`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, rate: 1.3 })
    }
  )

  if (!response.ok) {
    throw new Error('TTS generation failed')
  }

  const audioBuffer = await response.arrayBuffer()

  return new Response(audioBuffer, {
    headers: {
      'Content-Type': 'audio/wav',
      'Cache-Control': 'public, max-age=3600'
    }
  })
}
```

## 📊 Especificaciones Técnicas

### Modelo de voz
- **Modelo:** `es_ES-davefx-medium.onnx`
- **Idioma:** Español (España)
- **Calidad:** Media (50 MB)
- **Voz:** Masculina, natural
- **Fuente:** [Piper Voices](https://github.com/rhasspy/piper/blob/master/VOICES.md)

### Recursos
- **RAM:** 256-512 MB
- **CPU:** 0.25-0.5 cores
- **Disco:** ~300 MB (binario + modelo)

### Límites
- **Texto máximo:** 5000 caracteres
- **Timeout:** 30 segundos
- **Velocidad:** 0.5x - 2.0x (rate parameter)

## 🔍 Troubleshooting

### Service no responde

```bash
# Ver logs
docker logs semantika-tts

# Verificar health
docker exec semantika-tts curl http://localhost:5000/health

# Restart
docker-compose restart semantika-tts
```

### Audio con cortes o distorsión

Incrementar recursos:
```yaml
semantika-tts:
  deploy:
    resources:
      limits:
        cpus: '1.0'
        memory: 1G
```

### Latencia alta

- Reducir `rate` parameter (menos procesamiento)
- Verificar CPU disponible
- Considerar modelo `low` en lugar de `medium`

## 📚 Referencias

- **Piper TTS:** https://github.com/rhasspy/piper
- **Voces disponibles:** https://github.com/rhasspy/piper/blob/master/VOICES.md
- **Samples de audio:** https://rhasspy.github.io/piper-samples/

## 📝 Logs

El servicio usa JSON structured logging compatible con Semantika:

```json
{
  "level": "INFO",
  "timestamp": "2025-01-11T12:00:00",
  "service": "piper-tts",
  "action": "tts_success",
  "audio_size": 64000,
  "estimated_duration": "2s"
}
```
