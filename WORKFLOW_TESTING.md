# WORKFLOW SYSTEM TESTING GUIDE

## Estado Actual

✅ **Sistema de workflow implementado** con compatibilidad total hacia atrás
✅ **Usuario demo con tier unlimited** para testing sin límites
✅ **Control de uso por tiers** (starter, pro, unlimited)
✅ **Endpoints actuales funcionando** con nuevo sistema de workflow

## Aplicar Migraciones

### Opción 1: Script Automático (Recomendado)
```bash
# Con entorno Python configurado
python3 apply_workflow_migration.py
```

### Opción 2: Manual en Supabase SQL Editor
Ejecutar en orden:
1. `sql/create_companies_schema.sql`
2. `sql/create_workflow_system.sql`
3. `sql/create_demo_user.sql`

## Testing del Sistema

### 1. Verificar Usuario Demo
```bash
curl -H "X-API-Key: sk-demo-unlimited-test-key-0000000000000000000000000000" \
     http://localhost:8000/me
```

**Respuesta esperada:**
```json
{
  "client_id": "00000000-0000-0000-0000-000000000001",
  "client_name": "Demo User",
  "email": "demo@ekimen.ai",
  "is_active": true,
  "created_at": "..."
}
```

### 2. Test Micro-Edit (Endpoint Principal)
```bash
curl -X POST \
     -H "X-API-Key: sk-demo-unlimited-test-key-0000000000000000000000000000" \
     -H "Content-Type: application/json" \
     -d '{
       "text": "El evento se realizó ayer en Madrid",
       "command": "Mejorar el estilo y añadir más detalles",
       "params": {
         "language": "es",
         "preserve_meaning": true
       }
     }' \
     http://localhost:8000/api/process/micro-edit
```

### 3. Test Análisis de Texto
```bash
curl -X POST \
     -H "X-API-Key: sk-demo-unlimited-test-key-0000000000000000000000000000" \
     -H "Content-Type: application/json" \
     -d '{
       "text": "El Gobierno ha anunciado nuevas medidas económicas para estimular el crecimiento en el sector tecnológico.",
       "action": "analyze"
     }' \
     http://localhost:8000/process/analyze
```

### 4. Test Generación de Noticias
```bash
curl -X POST \
     -H "X-API-Key: sk-demo-unlimited-test-key-0000000000000000000000000000" \
     -H "Content-Type: application/json" \
     -d '{
       "text": "Hechos: Banco Central sube tipos 0.25%. Decisión unánime. Inflación 3.2%.",
       "action": "redact_news",
       "params": {
         "language": "es"
       }
     }' \
     http://localhost:8000/process/redact-news
```

## Verificación de Logs

Los logs deben mostrar:
```json
{"level": "INFO", "service": "workflow_manager", "action": "workflow_execution_start", "workflow_code": "micro_edit", "tier": "unlimited"}
{"level": "INFO", "service": "workflow_manager", "action": "workflow_execution_success", "workflow_code": "micro_edit", "execution_time_ms": 3500}
```

## Estados Esperados

### ✅ Funcionando (Usuario Demo)
- API Key: `sk-demo-unlimited-test-key-0000000000000000000000000000`
- Tier: `unlimited` (sin límites de uso)
- Todos los workflows disponibles
- Tracking de uso activado (pero sin límites)

### ⚠️ Con Límites (Usuarios Reales)
- Tier: `starter` o `pro`
- Límites diarios/mensuales aplicados
- HTTP 429 cuando se exceden límites
- Uso registrado en `workflow_usage`

## Estructura de Base de Datos

### Tablas Nuevas
- `companies` - Empresas con tier y configuración
- `workflow_configs` - Configuración de workflows y límites
- `workflow_usage` - Tracking de uso diario/mensual

### Datos Demo
- Company: `demo` (unlimited)
- Organization: `demo`
- Client: `Demo User`

## Workflow Codes Configurados

| Código | Endpoint | Límites Starter | Límites Pro | Unlimited |
|--------|----------|----------------|-------------|-----------|
| `micro_edit` | `/api/process/micro-edit` | 500/mes, 25/día | 2000/mes, 100/día | ∞ |
| `analyze` | `/process/analyze` | 1000/mes, 50/día | 5000/mes, 200/día | ∞ |
| `analyze_atomic` | `/process/analyze-atomic` | 500/mes, 25/día | 2000/mes, 100/día | ∞ |
| `redact_news` | `/process/redact-news` | 200/mes, 10/día | 1000/mes, 50/día | ∞ |
| `style_generation` | `/styles/generate` | 10/mes, 2/día | 50/mes, 5/día | ∞ |
| `url_processing` | `/process/url` | 500/mes, 25/día | 2000/mes, 100/día | ∞ |

## Monitoreo

### Logs de Workflow
```bash
# Ver ejecuciones de workflow
docker-compose logs -f semantika-api | grep workflow_execution

# Ver límites de uso
docker-compose logs -f semantika-api | grep usage_limit
```

### Base de Datos
```sql
-- Ver uso actual del demo user
SELECT * FROM workflow_usage 
WHERE company_id = '00000000-0000-0000-0000-000000000001';

-- Ver configuraciones de workflow
SELECT workflow_code, limits_starter, limits_pro, limits_unlimited 
FROM workflow_configs;
```

## Troubleshooting

### Error: "Workflow not found"
- Verificar que `workflow_configs` tiene datos
- Ejecutar `sql/create_workflow_system.sql`

### Error: "Company not found" 
- Verificar que existe company demo
- Ejecutar `sql/create_demo_user.sql`

### Error: "Usage limit exceeded" (no debería pasar con demo)
- Verificar tier = 'unlimited' en client metadata
- Verificar company.tier = 'unlimited'

### API Key no funciona
- Verificar que el demo user existe
- API Key exacta: `sk-demo-unlimited-test-key-0000000000000000000000000000`

## Next Steps

1. **Testing completo** - Verificar todos los endpoints
2. **Crear usuarios reales** - Con tiers starter/pro  
3. **Monitoring dashboard** - Ver uso por cliente
4. **Email routing** - Implementar p.{company}@ekimen.ai
5. **Workflow factory** - Cargar workflows dinámicamente