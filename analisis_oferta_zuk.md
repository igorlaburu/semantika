# Propuesta Comercial - Txus Díez (ZUK.EUS)

**Cliente**: Txus Díez - Periodista independiente  
**Web**: [zuk.eus](https://www.zuk.eus)  
**Territorio**: Álava (País Vasco)  
**Fecha**: 5 diciembre 2025  

---

## RESUMEN EJECUTIVO

**Pain point**: Txus dedica 2.5h/día a tareas manuales (SEO, enlaces, agenda) limitando su capacidad de producción.

**Solución**: Automatización completa de redacción, publicación WordPress, enlaces y agenda de eventos.

**ROI**: Ahorra 45h/mes (valoradas en 1,800€) invirtiendo 250-300€/mes → **Beneficio neto: +1,500€/mes**

---

## 1. NECESIDADES DEL CLIENTE

### Prioritarias (imprescindibles)
✅ WordPress automático con Yoast SEO (metadatos, slug, etiquetas)  
✅ Upload automático de imágenes con metadatos  
✅ Enlaces internos/externos automáticos (crítico para SEO)  
✅ Scraping de fuentes institucionales (Juntas, Parlamento)  

### Importantes (alto valor)
✅ Agenda de eventos municipales (60 eventos/día)  
✅ Clasificación por cuadrillas  
✅ Formato para WhatsApp/Telegram  

### Opcionales (no prioritarias ahora)
⏸️ Transcripción de streams en directo  
⏸️ Monitorización de mediateca  
⏸️ Audio transcription Whisper  

---

## 2. COSTES REALES

### Costes operativos mensuales (300 artículos + agenda)

| Concepto | Cálculo | Coste |
|----------|---------|-------|
| **LLM artículos** | 300 × 2.8K tokens × $0.003/$0.015 | 9€ |
| **LLM agenda** | 2,100 eventos × 0.5K tokens | 3€ |
| **LLM enlaces** | 300 × 1K tokens | 1€ |
| **Embeddings** | 2,400 × 200 tokens | 0.10€ |
| **VPS/Infra** | Prorrateado | 10€ |
| **TOTAL COSTES APIs** | - | **~23€/mes** |

### Costes de tu tiempo (soporte mensual)

| Actividad | Horas/mes | Coste (50€/h) |
|-----------|-----------|---------------|
| Emails/dudas cliente | 1h | 50€ |
| Ajustes/bugs menores | 2h | 100€ |
| Reunión mensual | 0.5h | 25€ |
| **TOTAL TIEMPO** | **3.5h** | **175€/mes** |

### Coste total mensual real
```
APIs:      23€
Tu tiempo: 175€
─────────────────
TOTAL:     198€/mes
```

---

## 3. COSTES DE IMPLEMENTACIÓN

### Funcionalidades fáciles (incluidas en mensualidad)
| Tarea | Horas | Coste |
|-------|-------|-------|
| WordPress + Yoast SEO | 3h | 150€ |
| Upload imágenes + metadatos | 2h | 100€ |
| Scraping Juntas (preguntas) | 2h | 100€ |
| Scraping Parlamento (preguntas) | 2h | 100€ |
| Scraping plenos de control | 2h | 100€ |
| Testing + ajustes | 2h | 100€ |
| **TOTAL FÁCIL** | **13h** | **650€** |

### Funcionalidades complejas (implementación aparte)
| Tarea | Horas | Coste |
|-------|-------|-------|
| Sistema enlaces automáticos | 4h | 200€ |
| Búsqueda histórico WordPress | 2h | 100€ |
| Inserción enlaces HTML | 3h | 150€ |
| **TOTAL ENLACES** | **9h** | **450€** |
| | | |
| Scraping webs municipales (5 pilotos) | 6h | 300€ |
| Clasificador cuadrillas (LLM) | 2h | 100€ |
| Generador WhatsApp/Telegram | 2h | 100€ |
| Testing agenda | 2h | 100€ |
| **TOTAL AGENDA** | **12h** | **600€** |

---

## 4. PROPUESTAS COMERCIALES

### **PLAN 1: ESENCIAL** (mínimo solicitado)
```
✅ WordPress automático + Yoast SEO
✅ Upload imágenes con metadatos  
✅ Scraping institucional (Juntas + Parlamento)
✅ 300 artículos/mes procesados

❌ No incluye: Enlaces automáticos
❌ No incluye: Agenda municipal
❌ No incluye: WhatsApp/Telegram

💰 Precio: 250€/mes
📅 Compromiso: 6 meses mínimo
🎁 Setup incluido (valor 650€)

Inversión primer año: 250€ × 12 = 3,000€
```

**Margen**:
- Coste operativo: 198€/mes
- Beneficio: 52€/mes (26%)
- Primer año: 52€ × 6 = 312€ (amortiza setup en 2 años)

---

### **PLAN 2: PROFESIONAL** ⭐ (recomendado)
```
✅ Todo lo de Plan Esencial
✅ Enlaces internos/externos automáticos
✅ Agenda 60 eventos/día (5 ayuntamientos)
✅ Clasificación por cuadrillas
✅ Formato WhatsApp/Telegram

💰 Precio: 300€/mes
📅 Compromiso: 6 meses mínimo
🎁 Setup básico incluido (valor 650€)
💵 Implementación enlaces: 450€ (pago único)
💵 Implementación agenda: 600€ (pago único)

Inversión primer año:
- Setup: 450€ + 600€ = 1,050€
- Mensualidad: 300€ × 12 = 3,600€
- TOTAL: 4,650€
```

**Margen año 1**:
- Implementación: 1,050€ - 1,050€ = 0€ (break-even)
- Operación: (300€ - 198€) × 12 = 1,224€
- Total año 1: 1,224€

**Margen año 2+**: (300€ - 198€) × 12 = **1,224€/año** (51%)

---

### **PLAN 3: TODO INCLUIDO** (sin setup aparte)
```
✅ Todo lo de Plan Profesional
✅ Agenda completa (20 ayuntamientos)
✅ Implementación de todo sin coste adicional

💰 Precio: 380€/mes
📅 Compromiso: 12 meses obligatorio
🎁 Todo el setup incluido en mensualidad

Inversión primer año: 380€ × 12 = 4,560€
```

**Margen**:
- Mes 1-6: (380€ - 198€) × 6 = 1,092€ - 1,700€ setup = **-608€** (pérdida)
- Mes 7-12: (380€ - 198€) × 6 = 1,092€
- **Total año 1**: 484€ (13%)
- **Año 2+**: 2,184€/año (48%)

**Por qué funciona**: Amortizas setup en 10 meses, luego es altamente rentable.

---

## 5. COMPARATIVA DE PLANES

| | Plan 1: Esencial | Plan 2: Profesional ⭐ | Plan 3: Todo Incluido |
|---|---|---|---|
| **Mensualidad** | 250€ | 300€ | 380€ |
| **Setup aparte** | Incluido (650€) | 1,050€ | Incluido |
| **Compromiso** | 6 meses | 6 meses | 12 meses |
| **WordPress + SEO** | ✅ | ✅ | ✅ |
| **Scraping institucional** | ✅ | ✅ | ✅ |
| **Enlaces automáticos** | ❌ | ✅ | ✅ |
| **Agenda municipal** | ❌ | ✅ (5 aytos) | ✅ (20 aytos) |
| **WhatsApp/Telegram** | ❌ | ✅ | ✅ |
| **Inversión año 1** | 3,000€ | 4,650€ | 4,560€ |
| **Tu margen año 1** | 312€ | 1,224€ | 484€ |
| **Tu margen año 2+** | 624€/año | 1,224€/año | 2,184€/año |

---

## 6. RECOMENDACIÓN

### **Para ti**: Plan 2 (Profesional)

**Ventajas**:
- ✅ Setup se paga aparte (cashflow inmediato: 1,050€)
- ✅ Margen año 1 positivo (1,224€)
- ✅ Compromiso solo 6 meses (reduce riesgo)
- ✅ Si Txus cancela, no pierdes dinero

**Desventajas**:
- Txus paga más upfront (puede rechazar)

---

### **Para Txus**: Plan 3 (Todo Incluido)

**Ventajas para él**:
- ✅ Sin sorpresas (todo en mensualidad)
- ✅ Cashflow mejor (no paga 1,050€ de golpe)
- ✅ Más barato año 1 (4,560€ vs 4,650€)

**Desventajas para ti**:
- Amortizas setup lentamente (10 meses)
- Si cancela mes 7, pierdes 608€

---

## 7. ESTRATEGIA DE PRESENTACIÓN

### **Ofrecer Plan 2 como principal + Plan 3 como alternativa**

```
Email propuesta:

"Hola Txus,

He preparado dos opciones según lo que comentamos:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPCIÓN 1: PROFESIONAL (recomendada)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ WordPress + Yoast SEO automático
✅ Scraping institucional (Juntas + Parlamento)
✅ Enlaces internos/externos automáticos
✅ Agenda 60 eventos/día (clasificada por cuadrillas)
✅ Formato WhatsApp/Telegram
✅ 300 artículos/mes procesados

💰 300€/mes (compromiso 6 meses)
💵 Setup: 1,050€ pago único
   - Enlaces automáticos: 450€
   - Agenda municipal: 600€

Inversión año 1: 4,650€

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPCIÓN 2: TODO INCLUIDO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Todo lo anterior
✅ Sin coste de setup (incluido en mensualidad)
✅ Agenda completa (20 ayuntamientos vs 5)

💰 380€/mes (compromiso 12 meses obligatorio)

Inversión año 1: 4,560€ (90€ menos que Opción 1)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ROI para ti:
- Tiempo ahorrado: 45h/mes = 1,800€/mes
- Inversión: 300-380€/mes
- Beneficio neto: +1,450€/mes

Payback: 2-3 meses

¿Cuál te encaja mejor? Puedo empezar en enero.

Saludos,
Igor"
```

---

## 8. ANÁLISIS DE SENSIBILIDAD

### Si Txus pide descuento o rechaza

**Opción A: Bajar Plan 2 a 280€/mes**
```
Margen: (280€ - 198€) × 12 = 984€/año
Setup: 1,050€ (cubre implementación)

Total año 1: 2,034€
```

**Opción B: Ofrecer Plan 1 (Esencial) como entrada**
```
250€/mes sin enlaces ni agenda
Luego upsell enlaces (50€/mes) + agenda (30€/mes)
= 330€/mes gradual
```

**Opción C: Pricing escalonado**
```
Meses 1-3: 250€/mes (solo WordPress + scraping)
Meses 4-6: 300€/mes (añadir enlaces)
Meses 7+: 350€/mes (añadir agenda)

Ventaja: Txus prueba sin compromiso total
Desventaja: Delays en implementación completa
```

---

## 9. TÉRMINOS Y CONDICIONES

### Incluido en todos los planes
- ✅ Soporte email (respuesta <24h)
- ✅ Ajustes menores sin coste
- ✅ 1 reunión mensual seguimiento (30 min)
- ✅ Actualizaciones de sistema incluidas

### NO incluido (cobrar aparte)
- ❌ Cambios de scope (nuevas features)
- ❌ Integración con nuevas plataformas
- ❌ Formación adicional (>2h)
- ❌ Desarrollo custom fuera de roadmap

### Condiciones de pago
- Setup: 50% al firmar, 50% al entregar
- Mensualidad: Pago adelantado cada mes
- Forma de pago: Transferencia o Stripe

### Cancelación
- Aviso: 30 días antes
- Penalización si <6 meses: 50% mensualidades restantes
- Plan 3 (12 meses): No cancelable antes de mes 12

---

## 10. PRÓXIMOS PASOS

1. **Hoy 5 dic**: Enviar esta propuesta a Txus por email
2. **Lunes 9 dic**: Follow-up si no responde
3. **Miércoles 11 dic**: Llamada para aclarar dudas
4. **Antes 20 dic**: Cierre y firma contrato
5. **Enero 2025**: Inicio implementación

---

## RESUMEN EJECUTIVO PARA TI

### Recomendación: **Plan 2 (Profesional) a 300€/mes + 1,050€ setup**

**Por qué**:
- ✅ Cashflow inmediato (1,050€ en diciembre/enero)
- ✅ Margen positivo año 1 (1,224€)
- ✅ Compromiso solo 6 meses (bajo riesgo)
- ✅ Txus ve valor claro (todo lo importante incluido)
- ✅ Setup separado = profesionalidad (no parece "barato")

**Tu ganancia**:
- Año 1: 1,224€ + 1,050€ setup = **2,274€**
- Año 2: 1,224€
- Año 3: 1,224€

**Total 3 años: 4,722€** con cliente satisfecho que puede referir.

---

**Preparado por**: Igor Laburu (gako.ai)  
**Fecha**: 5 diciembre 2025  
**Acción**: Enviar propuesta hoy
