"""Markdown report generator for web monitoring.

Generates structured Markdown reports for subsidies, government forms, etc.
Uses Jinja2 templates for consistent formatting.
"""

from datetime import datetime
from typing import Dict, List, Optional
from jinja2 import Template

from .logger import get_logger

logger = get_logger("md_report_generator")

# Jinja2 template for subsidy reports
SUBSIDY_REPORT_TEMPLATE = """# {{titulo}}

**Última actualización**: {{fecha_actualizacion}}  
**Fuente**: [{{url_text}}]({{url}})

---

## 📅 Plazos de Presentación

{% if plazos.estado %}
- **Estado**: {% if plazos.estado|lower == 'abierto' %}✅ ABIERTO{% elif plazos.estado|lower == 'cerrado' %}❌ CERRADO{% else %}⏸️ {{plazos.estado|upper}}{% endif %}
{% endif %}
{% if plazos.fecha_inicio %}
- **Fecha inicio**: {{plazos.fecha_inicio}}
{% endif %}
{% if plazos.fecha_fin %}
- **Fecha fin**: {{plazos.fecha_fin}}
{% endif %}
{% if plazos.dias_restantes %}
- **Días restantes**: {{plazos.dias_restantes}} días
{% endif %}
{% if plazos.notas %}

{{plazos.notas}}
{% endif %}

---

## 📋 Metodología de Presentación

{{metodologia}}

---

## 📄 Documentación a Presentar

{% if documentacion and documentacion|length > 0 %}
{% for doc in documentacion %}
### {{loop.index}}. {{doc.titulo}}

- **Enlace**: [{{doc.url}}]({{doc.url}})
{% if doc.descripcion %}
- **Descripción**: {{doc.descripcion}}
{% endif %}
{% if doc.summary_bullets and doc.summary_bullets|length > 0 %}
- **Resumen**:
{% for bullet in doc.summary_bullets %}
  - {{bullet}}
{% endfor %}
{% endif %}
{% if doc.error %}
- ⚠️ **Error**: {{doc.error}}
{% endif %}

{% endfor %}
{% else %}
*No se encontró documentación específica.*
{% endif %}

---

## 💰 Solicitudes de Justificación y Pago

{% if solicitudes_pago and solicitudes_pago|length > 0 %}
{% for solicitud in solicitudes_pago %}
- [{{solicitud.titulo}}]({{solicitud.url}}){% if solicitud.descripcion %} - {{solicitud.descripcion}}{% endif %}
{% endfor %}
{% else %}
*No se encontraron solicitudes de pago específicas.*
{% endif %}

---

## 📌 Información Adicional

{% if informacion_adicional %}
{{informacion_adicional}}
{% else %}
*No hay información adicional disponible en este momento.*
{% endif %}

---

**Generado automáticamente por semantika** | Sistema de Monitorización de Subvenciones
"""


class MarkdownReportGenerator:
    """Generate Markdown reports for web monitoring."""
    
    def __init__(self):
        """Initialize report generator."""
        self.template = Template(SUBSIDY_REPORT_TEMPLATE)
        logger.info("md_report_generator_initialized")
    
    def generate_subsidy_report(
        self,
        titulo: str,
        url: str,
        plazos: Dict,
        metodologia: str,
        documentacion: List[Dict],
        solicitudes_pago: List[Dict],
        informacion_adicional: Optional[str] = None,
        fecha_actualizacion: Optional[str] = None
    ) -> str:
        """
        Generate subsidy report in Markdown format.
        
        Args:
            titulo: Report title (e.g., "Subvenciones Forestales DFA 2025")
            url: Source URL
            plazos: Dict with:
                - estado: str (abierto/cerrado)
                - fecha_inicio: str (YYYY-MM-DD)
                - fecha_fin: str (YYYY-MM-DD)
                - dias_restantes: int (optional)
                - notas: str (optional)
            metodologia: str - Methodology description
            documentacion: List of dicts with:
                - titulo: str
                - url: str
                - descripcion: str (optional)
                - summary_bullets: List[str] (optional)
                - error: str (optional - if PDF processing failed)
            solicitudes_pago: List of dicts with:
                - titulo: str
                - url: str
                - descripcion: str (optional)
            informacion_adicional: Optional additional info
            fecha_actualizacion: Optional update date (ISO format)
            
        Returns:
            Markdown report as string
        """
        try:
            # Default fecha_actualizacion to now if not provided
            if not fecha_actualizacion:
                fecha_actualizacion = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            
            # Extract clean URL text for display
            url_text = url.replace('https://', '').replace('http://', '')
            if len(url_text) > 60:
                url_text = url_text[:57] + "..."
            
            # Calculate dias_restantes if not provided
            if plazos and plazos.get("fecha_fin") and not plazos.get("dias_restantes"):
                try:
                    from datetime import date
                    fecha_fin = datetime.strptime(plazos["fecha_fin"], "%Y-%m-%d").date()
                    hoy = date.today()
                    dias_restantes = (fecha_fin - hoy).days
                    if dias_restantes >= 0:
                        plazos["dias_restantes"] = dias_restantes
                except:
                    pass
            
            # Render template
            report = self.template.render(
                titulo=titulo,
                url=url,
                url_text=url_text,
                plazos=plazos,
                metodologia=metodologia,
                documentacion=documentacion,
                solicitudes_pago=solicitudes_pago,
                informacion_adicional=informacion_adicional,
                fecha_actualizacion=fecha_actualizacion
            )
            
            logger.info("subsidy_report_generated",
                titulo=titulo[:50],
                documentacion_count=len(documentacion),
                solicitudes_count=len(solicitudes_pago),
                report_length=len(report)
            )
            
            return report
        
        except Exception as e:
            logger.error("subsidy_report_generation_error",
                titulo=titulo,
                error=str(e)
            )
            raise
    
    def generate_simple_web_report(
        self,
        titulo: str,
        url: str,
        contenido: str,
        metadata: Optional[Dict] = None,
        fecha_actualizacion: Optional[str] = None
    ) -> str:
        """
        Generate simple web content report.
        
        For generic web monitoring (not subsidies).
        
        Args:
            titulo: Page title
            url: Source URL
            contenido: Main content
            metadata: Optional metadata dict
            fecha_actualizacion: Optional update date
            
        Returns:
            Markdown report
        """
        if not fecha_actualizacion:
            fecha_actualizacion = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        report = f"""# {titulo}

**Última actualización**: {fecha_actualizacion}  
**Fuente**: [{url}]({url})

---

{contenido}

---
"""
        
        if metadata:
            report += "\n## Metadata\n\n"
            for key, value in metadata.items():
                report += f"- **{key}**: {value}\n"
            report += "\n---\n"
        
        report += "\n**Generado automáticamente por semantika**\n"
        
        logger.info("simple_web_report_generated",
            titulo=titulo[:50],
            content_length=len(contenido),
            report_length=len(report)
        )
        
        return report


# Singleton instance
_report_generator_instance = None

def get_report_generator() -> MarkdownReportGenerator:
    """Get or create report generator singleton."""
    global _report_generator_instance
    if _report_generator_instance is None:
        _report_generator_instance = MarkdownReportGenerator()
    return _report_generator_instance
