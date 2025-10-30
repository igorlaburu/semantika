# Configuración de APIs en Semantika

## Cómo funcionan las claves API en el sistema

### 1. Configuración Backend (Variables de Entorno)

Las claves API se configuran en el archivo `.env` del servidor:

```bash
# Perplexity para noticias automáticas
PERPLEXITY_API_KEY=pplx-tu-clave-aqui

# OpenRouter para LLM processing
OPENROUTER_API_KEY=sk-or-v1-tu-clave-aqui
OPENROUTER_DEFAULT_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_FAST_MODEL=openai/gpt-4o-mini

# Otros servicios
SCRAPERTECH_API_KEY=tu-clave-scrapertech
```

### 2. Flujo de Datos con APIs

```
1. Scheduler → Detecta fuente tipo "api_news"
2. Perplexity Connector → Usa PERPLEXITY_API_KEY del entorno
3. Fetch News → Obtiene noticias estructuradas
4. Workflow → Procesa con OpenRouter (OPENROUTER_API_KEY)
5. Database → Guarda resultados en Supabase
```

### 3. Frontend vs Backend

**❌ Frontend NO maneja claves API:**
- Las claves nunca se exponen al cliente
- El frontend solo recibe datos ya procesados
- Seguridad: las claves están solo en el servidor

**✅ Backend maneja todas las APIs:**
- Lee claves de variables de entorno
- Ejecuta llamadas autenticadas
- Procesa y filtra respuestas

### 4. Configuración de Fuentes API

Las fuentes API se configuran en la base de datos:

```sql
INSERT INTO sources (
  company_id,
  source_type,
  source_name,
  config,
  schedule_config,
  workflow_code
) VALUES (
  'company-uuid',
  'api_news',
  'Medios Generalistas',
  '{"location": "Bilbao, Vizcaya", "news_count": 5}',
  '{"enabled": true, "cron": "0 9 * * *"}',
  'medios_generalistas'
);
```

### 5. Ejecución Automática

**Scheduler (scheduler.py):**
- Detecta fuentes con `schedule_config.enabled = true`
- Ejecuta según `cron` expression
- Usa connector apropiado (perplexity_news_connector.py)

**Workflow Processing:**
- Usa workflow_factory para obtener el workflow correcto
- Procesa contenido con LLM (OpenRouter)
- Aplica guardrails y filtros
- Guarda en base de datos

### 6. Test de Conexión

Para verificar que Perplexity funciona:

```bash
# Añadir clave a .env
echo "PERPLEXITY_API_KEY=pplx-tu-clave-aqui" >> .env

# Ejecutar test
python3 test_perplexity_simple.py
```

### 7. Monitoreo y Logs

El sistema loguea todas las operaciones:

```json
{
  "level": "INFO",
  "timestamp": "2024-01-20T09:00:00Z",
  "service": "perplexity_news_connector",
  "action": "news_fetched",
  "count": 5,
  "location": "Bilbao"
}
```

## Próximos Pasos

1. **Obtener clave Perplexity:** https://www.perplexity.ai/settings/api
2. **Añadir a .env:** `PERPLEXITY_API_KEY=pplx-...`
3. **Ejecutar test:** `python3 test_perplexity_simple.py`
4. **Configurar fuente:** Usar API `/companies/{id}/sources` 
5. **Verificar ejecución:** Logs en `docker-compose logs semantika-scheduler`

## Seguridad

- ✅ Claves API solo en backend (.env)
- ✅ Variables de entorno no commiteadas
- ✅ Frontend recibe solo datos procesados
- ✅ Logs no exponen claves (solo prefijos)
- ✅ Validación de permisos por company_id