# Workflows - Guía de Desarrollo

Este documento explica cómo crear, configurar e integrar nuevos workflows en el sistema semantika.

## Arquitectura de Workflows

### 1. **Estructura de Directorios**
```
/workflows/
├── workflow_factory.py         # Factory pattern para cargar workflows
├── base_workflow.py           # Clase base abstracta
├── default/                   # Workflow por defecto
│   └── default_workflow.py
├── demo/                      # Workflow para empresa demo
│   └── demo_workflow.py
├── elconfidencial/           # Workflow específico de empresa
│   └── elconfidencial_workflow.py
└── nuevo_workflow/           # Tu nuevo workflow
    └── nuevo_workflow.py
```

### 2. **Componentes del Sistema**
- **BaseWorkflow**: Clase abstracta que define la interfaz
- **WorkflowFactory**: Carga dinámicamente workflows por código
- **SourceContent**: Contenido de entrada estandarizado
- **Configuración BD**: Tabla `workflow_configs` para límites y metadatos

## Crear un Nuevo Workflow

### Paso 1: Crear Directorio y Archivo

```bash
mkdir /workflows/mi_empresa
touch /workflows/mi_empresa/mi_empresa_workflow.py
```

### Paso 2: Implementar el Workflow

```python
# /workflows/mi_empresa/mi_empresa_workflow.py
"""
Workflow específico para Mi Empresa.
Personaliza análisis de contenido según estilo periodístico.
"""

import uuid
from typing import Dict, Any
from datetime import datetime

from ..base_workflow import BaseWorkflow
from core.source_content import SourceContent
from utils.llm_pipeline import LLMPipeline
from utils.logger import get_logger

logger = get_logger("mi_empresa_workflow")

class MiEmpresaWorkflow(BaseWorkflow):
    """Workflow personalizado para Mi Empresa."""
    
    def __init__(self, company_settings: Dict[str, Any] = None):
        """
        Inicializar workflow.
        
        Args:
            company_settings: Configuración específica de la empresa
        """
        super().__init__(company_settings)
        self.workflow_code = "mi_empresa"
        
        # Configuración específica
        self.language = company_settings.get("language", "es")
        self.style_guide = company_settings.get("style_guide", "formal")
        
        # Inicializar pipeline LLM
        self.pipeline = LLMPipeline()
        
        logger.info("mi_empresa_workflow_initialized", 
            language=self.language,
            style=self.style_guide
        )
    
    async def process_content(self, content: SourceContent) -> Dict[str, Any]:
        """
        Procesar contenido según especificaciones de Mi Empresa.
        
        Args:
            content: Contenido fuente a procesar
            
        Returns:
            Dict con context_unit y metadatos
        """
        try:
            logger.info("processing_content", 
                source_type=content.source_type,
                content_length=len(content.text_content)
            )
            
            # 1. Análisis con atomic statements (específico de Mi Empresa)
            analysis_result = await self.pipeline.analyze_atomic(
                content.text_content,
                language=self.language,
                custom_prompt=self._get_custom_prompt()
            )
            
            # 2. Crear context unit con ID único
            context_unit_id = str(uuid.uuid4())
            
            context_unit = {
                "id": context_unit_id,
                "title": analysis_result.get("title", content.title),
                "summary": analysis_result.get("summary", ""),
                "tags": analysis_result.get("tags", []),
                "atomic_statements": analysis_result.get("atomic_statements", []),
                "raw_text": content.text_content,
                "source_metadata": {
                    **content.metadata,
                    "workflow_code": self.workflow_code,
                    "processed_at": datetime.utcnow().isoformat(),
                    "language": self.language,
                    "style_guide": self.style_guide
                }
            }
            
            # 3. Post-procesado específico de Mi Empresa
            context_unit = await self._post_process_content(context_unit)
            
            logger.info("content_processed_successfully",
                context_unit_id=context_unit_id,
                statements_count=len(context_unit["atomic_statements"])
            )
            
            return {
                "success": True,
                "context_unit": context_unit,
                "workflow_code": self.workflow_code
            }
            
        except Exception as e:
            logger.error("content_processing_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "workflow_code": self.workflow_code
            }
    
    def _get_custom_prompt(self) -> str:
        """Prompt personalizado para Mi Empresa."""
        return f"""
        Analiza el siguiente contenido según el estilo periodístico de Mi Empresa:
        - Enfoque en noticias locales y regionales
        - Tono {self.style_guide}
        - Idioma: {self.language}
        - Extractar hechos verificables como atomic statements
        - Generar tags relevantes para audiencia local
        """
    
    async def _post_process_content(self, context_unit: Dict[str, Any]) -> Dict[str, Any]:
        """Post-procesado específico de Mi Empresa."""
        # Ejemplo: Añadir tags específicos
        local_tags = ["álava", "vitoria", "euskadi"]
        
        for tag in local_tags:
            if tag.lower() in context_unit["raw_text"].lower():
                if tag not in context_unit["tags"]:
                    context_unit["tags"].append(tag)
        
        # Ejemplo: Filtrar statements por relevancia local
        relevant_statements = []
        for statement in context_unit["atomic_statements"]:
            if self._is_locally_relevant(statement.get("text", "")):
                relevant_statements.append(statement)
        
        context_unit["atomic_statements"] = relevant_statements
        
        return context_unit
    
    def _is_locally_relevant(self, text: str) -> bool:
        """Determinar si un statement es relevante localmente."""
        local_keywords = [
            "vitoria", "gasteiz", "álava", "araba", "euskadi", 
            "país vasco", "diputación", "ayuntamiento"
        ]
        
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in local_keywords)
```

### Paso 3: Configurar en Base de Datos

```sql
-- Insertar configuración del workflow
INSERT INTO workflow_configs (
    workflow_code,
    workflow_name,
    description,
    api_endpoint,
    is_api_enabled,
    limits_starter,
    limits_pro,
    limits_unlimited,
    estimated_cost_eur,
    is_active
) VALUES (
    'mi_empresa',
    'Mi Empresa Workflow',
    'Workflow personalizado para análisis de noticias locales de Mi Empresa',
    '/process/mi-empresa',
    true,
    '{"daily": 30, "monthly": 500}',
    '{"daily": 150, "monthly": 3000}',
    '{"daily": -1, "monthly": -1}',
    0.0075,
    true
);
```

### Paso 4: Registrar en WorkflowFactory

```python
# /workflows/workflow_factory.py
def get_workflow(workflow_code: str, company_settings: Dict[str, Any] = None) -> BaseWorkflow:
    """
    Factory para obtener workflow por código.
    """
    try:
        if workflow_code == "default":
            from .default.default_workflow import DefaultWorkflow
            return DefaultWorkflow(company_settings)
        
        elif workflow_code == "demo":
            from .demo.demo_workflow import DemoWorkflow
            return DemoWorkflow(company_settings)
            
        elif workflow_code == "mi_empresa":  # ← AÑADIR AQUÍ
            from .mi_empresa.mi_empresa_workflow import MiEmpresaWorkflow
            return MiEmpresaWorkflow(company_settings)
        
        else:
            logger.warn("unknown_workflow_code", workflow_code=workflow_code)
            from .default.default_workflow import DefaultWorkflow
            return DefaultWorkflow(company_settings)
            
    except Exception as e:
        logger.error("workflow_factory_error", workflow_code=workflow_code, error=str(e))
        from .default.default_workflow import DefaultWorkflow
        return DefaultWorkflow(company_settings)
```

### Paso 5: Asignar a Fuentes

```sql
-- Actualizar fuentes para usar el nuevo workflow
UPDATE sources 
SET workflow_code = 'mi_empresa'
WHERE client_id = 'tu-client-id' 
  AND source_type IN ('email', 'scraping');

-- O crear nueva fuente con el workflow
INSERT INTO sources (
    client_id,
    company_id,
    source_code,
    source_name,
    source_type,
    workflow_code,
    config,
    is_active
) VALUES (
    'tu-client-id',
    'tu-company-id',
    'email_mi_empresa',
    'Email Mi Empresa',
    'email',
    'mi_empresa',
    '{"email_pattern": "p.miempresa@ekimen.ai"}',
    true
);
```

## Configuración Avanzada

### 1. **Endpoints API Personalizados**

Si necesitas endpoints específicos para tu workflow:

```python
# En server.py
@app.post("/process/mi-empresa")
async def process_mi_empresa(
    request: ProcessTextRequest,
    client: Dict = Depends(get_current_client)
) -> Dict[str, Any]:
    """Endpoint específico para Mi Empresa."""
    try:
        from utils.workflow_endpoints import execute_workflow
        
        result = await execute_workflow(
            client=client,
            workflow_code="mi_empresa",
            text=request.text,
            params=request.params
        )
        
        return {
            "status": "ok",
            "workflow": "mi_empresa",
            "result": result
        }
        
    except Exception as e:
        logger.error("mi_empresa_endpoint_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
```

### 2. **Prompts Personalizados**

Crear archivos de prompts específicos:

```
/workflows/mi_empresa/
├── mi_empresa_workflow.py
├── prompts/
│   ├── analysis.txt
│   ├── atomic_statements.txt
│   └── summary.txt
└── config.json
```

### 3. **Configuración por JSON**

```json
// /workflows/mi_empresa/config.json
{
    "workflow_code": "mi_empresa",
    "default_language": "es",
    "style_guide": "formal",
    "local_keywords": [
        "vitoria", "gasteiz", "álava", "euskadi"
    ],
    "atomic_statements": {
        "min_confidence": 0.8,
        "max_statements": 15,
        "focus_areas": ["política local", "economía", "cultura"]
    },
    "post_processing": {
        "geo_tagging": true,
        "sentiment_analysis": false,
        "fact_checking": true
    }
}
```

## Testing y Validación

### 1. **Test Unitario**

```python
# tests/test_mi_empresa_workflow.py
import pytest
from workflows.mi_empresa.mi_empresa_workflow import MiEmpresaWorkflow
from core.source_content import SourceContent

@pytest.mark.asyncio
async def test_mi_empresa_workflow():
    """Test básico del workflow."""
    workflow = MiEmpresaWorkflow({"language": "es"})
    
    content = SourceContent(
        source_type="email",
        source_id="test-001",
        organization_slug="test",
        text_content="El Ayuntamiento de Vitoria anuncia nuevas medidas.",
        metadata={"subject": "Test"}
    )
    
    result = await workflow.process_content(content)
    
    assert result["success"] is True
    assert "context_unit" in result
    assert len(result["context_unit"]["atomic_statements"]) > 0
```

### 2. **Test de Integración**

```bash
# Test con curl
curl -X POST "https://api.ekimen.ai/process/mi-empresa" \
  -H "X-API-Key: tu-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "El alcalde de Vitoria ha anunciado nuevas inversiones...",
    "action": "analyze",
    "params": {"language": "es"}
  }'
```

## Monitoreo y Métricas

### 1. **Logs Estructurados**

El workflow debe loguear eventos importantes:

```python
logger.info("workflow_executed", 
    workflow_code="mi_empresa",
    content_length=len(text),
    statements_generated=len(statements),
    processing_time_ms=duration,
    client_id=client_id
)
```

### 2. **Métricas en BD**

Los workflows se trackean automáticamente en:

- **`workflow_usage`**: Conteo de ejecuciones por día
- **`llm_usage`**: Tokens y costos consumidos
- **`executions`**: Log de todas las ejecuciones

### 3. **Verificación de Health**

```python
# Método opcional en tu workflow
async def health_check(self) -> Dict[str, Any]:
    """Verificar estado del workflow."""
    return {
        "workflow_code": self.workflow_code,
        "status": "healthy",
        "dependencies": {
            "llm_pipeline": "ok",
            "database": "ok"
        }
    }
```

## Deployment

### 1. **Development**
```bash
# El workflow se carga automáticamente al reiniciar
docker-compose restart semantika-api
```

### 2. **Production**
```bash
# Deployment automático vía GitHub Actions
git add workflows/mi_empresa/
git commit -m "Add Mi Empresa workflow"
git push  # Auto-deploy
```

## Troubleshooting

### Errores Comunes

1. **ImportError**: Verificar estructura de directorios
2. **WorkflowNotFound**: Asegurar registro en factory
3. **Database Error**: Verificar configuración en `workflow_configs`
4. **LLM Timeout**: Ajustar timeouts en pipeline

### Debug Mode

```python
# En development, activar logs detallados
logger.setLevel("DEBUG")
```

## Ejemplos de Workflows Existentes

- **`default`**: Análisis básico sin personalización
- **`demo`**: Workflow de demostración con todas las funcionalidades
- **`elconfidencial`**: Ejemplo de workflow específico de empresa

¡Consulta estos workflows como referencia para implementar el tuyo!