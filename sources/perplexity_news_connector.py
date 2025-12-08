"""
Perplexity News Connector for semantika.

Fetches daily news from Perplexity API and processes them through workflows.
"""

import json
import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client
from utils.unified_context_verifier import verify_novelty
from utils.unified_context_ingester import ingest_context_unit
from workflows.workflow_factory import get_workflow
from core.source_content import SourceContent

logger = get_logger("perplexity_news_connector")


class PerplexityNewsConnector:
    """Connector for fetching news from Perplexity API."""
    
    def __init__(self, api_key: str):
        """
        Initialize Perplexity connector.
        
        Args:
            api_key: Perplexity API key
        """
        self.api_key = api_key
        self.api_url = "https://api.perplexity.ai/chat/completions"
        
        logger.info("perplexity_news_connector_initialized")
    
    async def fetch_news(
        self, 
        location: str = "Bilbao, Vizcaya o Bizkaia",
        news_count: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Fetch news from Perplexity API.
        
        Args:
            location: Geographic location for news
            news_count: Number of news items to fetch
            
        Returns:
            List of news items
        """
        try:
            logger.info("fetching_perplexity_news", location=location, count=news_count)
            
            # Prepare the prompt
            prompt = f"""{news_count} noticias de {location}. Para cada noticia, extrae:

1. CONTENIDO EXTENSO: 15-20 frases que capturen TODO el contenido semántico
2. DECLARACIONES: Si hay quotes de personas, identifícalas con formato: "PERSONA: declaración textual"
3. DATOS: Fechas, cifras, nombres completos
4. CONTEXTO: Antecedentes relevantes

Formato del texto:
- Una frase por línea
- Mantén orden cronológico del artículo original
- Incluye declaraciones literales con comillas y atribución
- Sin estructura de artículo, solo contenido semántico neutral

Responde SOLO este JSON:
{{"news": [{{"titulo": "...", "texto": "LINEA1\nLINEA2\nPERSONA: \"declaración\"\nLINEA3...", "fuente": "URL", "fecha": "YYYY-MM-DD"}}]}}

SIN markdown, {news_count} items exactos."""

            # Prepare the request payload
            payload = {
                "model": "sonar",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 8000
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Make the API call
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error("perplexity_api_error", 
                            status=response.status,
                            error=error_text,
                            headers=dict(response.headers)
                        )
                        return []
                    
                    response_data = await response.json()
                    logger.debug("perplexity_raw_response", response=response_data)
                    
            # Extract the content from response
            content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if not content:
                logger.error("empty_perplexity_response", response_data=response_data)
                return []
            
            # Parse JSON from content
            try:
                # Remove potential markdown formatting
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                # Clean invalid control characters that break JSON parsing
                import re
                content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)
                content = content.replace('\n', '\\n').replace('\r', '\\r')
                
                parsed_data = json.loads(content)
                news_items = parsed_data.get("news", [])
                
                logger.info("perplexity_news_fetched", 
                    count=len(news_items),
                    location=location
                )
                
                return news_items
                
            except json.JSONDecodeError as e:
                logger.error("perplexity_json_parse_error", 
                    error=str(e),
                    content_preview=content[:200]
                )
                return []
                
        except Exception as e:
            logger.error("perplexity_fetch_error", error=str(e), error_type=type(e).__name__)
            return []
    
    async def process_news_with_workflow(
        self,
        news_items: List[Dict[str, Any]],
        company: Dict[str, Any],
        organization: Dict[str, Any],
        source: Dict[str, Any],
        location: str
    ) -> List[Dict[str, Any]]:
        """
        Process news items through workflow.
        
        Args:
            news_items: List of news from Perplexity
            company: Company data
            organization: Organization data
            source: Source configuration
            
        Returns:
            List of processed context units
        """
        try:
            processed_units = []
            workflow_code = source.get("workflow_code", "default")
            
            logger.info("processing_news_with_workflow",
                news_count=len(news_items),
                workflow_code=workflow_code
            )
            
            # Get workflow
            workflow = get_workflow(workflow_code, company.get("settings", {}))
            
            for i, news_item in enumerate(news_items):
                try:
                    # Create SourceContent for each news item
                    source_content = SourceContent(
                        source_type="api_news",
                        source_id=f"perplexity_{datetime.now().strftime('%Y%m%d')}_{i+1}",
                        organization_slug=organization["slug"],
                        text_content=news_item.get("texto", ""),
                        metadata={
                            "title": news_item.get("titulo", ""),
                            "source_url": news_item.get("fuente", ""),
                            "fecha": news_item.get("fecha", ""),
                            "source": "perplexity_api",
                            "location": "Bilbao/Vizcaya",
                            "connector": "perplexity_news",
                            "workflow_code": workflow_code
                        },
                        title=news_item.get("titulo", f"Noticia {i+1}")
                    )
                    
                    # Process through workflow
                    result = await workflow.process_content(source_content)
                    
                    if result.get("success") or result.get("context_unit"):
                        context_unit = result.get("context_unit", {})
                        logger.debug("workflow_success", 
                            title=news_item.get("titulo", "")[:50],
                            context_unit_keys=list(context_unit.keys()) if context_unit else []
                        )
                        
                        processed_units.append(context_unit)
                        
                        logger.info("news_item_processed",
                            title=news_item.get("titulo", "")[:50],
                            context_unit_id=context_unit.get("id")
                        )
                        
                    else:
                        logger.error("news_item_processing_failed",
                            title=news_item.get("titulo", "")[:50],
                            error=result.get("error"),
                            workflow_result=result
                        )
                        # Use basic data if workflow failed
                        context_unit = {
                            "title": news_item.get("titulo", f"Noticia {i+1}"),
                            "summary": news_item.get("texto", "")[:200],
                            "atomic_statements": [],
                            "tags": [],
                            "raw_text": news_item.get("texto", "")
                        }
                    
                    # Phase 1: Verify novelty
                    verification_result = await verify_novelty(
                        source_type="perplexity",
                        content_data={
                            "title": news_item.get("titulo"),
                            "source_id": source["source_id"],
                            "date_published": news_item.get("fecha")
                        },
                        company_id=company["id"]
                    )

                    if not verification_result["is_novel"]:
                        logger.info("perplexity_news_duplicate_skipped",
                            title=news_item.get("titulo", "")[:50],
                            reason=verification_result["reason"],
                            duplicate_id=verification_result.get("duplicate_id")
                        )
                        continue

                    # Phase 2: Enrich content with unified enricher
                    from utils.unified_content_enricher import enrich_content
                    
                    enriched = await enrich_content(
                        raw_text=news_item.get("texto", ""),
                        source_type="perplexity",
                        company_id=company["id"],
                        pre_filled={
                            "title": news_item.get("titulo")
                        }
                    )
                    
                    # Phase 3: Ingest context unit with unified ingester
                    try:
                        ingest_result = await ingest_context_unit(
                            title=enriched["title"],
                            summary=enriched["summary"],
                            raw_text=news_item.get("texto"),
                            tags=enriched["tags"],
                            category=enriched["category"],
                            atomic_statements=enriched["atomic_statements"],

                            company_id=company["id"],
                            source_type="perplexity",
                            source_id=source["source_id"],

                            source_metadata={
                                "perplexity_query": location,
                                "perplexity_source": news_item.get("fuente"),
                                "perplexity_date": news_item.get("fecha"),
                                "perplexity_index": i + 1,
                                "enrichment_cost_usd": enriched["enrichment_cost_usd"],
                                "enrichment_model": enriched["enrichment_model"]
                            },

                            generate_embedding_flag=True,
                            check_duplicates=True
                        )

                        if ingest_result["success"]:
                            logger.info("perplexity_news_ingested",
                                title=news_item.get("titulo", "")[:50],
                                context_unit_id=ingest_result["context_unit_id"],
                                generated_fields=ingest_result.get("generated_fields", [])
                            )
                        elif ingest_result.get("duplicate"):
                            logger.info("perplexity_news_duplicate",
                                title=news_item.get("titulo", "")[:50],
                                duplicate_id=ingest_result.get("duplicate_id"),
                                similarity=ingest_result.get("similarity")
                            )
                        else:
                            logger.error("perplexity_news_ingest_failed",
                                title=news_item.get("titulo", "")[:50],
                                error=ingest_result.get("error")
                            )

                    except Exception as save_error:
                        logger.error("perplexity_news_ingest_error",
                            error=str(save_error),
                            title=news_item.get("titulo", "")
                        )
                        continue
                        
                except Exception as e:
                    logger.error("news_item_processing_error",
                        title=news_item.get("titulo", "")[:50],
                        error=str(e)
                    )
                    continue
            
            logger.info("news_processing_completed",
                total_items=len(news_items),
                successful_items=len(processed_units)
            )
            
            return processed_units
            
        except Exception as e:
            logger.error("news_workflow_processing_error", error=str(e))
            return []


async def execute_perplexity_news_task(source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute Perplexity news fetching task.
    
    Args:
        source: Source configuration from database
        
    Returns:
        Execution result
    """
    try:
        logger.info("executing_perplexity_news_task",
            source_id=source["source_id"],
            source_name=source["source_name"]
        )
        
        # Get configuration
        config = source.get("config", {})
        location = config.get("location", "Bilbao, Vizcaya o Bizkaia")
        news_count = config.get("news_count", 5)
        
        # Get API key from environment settings
        api_key = settings.perplexity_api_key
        if not api_key:
            logger.error("missing_perplexity_api_key_env", source_id=source["source_id"])
            return {
                "success": False,
                "error": "Missing PERPLEXITY_API_KEY environment variable"
            }
        
        # Get company and organization
        supabase = get_supabase_client()
        
        company = await supabase.get_company_by_id(source["company_id"])
        if not company:
            logger.error("company_not_found", company_id=source["company_id"])
            return {"success": False, "error": "Company not found"}
        
        # Get first active organization for this company
        org_result = supabase.client.table("organizations")\
            .select("*")\
            .eq("company_id", company["id"])\
            .eq("is_active", True)\
            .limit(1)\
            .execute()
        
        if not org_result.data:
            logger.error("organization_not_found", company_id=company["id"])
            return {"success": False, "error": "Organization not found"}
        
        organization = org_result.data[0]
        
        # Initialize connector and fetch news
        connector = PerplexityNewsConnector(api_key)
        news_items = await connector.fetch_news(location, news_count)
        
        if not news_items:
            logger.warn("no_news_fetched", source_id=source["source_id"])
            return {
                "success": True,
                "items_processed": 0,
                "message": "No news items fetched from Perplexity"
            }
        
        # Process news through workflow
        processed_units = await connector.process_news_with_workflow(
            news_items, company, organization, source, location
        )
        
        logger.info("perplexity_news_task_completed",
            source_id=source["source_id"],
            items_fetched=len(news_items),
            items_processed=len(processed_units)
        )
        
        return {
            "success": True,
            "items_fetched": len(news_items),
            "items_processed": len(processed_units),
            "processed_units": processed_units
        }
        
    except Exception as e:
        logger.error("perplexity_news_task_error", 
            source_id=source.get("source_id"),
            error=str(e)
        )
        return {
            "success": False,
            "error": str(e)
        }