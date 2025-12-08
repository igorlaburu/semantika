# Reflexiones sobre pgvector y Qdrant: Fuentes Propias y Pool Común

**Fecha:** 2 Diciembre 2024  
**Contexto:** Discusión sobre arquitectura de almacenamiento para noticias descubiertas vs fuentes directas

---

## 🎯 Problema Original

Estamos implementando un sistema Discovery que descubre automáticamente nuevas fuentes de contenido. Surge la pregunta: **¿Cómo almacenar este contenido descubierto?**

### Opciones Consideradas

1. **Segregar por tipo**: pgvector (fuentes directas) + Qdrant (discovery)
2. **Pool común multi-tenant**: Qdrant unificado con ranking global
3. **API separada**: Endpoints distintos para discovery vs fuentes propias

---

## 🏗️ Arquitectura Elegida: Híbrido Simplificado

### Principios Fundamentales

```
pgvector (Supabase)              Qdrant Pool Común
├─ Fuentes directas usuario      ├─ Discovery sources (todos)
├─ Enriquecimientos propios      ├─ Solo lectura para usuarios
├─ Metadata privada              ├─ Auto-poblado por sistema
├─ CRUD completo                 ├─ Ranking global agregado
└─ Starred, notes, tags          └─ Sin enriquecimientos (base común)
```

### Flujo de Datos

```
┌─────────────────────────────────────────────────────────┐
│ Sistema Discovery (Servicio Interno)                    │
│ ├─ Descubre fuentes (Perplexity, Google)              │
│ ├─ Valida y extrae contenido                          │
│ └─ Ingesta → Qdrant Pool (company_id: "shared")       │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ Qdrant Pool (Read-Only para usuarios)                   │
│ {                                                        │
│   "company_id": "shared",                               │
│   "global_usage_count": 5,                              │
│   "discovered_by": ["client-A", "client-B"],           │
│   "title": "...",                                       │
│   "content": "...",                                     │
│   "global_relevance_score": 0.75                       │
│ }                                                        │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ Usuario: Listing/Búsqueda (include_pool=true)          │
│ ├─ Ve contenido propio (pgvector)                      │
│ ├─ Ve contenido pool (Qdrant)                          │
│ └─ Puede "adoptar" item del pool                       │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ Usuario: Enriquecer item del pool                       │
│ ├─ NO modifica el pool (es común)                      │
│ ├─ Crea "enrichment layer" en pgvector                 │
│ └─ {                                                    │
│     "id": "uuid-enrichment-1",                         │
│     "company_id": "client-A",                          │
│     "pool_source_id": "uuid-pool-123",  ← Referencia  │
│     "enriched_statements": [...],       ← Propio      │
│     "title": null,                                     │
│     "content": null                                    │
│   }                                                     │
└─────────────────────────────────────────────────────────┘
```

---

## 📊 Ventajas de esta Arquitectura

### ✅ Separación Clara de Responsabilidades

| Aspecto | pgvector | Qdrant Pool |
|---------|----------|-------------|
| **Contenido** | Fuentes directas + enriquecimientos | Discovery (base común) |
| **Acceso** | CRUD completo | Solo lectura |
| **Ownership** | Usuario propietario | Compartido (todos) |
| **Enriquecimiento** | Sí, directo | No (se crea layer en pgvector) |
| **Metadata privada** | Sí (starred, notes) | No |
| **Deduplicación** | No necesaria | Automática por embedding |

### ✅ Beneficios del Pool Común

1. **Efecto red**: Cada cliente mejora el ranking global
2. **Deduplicación automática**: Si 5 clientes descubren Tubacex, solo hay 1 copia
3. **Serendipity**: Cliente A descubre fuente útil para Cliente B
4. **Costos optimizados**: No duplicar embeddings/storage
5. **Calidad colectiva**: `global_usage_count` es señal de relevancia

### ✅ Enriquecimientos como Capas

**Problema**: Usuario quiere enriquecer item del pool, pero no puede modificar contenido común.

**Solución**: Crear "enrichment layer" en pgvector:
```sql
-- Tabla: press_context_units (pgvector)
{
  "id": "uuid-enrichment-1",
  "company_id": "client-A",
  "pool_source_id": "uuid-pool-123",  -- 🔗 Apunta al pool
  
  -- Contenido base (NULL porque viene del pool)
  "title": null,
  "content": null,
  
  -- Enriquecimiento propio del usuario
  "enriched_statements": [
    {"text": "Nueva información encontrada...", "source": "web"},
    {"text": "Contexto adicional...", "source": "groq"}
  ],
  
  -- Metadata privada
  "is_starred": true,
  "user_notes": "Importante para artículo X",
  "tags": ["seguimiento", "prioritario"]
}
```

**Al mostrar el item**: Mergear contenido base (pool) + enrichment layer (pgvector)

---

## 🔧 Implementación Técnica

### Cambios en Base de Datos

#### 1. Nueva Columna en `press_context_units`

```sql
-- Migración: add_pool_source_id.sql

ALTER TABLE press_context_units
ADD COLUMN pool_source_id TEXT;

COMMENT ON COLUMN press_context_units.pool_source_id IS 
'Si no NULL, este context unit es un enrichment layer sobre un item del pool común en Qdrant';

CREATE INDEX idx_press_context_units_pool_source 
ON press_context_units(pool_source_id) 
WHERE pool_source_id IS NOT NULL;
```

#### 2. Qdrant Collection Schema

```python
# Collection: context_units_v2 (unificada)

{
  "id": "uuid",
  "vector": [768 dimensions],
  "payload": {
    "company_id": "shared" | "client-uuid",  # "shared" = pool común
    "source_id": "uuid",
    "source_type": "direct" | "discovered",
    
    # Ranking global (solo si company_id == "shared")
    "global_usage_count": 0,
    "global_relevance_score": 0.5,
    "discovered_by": ["client-A", "client-B"],
    
    # Contenido
    "title": "...",
    "content": "...",
    "atomic_statements": [...],
    
    # Metadata
    "category": "economía",
    "published_at": "2024-11-15T10:00:00Z",
    "source_metadata": {...}
  }
}
```

---

## 📡 Endpoints Modificados (Solo 3-4)

### 1. Listing: `GET /api/v1/context-units`

**Cambio**: Añadir flag `include_pool` (default: `true`)

```python
@app.get("/api/v1/context-units")
async def list_context_units(
    company_id: str = Depends(get_company_id_from_auth),
    include_pool: bool = True,  # 🆕 Flag
    limit: int = 20,
    offset: int = 0,
    # ... otros filtros ...
):
    """
    Lista context units del usuario + opcionalmente del pool común.
    
    Sources:
    - pgvector: Fuentes directas + enriquecimientos propios
    - Qdrant (si include_pool=True): Pool común
    """
    
    # 1. Fetch from pgvector (user's own content)
    user_items = supabase.table("press_context_units")\
        .select("*")\
        .eq("company_id", company_id)\
        .limit(limit // 2 if include_pool else limit)\
        .execute().data
    
    if not include_pool:
        return {"items": user_items, "source": "user_only"}
    
    # 2. Fetch from Qdrant pool
    pool_items = await search_pool(
        company_id=company_id,
        filters={...},
        limit=limit // 2,
        exclude_already_owned=True  # No duplicar
    )
    
    # 3. Merge results
    combined = [
        {**item, "source": "user"} for item in user_items
    ] + [
        {**item, "source": "pool"} for item in pool_items
    ]
    
    return {
        "items": combined[:limit],
        "sources": {
            "user": len(user_items),
            "pool": len(pool_items)
        }
    }
```

---

### 2. Detalle: `GET /api/v1/context-units/{id}`

**Cambio**: Fallback a Qdrant pool si no existe en pgvector

```python
@app.get("/api/v1/context-units/{context_unit_id}")
async def get_context_unit(
    context_unit_id: str,
    user: Dict = Depends(get_current_user_from_jwt)
):
    """
    Detalle de context unit (propio o del pool).
    """
    company_id = user["company_id"]
    
    # 1. Try pgvector first
    result = supabase.table("press_context_units")\
        .select("*")\
        .eq("id", context_unit_id)\
        .eq("company_id", company_id)\
        .maybe_single()\
        .execute()
    
    if result.data:
        # Si tiene pool_source_id, mergear con contenido del pool
        if result.data.get("pool_source_id"):
            pool_base = await get_from_pool(result.data["pool_source_id"])
            return {
                **pool_base,  # Contenido base del pool
                **result.data,  # Enrichments del usuario
                "source": "user_enrichment_layer",
                "can_edit": True
            }
        
        return {
            **result.data,
            "source": "user",
            "can_edit": True
        }
    
    # 2. Try Qdrant pool
    pool_item = await get_from_pool(context_unit_id, company_id)
    
    if pool_item:
        return {
            **pool_item,
            "source": "pool",
            "can_edit": False,      # 🔒 Read-only desde pool
            "can_enrich": True,     # ✅ Puede crear enrichment layer
            "can_adopt": True       # ✅ Puede copiar a su espacio
        }
    
    raise HTTPException(status_code=404, detail="Not found")
```

---

### 3. Búsqueda: `POST /api/v1/context-units/search-vector`

**Cambio**: Buscar en ambos lados y mergear por score

```python
@app.post("/api/v1/context-units/search-vector")
async def semantic_search(
    request: SemanticSearchRequest,
    company_id: str = Depends(get_company_id_from_auth)
):
    """
    Búsqueda semántica en pgvector + Qdrant pool.
    """
    
    # Generate embedding
    query_embedding = await generate_embedding_fastembed(request.query)
    
    # 1. Search in pgvector (user's content)
    pgvector_results = await search_pgvector(
        company_id=company_id,
        embedding=query_embedding,
        limit=request.limit,
        threshold=request.threshold
    )
    
    # 2. Search in Qdrant pool (if enabled)
    include_pool = getattr(request, 'include_pool', True)
    
    if include_pool:
        pool_results = await search_qdrant_pool(
            company_id=company_id,
            embedding=query_embedding,
            limit=request.limit,
            threshold=request.threshold,
            exclude_owned=True  # No duplicar lo que ya tiene
        )
    else:
        pool_results = []
    
    # 3. Merge and sort by similarity score
    combined = [
        {**r, "source": "user"} for r in pgvector_results
    ] + [
        {**r, "source": "pool"} for r in pool_results
    ]
    
    combined.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    
    return {
        "results": combined[:request.limit],
        "sources": {
            "user": len(pgvector_results),
            "pool": len(pool_results)
        }
    }
```

---

### 4. (Opcional) Adoptar desde Pool

```python
@app.post("/api/v1/context-units/adopt/{pool_id}")
async def adopt_from_pool(
    pool_id: str,
    client: Dict = Depends(get_current_client)
):
    """
    Copia un context unit del pool al espacio del usuario.
    
    Beneficios:
    - Usuario puede editarlo/enriquecerlo libremente
    - Se cuenta como "uso" para ranking del pool
    """
    
    # 1. Get from Qdrant pool
    pool_item = await get_from_pool(pool_id)
    
    if not pool_item:
        raise HTTPException(status_code=404, detail="Pool item not found")
    
    # 2. Create copy in pgvector
    context_unit_id = str(uuid.uuid4())
    
    await supabase.table("press_context_units").insert({
        "id": context_unit_id,
        "company_id": client["company_id"],
        "pool_source_id": pool_id,  # 🔗 Tracking
        **pool_item
    }).execute()
    
    # 3. Update pool usage count
    await increment_pool_usage(pool_id, client["company_id"])
    
    return {
        "id": context_unit_id,
        "message": "Content adopted from pool",
        "pool_source_id": pool_id
    }
```

---

## 🔄 Enriquecimiento sobre Pool Items

### Estrategia: Enrichment Layers en pgvector

```python
@app.post("/api/v1/context-units/{context_unit_id}/enrichment")
async def enrichment_context_unit(
    context_unit_id: str,
    request: EnrichContextUnitRequest,
    client: Dict = Depends(get_current_client)
):
    """
    Enriquece context unit (propio o del pool).
    
    - Si es del pool: crea enrichment layer en pgvector
    - Si es propio: actualiza directamente
    """
    
    # 1. Check if it's user's own content
    user_content = supabase.table("press_context_units")\
        .select("*")\
        .eq("id", context_unit_id)\
        .eq("company_id", client["company_id"])\
        .maybe_single()\
        .execute()
    
    if user_content.data:
        # Caso 1: Propio → actualizar directamente
        enrichment = await enrich_with_groq(user_content.data, request.enrich_type)
        
        supabase.table("press_context_units")\
            .update({"enriched_statements": enrichment})\
            .eq("id", context_unit_id)\
            .execute()
        
        return {"enrichment": enrichment, "mode": "updated_own"}
    
    # 2. Check if it's from pool
    pool_item = await get_from_pool(context_unit_id)
    
    if pool_item:
        # Caso 2: Pool → crear enrichment layer
        enrichment = await enrich_with_groq(pool_item, request.enrich_type)
        
        enrichment_id = str(uuid.uuid4())
        
        supabase.table("press_context_units").insert({
            "id": enrichment_id,
            "company_id": client["company_id"],
            "pool_source_id": context_unit_id,  # Referencia al pool
            "enriched_statements": enrichment,
            "title": null,  # Solo enrichment, no contenido base
            "content": null
        }).execute()
        
        return {
            "enrichment": enrichment,
            "mode": "enrichment_layer_created",
            "enrichment_id": enrichment_id
        }
    
    raise HTTPException(status_code=404, detail="Context unit not found")
```

---

## 🛠️ Componentes Nuevos

### 1. Qdrant Pool Client

**Archivo:** `utils/qdrant_pool_client.py`

```python
"""Client for accessing Qdrant shared pool."""

from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from .config import settings
from .logger import get_logger

logger = get_logger("qdrant_pool_client")

class QdrantPoolClient:
    """Client for Qdrant shared pool operations."""
    
    def __init__(self):
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key
        )
        self.collection_name = "context_units_v2"
    
    async def search_pool(
        self,
        company_id: str,
        embedding: List[float],
        filters: Dict = None,
        limit: int = 10,
        threshold: float = 0.7,
        exclude_owned: bool = True
    ) -> List[Dict]:
        """
        Search in shared pool.
        
        Args:
            company_id: For deduplication (exclude items user already has)
            embedding: Query vector
            filters: Additional filters (category, date range, etc.)
            limit: Max results
            threshold: Min similarity score
            exclude_owned: Don't return items user already adopted
        
        Returns:
            List of matching context units from pool
        """
        
        # Build filter: company_id == "shared"
        must_conditions = [
            FieldCondition(
                key="company_id",
                match=MatchValue(value="shared")
            )
        ]
        
        # Add custom filters
        if filters:
            if filters.get("category"):
                must_conditions.append(
                    FieldCondition(
                        key="category",
                        match=MatchValue(value=filters["category"])
                    )
                )
            # ... más filtros
        
        # Exclude items user already has (if requested)
        must_not_conditions = []
        if exclude_owned:
            owned_ids = await self._get_user_adopted_ids(company_id)
            if owned_ids:
                must_not_conditions.append(
                    HasIdCondition(has_id=owned_ids)
                )
        
        # Search
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=embedding,
            query_filter=Filter(
                must=must_conditions,
                must_not=must_not_conditions
            ),
            limit=limit,
            score_threshold=threshold
        )
        
        return [
            {
                "id": hit.id,
                "similarity": hit.score,
                **hit.payload
            }
            for hit in results
        ]
    
    async def get_from_pool(
        self,
        point_id: str,
        company_id: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get single item from pool by ID.
        
        Args:
            point_id: Qdrant point ID
            company_id: Optional, for visibility check
        
        Returns:
            Context unit payload or None
        """
        try:
            result = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
                with_payload=True
            )
            
            if not result:
                return None
            
            point = result[0]
            
            # Verify it's from pool
            if point.payload.get("company_id") != "shared":
                logger.warn("attempted_access_non_pool_item",
                    point_id=point_id,
                    company_id=company_id
                )
                return None
            
            return {
                "id": point.id,
                **point.payload
            }
        
        except Exception as e:
            logger.error("get_from_pool_error",
                error=str(e),
                point_id=point_id
            )
            return None
    
    async def increment_pool_usage(
        self,
        pool_id: str,
        company_id: str
    ):
        """
        Increment usage count when user adopts/uses pool item.
        
        Updates:
        - global_usage_count++
        - discovered_by array (if not already included)
        """
        
        # Get current data
        item = await self.get_from_pool(pool_id)
        
        if not item:
            return
        
        # Update counters
        new_usage = item.get("global_usage_count", 0) + 1
        discovered_by = set(item.get("discovered_by", []))
        discovered_by.add(company_id)
        
        # Update in Qdrant
        self.client.set_payload(
            collection_name=self.collection_name,
            points=[pool_id],
            payload={
                "global_usage_count": new_usage,
                "discovered_by": list(discovered_by)
            }
        )
        
        logger.info("pool_usage_incremented",
            pool_id=pool_id,
            company_id=company_id,
            new_usage_count=new_usage
        )
    
    async def _get_user_adopted_ids(self, company_id: str) -> List[str]:
        """Get list of pool IDs that user has already adopted."""
        from .supabase_client import get_supabase_client
        
        supabase = get_supabase_client()
        
        result = supabase.client.table("press_context_units")\
            .select("pool_source_id")\
            .eq("company_id", company_id)\
            .not_.is_("pool_source_id", "null")\
            .execute()
        
        return [row["pool_source_id"] for row in result.data if row.get("pool_source_id")]


# Singleton
_pool_client = None

def get_qdrant_pool_client() -> QdrantPoolClient:
    """Get singleton Qdrant pool client."""
    global _pool_client
    if _pool_client is None:
        _pool_client = QdrantPoolClient()
    return _pool_client
```

---

## 📅 Plan de Implementación

### **Fase 1: Pool Client (2 días)**
- [x] Crear `utils/qdrant_pool_client.py`
- [x] Métodos: `search_pool()`, `get_from_pool()`, `increment_pool_usage()`
- [x] Testing básico con datos mock

### **Fase 2: Modificar Endpoints (2 días)**
- [ ] Añadir columna `pool_source_id` a `press_context_units`
- [ ] Modificar `GET /api/v1/context-units` (listing con pool)
- [ ] Modificar `GET /api/v1/context-units/{id}` (detalle con fallback)
- [ ] Modificar `POST /api/v1/context-units/search-vector` (búsqueda dual)

### **Fase 3: Enrichment Layers (1 día)**
- [ ] Modificar `POST /api/v1/context-units/{id}/enrichment`
- [ ] Lógica para crear enrichment layer sobre pool items
- [ ] Mergear contenido base + enrichments al devolver

### **Fase 4: Adopción (1 día)**
- [ ] Endpoint `POST /api/v1/context-units/adopt/{pool_id}`
- [ ] Tracking de adoptions en pool (`global_usage_count++`)

### **Fase 5: Testing End-to-End (1 día)**
- [ ] Probar con 1 cliente + pool de 20 noticias
- [ ] Verificar deduplicación (exclude_owned)
- [ ] Validar enriquecimientos sobre pool items
- [ ] Validar adopción y tracking

**Total: ~7 días**

---

## 🎯 Conclusiones

### ✅ **NO es mucho lío**

**Cambios mínimos necesarios**:
1. ✅ Añadir columna `pool_source_id` (1 migración SQL)
2. ✅ Crear `utils/qdrant_pool_client.py` (~200 líneas)
3. ✅ Modificar 3 endpoints (listing, detalle, búsqueda)
4. ✅ Adaptar enriquecimiento para soportar layers

**Complejidad**: ⭐⭐⭐ (Media, muy manejable)

### 🎁 Beneficios

1. **Efecto red**: Clientes contribuyen al ranking global
2. **Costos optimizados**: Deduplicación automática
3. **UX mejorado**: Acceso transparente a contenido descubierto
4. **Flexibilidad**: Usuario puede adoptar o solo enriquecer
5. **Escalabilidad**: Pool común escala independiente de pgvector

### ⚠️ Consideraciones

1. **Privacidad**: Pool solo para fuentes públicas (salas de prensa, ayuntamientos)
2. **Calidad**: Threshold mínimo para entrar al pool (`avg_quality_score > 0.6`)
3. **GDPR**: Solo URLs y contenido público, no PII
4. **Performance**: Búsqueda dual (pgvector + Qdrant) debe ser <500ms

---

**Preparado por:** Claude Code  
**Fecha:** 2 Diciembre 2024  
**Versión:** 1.0
