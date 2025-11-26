"""PDF extraction utilities for web monitoring.

Downloads PDFs, extracts text using multiple methods, and generates LLM summaries.
Used by DFA subsidies monitor and other web scraping workflows.
"""

import io
import tempfile
from typing import Dict, List, Optional, Tuple
import aiohttp
import PyPDF2
import pdfplumber

from .logger import get_logger
from .llm_client import LLMClient

logger = get_logger("pdf_extractor")

# Constants
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_SIZE_MB = 10
MAX_TEXT_LENGTH_FOR_SUMMARY = 50000  # ~12k tokens


class PDFExtractor:
    """Extract and process PDF documents."""
    
    def __init__(
        self,
        max_size_mb: int = DEFAULT_MAX_SIZE_MB,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    ):
        """
        Initialize PDF extractor.
        
        Args:
            max_size_mb: Maximum PDF file size in MB
            timeout_seconds: HTTP request timeout
        """
        self.max_size_mb = max_size_mb
        self.timeout_seconds = timeout_seconds
        self.max_size_bytes = max_size_mb * 1024 * 1024
        
        logger.info("pdf_extractor_initialized",
            max_size_mb=max_size_mb,
            timeout_seconds=timeout_seconds
        )
    
    async def download_pdf(self, url: str) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Download PDF from URL with size and timeout limits.
        
        Args:
            url: PDF URL
            
        Returns:
            Tuple of (pdf_bytes, error_message)
            If successful: (bytes, None)
            If failed: (None, error_message)
        """
        try:
            logger.info("pdf_download_start", url=url)
            
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    
                    # Check status code
                    if response.status != 200:
                        error_msg = f"HTTP {response.status}"
                        logger.warn("pdf_download_failed", url=url, error=error_msg)
                        return (None, error_msg)
                    
                    # Check content type
                    content_type = response.headers.get('Content-Type', '')
                    if 'pdf' not in content_type.lower() and 'octet-stream' not in content_type.lower():
                        logger.warn("pdf_download_wrong_content_type",
                            url=url,
                            content_type=content_type
                        )
                    
                    # Check content length
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > self.max_size_bytes:
                        error_msg = f"File too large: {int(content_length) / 1024 / 1024:.1f}MB (max {self.max_size_mb}MB)"
                        logger.warn("pdf_download_too_large", url=url, error=error_msg)
                        return (None, error_msg)
                    
                    # Read content with size limit
                    pdf_bytes = await response.read()
                    
                    # Final size check
                    if len(pdf_bytes) > self.max_size_bytes:
                        error_msg = f"Downloaded file too large: {len(pdf_bytes) / 1024 / 1024:.1f}MB"
                        logger.warn("pdf_download_too_large_after_read",
                            url=url,
                            error=error_msg
                        )
                        return (None, error_msg)
                    
                    logger.info("pdf_download_success",
                        url=url,
                        size_kb=len(pdf_bytes) / 1024
                    )
                    
                    return (pdf_bytes, None)
        
        except aiohttp.ClientError as e:
            error_msg = f"Network error: {str(e)}"
            logger.error("pdf_download_network_error", url=url, error=error_msg)
            return (None, error_msg)
        
        except asyncio.TimeoutError:
            error_msg = f"Timeout after {self.timeout_seconds}s"
            logger.error("pdf_download_timeout", url=url, error=error_msg)
            return (None, error_msg)
        
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error("pdf_download_error", url=url, error=error_msg)
            return (None, error_msg)
    
    def extract_text_pypdf2(self, pdf_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract text using PyPDF2.
        
        Args:
            pdf_bytes: PDF file bytes
            
        Returns:
            Tuple of (text, error_message)
        """
        try:
            pdf_file = io.BytesIO(pdf_bytes)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text_parts = []
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            
            full_text = "\n\n".join(text_parts)
            
            if not full_text.strip():
                return (None, "No text extracted (possibly scanned PDF)")
            
            logger.info("pdf_text_extracted_pypdf2",
                pages=len(pdf_reader.pages),
                text_length=len(full_text)
            )
            
            return (full_text, None)
        
        except Exception as e:
            error_msg = f"PyPDF2 extraction failed: {str(e)}"
            logger.warn("pdf_extraction_pypdf2_error", error=error_msg)
            return (None, error_msg)
    
    def extract_text_pdfplumber(self, pdf_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract text using pdfplumber (fallback method).
        
        Args:
            pdf_bytes: PDF file bytes
            
        Returns:
            Tuple of (text, error_message)
        """
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(pdf_bytes)
                tmp_path = tmp_file.name
            
            try:
                text_parts = []
                with pdfplumber.open(tmp_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                
                full_text = "\n\n".join(text_parts)
                
                if not full_text.strip():
                    return (None, "No text extracted")
                
                logger.info("pdf_text_extracted_pdfplumber",
                    pages=len(text_parts),
                    text_length=len(full_text)
                )
                
                return (full_text, None)
            
            finally:
                # Cleanup temp file
                import os
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        
        except Exception as e:
            error_msg = f"pdfplumber extraction failed: {str(e)}"
            logger.warn("pdf_extraction_pdfplumber_error", error=error_msg)
            return (None, error_msg)
    
    def extract_text(self, pdf_bytes: bytes) -> Tuple[Optional[str], List[str]]:
        """
        Extract text from PDF using multiple methods (fallback chain).
        
        Tries:
        1. PyPDF2 (fast, good for text-based PDFs)
        2. pdfplumber (slower, better for complex layouts)
        
        Args:
            pdf_bytes: PDF file bytes
            
        Returns:
            Tuple of (text, errors_list)
            If successful: (text, [])
            If failed: (None, [error1, error2, ...])
        """
        errors = []
        
        # Try PyPDF2 first
        text, error = self.extract_text_pypdf2(pdf_bytes)
        if text:
            return (text, errors)
        if error:
            errors.append(f"PyPDF2: {error}")
        
        # Fallback to pdfplumber
        text, error = self.extract_text_pdfplumber(pdf_bytes)
        if text:
            return (text, errors)
        if error:
            errors.append(f"pdfplumber: {error}")
        
        logger.error("pdf_extraction_all_methods_failed",
            errors=errors
        )
        
        return (None, errors)
    
    async def summarize_with_llm(
        self,
        text: str,
        filename: str = "documento",
        max_bullets: int = 5
    ) -> List[str]:
        """
        Generate bullet-point summary of PDF text using LLM.
        
        Args:
            text: Extracted PDF text
            filename: Original filename (for context)
            max_bullets: Maximum number of bullet points
            
        Returns:
            List of bullet points (strings)
        """
        try:
            # Truncate if too long
            if len(text) > MAX_TEXT_LENGTH_FOR_SUMMARY:
                logger.warn("pdf_text_truncated_for_summary",
                    original_length=len(text),
                    truncated_length=MAX_TEXT_LENGTH_FOR_SUMMARY
                )
                text = text[:MAX_TEXT_LENGTH_FOR_SUMMARY] + "\n\n[...texto truncado...]"
            
            # Prepare prompt
            prompt = f"""Resume el siguiente documento PDF en {max_bullets} puntos clave (bullet points).

Documento: {filename}

Contenido:
{text}

Instrucciones:
- Extrae los {max_bullets} puntos más importantes
- Cada punto debe ser claro y conciso
- Enfócate en información práctica (requisitos, plazos, documentación, etc.)
- Responde SOLO con los bullet points, sin introducción ni conclusión
- Formato: Un bullet point por línea, comenzando con "-"

Puntos clave:"""
            
            # Call LLM using proper interface
            from langchain_core.messages import HumanMessage, SystemMessage
            
            llm_client = LLMClient()
            provider = llm_client.registry.get('groq_fast')
            
            messages = [
                SystemMessage(content="Eres un asistente especializado en resumir documentos legales y administrativos de forma clara y concisa."),
                HumanMessage(content=prompt)
            ]
            
            config = {
                'tracking': {
                    'organization_id': None,
                    'operation': 'pdf_summary'
                }
            }
            
            response = await provider.ainvoke(messages, config=config)
            
            # Parse bullet points
            lines = response.content.strip().split('\n')
            bullets = []
            for line in lines:
                line = line.strip()
                if line.startswith('-') or line.startswith('•') or line.startswith('*'):
                    bullet = line.lstrip('-•* ').strip()
                    if bullet:
                        bullets.append(bullet)
            
            # Limit to max_bullets
            bullets = bullets[:max_bullets]
            
            logger.info("pdf_summary_generated",
                filename=filename,
                bullet_count=len(bullets),
                text_length=len(text)
            )
            
            return bullets
        
        except Exception as e:
            logger.error("pdf_summary_error",
                filename=filename,
                error=str(e)
            )
            return [f"Error al generar resumen: {str(e)}"]
    
    async def process_pdf(
        self,
        url: str,
        filename: Optional[str] = None,
        summarize: bool = True
    ) -> Dict:
        """
        Complete PDF processing pipeline: download → extract → summarize.
        
        Args:
            url: PDF URL
            filename: Optional filename (for logging/context)
            summarize: Whether to generate LLM summary
            
        Returns:
            Dict with:
            - success: bool
            - text: str (if successful)
            - summary_bullets: List[str] (if summarize=True)
            - error: str (if failed)
            - size_kb: float
            - extraction_method: str
        """
        if not filename:
            filename = url.split('/')[-1] or "documento.pdf"
        
        logger.info("pdf_processing_start", url=url, filename=filename)
        
        # Step 1: Download
        pdf_bytes, download_error = await self.download_pdf(url)
        if not pdf_bytes:
            return {
                "success": False,
                "error": download_error,
                "url": url,
                "filename": filename
            }
        
        size_kb = len(pdf_bytes) / 1024
        
        # Step 2: Extract text
        text, extraction_errors = self.extract_text(pdf_bytes)
        if not text:
            return {
                "success": False,
                "error": f"Text extraction failed: {'; '.join(extraction_errors)}",
                "url": url,
                "filename": filename,
                "size_kb": size_kb
            }
        
        # Step 3: Summarize (optional)
        summary_bullets = []
        if summarize:
            summary_bullets = await self.summarize_with_llm(text, filename)
        
        logger.info("pdf_processing_complete",
            url=url,
            filename=filename,
            text_length=len(text),
            summary_bullets=len(summary_bullets)
        )
        
        return {
            "success": True,
            "text": text,
            "summary_bullets": summary_bullets,
            "url": url,
            "filename": filename,
            "size_kb": size_kb,
            "text_length": len(text)
        }


# Singleton instance
_pdf_extractor_instance = None

def get_pdf_extractor(
    max_size_mb: int = DEFAULT_MAX_SIZE_MB,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> PDFExtractor:
    """Get or create PDF extractor singleton."""
    global _pdf_extractor_instance
    if _pdf_extractor_instance is None:
        _pdf_extractor_instance = PDFExtractor(
            max_size_mb=max_size_mb,
            timeout_seconds=timeout_seconds
        )
    return _pdf_extractor_instance
