"""Stateless processing endpoints (analyze, redact, micro-edit, styles)."""

from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_auth_context
from utils.helpers import (
    strip_markdown,
    markdown_to_html,
    generate_slug_from_title,
    extract_statements_from_context_units
)

logger = get_logger("api.process")
router = APIRouter(tags=["process"])


# ============================================
# PYDANTIC MODELS
# ============================================

class ProcessTextRequest(BaseModel):
    """Request model for stateless text processing."""
    text: str
    action: str
    params: Optional[Dict[str, Any]] = None


class ProcessURLRequest(BaseModel):
    """Request model for stateless URL processing."""
    url: str
    action: str
    params: Optional[Dict[str, Any]] = None


class GenerateStyleRequest(BaseModel):
    """Request model for style guide generation."""
    style_name: str
    urls: List[str]


class MicroEditRequest(BaseModel):
    """Request model for micro-editing."""
    text: str
    command: str
    context: Optional[str] = None
    params: Optional[Dict[str, Any]] = {}


class RedactNewsRichRequest(BaseModel):
    """Request model for rich news redaction from context units."""
    context_unit_ids: List[str]
    title: Optional[str] = None
    instructions: Optional[str] = None
    style_guide: Optional[str] = None
    style_id: Optional[str] = None  # Style ID to use (overrides default)
    language: str = "es"
    save_article: bool = False  # When True, performs all transformations and saves to DB


# ============================================
# PROCESSING ENDPOINTS
# ============================================

@router.post("/process/analyze")
async def process_analyze(
    request: ProcessTextRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Analyze text and extract: title, summary, tags with usage control.

    Requires: X-API-Key header

    Body:
        - text: Text to analyze (required)
        - action: Must be "analyze"
        - params: Optional parameters (not used)

    Returns:
        Analysis result with title, summary, tags
    """
    try:
        from utils.workflow_endpoints import execute_analyze

        result = await execute_analyze(
            client=auth,
            text=request.text,
            params=request.params
        )

        # Handle workflow result format
        if result.get("success", True):
            data = result.get("data", result)
            return {
                "status": "ok",
                "action": "analyze",
                "result": data,
                "text_length": len(request.text)
            }
        else:
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429,
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_analyze_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/analyze-atomic")
async def process_analyze_atomic(
    request: ProcessTextRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Analyze text and extract: title, summary, tags, atomic facts with usage control.

    Requires: X-API-Key header

    Body:
        - text: Text to analyze (required)
        - action: Must be "analyze_atomic"
        - params: Optional parameters (not used)

    Returns:
        Analysis result with title, summary, tags, atomic_facts
    """
    try:
        from utils.workflow_endpoints import execute_analyze_atomic

        result = await execute_analyze_atomic(
            client=auth,
            text=request.text,
            params=request.params
        )

        # Handle workflow result format
        if result.get("success", True):
            data = result.get("data", result)
            return {
                "status": "ok",
                "action": "analyze_atomic",
                "result": data,
                "text_length": len(request.text)
            }
        else:
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429,
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_analyze_atomic_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/redact-news")
async def process_redact_news(
    request: ProcessTextRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Generate news article from text/facts with specific style and usage control.

    Requires: X-API-Key header

    Body:
        - text: Source text or atomic facts (required)
        - action: Must be "redact_news"
        - params: Optional parameters
          - style_guide: Markdown style guide (string)
          - language: Target language (default: "es")

    Returns:
        Generated article with title, summary, tags
    """
    try:
        from utils.workflow_endpoints import execute_redact_news

        result = await execute_redact_news(
            client=auth,
            text=request.text,
            params=request.params
        )

        # Handle workflow result format
        if result.get("success", True):
            data = result.get("data", result)
            return {
                "status": "ok",
                "action": "redact_news",
                "result": data,
                "text_length": len(request.text)
            }
        else:
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429,
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_redact_news_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/url")
async def process_url(
    request: ProcessURLRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Scrape URL and process content (stateless, no storage).

    Requires: X-API-Key header

    Body:
        - url: URL to scrape (required)
        - action: Action to perform (analyze, analyze_atomic, redact_news)
        - params: Optional parameters for the action

    Returns:
        Processing result
    """
    try:
        from core_stateless import StatelessPipeline

        pipeline = StatelessPipeline(
            organization_id=auth.get('organization_id'),
            client_id=auth['client_id']
        )

        result = await pipeline.process_url(
            url=request.url,
            action=request.action,
            params=request.params
        )

        return {
            "status": "ok",
            "url": request.url,
            "action": request.action,
            "result": result
        }

    except Exception as e:
        logger.error("process_url_error", error=str(e), url=request.url)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/styles/generate")
async def generate_style_guide(
    request: GenerateStyleRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Generate writing style guide from example articles.

    Requires: X-API-Key header

    Body:
        - style_name: Name for this style (required)
        - urls: List of URLs to analyze (3-20 articles recommended)

    Returns:
        Style guide in Markdown format with examples

    Note: This endpoint may take 1-3 minutes depending on number of URLs.
    """
    try:
        from core_stateless import StatelessPipeline

        if len(request.urls) < 1:
            raise HTTPException(
                status_code=400,
                detail="At least 1 URL required for style analysis"
            )

        if len(request.urls) > 10:
            raise HTTPException(
                status_code=400,
                detail="Maximum 10 URLs allowed"
            )

        pipeline = StatelessPipeline(
            organization_id=auth.get('organization_id'),
            client_id=auth['client_id']
        )

        result = await pipeline.generate_style_guide(
            urls=request.urls,
            style_name=request.style_name
        )

        result["generated_at"] = datetime.utcnow().isoformat() + "Z"

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("generate_style_guide_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/redact-news-rich")
async def process_redact_news_rich(
    request: RedactNewsRichRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Generate rich news article from multiple context units with custom instructions.

    Requires: X-API-Key header

    Body:
        - context_unit_ids: List of context unit UUIDs (required)
        - title: Optional title suggestion (if empty, LLM generates it)
        - instructions: Optional writing instructions (if empty, ignored)
        - style_guide: Optional markdown style guide (string)
        - language: Target language (default: "es")
        - save_article: If True, transforms and saves article to DB (default: False)

    Returns:
        Generated article with title, summary, tags, and sources.
        If save_article=True, also returns saved article with id.
    """
    try:
        from utils.workflow_endpoints import execute_redact_news_rich
        import uuid as uuid_module

        result = await execute_redact_news_rich(
            client=auth,
            context_unit_ids=request.context_unit_ids,
            title=request.title,
            instructions=request.instructions,
            style_guide=request.style_guide,
            language=request.language
        )

        if not result.get("success", True):
            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429,
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

        data = result.get("data", result)

        # If save_article=True, perform transformations and save to DB
        if request.save_article:
            logger.info("save_article_enabled",
                client_id=auth["client_id"],
                context_unit_ids=request.context_unit_ids
            )

            supabase = get_supabase_client()
            company_id = auth["company_id"]

            # 1. Strip markdown from title and summary
            raw_title = data.get("title", "")
            raw_summary = data.get("summary", "")
            clean_title = strip_markdown(raw_title)
            clean_summary = strip_markdown(raw_summary)

            # 2. Convert article markdown to HTML
            raw_article = data.get("article", "")
            article_html = markdown_to_html(raw_article)

            # 3. Generate slug from clean title
            slug = generate_slug_from_title(clean_title)

            # 4. Fetch context units to extract statements
            context_units = []
            pool_company_id = "99999999-9999-9999-9999-999999999999"

            for cu_id in request.context_unit_ids:
                cu_result = supabase.client.table("press_context_units")\
                    .select("*")\
                    .eq("id", cu_id)\
                    .or_(f"company_id.eq.{company_id},company_id.eq.{pool_company_id}")\
                    .maybe_single()\
                    .execute()

                if cu_result and cu_result.data:
                    context_units.append(cu_result.data)

            # 5. Extract statements from context units
            statements = extract_statements_from_context_units(context_units)

            # 6. Determine imagen_uuid and build source_images list
            # Priority: AI-generated (null) → first context_unit with featured_image → null
            imagen_uuid = None
            source_images = []
            for cu in context_units:
                cu_id = cu["id"]
                image_count = cu.get("image_count") or 0

                # Build source_images list (e.g., "uuid_0", "uuid_1")
                for i in range(image_count):
                    source_images.append(f"{cu_id}_{i}")

                # Set imagen_uuid to first context unit with featured_image
                if imagen_uuid is None:
                    source_metadata = cu.get("source_metadata") or {}
                    featured_image = source_metadata.get("featured_image")
                    if featured_image and featured_image.get("url"):
                        imagen_uuid = cu_id

            # 7. Build working_json structure
            working_json = {
                "context_unit_ids": request.context_unit_ids,
                "statements": statements,
                "statements_used": data.get("statements_used", {}),
                "sources": data.get("sources", []),
                "source_images": source_images,
                "raw_title": raw_title,
                "raw_summary": raw_summary,
                "raw_article": raw_article,
                "image_prompt": data.get("image_prompt", ""),
                "tags": data.get("tags", []),
                "generated_at": datetime.utcnow().isoformat() + "Z"
            }

            # 8. Generate new article UUID
            article_id = str(uuid_module.uuid4())

            # 9. Prepare article data for save
            article_data = {
                "id": article_id,
                "company_id": company_id,
                "titulo": clean_title,
                "excerpt": clean_summary,
                "slug": slug,
                "contenido": article_html,
                "autor": data.get("author", "Redacción"),
                "tags": data.get("tags", []),
                "category": data.get("category"),
                "imagen_uuid": imagen_uuid,
                "context_unit_ids": request.context_unit_ids,
                "working_json": working_json,
                "estado": "borrador",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            # 10. Get style_id (from request or default)
            if request.style_id:
                article_data["style_id"] = request.style_id
            else:
                default_style = supabase.client.table("press_styles")\
                    .select("id")\
                    .eq("company_id", company_id)\
                    .eq("predeterminado", True)\
                    .maybe_single()\
                    .execute()

                if default_style.data:
                    article_data["style_id"] = default_style.data["id"]

            # 11. Save to database
            save_result = supabase.client.table("press_articles")\
                .insert(article_data)\
                .execute()

            if not save_result.data:
                raise HTTPException(status_code=500, detail="Failed to save article")

            saved_article = save_result.data[0]

            # 12. Generate embedding for article
            if clean_title and clean_summary:
                try:
                    from utils.embedding_generator import generate_article_embedding

                    embedding = await generate_article_embedding(saved_article)
                    embedding_generated_at = datetime.utcnow().isoformat()

                    supabase.client.table("press_articles")\
                        .update({
                            "embedding": embedding,
                            "embedding_generated_at": embedding_generated_at
                        })\
                        .eq("id", article_id)\
                        .execute()

                    saved_article["embedding_generated_at"] = embedding_generated_at
                    logger.info("article_embedding_generated",
                        article_id=article_id,
                        embedding_dimensions=len(embedding)
                    )
                except Exception as e:
                    logger.error("article_embedding_generation_failed",
                        article_id=article_id,
                        error=str(e)
                    )

            logger.info("article_saved_via_redact_news_rich",
                article_id=article_id,
                company_id=company_id,
                titulo=clean_title[:50],
                context_unit_ids_count=len(request.context_unit_ids)
            )

            # Return saved article with original generation data
            return {
                "status": "ok",
                "action": "redact_news_rich",
                "result": data,
                "saved_article": saved_article
            }

        # Normal flow (save_article=False)
        return {
            "status": "ok",
            "action": "redact_news_rich",
            "result": data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_redact_news_rich_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/micro-edit")
async def micro_edit(
    request: MicroEditRequest,
    auth: Dict = Depends(get_auth_context)
) -> Dict[str, Any]:
    """
    Perform micro-editing on text using LLM with usage control.

    Requires: X-API-Key header

    Args:
        request: Micro-edit request data
        client: Authenticated client

    Returns:
        Dict with original_text, edited_text, explanation, word_count_change
    """
    try:
        logger.info(
            "micro_edit_request",
            client_id=auth["client_id"],
            text_length=len(request.text),
            command=request.command[:100]
        )

        # Use workflow-enabled function
        from utils.workflow_endpoints import execute_micro_edit

        result = await execute_micro_edit(
            client=auth,
            text=request.text,
            command=request.command,
            context=request.context,
            params=request.params
        )

        # Handle workflow result format
        if result.get("success", True):
            data = result.get("data", result)
            logger.info(
                "micro_edit_completed",
                client_id=auth["client_id"],
                word_count_change=data.get("word_count_change", 0)
            )
            return {
                "success": True,
                "data": data
            }
        else:
            # Usage limit exceeded or other workflow error
            logger.warn(
                "micro_edit_workflow_failed",
                client_id=auth["client_id"],
                error=result.get("error"),
                details=result.get("details")
            )

            if result.get("error") == "usage_limit_exceeded":
                raise HTTPException(
                    status_code=429,
                    detail=f"Usage limit exceeded: {result.get('details', 'Daily or monthly limit reached')}"
                )
            else:
                raise HTTPException(status_code=500, detail=result.get("details", "Workflow execution failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("micro_edit_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
