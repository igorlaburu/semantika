# Análisis de Oferta - Txus Díez (ZUK.EUS)

**Cliente**: Txus Díez - Periodista independiente  
**Web**: [zuk.eus](https://www.zuk.eus)  
**Territorio**: Álava (País Vasco)  
**Fecha**: 5 diciembre 2025  

---

## 1. PERFIL DEL CLIENTE

### Situación actual
- Publica ~10 artículos/día en WordPress
- Ya usa scripts propios + ChatGPT para automatización parcial
- Tiempo invertido: ~2.5h/día (10min agenda + 2h redacción/SEO/fotos)
- Pain points principales:
  - Metadatos SEO (Yoast) manual
  - Enlaces internos/externos manual (crítico para SEO)
  - Agenda limitada a Vitoria (no pueblos)
  - Procesamiento de fuentes institucionales lento

### Nivel técnico
- Alto: Ya tiene scripts, usa APIs, conoce ChatGPT
- Busca solución que supere sus limitaciones técnicas
- Valora inmediatez y automatización completa

---

## 2. REQUISITOS SOLICITADOS

### A) Fuentes de información

#### Preguntas parlamentarias
- **Origen**: Webs de Juntas Generales y Parlamento Vasco
- **Filtro**: Palabras clave específicas + "Álava"
- **Frecuencia**: Diaria
- **Complejidad**: ⭐⭐ Media

#### Plenos de control
- **Origen**: Parlamento Vasco
- **Frecuencia**: Cada 2 viernes
- **Formato**: Transcripciones inmediatas
- **Filtro**: Palabras clave + mención a Álava
- **Complejidad**: ⭐⭐ Media

#### Streams en directo (opcional futuro)
- **Origen**: Juntas Generales, Parlamento
- **Objetivo**: Mayor inmediatez que mediateca
- **Complejidad**: ⭐⭐⭐⭐⭐ Muy alta
- **Nota**: Requiere detección automática + transcripción real-time

---

### B) Redacción y publicación

#### WordPress automático con Yoast SEO
- Palabras clave
- Meta descripción
- Slug amigable ✅ (ya lo generamos)
- Etiquetas
- Título alternativo
- Metadatos de imagen
- **Complejidad**: ⭐⭐ Media

#### Enlaces automáticos
- **Externos**: A instituciones/asociaciones mencionadas
- **Internos**: A noticias anteriores propias (contexto)
- **Importancia**: CRÍTICA para SEO
- **Complejidad**: ⭐⭐⭐⭐ Alta

#### Procesamiento de imágenes
- Upload automático a WordPress
- Metadatos completos
- **Complejidad**: ⭐ Baja

---

### C) Agenda de eventos

#### Situación actual (script propio)
- Fuente: Kulturklik (solo Vitoria)
- Tiempo: procesamiento + generación = 10 min/día
- Output: Web + WhatsApp + Telegram
- **Problema**: No cubre pueblos

#### Solicitud nueva
- **Volumen**: ~60 eventos/día
- **Fuentes**: 
  - Canales WhatsApp de ayuntamientos
  - Webs municipales (formatos heterogéneos)
- **Formato deseado**: Ordenado por cuadrillas
- **Output**: Texto para WhatsApp/Telegram (~10 titulares con URL)
- **Complejidad**: ⭐⭐⭐⭐ Alta

---

## 3. ANÁLISIS DE COSTES

### Costes de desarrollo (una vez)

#### Fase 1: Quick Wins (13 horas)
| Tarea | Horas | Coste |
|-------|-------|-------|
| WordPress + Yoast SEO metadata | 3h | 300€ |
| Upload automático de imágenes | 2h | 200€ |
| Scraping preguntas Juntas | 2h | 200€ |
| Scraping preguntas Parlamento | 2h | 200€ |
| Scraping plenos de control | 2h | 200€ |
| Testing + ajustes | 2h | 200€ |
| **TOTAL FASE 1** | **13h** | **1,300€** |

#### Fase 2: Funcionalidades Complejas (22 horas)
| Tarea | Horas | Coste |
|-------|-------|-------|
| Sistema enlaces automáticos (entidades) | 4h | 400€ |
| Búsqueda histórico WordPress | 2h | 200€ |
| Inserción enlaces HTML | 3h | 300€ |
| Scraping webs municipales (5 pilotos) | 6h | 600€ |
| Clasificador por cuadrillas (LLM) | 2h | 200€ |
| Generador WhatsApp/Telegram | 2h | 200€ |
| Testing + ajustes | 3h | 300€ |
| **TOTAL FASE 2** | **22h** | **2,200€** |

#### Fase 3: Streams (opcional - 16 horas)
| Tarea | Horas | Coste |
|-------|-------|-------|
| Detección automática streams | 4h | 400€ |
| Transcripción Whisper real-time | 6h | 600€ |
| Extractor puntos tratados (LLM) | 3h | 300€ |
| Testing + infraestructura | 3h | 300€ |
| **TOTAL FASE 3** | **16h** | **1,600€** |

---

### Costes operativos mensuales

#### Volumen estimado
- **70 eventos/día** → 2,100/mes (captura + procesamiento)
- **10 artículos publicados/día** → 300/mes
- **Context units creados/mes**: ~2,400
- **Análisis LLM**: ~5,000 llamadas/mes

#### Desglose infraestructura
| Concepto | Uso mensual | Coste unitario | Coste mensual |
|----------|-------------|----------------|---------------|
| **LLM (Sonnet 3.5)** | 5,000 calls × 2K tokens | $0.015/1K in + $0.075/1K out | ~550€ |
| **LLM (GPT-4o-mini)** | 3,000 calls × 1K tokens | $0.00015/1K in + $0.0006/1K out | ~3€ |
| **Embeddings** | 2,400 units × 200 tokens | $0.02/1M tokens | ~0.10€ |
| **VPS Docker** | Prorrateado | - | ~15€ |
| **Contingencia** | 10% buffer | - | ~57€ |
| **TOTAL OPERATIVO** | - | - | **~625€/mes** |

**Margen objetivo**: 90%  
**Precio mínimo teórico**: ~1,187€/mes

---

## 4. PROPUESTA COMERCIAL

### Implantación (one-time)

| Nivel | Incluye | Precio |
|-------|---------|--------|
| **Starter** | Fase 1 (WordPress + Scraping básico) | 1,500€ |
| **Pro** ⭐ | Fase 1 + 2 (Enlaces + Agenda completa) | 3,800€ |
| **Enterprise** | Fase 1 + 2 + 3 (+ Streams) | 5,800€ |

**Recomendación**: **Pro (3,800€)** - Cubre todo lo solicitado excepto streams

---

### Suscripción mensual

#### Modelo de créditos
- **Automatización compleja**: Artículo completo (scraping + LLM + publicación) → **1 crédito**
- **Automatización simple**: Edición/clasificación/comando → **0.2 créditos**

#### Volumen Txus
- 300 artículos/mes → **300 créditos complejos**
- 2,100 eventos agenda/mes → **420 créditos simples**
- **Total equivalente**: ~320 créditos complejos

#### Planes estándar

| Plan | Créditos complejos | Créditos simples | Precio | Margen |
|------|-------------------|------------------|--------|--------|
| **Essential** | 150/mes | 750/mes | 600€/mes | ~80% |
| **Professional** | 350/mes | 2,500/mes | 1,200€/mes | ~92% |

---

## 5. PROPUESTA ESPECIAL PILOTO

### Contexto
- Cliente ideal para caso de éxito (periodista independiente, nicho local)
- Necesidades alineadas 100% con roadmap de producto
- Feedback valioso para refinar features
- Potencial upsell a otros periodistas (Gipuzkoa, Bizkaia)

### Opción A: Estándar

```
💰 Implantación: 3,800€ (Fase 1 + 2)
📅 Suscripción: 650€/mes (6 meses) → 1,200€/mes

Incluye:
✅ WordPress automático con Yoast SEO
✅ Scraping preguntas parlamentarias + plenos
✅ Enlaces internos/externos automáticos
✅ Agenda consolidada por cuadrillas (60 eventos/día)
✅ Formato WhatsApp/Telegram
✅ 350 artículos/mes + 2,500 eventos/mes
✅ Soporte prioritario

🎯 Inversión primer año: 14,900€
```

### Opción B: Piloto (RECOMENDADA) ⭐

```
💰 Implantación: 3,000€ (descuento 21%)
📅 Suscripción: 500€/mes (precio fijo 12 meses)

Incluye:
✅ Todo lo de Opción A
✅ Precio bloqueado 12 meses
✅ Caso de éxito (testimonial + logo en web)
✅ Feedback prioritario para roadmap

🎯 Inversión primer año: 9,000€

Condiciones:
- Testimonial después de 3 meses
- Reunión mensual feedback (30 min)
- Logo ZUK.EUS en ekimen.ai
- Renovación año 2: 800€/mes (descuento 33% vs estándar)

Margen real: ~20% primer año
Break-even: Inmediato (cubre costes operativos)
```

---

## 6. ANÁLISIS ROI PARA TXUS

### Tiempo ahorrado

**Actual**:
- 10 min/día → Agenda (ya automatizado parcialmente)
- 2h/día → Redacción, SEO, metadatos, fotos, enlaces

**Total**: ~2.5h/día = **50h/mes**

**Con Ekimen**:
- 15 min/día → Revisión final y ajustes

**Ahorro**: ~2h 15min/día = **45h/mes**

### Valoración económica

**Tarifa freelance periodista**: ~40€/h  
**Ahorro mensual**: 45h × 40€ = **1,800€/mes**

**ROI Opción B**:
- Inversión mensual: 500€
- Ahorro tiempo: 1,800€
- **Beneficio neto: +1,300€/mes**

**Payback implantación**: 3,000€ / 1,300€ = **2.3 meses**

### Beneficios adicionales (no cuantificados)

- **Mejor SEO**: Enlaces automáticos → más tráfico orgánico
- **Mayor cobertura**: 60 eventos/día vs ~10 actuales (Kulturklik)
- **Inmediatez**: Plenos/preguntas parlamentarias antes que competencia
- **Escalabilidad**: Capacidad de cubrir más territorio sin más tiempo

---

## 7. COMPARATIVA ALTERNATIVAS

| Solución | Setup | Mensual | Pros | Contras |
|----------|-------|---------|------|---------|
| **Ekimen Opción A** | 3,800€ | 650→1,200€ | Solución completa | Precio alto |
| **Ekimen Opción B** ⭐ | 3,000€ | 500€ | ROI inmediato | Margen ajustado |
| **Freelance + ChatGPT** | ~5,000€ | 120€ | Económico | No automatizado, 2h/día manual |
| **Agencia tradicional** | 8-15k€ | 800-1,500€ | Custom | Lento, caro |
| **DIY (él mismo)** | 0€ | 20€ | Control total | 2-3h/día trabajo, límite técnico |

---

## 8. RIESGOS Y MITIGACIONES

### Riesgos técnicos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Scraping webs municipales falla (HTML cambia) | Media | Alto | Alertas automáticas + fix en 24h |
| LLM genera enlaces incorrectos | Baja | Medio | Revisión manual pre-publicación (opcional) |
| Detección de entidades imprecisa | Media | Bajo | Mejora continua con feedback |
| WhatsApp API limitaciones | Baja | Medio | Usar Telegram como backup |

### Riesgos comerciales

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Cliente cancela tras 6 meses | Media | Alto | Contrato 12 meses con descuento |
| Costes LLM suben 50% | Baja | Alto | Cláusula revisión precio anual |
| Cliente pide features fuera scope | Alta | Medio | Roadmap trimestral acordado |

---

## 9. ROADMAP DE IMPLEMENTACIÓN

### Mes 1: Setup + Fase 1
- **Semana 1**: Configuración WordPress + Yoast SEO
- **Semana 2**: Scraping preguntas parlamentarias
- **Semana 3**: Scraping plenos de control
- **Semana 4**: Testing + ajustes + formación

### Mes 2: Fase 2 - Agenda
- **Semana 1**: Identificar webs municipales (5 aytos piloto)
- **Semana 2**: Scraping + clasificador cuadrillas
- **Semana 3**: Generador WhatsApp/Telegram
- **Semana 4**: Testing + ajustes

### Mes 3: Fase 2 - Enlaces
- **Semana 1**: Sistema detección entidades
- **Semana 2**: Búsqueda histórico WordPress
- **Semana 3**: Inserción automática enlaces
- **Semana 4**: Testing + optimización

### Mes 4-6: Refinamiento
- Añadir resto de ayuntamientos (escalar de 5 a 20)
- Optimización LLM prompts
- Mejoras según feedback Txus

---

## 10. CRITERIOS DE ÉXITO

### KPIs técnicos (3 meses)

- **Uptime sources**: >95%
- **Artículos publicados/día**: 8-12 (vs 10 actual)
- **Eventos agenda/día**: 50+ (vs 10 actual)
- **Tiempo revisión/día**: <20 min (vs 2.5h actual)
- **Precisión enlaces**: >85% correctos

### KPIs negocio (6 meses)

- **Tráfico web**: +30% (mejor SEO)
- **Engagement WhatsApp/Telegram**: +50% (mejor agenda)
- **Tiempo ahorrado**: 40h/mes
- **Satisfacción cliente**: 8/10

### Hitos entregables

- **Mes 1**: WordPress + scraping institucional operativo
- **Mes 2**: Agenda 5 ayuntamientos funcionando
- **Mes 3**: Enlaces automáticos + agenda completa (20 aytos)
- **Mes 6**: Sistema refinado + caso de éxito documentado

---

## 11. PRÓXIMOS PASOS

1. **Miércoles 10 diciembre**: Enviar propuesta formal PDF
2. **Semana 16 diciembre**: Reunión + aclaración dudas
3. **Antes Navidad**: Firma contrato (si acepta)
4. **Enero 2025**: Inicio desarrollo Fase 1

---

## 12. NOTAS ADICIONALES

### Upsell futuro

- **Streams en directo** (+300€/mes): Cuando esté maduro
- **Análisis competencia** (+100€/mes): Monitorizar otros medios locales
- **Newsletter automático** (+50€/mes): Resumen semanal
- **Redes sociales** (+150€/mes): Auto-publicación Twitter/LinkedIn

### Potencial expansión

Si caso de éxito con Txus:
- **Periodistas Gipuzkoa**: 5-10 potenciales (Goiena, Noticias de Gipuzkoa...)
- **Periodistas Bizkaia**: 5-10 potenciales (medios comarcales)
- **Medios institucionales**: Diputaciones, ayuntamientos grandes

**Objetivo**: 10 clientes similares = ~60,000€ ARR (10 × 500€ × 12)

---

## RECOMENDACIÓN FINAL

**Proponer Opción B (Piloto)** por:

1. ✅ **ROI inmediato** para cliente (1,300€/mes beneficio neto)
2. ✅ **Caso de éxito** ideal (periodista independiente, nicho local)
3. ✅ **Feedback valioso** para refinar producto
4. ✅ **Margen suficiente** (20% primer año, >80% después)
5. ✅ **Potencial expansión** a otros periodistas locales
6. ✅ **Break-even inmediato** (cubre costes operativos desde mes 1)

**Riesgo**: Bajo (cliente técnico, presupuesto ajustado pero viable)  
**Oportunidad**: Alta (validación producto + referencias)

---

**Preparado por**: Igor Laburu (gako.ai)  
**Fecha**: 5 diciembre 2025  
**Próxima acción**: Enviar propuesta formal 10 diciembre
