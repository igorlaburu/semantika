# EKIMEN PRICING & COMMERCIAL STRATEGY
## Press Vertical Implementation

### Executive Summary

Ekimen Press es una plataforma SaaS que automatiza el análisis y generación de contenido periodístico mediante IA. Con márgenes del 95-98%, ofrecemos workflows especializados para medios de comunicación con tarifas competitivas y escalables.

---

## PRICING TIERS

### 🚀 STARTER PLAN - 149€/mes
**Ideal para medios locales y freelancers**

| Workflow | Límite Mensual | Límite Diario | Descripción |
|----------|----------------|---------------|-------------|
| **Análisis de Artículos** | 1,000 análisis | 50/día | Extrae título, resumen, tags |
| **Micro-Edición** | 500 ediciones | 25/día | Correcciones y mejoras de estilo |
| **Generación de Noticias** | 200 artículos | 10/día | De hechos atómicos a artículo |
| **Análisis Atómico** | 500 análisis | 25/día | Extracción de hechos verificables |
| **Guías de Estilo** | 5 guías | 1/día | Generación desde artículos ejemplo |

**Incluye:**
- API completa con documentación
- Entrada por email (p.{codigo}@ekimen.ai)
- Ingesta automática RSS/web
- Soporte por email
- Dashboard de uso

---

### 🏢 PRO PLAN - 250€/mes
**Para medios medianos y agencias**

| Workflow | Límite Mensual | Límite Diario | Descripción |
|----------|----------------|---------------|-------------|
| **Análisis de Artículos** | 5,000 análisis | 200/día | Extrae título, resumen, tags |
| **Micro-Edición** | 2,000 ediciones | 100/día | Correcciones y mejoras de estilo |
| **Generación de Noticias** | 1,000 artículos | 50/día | De hechos atómicos a artículo |
| **Análisis Atómico** | 2,000 análisis | 100/día | Extracción de hechos verificables |
| **Guías de Estilo** | 20 guías | 3/día | Generación desde artículos ejemplo |

**Incluye todo Starter +:**
- Workflows personalizados
- Integración Slack/Teams
- Soporte prioritario
- Analytics avanzado
- Backup automático

---

## WORKFLOWS DETALLADOS

### 📊 Análisis de Artículos
**Endpoint:** `POST /process/analyze`

**Entrada:**
```json
{
  "text": "El Gobierno ha anunciado nuevas medidas económicas...",
  "params": {
    "language": "es",
    "extract_entities": true
  }
}
```

**Salida:**
```json
{
  "title": "Gobierno anuncia paquete de medidas económicas",
  "summary": "El ejecutivo presenta un plan de estímulo...",
  "tags": ["economía", "gobierno", "política fiscal"],
  "entities": ["Gobierno", "medidas económicas"],
  "sentiment": "neutral",
  "readability_score": 7.2
}
```

**Casos de uso:**
- Clasificación automática de noticias
- Generación de metadatos SEO
- Análisis de tendencias

---

### ✏️ Micro-Edición
**Endpoint:** `POST /api/process/micro-edit`

**Entrada:**
```json
{
  "text": "El evento se realizó ayer en Madrid con gran éxito",
  "command": "Mejorar el estilo y añadir más detalles",
  "params": {
    "style_guide_id": "el-confidencial-style",
    "max_length": 200,
    "preserve_meaning": true
  }
}
```

**Salida:**
```json
{
  "original_text": "El evento se realizó ayer en Madrid...",
  "edited_text": "La conferencia se celebró este martes en la capital, congregando a más de 500 asistentes...",
  "explanation": "Mejoras: especificidad temporal, localización precisa, datos cuantitativos",
  "word_count_change": +12,
  "style_improvements": ["precisión temporal", "datos específicos"]
}
```

**Casos de uso:**
- Mejora de borradores
- Adaptación a guía de estilo
- Corrección de estilo

---

### 📰 Generación de Noticias
**Endpoint:** `POST /process/redact-news`

**Entrada:**
```json
{
  "text": "Hechos: Banco Central sube tipos 0.25%. Decisión unánime. Inflación 3.2%.",
  "params": {
    "style_guide": "## Estilo El País\n- Títulos concisos\n- Lead de 40 palabras máximo...",
    "language": "es",
    "target_length": 300
  }
}
```

**Salida:**
```json
{
  "title": "El Banco Central eleva los tipos de interés un 0,25% ante la inflación",
  "lead": "La decisión, adoptada por unanimidad, busca contener el alza de precios que alcanzó el 3,2% interanual.",
  "article": "El Banco Central decidió ayer elevar los tipos de interés oficiales...",
  "word_count": 287,
  "estimated_reading_time": "1 min 30 seg"
}
```

**Casos de uso:**
- Generación rápida de noticias de última hora
- Cobertura de eventos en tiempo real
- Adaptación de notas de prensa

---

### 🔬 Análisis Atómico
**Endpoint:** `POST /process/analyze-atomic`

**Entrada:**
```json
{
  "text": "La empresa XYZ reportó beneficios de 100M€ en Q3, un aumento del 15% respecto al año anterior. El CEO declaró que esperan crecer un 20% en 2024.",
  "params": {
    "fact_types": ["financial", "quotes", "predictions"]
  }
}
```

**Salida:**
```json
{
  "atomic_facts": [
    {
      "fact": "XYZ reportó 100M€ de beneficios en Q3",
      "type": "financial_result",
      "verifiable": true,
      "source_span": "beneficios de 100M€ en Q3"
    },
    {
      "fact": "Aumento del 15% respecto año anterior",
      "type": "financial_comparison",
      "verifiable": true
    },
    {
      "fact": "CEO espera 20% crecimiento en 2024",
      "type": "prediction",
      "verifiable": false,
      "attribution": "CEO de XYZ"
    }
  ]
}
```

**Casos de uso:**
- Fact-checking automatizado
- Separación hechos/opiniones
- Verificación de fuentes

---

### 🎨 Generación de Guías de Estilo
**Endpoint:** `POST /styles/generate`

**Entrada:**
```json
{
  "style_name": "Estilo El Confidencial",
  "urls": [
    "https://elconfidencial.com/articulo1",
    "https://elconfidencial.com/articulo2",
    "https://elconfidencial.com/articulo3"
  ]
}
```

**Salida:**
```markdown
# Guía de Estilo: El Confidencial

## Características principales
- **Tono**: Directo y analítico
- **Estructura**: Pirámide invertida estricta
- **Títulos**: Máximo 60 caracteres, incluyen verbo de acción
- **Lead**: 2-3 oraciones, máximo 50 palabras

## Ejemplos de titulares
✅ "Sánchez anuncia medidas fiscales que dividen al empresariado"
❌ "El presidente del Gobierno español ha comunicado..."

## Vocabulario específico
- Usar "empresariado" en lugar de "empresarios"
- Preferir "ejecutivo" a "gobierno"
- Evitar anglicismos innecesarios
```

---

## CASOS DE USO POR TIPO DE MEDIO

### 📺 Medios Digitales Nativos
**Ejemplo: ElDiario.es, El Confidencial**
- **Flujo típico**: RSS → Análisis → Micro-edición → Publicación
- **Volumen**: 50-100 artículos/día
- **Plan recomendado**: PRO
- **ROI estimado**: 40 horas/semana ahorradas = 6,400€/mes valor

### 📰 Prensa Tradicional Digital
**Ejemplo: El País, La Vanguardia**
- **Flujo típico**: Email → Análisis atómico → Verificación → Generación
- **Volumen**: 20-50 artículos/día
- **Plan recomendado**: PRO
- **ROI estimado**: Mejora tiempo de publicación 60%

### 🏢 Agencias de Comunicación
**Ejemplo: Llorente y Cuenca, Atrevia**
- **Flujo típico**: Notas prensa → Adaptación estilo → Múltiples medios
- **Volumen**: 30-80 adaptaciones/día
- **Plan recomendado**: PRO + Custom
- **ROI estimado**: 1 periodista = 1,800€/mes, automatización = 250€/mes

### 👤 Periodistas Freelance
**Ejemplo: Corresponsales, columnistas**
- **Flujo típico**: Investigación → Análisis → Micro-edición
- **Volumen**: 5-15 artículos/día
- **Plan recomendado**: STARTER
- **ROI estimado**: 2-3 horas/día ahorradas = tiempo para más clientes

---

## ANÁLISIS DE MÁRGENES

### Costes Operativos por Workflow

| Workflow | Coste Interno | Precio Starter | Precio Pro | Margen |
|----------|---------------|----------------|------------|--------|
| Análisis | 0.002€ | 0.149€ | 0.050€ | 98.7% / 96.0% |
| Micro-edit | 0.008€ | 0.298€ | 0.125€ | 97.3% / 93.6% |
| Generación | 0.015€ | 0.745€ | 0.250€ | 98.0% / 94.0% |
| Atómico | 0.005€ | 0.298€ | 0.125€ | 98.3% / 96.0% |
| Guías Estilo | 0.120€ | 29.80€ | 12.50€ | 99.6% / 99.0% |

**Margen global estimado**: 95-98%

### Estructura de Costes
- **LLM APIs (OpenRouter)**: 85% del coste
- **Infraestructura (VPS + Supabase)**: 10%
- **Desarrollo y mantenimiento**: 5%

---

## ESTRATEGIA COMERCIAL

### 🎯 Segmentación de Mercado

**Segmento 1: Medios Locales (STARTER)**
- 500+ medios locales en España
- Presupuesto limitado: 100-300€/mes
- Necesidad: Automatización básica
- **TAM**: 75M€ (500 medios × 149€ × 12 meses)

**Segmento 2: Medios Nacionales (PRO)**
- 50 medios nacionales digitales
- Presupuesto medio: 1,000-5,000€/mes
- Necesidad: Escalabilidad y personalización
- **TAM**: 15M€ (50 medios × 250€ × 12 meses × 10 verticales)

**Segmento 3: Agencias (ENTERPRISE)**
- 200 agencias de comunicación
- Presupuesto alto: 2,000-10,000€/mes
- Necesidad: Multi-cliente, white label
- **TAM**: 48M€ (200 agencias × 2,000€ × 12 meses)

### 📈 Estrategia de Penetración

**Fase 1 (Q1 2025): Validación**
- 10 clientes piloto
- Pricing feedback
- Product-market fit

**Fase 2 (Q2-Q3 2025): Escalado**
- 100 clientes STARTER
- 10 clientes PRO
- Ingresos objetivo: 2M€ ARR

**Fase 3 (Q4 2025+): Expansión**
- Nuevos verticales (finanzas, legal)
- Expansión internacional
- Enterprise features

### 💰 Proyección de Ingresos

**Año 1 (Conservador):**
- 200 STARTER × 149€ × 12 = 358,800€
- 20 PRO × 250€ × 12 = 60,000€
- **Total**: 418,800€ ARR

**Año 2 (Moderado):**
- 500 STARTER × 149€ × 12 = 894,000€
- 50 PRO × 250€ × 12 = 150,000€
- 10 ENTERPRISE × 1,000€ × 12 = 120,000€
- **Total**: 1,164,000€ ARR

**Año 3 (Optimista):**
- 1,000 STARTER × 149€ × 12 = 1,788,000€
- 100 PRO × 250€ × 12 = 300,000€
- 25 ENTERPRISE × 2,000€ × 12 = 600,000€
- **Total**: 2,688,000€ ARR

---

## VENTAJAS COMPETITIVAS

### ✅ Diferenciadores Clave
1. **Especialización en prensa española**: Conocimiento del mercado local
2. **Workflows específicos**: No herramientas genéricas
3. **Precios transparentes**: Sin sorpresas, límites claros
4. **Integración completa**: Email, RSS, API
5. **Márgenes sostenibles**: Modelo económico robusto

### 🏆 vs Competencia

**vs ChatGPT/Claude directo:**
- ❌ Sin límites de uso
- ❌ Sin workflows específicos
- ❌ Requiere prompt engineering
- ✅ Ekimen: Plug & play para periodistas

**vs Jasper/Copy.ai:**
- ❌ Genérico, no especializado
- ❌ Caro para uso intensivo
- ❌ Sin verificación de hechos
- ✅ Ekimen: Específico para prensa

**vs Desarrollos internos:**
- ❌ Requiere equipo técnico
- ❌ Coste desarrollo 100k€+
- ❌ Mantenimiento constante
- ✅ Ekimen: SaaS listo para usar

---

## IMPLEMENTACIÓN COMERCIAL

### 🚀 Go-to-Market Strategy

**1. Lanzamiento Piloto (Enero 2025)**
- 5 medios locales conocidos
- Precio especial: 50% descuento 3 meses
- Feedback intensivo y mejoras

**2. Programa Partners (Febrero 2025)**
- Agencias de comunicación como revendedores
- Comisión 20% primeros 6 meses
- Training y materiales de venta

**3. Marketing Digital (Marzo 2025)**
- SEO: "automatización periodismo IA"
- LinkedIn: Targeting editores y directores
- Content marketing: Casos de éxito

**4. Eventos Sector (Q2 2025)**
- Conferencias de periodismo
- Demo en vivo de workflows
- Networking con decision makers

### 📞 Sales Process

**1. Lead Generation**
- Inbound: Content marketing + SEO
- Outbound: LinkedIn outreach
- Referrals: Programa partners

**2. Qualification (BANT)**
- Budget: >149€/mes disponible
- Authority: Editor/CTO con decision power
- Need: Automatización/escalabilidad
- Timeline: Implementación <30 días

**3. Demo Personalizada**
- Workflow con contenido real del cliente
- ROI calculation específico
- Integración con sus sistemas actuales

**4. Trial & Onboarding**
- 14 días gratis plan PRO
- Setup asistido
- Training team editorial

**5. Close & Expansion**
- Contrato anual con descuento
- Quarterly business reviews
- Upsell a funcionalidades premium

---

## CONCLUSIONES

Ekimen Press representa una oportunidad de mercado de **138M€ TAM** con márgenes excepcionales del 95-98%. La especialización en workflows periodísticos, combined con precios transparentes y escalables, posiciona la plataforma para capturar una porción significativa del mercado de automatización editorial en España.

La estrategia de penetración gradual (piloto → escala → expansión) minimiza riesgos mientras maximiza el aprendizaje del mercado. Con proyecciones conservadoras de 1.2M€ ARR en año 2, Ekimen puede convertirse en el estándar de facto para automatización periodística en el mercado hispanohablante.