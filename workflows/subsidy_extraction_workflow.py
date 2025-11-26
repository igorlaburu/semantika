"""Subsidy extraction workflow for DFA and similar sources.

Extracts structured information from subsidy/grant pages:
- Deadlines (plazos)
- Documentation requirements
- Payment requests
- Methodology

Processes PDFs and generates comprehensive Markdown reports.
"""

import asyncio
import json
from typing import Dict, List, Any, Optional
from datetime import datetime

from workflows.base_workflow import BaseWorkflow
from core.source_content import SourceContent
from utils.llm_client import LLMClient
from utils.pdf_extractor import get_pdf_extractor
from utils.md_report_generator import get_report_generator
from utils.logger import get_logger

logger = get_logger("subsidy_extraction_workflow")


class SubsidyExtractionWorkflow(BaseWorkflow):
    """Workflow for extracting structured subsidy information."""
    
    def __init__(self, company_code: str, company_settings: Optional[Dict[str, Any]] = None):
        """Initialize subsidy extraction workflow."""
        super().__init__(company_code, company_settings)
        self.llm_client = LLMClient()
        self.pdf_extractor = get_pdf_extractor()
        self.report_generator = get_report_generator()
    
    async def generate_context_unit(self, source_content: SourceContent) -> Dict[str, Any]:
        """
        Generate context unit by extracting structured subsidy data.
        
        Pipeline:
        1. LLM extracts structured JSON (plazos, docs, methodology)
        2. Download and process all linked PDFs
        3. Generate comprehensive Markdown report
        4. Return as context unit
        
        Args:
            source_content: HTML content from subsidy page
            
        Returns:
            Context unit with structured data
        """
        try:
            self.logger.info("subsidy_extraction_start",
                source_id=source_content.source_id
            )
            
            # Step 1: LLM extraction of structured data
            extracted_data = await self._extract_subsidy_data_with_llm(
                source_content.text_content
            )
            
            # Step 2: Process PDFs (parallel)
            if extracted_data.get("documentacion_presentar"):
                await self._process_pdf_documents(
                    extracted_data["documentacion_presentar"]
                )
            
            if extracted_data.get("solicitudes_pago"):
                await self._process_pdf_documents(
                    extracted_data["solicitudes_pago"],
                    summarize=False  # Just check if accessible
                )
            
            # Step 3: Generate Markdown report
            md_report = self._generate_markdown_report(
                source_content=source_content,
                extracted_data=extracted_data
            )
            
            # Step 4: Build context unit
            context_unit = {
                "id": source_content.metadata.get("context_unit_id"),
                "title": extracted_data.get("titulo", source_content.title or "Subvención"),
                "summary": extracted_data.get("resumen_ejecutivo", ""),
                "raw_text": md_report,
                "tags": self._extract_tags(extracted_data),
                "category": "subvenciones",
                "atomic_statements": self._extract_atomic_statements(extracted_data),
                "source_metadata": {
                    **source_content.metadata,
                    "extracted_data": extracted_data,
                    "generation_timestamp": datetime.utcnow().isoformat()
                }
            }
            
            self.logger.info("subsidy_extraction_complete",
                source_id=source_content.source_id,
                pdf_count=len(extracted_data.get("documentacion_presentar", []))
            )
            
            return context_unit
        
        except Exception as e:
            self.logger.error("subsidy_extraction_error",
                source_id=source_content.source_id,
                error=str(e)
            )
            raise
    
    async def _extract_subsidy_data_with_llm(self, html_content: str) -> Dict:
        """
        Extract structured subsidy data using LLM.
        
        Args:
            html_content: HTML content from page
            
        Returns:
            Dict with structured data
        """
        prompt = f"""Extrae información estructurada de la siguiente página de subvenciones.

Contenido HTML:
{html_content[:30000]}  

Extrae la siguiente información en formato JSON:

{{
  "titulo": "Título completo de la convocatoria",
  "resumen_ejecutivo": "Resumen breve (2-3 líneas) de la subvención",
  "plazos": {{
    "estado": "abierto|cerrado|pendiente",
    "fecha_inicio": "YYYY-MM-DD o null",
    "fecha_fin": "YYYY-MM-DD o null",
    "notas": "Información adicional sobre plazos"
  }},
  "metodologia": "Texto descriptivo sobre cómo presentar la solicitud (qué pasos seguir, dónde presentarla, requisitos generales)",
  "documentacion_presentar": [
    {{
      "titulo": "Nombre descriptivo del documento",
      "url": "URL completa del PDF o documento",
      "descripcion": "Breve descripción de qué contiene"
    }}
  ],
  "solicitudes_pago": [
    {{
      "titulo": "Nombre del documento de pago/justificación",
      "url": "URL completa",
      "descripcion": "Para qué sirve este documento"
    }}
  ],
  "informacion_adicional": "Cualquier otra información relevante no cubierta arriba"
}}

IMPORTANTE:
- Extrae TODAS las URLs de PDFs o documentos que encuentres
- Si no encuentras algún campo, usa null o array vacío
- Las URLs deben ser completas (con https://)
- Si las URLs son relativas, completa con el dominio base

Responde SOLO con el JSON, sin explicaciones adicionales.

JSON:"""
        
        try:
            # Use provider interface for tracking and cost calculation
            from langchain_core.messages import HumanMessage, SystemMessage
            
            provider = self.llm_client.registry.get('groq_fast')
            messages = [
                SystemMessage(content="Eres un experto en extraer información estructurada de páginas web de administraciones públicas. Respondes siempre en formato JSON válido."),
                HumanMessage(content=prompt)
            ]
            
            config = {
                'tracking': {
                    'organization_id': self.company_id,
                    'operation': 'subsidy_extraction'
                }
            }
            
            response = await provider.ainvoke(messages, config=config)
            
            # Parse JSON
            # Remove markdown code blocks if present
            cleaned_response = response.content.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            if cleaned_response.startswith("```"):
                cleaned_response = cleaned_response[3:]
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            cleaned_response = cleaned_response.strip()
            
            extracted_data = json.loads(cleaned_response)
            
            self.logger.info("llm_extraction_success",
                docs_count=len(extracted_data.get("documentacion_presentar", [])),
                payment_count=len(extracted_data.get("solicitudes_pago", []))
            )
            
            return extracted_data
        
        except json.JSONDecodeError as e:
            self.logger.error("llm_extraction_json_error",
                error=str(e),
                response_preview=response[:200] if 'response' in locals() else "N/A"
            )
            # Return minimal structure
            return {
                "titulo": "Error en extracción",
                "plazos": {},
                "metodologia": html_content[:500],
                "documentacion_presentar": [],
                "solicitudes_pago": [],
                "error": f"JSON parse error: {str(e)}"
            }
        
        except Exception as e:
            self.logger.error("llm_extraction_error", error=str(e))
            raise
    
    async def _process_pdf_documents(
        self,
        documents: List[Dict],
        summarize: bool = True
    ):
        """
        Process all PDF documents in parallel.
        
        Modifies documents list in-place with:
        - summary_bullets: List[str]
        - text: str (if needed)
        - error: str (if failed)
        
        Args:
            documents: List of document dicts with 'url'
            summarize: Whether to generate summaries
        """
        if not documents:
            return
        
        self.logger.info("pdf_processing_batch_start",
            count=len(documents),
            summarize=summarize
        )
        
        # Process PDFs in parallel (limit concurrency to avoid overwhelming)
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent downloads
        
        async def process_single_pdf(doc: Dict):
            async with semaphore:
                try:
                    result = await self.pdf_extractor.process_pdf(
                        url=doc["url"],
                        filename=doc.get("titulo", "documento"),
                        summarize=summarize
                    )
                    
                    if result["success"]:
                        doc["summary_bullets"] = result.get("summary_bullets", [])
                        doc["text"] = result.get("text", "")
                        doc["size_kb"] = result.get("size_kb", 0)
                    else:
                        doc["error"] = result.get("error", "Unknown error")
                
                except Exception as e:
                    doc["error"] = str(e)
                    self.logger.error("pdf_processing_error",
                        url=doc["url"],
                        error=str(e)
                    )
        
        # Process all documents
        await asyncio.gather(*[process_single_pdf(doc) for doc in documents])
        
        success_count = sum(1 for doc in documents if "summary_bullets" in doc or not summarize)
        self.logger.info("pdf_processing_batch_complete",
            total=len(documents),
            success=success_count,
            failed=len(documents) - success_count
        )
    
    def _generate_markdown_report(
        self,
        source_content: SourceContent,
        extracted_data: Dict
    ) -> str:
        """
        Generate comprehensive Markdown report.
        
        Args:
            source_content: Original source content
            extracted_data: Extracted structured data
            
        Returns:
            Markdown report
        """
        try:
            report = self.report_generator.generate_subsidy_report(
                titulo=extracted_data.get("titulo", "Subvención"),
                url=source_content.metadata.get("url", ""),
                plazos=extracted_data.get("plazos", {}),
                metodologia=extracted_data.get("metodologia", ""),
                documentacion=extracted_data.get("documentacion_presentar", []),
                solicitudes_pago=extracted_data.get("solicitudes_pago", []),
                informacion_adicional=extracted_data.get("informacion_adicional"),
                fecha_actualizacion=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            )
            
            return report
        
        except Exception as e:
            self.logger.error("report_generation_error", error=str(e))
            # Fallback to simple report
            return f"""# {extracted_data.get("titulo", "Subvención")}

**Error al generar informe completo**: {str(e)}

## Contenido extraído:

{json.dumps(extracted_data, indent=2, ensure_ascii=False)}
"""
    
    def _extract_tags(self, extracted_data: Dict) -> List[str]:
        """Extract tags from extracted data."""
        tags = ["subvención", "DFA"]
        
        # Add estado as tag
        estado = extracted_data.get("plazos", {}).get("estado")
        if estado:
            tags.append(f"estado:{estado}")
        
        # Add year if fecha_fin exists
        fecha_fin = extracted_data.get("plazos", {}).get("fecha_fin")
        if fecha_fin and len(fecha_fin) >= 4:
            year = fecha_fin[:4]
            tags.append(year)
        
        return tags
    
    def _extract_atomic_statements(self, extracted_data: Dict) -> List[Dict]:
        """Extract atomic statements from structured data."""
        statements = []
        
        # Plazo statement
        plazos = extracted_data.get("plazos", {})
        if plazos.get("estado") or plazos.get("fecha_fin"):
            statements.append({
                "type": "deadline",
                "text": f"Estado: {plazos.get('estado', 'desconocido')}. Fecha fin: {plazos.get('fecha_fin', 'no especificada')}",
                "order": 1
            })
        
        # Documentation statements
        docs = extracted_data.get("documentacion_presentar", [])
        for i, doc in enumerate(docs[:5]):  # Limit to 5
            statements.append({
                "type": "requirement",
                "text": f"Documentación requerida: {doc.get('titulo', 'documento')}",
                "order": i + 2
            })
        
        return statements
    
    async def analyze_content(self, source_content: SourceContent, context_unit: Dict[str, Any]) -> Dict[str, Any]:
        """Additional analysis (not needed for subsidies)."""
        return {}
    
    async def custom_processing(self, source_content: SourceContent, context_unit: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Custom processing (not needed for subsidies)."""
        return {}
