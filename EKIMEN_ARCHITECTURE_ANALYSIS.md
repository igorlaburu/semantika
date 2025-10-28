# EKIMEN ARCHITECTURE ANALYSIS

## Executive Summary

Ekimen es una plataforma SaaS multi-tenant que transforma datos semánticos no estructurados en información procesable mediante LLM workflows. La arquitectura combina pipelines de ingesta, vectorización con Qdrant, y workflows LangChain para diferentes verticales (prensa, finanzas, IoT).

## Stack Tecnológico

### Core Infrastructure
- **Backend**: Python 3.10+, FastAPI, APScheduler
- **Base de Datos**: Supabase (configuración), Qdrant (vectores)
- **LLM Provider**: OpenRouter (Claude 3.5 Sonnet, GPT-4o-mini)
- **Embeddings**: fastembed (integrado en Qdrant)
- **Orquestación**: Docker Compose
- **Deployment**: GitHub Actions → VPS

### Components Architecture

```
┌─────────────────┐    ┌───────────────────┐    ┌─────────────────┐
│   semantika-api │    │semantika-scheduler│    │   qdrant-db     │
│   (FastAPI)     │◄──►│  (APScheduler)    │◄──►│  (Vector Store) │
│   Port: 8000    │    │   (Cron Jobs)     │    │   Port: 6333    │
└─────────────────┘    └───────────────────┘    └─────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Supabase Database                          │
│  • Multi-tenancy (companies, clients)                           │
│  • Workflow configs & usage tracking                            │
│  • LLM usage & cost tracking                                    │
│  • Task scheduling & execution logs                             │
└─────────────────────────────────────────────────────────────────┘
```

## Multi-Tenancy Architecture

### Company Isolation
- **Strict filtering**: Todos los queries incluyen `company_id`
- **API Key validation**: Cada request valida cliente → empresa
- **Data segregation**: Qdrant filters por `client_id`
- **Workflow isolation**: Cada empresa accede solo a sus workflows

### Email Routing System
```
p.{company_code}@ekimen.ai → Company Lookup → Workflow Execution
```
- `p.elconfidencial@ekimen.ai` → El Confidencial workflows
- `p.lavanguardia@ekimen.ai` → La Vanguardia workflows
- Configurado en `companies.settings.email_alias`

## Workflow System Architecture

### Workflow Factory Pattern
```python
workflows/
├── base_workflow.py          # Abstract base class
├── workflow_factory.py       # Dynamic loading
├── elconfidencial/
│   ├── elconfidencial_workflow.py
│   └── config.json
└── lavanguardia/
    ├── lavanguardia_workflow.py
    └── config.json
```

### Workflow Isolation & Safety
- **Dynamic imports**: `importlib.import_module()` para cargar workflows
- **Error containment**: Try/catch per workflow, no propagation
- **Timeout protection**: Límites de ejecución por workflow
- **Resource limits**: Memory/CPU bounds per execution

### Workflow Configuration
```sql
workflow_configs:
- workflow_code: 'micro_edit'
- estimated_cost_eur: 0.0125
- limits_starter: {"monthly": 500, "daily": 25}
- limits_pro: {"monthly": 2000, "daily": 100}
- avg_execution_time_ms: 3500
- primary_model: 'anthropic/claude-3.5-sonnet'
```

## Data Flow Architecture

### Ingestion Pipeline
```
Source → Guardrails (PII/Copyright) → Deduplication → Qdrant
   │            │                          │             │
   ▼            ▼                          ▼             ▼
Email/Web  LLM Analysis              Similarity      Vector Store
Audio      Privacy Check            Check 0.98      + Metadata
```

### Processing Pipeline
```
API Request → Auth → Usage Check → Workflow Factory → LLM → Response
     │          │        │              │            │       │
     ▼          ▼        ▼              ▼            ▼       ▼
Client Key  Company  Usage Limits   Dynamic Load  Track    JSON
Validation   Lookup   Validation     Execution     Costs   Result
```

## Usage Control & Economics

### Tier-Based Limits
- **Starter (149€)**: 500 micro-edits/mes, 25/día
- **Pro (250€)**: 2000 micro-edits/mes, 100/día
- **Pre-execution check**: Block if limits exceeded
- **Real-time tracking**: Daily/monthly usage counters

### Cost Tracking
```sql
llm_usage:
- organization_id, client_id
- model, prompt_tokens, completion_tokens
- estimated_cost_eur
- execution_timestamp

workflow_executions:
- workflow_id, company_id
- estimated_cost_eur (per execution)
- actual_tokens_used
- execution_time_ms
```

## Security Architecture

### API Security
- **API Key rotation**: `sk-xxxx` format, configurable TTL
- **Rate limiting**: Per client, per endpoint
- **Input validation**: Pydantic schemas
- **Error masking**: No internal details in responses

### Data Protection
- **PII Detection**: LLM-based before vectorization
- **Copyright Check**: Pattern matching antes de ingesta
- **Robots.txt**: Verification para web scraping
- **Audit logs**: All operations logged to JSON stdout

### Multi-tenant Security
- **No cross-tenant access**: Company ID filtering en todas las queries
- **Isolated workflows**: Error en un workflow no afecta otros
- **Resource isolation**: Per-company usage limits
- **Data encryption**: At rest (Supabase) y in transit (HTTPS)

## Scalability Considerations

### Horizontal Scaling
- **Stateless API**: Multiple FastAPI instances
- **Queue-based scheduling**: APScheduler con database backend
- **Vector database**: Qdrant clustering support
- **Workflow distribution**: Async execution model

### Performance Optimization
- **Embedding caching**: Qdrant built-in optimization
- **LLM response caching**: For repeated queries
- **Database indexing**: Company ID, workflow code, dates
- **Async processing**: FastAPI + async/await throughout

## Vertical Expansion Strategy

### Current: Press Vertical
- News analysis, style guides, article generation
- Source: RSS, email, direct URLs
- Workflows: analyze, redact_news, micro_edit

### Future Verticals
- **Finance**: Market analysis, report generation, compliance
- **IoT**: Sensor data analysis, alerting, predictive maintenance
- **Legal**: Document analysis, contract review, compliance checking

### Workflow Extensibility
```python
# New vertical example
class FinanceWorkflow(BaseWorkflow):
    async def analyze_market_data(self, data):
        # Specific finance analysis
        pass
    
    async def generate_report(self, analysis):
        # Financial report generation
        pass
```

## Deployment Architecture

### Production Environment
```yaml
VPS Deployment:
- Docker Compose orchestration
- GitHub Actions CI/CD
- Automated health checks
- Log aggregation (JSON stdout)
- Backup strategies (Supabase automated)
```

### Development Environment
```yaml
Local Development:
- Hot reload via volume mounts
- Local .env configuration
- Docker network isolation
- Development-specific settings
```

## Risk Mitigation

### Technical Risks
- **LLM API failures**: Retry logic + fallback models
- **Vector DB downtime**: Health checks + alerts
- **Workflow errors**: Isolation + graceful degradation
- **Rate limiting**: Usage prediction + tier management

### Business Risks
- **Cost overruns**: Real-time cost tracking + alerts
- **Usage abuse**: Strict tier limits + monitoring
- **Data leakage**: Multi-tenant isolation validation
- **Compliance**: PII detection + audit trails

## Monitoring & Observability

### Metrics Collection
- **API performance**: Response times, error rates
- **Workflow execution**: Success rates, execution times
- **LLM usage**: Token consumption, cost tracking
- **Database performance**: Query times, connection pools

### Alerting Strategy
- **Usage threshold alerts**: 80% of tier limits
- **Error rate spikes**: > 5% error rate
- **Cost anomalies**: Unexpected cost increases
- **System health**: Component availability

## Conclusion

La arquitectura Ekimen está diseñada para:
1. **Escalabilidad**: Multi-tenant desde el diseño inicial
2. **Seguridad**: Aislamiento completo entre empresas
3. **Extensibilidad**: Fácil adición de nuevos verticales
4. **Observabilidad**: Tracking completo de uso y costes
5. **Rentabilidad**: Márgenes 95-98% con control de costes

La combinación de workflows LangChain, vectorización Qdrant, y control de uso por tiers permite monetizar eficientemente el procesamiento semántico para múltiples verticales.
