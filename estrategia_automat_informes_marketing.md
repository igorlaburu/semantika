# Estrategia de Automatización de Informes de Marketing

## Resumen Ejecutivo

Sistema automatizado para generar informes PDF profesionales de campañas de marketing digital, diseñado para GasteizHoy y extensible a otras agencias.

**Cliente principal**: GasteizHoy (gasteizhoy.com) - agencia de marketing digital  
**Clientes finales**: 30+ empresas variables cada mes (Agromotor, etc.)  
**Input**: Email con datos + imágenes O APIs directas de plataformas  
**Output**: PDF branded profesional (7 páginas, estilo corporativo)

---

## Análisis: Dos Enfoques Posibles

### Opción A: Email Manual
**Flujo**: GasteizHoy copia/pega datos → Envía email → Sistema genera PDF

**Ventajas**:
- ✅ Funciona sin credenciales de terceros
- ✅ Implementación más rápida
- ✅ No requiere acceso a cuentas de clientes

**Desventajas**:
- ❌ Requiere trabajo manual mensual
- ❌ Propenso a errores humanos
- ❌ No escalable para 30+ clientes
- ❌ Datos pueden estar incompletos

### Opción B: APIs Directas ⭐ RECOMENDADA
**Flujo**: Sistema obtiene datos automáticamente → Genera PDF → Envía

**Ventajas**:
- ✅ **Automatización total**: Scheduler ejecuta sin intervención
- ✅ **Datos precisos**: Directos desde plataformas
- ✅ **Escalable**: 30 clientes o 300, mismo esfuerzo
- ✅ **Tiempo real**: Datos siempre actualizados
- ✅ **Históricos**: Informes de cualquier periodo

**Desventajas**:
- ⚠️ Requiere credenciales/tokens por cliente
- ⚠️ Setup inicial más complejo

---

## APIs Disponibles y Viabilidad

### 1. Meta Business (Facebook + Instagram) ✅ MUY VIABLE

**API**: Meta Marketing API / Graph API  
**Autenticación**: OAuth 2.0 + Access Tokens de larga duración  
**Complejidad**: Media  
**Coste**: Gratis (límites generosos)

**Datos disponibles**:
- Alcance, impresiones, clics
- Engagement (likes, shares, comments)
- Demografía de audiencia
- Costes por campaña (CPC, CPM, CTR)
- Insights de posts específicos
- Métricas de Instagram Business

**Setup por cliente**:
- Access Token (renovable)
- Ad Account ID
- App ID + App Secret (una vez para todos)

**Código ejemplo**:
```python
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount

FacebookAdsApi.init(
    app_id=settings.meta_app_id,
    app_secret=settings.meta_app_secret,
    access_token=client_credentials['meta_access_token']
)

account = AdAccount(f"act_{client_meta_ad_account_id}")
campaigns = account.get_campaigns(fields=[
    'name', 'spend', 'impressions', 'clicks', 
    'cpc', 'cpm', 'ctr', 'reach'
])
```

---

### 2. Google Analytics (GA4) ✅ MUY VIABLE

**API**: Google Analytics Data API (GA4)  
**Autenticación**: OAuth 2.0 + Service Account  
**Complejidad**: Media  
**Coste**: Gratis (cuotas muy altas)

**Datos disponibles**:
- Lectores únicos
- Visitas, pageviews
- Fuentes de tráfico (Facebook, Twitter, Direct, etc.)
- Tiempo en página, bounce rate
- Conversiones

**Setup por cliente**:
- Service Account JSON
- Property ID (GA4)

**Código ejemplo**:
```python
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest

client = BetaAnalyticsDataClient(credentials=service_account_creds)

request = RunReportRequest(
    property=f"properties/{ga4_property_id}",
    date_ranges=[{"start_date": "2025-10-01", "end_date": "2025-10-31"}],
    dimensions=[{"name": "pagePath"}, {"name": "source"}],
    metrics=[
        {"name": "activeUsers"},
        {"name": "sessions"},
        {"name": "screenPageViews"}
    ]
)

response = client.run_report(request)
```

---

### 3. Google Ads (Display/Banner) ✅ VIABLE

**API**: Google Ads API  
**Autenticación**: OAuth 2.0  
**Complejidad**: Media-Alta  
**Coste**: Gratis

**Datos disponibles**:
- Impresiones de banners/display
- Clics en anuncios
- CPC, CPM, CTR
- Conversiones

**Setup por cliente**:
- Developer Token (una vez)
- Customer ID
- OAuth Refresh Token

**Código ejemplo**:
```python
from google.ads.googleads.client import GoogleAdsClient

client = GoogleAdsClient.load_from_dict(credentials_dict)
ga_service = client.get_service("GoogleAdsService")

query = """
    SELECT 
        campaign.name,
        metrics.impressions,
        metrics.clicks,
        metrics.cost_micros,
        metrics.ctr
    FROM campaign
    WHERE segments.date BETWEEN '2025-10-01' AND '2025-10-31'
"""

response = ga_service.search(customer_id=client_customer_id, query=query)
```

---

### 4. Twitter/X ⚠️ COMPLICADO (Mantener email)

**API**: Twitter Ads API (requiere aprobación) o API v2 básica  
**Complejidad**: Alta (Ads) / Media (v2)  
**Coste**: $100/mes+ para Ads API

**Recomendación**: **Mantener datos Twitter via email** - menos crítico y API compleja

---

## Arquitectura del Sistema

### Sistema de Email Monitoring Actual

**Flujo existente**:
```
Email llega a: contact@ekimen.ai
Patrón: p.{company_code}@ekimen.ai
  ↓
Tabla email_routing (pattern matching)
  ↓
Source (email type)
  ↓
Company + Organization
  ↓
Workflow (custom o default)
```

**Ejemplo**:
```
p.demo@ekimen.ai 
  → email_routing (exact match, priority 200)
  → source: "Email Principal"
  → company: "Demo Company"
  → workflow: "demo"
```

---

### Nueva Source para GasteizHoy

#### 1. Company
```sql
INSERT INTO companies (company_code, company_name, is_active)
VALUES ('gasteizhoy', 'GasteizHoy - Informes', true);
```

#### 2. Source
```sql
INSERT INTO sources (
  source_name,
  source_type,
  source_code,
  company_id,
  workflow_code,
  is_active,
  config
) VALUES (
  'GasteizHoy - Generación Informes PDF',
  'email',
  'gasteizhoy_reports',
  (SELECT id FROM companies WHERE company_code = 'gasteizhoy'),
  'gasteizhoy',
  true,
  '{
    "description": "Recibe datos de campañas y genera informes PDF profesionales",
    "expected_attachments": ["images"],
    "auto_reply": true
  }'::jsonb
);
```

#### 3. Email Routing
```sql
INSERT INTO email_routing (
  email_pattern,
  pattern_type,
  priority,
  source_id
) VALUES (
  'p.informegh@ekimen.ai',
  'exact',
  200,
  (SELECT source_id FROM sources WHERE source_code = 'gasteizhoy_reports')
);
```

---

### Estructura de Archivos

```
/workflows/gasteizhoy/
├── __init__.py
├── gasteizhoy_workflow.py          # Clase GasteizhoyWorkflow
├── pdf_generator.py                # Generador PDF con WeasyPrint
├── metrics_extractor.py            # Extrae métricas del email con LLM
├── api_connectors/
│   ├── __init__.py
│   ├── meta_connector.py           # Meta Marketing API
│   ├── ga4_connector.py            # Google Analytics 4
│   └── google_ads_connector.py     # Google Ads
├── templates/
│   ├── campaign_report.html        # Template HTML del PDF
│   └── email_reply.html            # Template email respuesta
├── styles/
│   └── report.css                  # Estilos CSS del PDF
└── assets/
    ├── gasteizhoy_logo.png         # Logo GasteizHoy
    └── footer_logo.png             # Logo pie de página
```

---

### Tabla de Credenciales API

```sql
CREATE TABLE client_api_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    client_final_name VARCHAR(255),  -- "Agromotor", "Cliente2", etc.
    
    -- Meta/Facebook
    meta_access_token TEXT,
    meta_ad_account_id VARCHAR(50),
    meta_token_expires_at TIMESTAMPTZ,
    
    -- Google Analytics
    ga4_property_id VARCHAR(50),
    ga4_service_account_json JSONB,
    
    -- Google Ads
    google_ads_customer_id VARCHAR(50),
    google_ads_refresh_token TEXT,
    
    -- Twitter (opcional)
    twitter_bearer_token TEXT,
    
    -- Configuración
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(company_id, client_final_name)
);
```

---

## Flujo Completo del Sistema

### Modo 1: Email Manual (Fase 1)

```
1. Email llega a: contact@ekimen.ai con TO: p.informegh@ekimen.ai
   ├─ Asunto: "Informe Agromotor - Feria Outlet"
   ├─ Cuerpo: Datos estructurados de métricas
   └─ Adjuntos: Screenshots Instagram/Facebook (PNG/JPG)

2. MultiCompanyEmailMonitor detecta el email
   ├─ Extrae TO header: "p.informegh@ekimen.ai"
   ├─ Busca en email_routing → encuentra source_id
   └─ Obtiene: company (gasteizhoy), organization, source

3. Crea SourceContent con:
   ├─ source_type: "email"
   ├─ text_content: Asunto + Cuerpo + Transcripciones
   ├─ raw_content: {
   │     "subject": "Informe Agromotor...",
   │     "body": "Cliente: Agromotor\nCampaña: ...",
   │     "from": "marketing@gasteizhoy.com",
   │     "attachments": [
   │       {"type": "image", "filename": "instagram.png", "content": <bytes>}
   │     ]
   │   }
   └─ organization_slug: "gasteizhoy"

4. workflow_factory.get_workflow("gasteizhoy")
   ├─ Intenta importar: workflows.gasteizhoy.gasteizhoy_workflow
   ├─ Busca clase: GasteizhoyWorkflow
   └─ Usa custom workflow

5. GasteizhoyWorkflow.process_content(source_content)
   ├─ Extrae métricas del email con LLM (GPT-4o-mini)
   │   └─ Parsea: cliente, campaña, fecha, investment, facebook, instagram, etc.
   │
   ├─ Procesa imágenes adjuntas
   │   └─ Convierte a base64 para embeber en PDF
   │
   ├─ Genera conclusiones profesionales con LLM (Sonnet 4.5)
   │   └─ Prompt estilo GasteizHoy: "▀ El artículo ha llegado a..."
   │
   ├─ Genera PDF (WeasyPrint + Jinja2)
   │   ├─ Renderiza template HTML con datos
   │   ├─ Aplica estilos CSS branded
   │   ├─ Genera portada con imagen de fondo
   │   ├─ Crea páginas de métricas (tablas formateadas)
   │   ├─ Inserta imágenes de redes sociales
   │   ├─ Añade página de conclusiones
   │   └─ Genera PDF bytes
   │
   ├─ Guarda PDF en Supabase Storage
   │   └─ Path: informes/gasteizhoy/{fecha}/{cliente}_{campaña}.pdf
   │
   ├─ Envía PDF por email (SMTP)
   │   ├─ TO: Email remitente original
   │   ├─ Subject: "Informe generado: {cliente} - {campaña}"
   │   ├─ Body HTML: Email profesional con link descarga
   │   └─ Attachment: PDF
   │
   └─ Retorna context_unit con metadata

6. Log execution en tabla executions
   ├─ source_name: "GasteizHoy - Generación Informes PDF"
   ├─ status: "success"
   ├─ details: "Informe generado para Agromotor - Feria Outlet"
   └─ duration_ms: ~15000
```

---

### Modo 2: APIs Automáticas (Fases 2-5)

```
1. Scheduler ejecuta tarea programada (ej: día 1 de cada mes)

2. Para cada cliente en client_api_credentials (activos):
   ├─ Fetch Meta API (Facebook + Instagram)
   │   └─ Alcance, interacciones, clics, inversión
   │
   ├─ Fetch Google Analytics (artículo específico)
   │   └─ Lectores únicos, visitas, fuentes de tráfico
   │
   ├─ Fetch Google Ads (banner/display)
   │   └─ Impresiones, clics, CPC, CPM, CTR
   │
   └─ Genera conclusiones con LLM basado en datos

3. Genera PDF automáticamente (mismo flujo)

4. Envía PDF a:
   ├─ GasteizHoy (internal@gasteizhoy.com)
   └─ O directamente al cliente final (configurable)

5. GasteizHoy recibe 30 PDFs listos sin hacer nada
```

---

## Implementación: Plan por Fases

### Fase 1: Base Email Manual (MVP)
**Objetivo**: Sistema funcional end-to-end con email

**Tareas**:
1. ✅ Crear company + source + email_routing en BD
2. ✅ Crear estructura `/workflows/gasteizhoy/`
3. ✅ Implementar `GasteizhoyWorkflow`:
   - `metrics_extractor.py`: LLM extrae métricas del email
   - `pdf_generator.py`: WeasyPrint + Jinja2
   - Template HTML con estilo GasteizHoy
4. ✅ Implementar envío email con attachment (SMTP)
5. ✅ Testing con email real

**Dependencias**:
```txt
weasyprint>=60.0
jinja2>=3.1.0
pillow>=10.0.0
cairocffi>=1.6.0
```

**Tiempo estimado**: 2-3 días  
**Entregable**: PDF generado desde email manual

---

### Fase 2: Meta API (Facebook + Instagram)
**Objetivo**: Obtener datos automáticamente de Meta

**Tareas**:
1. ✅ Crear tabla `client_api_credentials`
2. ✅ Implementar `api_connectors/meta_connector.py`
3. ✅ Modificar workflow: modo híbrido
   - Si hay credenciales API → fetch de Meta
   - Si no → usar datos del email
4. ✅ Configurar Meta App (una vez para todos los clientes)
5. ✅ Documentar setup de Access Token por cliente

**Dependencias**:
```txt
facebook-business>=19.0.0
```

**Tiempo estimado**: 1-2 días  
**Entregable**: Datos precisos de Facebook/Instagram desde API

---

### Fase 3: Google Analytics (GA4)
**Objetivo**: Métricas precisas de artículos web

**Tareas**:
1. ✅ Implementar `api_connectors/ga4_connector.py`
2. ✅ Añadir campos GA4 a `client_api_credentials`
3. ✅ Modificar workflow para incluir GA4 data
4. ✅ Documentar setup Service Account

**Dependencias**:
```txt
google-analytics-data>=0.18.0
```

**Tiempo estimado**: 1 día  
**Entregable**: Lectores únicos y tráfico desde GA4

---

### Fase 4: Google Ads (Display/Banner)
**Objetivo**: Métricas de campañas display

**Tareas**:
1. ✅ Implementar `api_connectors/google_ads_connector.py`
2. ✅ Añadir campos Google Ads a `client_api_credentials`
3. ✅ Modificar workflow para incluir Ads data
4. ✅ Documentar setup Developer Token + OAuth

**Dependencias**:
```txt
google-ads>=23.0.0
```

**Tiempo estimado**: 1-2 días  
**Entregable**: Datos de impresiones, clics, CPC/CPM desde Ads

---

### Fase 5: Scheduler Automático
**Objetivo**: Generación masiva sin intervención

**Tareas**:
1. ✅ Crear source tipo "scheduled" para informes
2. ✅ Configurar APScheduler job mensual
3. ✅ Implementar generación batch (loop clientes)
4. ✅ Sistema de notificaciones si falla algún cliente
5. ✅ Dashboard de estado (opcional)

**Tiempo estimado**: 1 día  
**Entregable**: 30 PDFs generados automáticamente cada mes

---

## Configuración Adicional

### Environment Variables (.env)
```bash
# Existing...
IMAP_HOST=...
IMAP_USER=contact@ekimen.ai

# SMTP para envío de PDFs
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@ekimen.ai
SMTP_PASSWORD=...
SMTP_FROM_NAME=Semantika Reports

# Supabase Storage
SUPABASE_STORAGE_BUCKET=informes

# Meta API (Fase 2)
META_APP_ID=...
META_APP_SECRET=...

# Google API (Fases 3-4)
GOOGLE_DEVELOPER_TOKEN=...
```

---

## Ejemplo: Email de Test

```
TO: p.informegh@ekimen.ai
FROM: marketing@gasteizhoy.com
SUBJECT: Informe Agromotor - Feria Outlet

BODY:
Cliente: Agromotor
Campaña: Feria Outlet
Fecha: 14.10.2025

INVERSIÓN:
Total: 888799.20
Instagram: 299
Facebook: 0
Banner: 384.42

ARTÍCULO:
Lectores únicos: 6309
Visitas: 6777
Coste por lector: 0.13

FACEBOOK:
Alcance: 19607
Interacciones: 72
Comentarios: 1
Compartido: 8
Tráfico: 1078 (16%)

INSTAGRAM:
Descubrimiento: 38505
Clics: 1758 (26%)
Inversión: 299
Coste por clic: 0.17
Coste por cuenta: 0.008

TWITTER:
Alcance: 4694
RT: 1
MG: 6
Tráfico: 264 (4%)

BANNER:
Impresiones: 473341
Clics: 325
CPC: 1.18
CPM: 0.81
CTR: 0.07
Duración: 10 días

ATTACHMENTS:
- instagram_screenshot1.png
- instagram_screenshot2.png
- facebook_post.png
```

**Resultado esperado**:
1. Sistema procesa email en <30s
2. Extrae todas las métricas con LLM
3. Genera PDF de 7 páginas profesional
4. Envía PDF a marketing@gasteizhoy.com
5. Guarda en storage para histórico
6. Crea context_unit en BD con metadata

---

## Ventajas del Sistema

### Para GasteizHoy:
✅ **Ahorro de tiempo**: De 30 min/informe → 0 min (automático)  
✅ **Escalabilidad**: 1 cliente o 100, mismo esfuerzo  
✅ **Consistencia**: Todos los informes con mismo formato profesional  
✅ **Datos precisos**: API elimina errores de copia/pega  
✅ **Históricos**: Todos los informes guardados y accesibles  

### Para Clientes Finales:
✅ **Profesionalidad**: Informes branded de alta calidad  
✅ **Transparencia**: Datos verificables desde plataformas oficiales  
✅ **Automatización**: Reciben informes puntualmente cada mes  

### Para el Sistema:
✅ **Extensible**: Fácil añadir nuevas métricas o plataformas  
✅ **Replicable**: Mismo sistema para otras agencias  
✅ **Trazable**: Todo registrado en BD para auditoría  

---

## Próximos Pasos

1. ✅ **Aprobar estrategia** y decidir enfoque inicial
2. ✅ **Configurar BD**: Company, source, email_routing
3. ✅ **Implementar Fase 1**: Email → PDF funcional
4. ✅ **Testing** con datos reales de Agromotor
5. ✅ **Iterar**: Añadir APIs según prioridad

---

## Decisión Recomendada

🎯 **Enfoque Pragmático**:
1. Empezar con **Fase 1 (Email)** → validar concepto rápido (2-3 días)
2. Añadir **Fase 2 (Meta API)** inmediatamente → máximo valor (1-2 días)
3. **Fase 3 (GA4)** si GasteizHoy gestiona Analytics de clientes (1 día)
4. **Fase 4 (Google Ads)** si gestionan campañas display (1-2 días)
5. **Fase 5 (Scheduler)** cuando quieran full-automation (1 día)

**Ventaja**: Cada fase es independiente y añade valor incremental. Pueden empezar a usar el sistema con email mientras se construyen las integraciones API.

**Total Fase 1-2**: ~4-5 días para sistema funcional con Meta API  
**Total Fase 1-5**: ~8-10 días para sistema completamente automatizado

---

## Contacto y Soporte

**Desarrollado por**: Semantika Team  
**Fecha**: Noviembre 2025  
**Versión**: 1.0
