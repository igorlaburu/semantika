"""Articles endpoints for Press module.

Handles article CRUD, publishing to platforms, and related articles.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any, List
import asyncio

from fastapi import APIRouter, HTTPException, Depends

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_company_id_from_auth, get_auth_context
from utils.helpers import generate_slug_from_title

# Initialize
logger = get_logger("api.articles")
router = APIRouter(tags=["articles"])


# ============================================
# ARTICLE ENDPOINTS
# ============================================

@router.get("/api/v1/articles")
async def list_articles(
    company_id: str = Depends(get_company_id_from_auth),
    status: str = "all",
    category: str = "all",
    limit: int = 20,
    offset: int = 0
) -> Dict:
    """
    Get paginated list of articles (borradores or publicados).

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)

    Filters by company_id from authentication.
    """
    try:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")
        supabase = get_supabase_client()

        # Build query
        query = supabase.client.table("press_articles")\
            .select("*", count="exact")\
            .eq("company_id", company_id)

        # Apply status filter (estado in Spanish)
        if status and status != "all":
            query = query.eq("estado", status)

        # Apply category filter
        if category and category != "all":
            query = query.eq("category", category)

        # Order and paginate
        query = query.order("created_at", desc=True)\
            .range(offset, offset + limit - 1)

        result = query.execute()
        total = result.count if hasattr(result, 'count') else 0
        items = result.data or []

        # Extract image_prompt and social_hooks from working_json for each article
        for article in items:
            if article.get("working_json") and isinstance(article["working_json"], dict):
                if "image_prompt" in article["working_json"]:
                    article["image_prompt"] = article["working_json"]["image_prompt"]
                if "social_hooks" in article["working_json"]:
                    article["social_hooks"] = article["working_json"]["social_hooks"]

        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total
        }

    except Exception as e:
        logger.error("list_articles_error", error=str(e), company_id=company_id)
        raise HTTPException(status_code=500, detail=f"Failed to fetch articles: {str(e)}")


@router.get("/api/v1/articles/by-slug/{slug}")
async def get_article_by_slug(
    slug: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Get article by slug.

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table("press_articles")\
            .select("*")\
            .eq("slug", slug)\
            .eq("company_id", company_id)\
            .maybe_single()\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Article not found")

        # Extract image_prompt and social_hooks from working_json if available
        article = result.data
        if article.get("working_json") and isinstance(article["working_json"], dict):
            if "image_prompt" in article["working_json"]:
                article["image_prompt"] = article["working_json"]["image_prompt"]
            if "social_hooks" in article["working_json"]:
                article["social_hooks"] = article["working_json"]["social_hooks"]

        return article

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_article_by_slug_error", error=str(e), slug=slug)
        raise HTTPException(status_code=500, detail="Failed to fetch article")


@router.post("/api/v1/articles")
async def create_article(
    article: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Create a new article.

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)

    **Body example**:
        {
            "titulo": "Mi artículo",
            "contenido": "Contenido del artículo...",
            "categoria": "política",
            "estado": "borrador",
            "context_unit_ids": ["uuid1", "uuid2"],
            "imagen_uuid": "uuid-de-imagen",
            "tags": ["tag1", "tag2"],
            "source_ids": ["source-uuid-1"],
            "working_json": {...}
        }
    """
    try:
        supabase = get_supabase_client()

        # Generate slug from title
        titulo = article.get("titulo", "Sin título")
        slug = generate_slug_from_title(titulo)

        # Prepare article data
        article_data = {
            "company_id": company_id,
            "titulo": titulo,
            "slug": slug,
            "contenido": article.get("contenido", ""),
            "category": article.get("categoria") or article.get("category"),
            "estado": article.get("estado", "borrador"),
            "context_unit_ids": article.get("context_unit_ids", []),
            "imagen_uuid": article.get("imagen_uuid"),
            "tags": article.get("tags", []),
            "source_ids": article.get("source_ids", []),
            "working_json": article.get("working_json"),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        # Generate embedding for the article (for related articles search)
        try:
            from utils.embedding_generator import generate_embedding_fastembed

            # Create text for embedding: title + first 500 chars of content
            embedding_text = f"{titulo}. {article_data['contenido'][:500]}"
            embedding = await generate_embedding_fastembed(embedding_text)

            # Convert to string format for pgvector
            article_data["embedding"] = f"[{','.join(map(str, embedding))}]"

            logger.info("article_embedding_generated",
                title=titulo[:50],
                embedding_dim=len(embedding)
            )
        except Exception as e:
            logger.warn("article_embedding_failed",
                title=titulo[:50],
                error=str(e)
            )
            # Continue without embedding - not critical

        result = supabase.client.table("press_articles")\
            .insert(article_data)\
            .execute()

        if not result.data or len(result.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create article")

        created_article = result.data[0]

        logger.info(
            "article_created",
            article_id=created_article["id"],
            company_id=company_id,
            title=titulo[:50],
            slug=slug
        )

        return created_article

    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_article_error", error=str(e), company_id=company_id)
        raise HTTPException(status_code=500, detail=f"Failed to create article: {str(e)}")


@router.get("/api/v1/articles/{article_id}")
async def get_article(
    article_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Get article by ID.

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table("press_articles")\
            .select("*")\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .maybe_single()\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Article not found")

        # Extract image_prompt and social_hooks from working_json if available
        article = result.data
        if article.get("working_json") and isinstance(article["working_json"], dict):
            if "image_prompt" in article["working_json"]:
                article["image_prompt"] = article["working_json"]["image_prompt"]
            if "social_hooks" in article["working_json"]:
                article["social_hooks"] = article["working_json"]["social_hooks"]

        return article

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_article_error", error=str(e), article_id=article_id)
        raise HTTPException(status_code=500, detail="Failed to fetch article")


@router.get("/api/v1/articles/{article_id}/related")
async def get_related_articles(
    article_id: str,
    company_id: str = Depends(get_company_id_from_auth),
    limit: int = 3
) -> Dict:
    """
    Get related articles using semantic similarity.

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)

    Returns up to `limit` articles similar to the given article,
    using pgvector cosine similarity on embeddings.
    """
    try:
        supabase = get_supabase_client()

        # Get the current article's embedding
        article_result = supabase.client.table("press_articles")\
            .select("embedding, titulo")\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .maybe_single()\
            .execute()

        if not article_result.data:
            raise HTTPException(status_code=404, detail="Article not found")

        if not article_result.data.get("embedding"):
            logger.info("no_embedding_for_related_articles",
                article_id=article_id,
                title=article_result.data.get("titulo", "")[:50]
            )
            return {"items": [], "count": 0}

        # Use the RPC function for similarity search
        similar_result = supabase.client.rpc(
            'find_similar_articles',
            {
                'target_embedding': article_result.data["embedding"],
                'target_company_id': company_id,
                'target_article_id': article_id,
                'similarity_threshold': 0.5,
                'max_results': limit
            }
        ).execute()

        items = similar_result.data or []

        logger.info("related_articles_found",
            article_id=article_id,
            count=len(items)
        )

        return {
            "items": items,
            "count": len(items)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_related_articles_error",
            error=str(e),
            article_id=article_id,
            company_id=company_id
        )
        raise HTTPException(status_code=500, detail="Failed to fetch related articles")


@router.patch("/api/v1/articles/{article_id}")
async def update_article(
    article_id: str,
    updates: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Update article fields (partial update).

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)

    **Body**: JSON object with fields to update, e.g.:
        {
            "estado": "publicado",
            "fecha_publicacion": "2025-11-23T10:00:00Z",
            "imagen_uuid": "a1b2c3d4-5678-90ab-cdef-1234567890ab"
        }

    **Note**: Use imagen_uuid (not imagen_url) for images. Frontend will construct URL.
    """
    try:
        supabase = get_supabase_client()

        # Clean None/undefined values
        clean_data = {k: v for k, v in updates.items() if v is not None}

        if not clean_data:
            raise HTTPException(status_code=400, detail="No valid fields")

        clean_data["updated_at"] = datetime.utcnow().isoformat()

        # Update only the provided fields
        result = supabase.client.table("press_articles")\
            .update(clean_data)\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .execute()

        if not result.data or len(result.data) == 0:
            raise HTTPException(status_code=404, detail="Article not found")

        logger.info(
            "article_updated",
            article_id=article_id,
            company_id=company_id,
            fields=list(clean_data.keys())
        )

        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_article_error", error=str(e), article_id=article_id)
        raise HTTPException(status_code=500, detail="Failed to update article")


@router.delete("/api/v1/articles/{article_id}")
async def delete_article(
    article_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Delete an article.

    **Authentication**: Accepts either JWT (Authorization: Bearer) or API Key (X-API-Key)

    **Note**: This is a hard delete. The article cannot be recovered.
    """
    try:
        supabase = get_supabase_client()

        # First verify the article exists and belongs to this company
        check_result = supabase.client.table("press_articles")\
            .select("id, titulo")\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .execute()

        if not check_result.data or len(check_result.data) == 0:
            raise HTTPException(status_code=404, detail="Article not found")

        article_title = check_result.data[0].get("titulo", "Unknown")

        # Delete the article
        result = supabase.client.table("press_articles")\
            .delete()\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .execute()

        logger.info(
            "article_deleted",
            article_id=article_id,
            company_id=company_id,
            title=article_title[:50]
        )

        return {
            "success": True,
            "message": f"Article '{article_title}' deleted successfully",
            "article_id": article_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_article_error", error=str(e), article_id=article_id)
        raise HTTPException(status_code=500, detail="Failed to delete article")


# ============================================
# PUBLICATION HELPERS
# ============================================

async def publish_to_platforms(
    article: Dict[str, Any],
    company_id: str,
    target_ids: list,
    publish_as_draft: bool = False
) -> Dict[str, Any]:
    """Publish article to specified platforms or default platforms.

    If publish_as_draft=True:
    - WordPress targets publish with status="draft" instead of "publish"
    - Social media targets (Twitter, LinkedIn, etc.) are SKIPPED entirely
      (cannot post to RRSS without a published URL)
    """
    from publishers.publisher_factory import PublisherFactory

    publication_results = {}
    supabase = get_supabase_client()

    try:
        # Get publication targets
        if target_ids:
            # Use specified targets
            targets_query = supabase.client.table("press_publication_targets")\
                .select("*")\
                .eq("company_id", company_id)\
                .eq("is_active", True)\
                .in_("id", target_ids)

            targets_result = targets_query.execute()
            targets = targets_result.data or []
        else:
            # First try default targets for each platform
            targets_query = supabase.client.table("press_publication_targets")\
                .select("*")\
                .eq("company_id", company_id)\
                .eq("is_active", True)\
                .eq("is_default", True)

            targets_result = targets_query.execute()
            targets = targets_result.data or []

            # If no default targets found, use the first available target
            if not targets:
                logger.info("no_default_targets_found_using_first_available",
                    company_id=company_id
                )

                targets_query = supabase.client.table("press_publication_targets")\
                    .select("*")\
                    .eq("company_id", company_id)\
                    .eq("is_active", True)\
                    .order("created_at")\
                    .limit(1)

                targets_result = targets_query.execute()
                targets = targets_result.data or []

        if not targets:
            logger.warn("no_publication_targets_found",
                company_id=company_id,
                specified_targets=target_ids
            )
            return {}

        # Update article with auto-assigned targets if needed
        if not target_ids:  # Only if no targets were specified (auto-assignment case)
            assigned_target_ids = [t['id'] for t in targets]
            try:
                supabase.client.table("press_articles")\
                    .update({"publication_targets": assigned_target_ids})\
                    .eq("id", article['id'])\
                    .eq("company_id", company_id)\
                    .execute()

                logger.info("publication_targets_auto_assigned",
                    article_id=article['id'],
                    target_ids=assigned_target_ids,
                    target_names=[t['name'] for t in targets]
                )
            except Exception as e:
                logger.warn("failed_to_update_article_targets",
                    article_id=article['id'],
                    error=str(e)
                )

        # Prepare article data for publication
        title = article.get('titulo', 'Untitled')
        content = article.get('contenido', '')
        excerpt = article.get('excerpt', '')
        tags = article.get('tags', [])
        category = article.get('category', None)

        # Use article slug (required field in press_articles)
        slug = article.get('slug')
        if not slug:
            logger.warn("article_missing_slug_field",
                article_id=article.get('id'),
                title=title[:50]
            )
            # Fallback to generated slug if missing
            slug = generate_slug_from_title(title)

        # Get image UUID for unified image endpoint
        imagen_uuid = article.get('imagen_uuid')
        temp_image_path = None

        # Transform image for publication if present
        if imagen_uuid:
            try:
                from utils.image_transformer import ImageTransformer
                from pathlib import Path
                import os

                # Read image from cache using same logic as GET /api/v1/images/{image_id}
                # The imagen_uuid from frontend already includes _0 suffix when needed
                cache_dir = Path("/app/cache/images")
                extensions = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]
                original_image_data = None

                for ext in extensions:
                    cache_file = cache_dir / f"{imagen_uuid}{ext}"
                    if cache_file.exists():
                        original_image_data = cache_file.read_bytes()
                        logger.debug("publication_image_cache_hit",
                            imagen_uuid=imagen_uuid,
                            extension=ext,
                            cache_file=str(cache_file)
                        )
                        break

                if original_image_data:
                    # Transform image to temporary file with brand consistency and uniqueness
                    temp_image_path = ImageTransformer.transform_for_publication(
                        image_data=original_image_data,
                        platform="wordpress",  # TODO: Make dynamic per platform
                        image_uuid=imagen_uuid
                    )

                    if temp_image_path:
                        temp_size_kb = round(os.path.getsize(temp_image_path) / 1024, 2)
                        logger.info("publication_image_transformed",
                            article_id=article.get('id'),
                            imagen_uuid=imagen_uuid,
                            temp_image_path=temp_image_path,
                            transformed_size_kb=temp_size_kb
                        )
                    else:
                        logger.error("publication_image_transformation_returned_none",
                            article_id=article.get('id'),
                            imagen_uuid=imagen_uuid
                        )
                else:
                    logger.warn("publication_image_not_found_in_cache",
                        article_id=article.get('id'),
                        imagen_uuid=imagen_uuid
                    )
            except Exception as e:
                logger.error("publication_image_transformation_failed",
                    article_id=article.get('id'),
                    imagen_uuid=imagen_uuid,
                    error=str(e)
                )
                # Continue without transformed image (fallback to UUID method)

        # Add references and image attribution footer
        content = await _add_article_footer(content, article.get('id'), company_id)

        # Separate targets: WordPress (destinations) vs Social Media (RRSS)
        SOCIAL_PLATFORMS = ('twitter', 'linkedin', 'facebook', 'instagram')
        wordpress_targets = [t for t in targets if t['platform_type'] == 'wordpress']
        social_targets = [t for t in targets if t['platform_type'] in SOCIAL_PLATFORMS]

        logger.info("publication_targets_separated",
            article_id=article['id'],
            wordpress_count=len(wordpress_targets),
            social_count=len(social_targets),
            wordpress_names=[t['name'] for t in wordpress_targets],
            social_names=[t['name'] for t in social_targets],
            publish_as_draft=publish_as_draft
        )

        # If publishing as draft, skip social media entirely (no URL to share)
        if publish_as_draft:
            if social_targets:
                logger.info("skipping_social_targets_draft_mode",
                    article_id=article['id'],
                    skipped_targets=[t['name'] for t in social_targets]
                )
            social_targets = []

        # Step 1: Publish to WordPress first (to get URL for social media)
        wordpress_url = None

        for target in wordpress_targets:
            target_id = target['id']

            try:
                publisher = PublisherFactory.create_publisher(
                    target['platform_type'],
                    target['base_url'],
                    target['credentials_encrypted']
                )

                publish_kwargs = {
                    "title": title,
                    "content": content,
                    "excerpt": excerpt,
                    "tags": tags,
                    "category": category,
                    "status": "draft" if publish_as_draft else "publish",
                    "slug": slug,
                    "fecha_publicacion": article.get('fecha_publicacion')
                }

                if temp_image_path:
                    publish_kwargs["temp_image_path"] = temp_image_path
                else:
                    publish_kwargs["imagen_uuid"] = imagen_uuid

                result = await publisher.publish_article(**publish_kwargs)

                publication_results[target_id] = {
                    "success": result.success,
                    "platform": target['platform_type'],
                    "target_name": target['name'],
                    "url": result.url,
                    "external_id": result.external_id,
                    "published_at": result.published_at,
                    "error": result.error,
                    "metadata": result.metadata
                }

                # Capture WordPress URL for social media
                if result.success and result.url and not wordpress_url:
                    wordpress_url = result.url

                logger.info("article_published_to_platform",
                    article_id=article['id'],
                    target_id=target_id,
                    platform=target['platform_type'],
                    success=result.success,
                    url=result.url
                )

            except Exception as e:
                publication_results[target_id] = {
                    "success": False,
                    "platform": target['platform_type'],
                    "target_name": target['name'],
                    "error": f"Publication error: {str(e)}"
                }

                logger.error("platform_publication_failed",
                    article_id=article['id'],
                    target_id=target_id,
                    platform=target['platform_type'],
                    error=str(e)
                )

        # Step 2: Publish to Social Media with WordPress URL
        if social_targets:
            # Brief delay to ensure WordPress has finished processing
            if wordpress_url:
                logger.info("brief_delay_before_social",
                    article_id=article['id'],
                    delay_seconds=2
                )
                await asyncio.sleep(2)

            # Get social_hooks from working_json (platform-specific hooks)
            working_json = article.get('working_json') or {}
            social_hooks = working_json.get('social_hooks') or {}

            # Mapping: platform -> hook type
            PLATFORM_HOOK_MAP = {
                'twitter': 'direct',
                'linkedin': 'professional',
                'facebook': 'emotional',
                'instagram': 'emotional'  # Same as Facebook
            }

            # Fallback hook (truncated title)
            fallback_hook = title[:147] + "..." if len(title) > 150 else title

            # Get URL: published article URL or fallback
            # Priority: wordpress_url (if valid) > published_url (if valid) > base_url
            social_url = None

            # Try wordpress_url from current publication
            if _is_valid_public_url(wordpress_url):
                social_url = wordpress_url
            elif wordpress_url:
                logger.info("social_skipping_draft_url",
                    article_id=article['id'],
                    draft_url=wordpress_url
                )

            # Try previous published_url if no valid URL yet
            if not social_url and article.get('published_url'):
                if _is_valid_public_url(article['published_url']):
                    social_url = article['published_url']
                    logger.info("social_using_previous_published_url",
                        article_id=article['id'],
                        published_url=social_url
                    )

            # Fallback to WordPress target's base_url
            if not social_url and wordpress_targets:
                social_url = wordpress_targets[0].get('base_url', '')
                logger.info("social_using_fallback_base_url",
                    article_id=article['id'],
                    fallback_url=social_url
                )

            if not social_url:
                try:
                    default_wp = supabase.client.table("press_publication_targets")\
                        .select("base_url")\
                        .eq("company_id", company_id)\
                        .eq("platform_type", "wordpress")\
                        .eq("is_active", True)\
                        .eq("is_default", True)\
                        .limit(1)\
                        .execute()
                    if default_wp.data:
                        social_url = default_wp.data[0].get('base_url', '')
                        logger.info("social_using_default_wordpress_url",
                            article_id=article['id'],
                            default_url=social_url
                        )
                except Exception as e:
                    logger.warn("social_failed_to_get_default_wordpress",
                        article_id=article['id'],
                        error=str(e)
                    )

            for target in social_targets:
                target_id = target['id']
                platform = target['platform_type']

                try:
                    # Get platform-specific hook
                    hook_type = PLATFORM_HOOK_MAP.get(platform, 'direct')
                    hook_text = social_hooks.get(hook_type) or fallback_hook

                    # Ensure hook is within limits (150 chars max)
                    if len(hook_text) > 150:
                        hook_text = hook_text[:147] + "..."

                    # Build social content: hook + URL (no hashtags)
                    social_content = f"{hook_text}\n\n{social_url}" if social_url else hook_text

                    logger.info("social_content_prepared",
                        article_id=article['id'],
                        platform=platform,
                        hook_type=hook_type,
                        content_length=len(social_content),
                        hook_preview=hook_text[:50]
                    )

                    publisher = PublisherFactory.create_publisher(
                        platform,
                        target.get('base_url', ''),
                        target['credentials_encrypted']
                    )

                    # Social media publish - different method than WordPress
                    result = await publisher.publish_social(
                        content=social_content,
                        url=social_url,
                        image_uuid=imagen_uuid,
                        tags=[],  # No hashtags
                        temp_image_path=temp_image_path
                    )

                    publication_results[target_id] = {
                        "success": result.success,
                        "platform": platform,
                        "target_name": target['name'],
                        "url": result.url,
                        "external_id": result.external_id,
                        "published_at": result.published_at,
                        "error": result.error,
                        "metadata": result.metadata
                    }

                    logger.info("article_published_to_social",
                        article_id=article['id'],
                        target_id=target_id,
                        platform=platform,
                        hook_type=hook_type,
                        success=result.success,
                        url=result.url
                    )

                except Exception as e:
                    publication_results[target_id] = {
                        "success": False,
                        "platform": platform,
                        "target_name": target['name'],
                        "error": f"Social publication error: {str(e)}"
                    }

                    logger.error("social_platform_publication_failed",
                        article_id=article['id'],
                        target_id=target_id,
                        platform=platform,
                        error=str(e)
                    )

        # Clean up temp image file if it was created
        if temp_image_path:
            try:
                import os
                if os.path.exists(temp_image_path):
                    os.remove(temp_image_path)
                    logger.debug("temp_image_cleaned_up",
                        article_id=article['id'],
                        temp_image_path=temp_image_path
                    )
            except Exception as e:
                logger.warn("failed_to_cleanup_temp_image",
                    article_id=article['id'],
                    temp_image_path=temp_image_path,
                    error=str(e)
                )

    except Exception as e:
        logger.error("publish_to_platforms_error",
            article_id=article.get('id'),
            error=str(e)
        )
        # Return empty dict on error rather than failing the whole publication

    return publication_results


def _is_valid_public_url(url: str) -> bool:
    """Check if URL is valid for public sharing (not a draft URL).

    Draft URLs from WordPress look like: https://example.com/?p=1194
    We want to detect these and use fallback instead.
    """
    if not url:
        return False

    # Draft URLs contain ?p= parameter
    if '?p=' in url:
        return False

    # Must be a proper HTTP URL
    if not url.startswith(('http://', 'https://')):
        return False

    return True


async def _add_article_footer(content: str, article_id: str, company_id: str) -> str:
    """Add references and image attribution footer to article content."""
    from urllib.parse import urlparse

    try:
        supabase = get_supabase_client()
        footer_parts = []

        # Get context units used in this article
        # Get article data to find context_unit_ids
        article_data = supabase.client.table("press_articles")\
            .select("context_unit_ids")\
            .eq("id", article_id)\
            .maybe_single()\
            .execute()

        context_units_result = {"data": []}

        if article_data.data and article_data.data.get("context_unit_ids"):
            # Use context units linked to this article
            context_unit_ids = article_data.data["context_unit_ids"]
            if context_unit_ids:
                context_units_result = supabase.client.table("press_context_units")\
                    .select("source_metadata, id")\
                    .in_("id", context_unit_ids)\
                    .execute()

        # If no context units found, use fallback to recent units from same company (no time limit)
        if not context_units_result.data or len(context_units_result.data) == 0:
            context_units_result = supabase.client.table("press_context_units")\
                .select("source_metadata, id")\
                .eq("company_id", company_id)\
                .is_not("source_metadata->url", "null")\
                .order("created_at", desc=True)\
                .limit(10)\
                .execute()

        context_units = context_units_result.data or []

        # Collect unique references (URLs)
        references = set()

        for unit in context_units:
            metadata = unit.get("source_metadata") or {}
            url = metadata.get("url")

            if url and url.startswith("http"):
                try:
                    parsed = urlparse(url)
                    domain = parsed.netloc
                    references.add((domain, url))
                except:
                    continue

        # Get article image info for attribution
        article_result = supabase.client.table("press_articles")\
            .select("imagen_uuid, working_json")\
            .eq("id", article_id)\
            .maybe_single()\
            .execute()

        image_attribution = None
        if article_result.data and article_result.data.get("imagen_uuid"):
            imagen_uuid = article_result.data["imagen_uuid"]

            # Check if it's a featured image from a source (has _0, _1, etc suffix)
            if '_' in imagen_uuid and imagen_uuid.split('_')[-1].isdigit():
                # Featured image from source - use first reference domain
                if references:
                    first_domain, first_url = next(iter(references))
                    image_attribution = first_domain
            else:
                # Check if it's AI generated
                working_json = article_result.data.get("working_json") or {}
                generated_images = working_json.get("article", {}).get("generated_images", [])
                ai_image_uuids = [img.get("uuid") for img in generated_images if img.get("uuid")]

                if imagen_uuid in ai_image_uuids:
                    image_attribution = "Generada con IA"
                # If neither featured nor AI -> manual upload, no attribution needed

        # Build footer - ORDER: Related Articles -> References -> Image

        # Add related articles section (FIRST)
        try:
            # Get the current article's embedding
            current_article = supabase.client.table("press_articles")\
                .select("embedding")\
                .eq("id", article_id)\
                .eq("company_id", company_id)\
                .maybe_single()\
                .execute()

            if current_article.data and current_article.data.get("embedding"):
                # Get related articles using similarity search
                similar_result = supabase.client.rpc(
                    'find_similar_articles',
                    {
                        'target_embedding': current_article.data["embedding"],
                        'target_company_id': company_id,
                        'target_article_id': article_id,
                        'similarity_threshold': 0.5,
                        'max_results': 3
                    }
                ).execute()

                if similar_result.data and len(similar_result.data) > 0:
                    footer_parts.append("<strong>Artículos relacionados:</strong>")
                    for related_article in similar_result.data:
                        published_url = related_article.get("published_url")
                        title = related_article.get("titulo", "Artículo relacionado")

                        # Only include if we have a published URL
                        if published_url and published_url.startswith("http"):
                            footer_parts.append(f'<a href="{published_url}">{title}</a>')

                    logger.info("related_articles_added_to_footer",
                        article_id=article_id,
                        related_count=len(similar_result.data)
                    )
                else:
                    logger.info("no_related_articles_found_for_footer",
                        article_id=article_id,
                        threshold=0.5
                    )
            else:
                logger.info("no_embedding_available_for_related_articles",
                    article_id=article_id
                )

        except Exception as e:
            logger.error("failed_to_add_related_articles_to_footer",
                article_id=article_id,
                error=str(e)
            )
            # Don't fail footer generation if related articles fail

        # Add references (SECOND)
        if references:
            footer_parts.append("<strong>Referencias:</strong>")
            for domain, url in sorted(references):
                footer_parts.append(f'<a href="{url}">{domain}</a>')

        # Add image attribution (THIRD, only if we have attribution info)
        if image_attribution:
            footer_parts.append("<strong>Imagen:</strong>")
            footer_parts.append(image_attribution)

        if footer_parts:
            footer_html = "<br>".join(footer_parts) + "<br>"
            content = f"{content}<br><br>{footer_html}"

            logger.info("article_footer_added",
                article_id=article_id,
                references_count=len(references),
                image_attribution=image_attribution
            )

        return content

    except Exception as e:
        logger.error("add_article_footer_error",
            article_id=article_id,
            error=str(e)
        )
        # Return original content if footer generation fails
        return content


@router.post("/api/v1/articles/{article_id}/publish")
async def publish_article(
    article_id: str,
    request: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Publish an article to multiple platforms.

    Supports two modes:

    **NEW FORMAT (target_schedules):**
        {
            "target_schedules": [
                {"target_id": "uuid", "schedule_time": null},        // null = immediate
                {"target_id": "uuid", "schedule_time": "ISO-8601"}   // scheduled
            ],
            "social_hooks": {                                        // optional, override hooks
                "direct": "Hook for Twitter",
                "professional": "Hook for LinkedIn",
                "emotional": "Hook for Facebook"
            },
            "publish_as_draft": false
        }

    **LEGACY FORMAT (backwards compatible):**
        {
            "publish_now": false,
            "preserve_original_date": false,
            "schedule_time": null,
            "targets": ["uuid1", "uuid2"],
            "publish_as_draft": false
        }

    **Authentication**: Accepts either JWT or API Key

    **Returns**:
        {
            "success": true,
            "article_id": "xxx",
            "status": "scheduled" | "published" | "mixed",
            "publications": [
                {"target_id": "uuid", "platform_type": "wordpress", "status": "published", "url": "..."},
                {"target_id": "uuid", "platform_type": "twitter", "status": "scheduled", "scheduled_for": "..."}
            ]
        }
    """
    try:
        supabase = get_supabase_client()

        # Get article to verify it exists and belongs to company
        article_result = supabase.client.table("press_articles")\
            .select("*")\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .single()\
            .execute()

        if not article_result.data:
            raise HTTPException(status_code=404, detail="Article not found")

        article = article_result.data

        # Check if using NEW FORMAT (target_schedules) or LEGACY FORMAT
        target_schedules = request.get('target_schedules')

        if target_schedules is not None:
            # ==========================================
            # NEW FORMAT: target_schedules
            # ==========================================
            return await _publish_with_target_schedules(
                article_id=article_id,
                article=article,
                company_id=company_id,
                target_schedules=target_schedules,
                social_hooks=request.get('social_hooks'),
                publish_as_draft=request.get('publish_as_draft', False),
                supabase=supabase
            )
        else:
            # ==========================================
            # LEGACY FORMAT: publish_now, targets, etc.
            # ==========================================
            return await _publish_legacy_format(
                article_id=article_id,
                article=article,
                company_id=company_id,
                request=request,
                supabase=supabase
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("publish_article_error",
            error=str(e),
            article_id=article_id
        )
        raise HTTPException(status_code=500, detail="Failed to publish article")


async def _publish_with_target_schedules(
    article_id: str,
    article: Dict,
    company_id: str,
    target_schedules: List[Dict],
    social_hooks: Optional[Dict],
    publish_as_draft: bool,
    supabase
) -> Dict:
    """Handle publication with new target_schedules format."""

    # Log incoming target_schedules for debugging
    logger.info("publish_target_schedules_received",
        article_id=article_id,
        target_schedules_count=len(target_schedules),
        target_schedules_raw=[
            {"target_id": ts.get('target_id'), "schedule_time": ts.get('schedule_time')}
            for ts in target_schedules
        ]
    )

    # Check article state - allow republishing to additional targets
    if article['estado'] not in ['borrador', 'programado', 'publicado']:
        raise HTTPException(
            status_code=400,
            detail=f"Article cannot be published. Current state: {article['estado']}"
        )

    # Get target details
    target_ids = [ts['target_id'] for ts in target_schedules]
    targets_result = supabase.client.table("press_publication_targets")\
        .select("id, platform_type, name, base_url, credentials_encrypted")\
        .eq("company_id", company_id)\
        .eq("is_active", True)\
        .in_("id", target_ids)\
        .execute()

    targets_by_id = {t['id']: t for t in (targets_result.data or [])}

    # Update social_hooks in working_json if provided
    if social_hooks:
        working_json = article.get('working_json') or {}
        working_json['social_hooks'] = social_hooks
        supabase.client.table("press_articles")\
            .update({"working_json": working_json, "updated_at": datetime.utcnow().isoformat()})\
            .eq("id", article_id)\
            .execute()
        article['working_json'] = working_json

    # Mapping: platform -> hook type
    PLATFORM_HOOK_MAP = {
        'twitter': 'direct',
        'linkedin': 'professional',
        'facebook': 'emotional',
        'instagram': 'emotional'
    }

    # Get hooks from working_json or request
    hooks = social_hooks or (article.get('working_json') or {}).get('social_hooks') or {}
    fallback_hook = article.get('titulo', '')[:147] + "..." if len(article.get('titulo', '')) > 150 else article.get('titulo', '')

    # Separate immediate vs scheduled
    immediate_targets = []
    scheduled_targets = []

    for ts in target_schedules:
        target_id = ts['target_id']
        schedule_time = ts.get('schedule_time')

        if target_id not in targets_by_id:
            logger.warn("target_not_found", target_id=target_id)
            continue

        target = targets_by_id[target_id]

        if schedule_time is None:
            # Immediate publication
            immediate_targets.append(target)
        else:
            # Scheduled publication
            try:
                scheduled_dt = datetime.fromisoformat(schedule_time.replace('Z', '+00:00'))
                if scheduled_dt <= datetime.now(timezone.utc):
                    # Time in past, publish immediately instead
                    immediate_targets.append(target)
                else:
                    scheduled_targets.append({
                        'target': target,
                        'schedule_time': scheduled_dt
                    })
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid schedule_time format for target {target_id}")

    publications = []
    publication_results = {}

    # Handle immediate publications
    if immediate_targets:
        if publish_as_draft:
            # Only publish WordPress targets as draft, skip social
            wp_targets = [t for t in immediate_targets if t['platform_type'] == 'wordpress']
            immediate_targets = wp_targets

        if immediate_targets:
            # Use existing publish_to_platforms for immediate
            immediate_target_ids = [t['id'] for t in immediate_targets]
            publication_results = await publish_to_platforms(
                article,
                company_id,
                immediate_target_ids,
                publish_as_draft=publish_as_draft
            )

            for target_id, result in publication_results.items():
                target = targets_by_id.get(target_id, {})
                pub_status = "published" if result.get('success') else "failed"

                # Get hook for this platform (for logging purposes)
                hook_type = PLATFORM_HOOK_MAP.get(target.get('platform_type'), 'direct')
                hook_text = hooks.get(hook_type) or fallback_hook if target.get('platform_type') != 'wordpress' else None

                # Log immediate publication to scheduled_publications table
                try:
                    supabase.client.table("scheduled_publications")\
                        .upsert({
                            "article_id": article_id,
                            "target_id": target_id,
                            "company_id": company_id,
                            "platform_type": target.get('platform_type'),
                            "scheduled_for": None,  # Immediate = no scheduled time
                            "status": pub_status,
                            "published_at": datetime.now(timezone.utc).isoformat(),
                            "social_hook": hook_text,
                            "publication_result": result,
                            "error_message": result.get('error') if not result.get('success') else None,
                            "created_at": datetime.utcnow().isoformat()
                        }, on_conflict="article_id,target_id")\
                        .execute()
                except Exception as log_err:
                    logger.warn("immediate_publication_log_failed",
                        article_id=article_id, target_id=target_id, error=str(log_err))

                publications.append({
                    "target_id": target_id,
                    "platform_type": target.get('platform_type'),
                    "target_name": target.get('name'),
                    "status": pub_status,
                    "url": result.get('url'),
                    "error": result.get('error')
                })

    # Handle scheduled publications
    for scheduled in scheduled_targets:
        target = scheduled['target']
        schedule_time = scheduled['schedule_time']

        # Get hook for this platform
        hook_type = PLATFORM_HOOK_MAP.get(target['platform_type'], 'direct')
        hook_text = hooks.get(hook_type) or fallback_hook

        # Create scheduled_publication record
        try:
            insert_result = supabase.client.table("scheduled_publications")\
                .upsert({
                    "article_id": article_id,
                    "target_id": target['id'],
                    "company_id": company_id,
                    "platform_type": target['platform_type'],
                    "scheduled_for": schedule_time.isoformat(),
                    "status": "scheduled",
                    "social_hook": hook_text if target['platform_type'] != 'wordpress' else None,
                    "created_at": datetime.utcnow().isoformat()
                }, on_conflict="article_id,target_id")\
                .execute()

            publications.append({
                "target_id": target['id'],
                "platform_type": target['platform_type'],
                "target_name": target['name'],
                "status": "scheduled",
                "scheduled_for": schedule_time.isoformat() + "Z"
            })

            logger.info("publication_scheduled",
                article_id=article_id,
                target_id=target['id'],
                platform=target['platform_type'],
                scheduled_for=schedule_time.isoformat()
            )
        except Exception as e:
            logger.error("schedule_publication_failed",
                article_id=article_id,
                target_id=target['id'],
                error=str(e)
            )
            publications.append({
                "target_id": target['id'],
                "platform_type": target['platform_type'],
                "target_name": target['name'],
                "status": "failed",
                "error": str(e)
            })

    # Update article state based on results
    has_published = any(p['status'] == 'published' for p in publications)
    has_scheduled = any(p['status'] == 'scheduled' for p in publications)

    if has_published and has_scheduled:
        new_status = "mixed"
        article_estado = "programado"  # Keep as programado if there are pending schedules
    elif has_published:
        new_status = "published"
        article_estado = "publicado"
    elif has_scheduled:
        new_status = "scheduled"
        article_estado = "programado"
    else:
        new_status = "failed"
        article_estado = article['estado']  # Keep current state

    # Update article
    update_data = {
        "estado": article_estado,
        "updated_at": datetime.utcnow().isoformat()
    }

    # Update publication_status with immediate results
    if publication_results:
        existing_status = article.get('publication_status') or {}
        for target_id, result in publication_results.items():
            existing_status[target_id] = {
                **result,
                "published_at": datetime.utcnow().isoformat()
            }
        update_data["publication_status"] = existing_status

        # Update published_url if WordPress succeeded
        for target_id, result in publication_results.items():
            if result.get("success") and result.get("platform") == "wordpress" and result.get("url"):
                update_data["published_url"] = result["url"]
                update_data["fecha_publicacion"] = datetime.utcnow().isoformat()
                break

    supabase.client.table("press_articles")\
        .update(update_data)\
        .eq("id", article_id)\
        .execute()

    logger.info("publish_with_schedules_completed",
        article_id=article_id,
        immediate_count=len(immediate_targets),
        scheduled_count=len(scheduled_targets),
        status=new_status
    )

    return {
        "success": True,
        "article_id": article_id,
        "status": new_status,
        "publications": publications,
        "message": f"Article processed: {len([p for p in publications if p['status'] == 'published'])} published, {len([p for p in publications if p['status'] == 'scheduled'])} scheduled"
    }


async def _publish_legacy_format(
    article_id: str,
    article: Dict,
    company_id: str,
    request: Dict,
    supabase
) -> Dict:
    """Handle publication with legacy format (backwards compatible)."""

    publish_now = request.get('publish_now', False)
    preserve_original_date = request.get('preserve_original_date', False)
    publish_as_draft = request.get('publish_as_draft', False)

    # Check article state
    if article['estado'] == 'borrador':
        pass
    elif article['estado'] == 'programado' and publish_now:
        pass
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Article cannot be processed. Current state: {article['estado']}, publish_now: {publish_now}"
        )

    schedule_time = request.get('schedule_time')
    publication_results = {}

    if publish_now:
        publication_results = await publish_to_platforms(
            article,
            company_id,
            request.get('targets', []),
            publish_as_draft=publish_as_draft
        )

    if publish_now:
        existing_date = article.get('fecha_publicacion')

        if preserve_original_date and existing_date:
            publication_date = existing_date
        else:
            publication_date = datetime.utcnow().isoformat()

        existing_status = article.get('publication_status') or {}
        for target_id, result in publication_results.items():
            existing_status[target_id] = {
                **result,
                "published_at": datetime.utcnow().isoformat()
            }

        current_published_url = article.get('published_url')
        new_published_url = current_published_url

        for target_id, result in publication_results.items():
            if result.get("success") and result.get("url"):
                is_wordpress = result.get("platform") == "wordpress"
                if not new_published_url or is_wordpress:
                    new_published_url = result["url"]
                    if is_wordpress:
                        break

        update_data = {
            "estado": "publicado",
            "fecha_publicacion": publication_date,
            "published_url": new_published_url,
            "publication_status": existing_status,
            "published_date": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        scheduled_for = None
        new_status = "publicado"
    else:
        if schedule_time:
            try:
                scheduled_datetime = datetime.fromisoformat(
                    schedule_time.replace('Z', '+00:00')
                )
                if scheduled_datetime <= datetime.now(timezone.utc):
                    raise HTTPException(
                        status_code=400,
                        detail="Schedule time must be in the future"
                    )
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid datetime format"
                )
        else:
            scheduled_datetime = await calculate_optimal_schedule_time(company_id)

        update_data = {
            "estado": "programado",
            "to_publish_at": scheduled_datetime.isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        scheduled_for = scheduled_datetime.isoformat()
        new_status = "programado"

    update_result = supabase.client.table("press_articles")\
        .update(update_data)\
        .eq("id", article_id)\
        .eq("company_id", company_id)\
        .execute()

    if not update_result.data:
        raise HTTPException(status_code=500, detail="Failed to update article")

    logger.info("article_published_legacy",
        article_id=article_id,
        company_id=company_id,
        new_status=new_status,
        scheduled_for=scheduled_for
    )

    response = {
        "success": True,
        "article_id": article_id,
        "status": new_status,
        "scheduled_for": scheduled_for,
        "message": f"Article {'published as draft' if (publish_now and publish_as_draft) else 'published' if publish_now else 'scheduled for publication'}",
        "published_as_draft": publish_as_draft if publish_now else None
    }

    if publish_now and publication_results:
        response["publication_results"] = publication_results

    return response


async def calculate_optimal_schedule_time(company_id: str) -> datetime:
    """
    Calculate optimal publication time for an article.

    Strategy:
    - Avoid oversaturation (max 2 articles/hour)
    - Prefer high-engagement hours (9-11, 13-15, 18-20)
    - Distribute evenly across the day
    - Start from 2 hours in the future minimum
    """
    supabase = get_supabase_client()

    # Get already scheduled articles for next 48 hours
    now = datetime.utcnow()
    start_time = now + timedelta(hours=2)  # Minimum 2 hours from now
    end_time = now + timedelta(hours=48)

    scheduled_result = supabase.client.table("press_articles")\
        .select("to_publish_at")\
        .eq("company_id", company_id)\
        .eq("estado", "programado")\
        .gte("to_publish_at", start_time.isoformat())\
        .lte("to_publish_at", end_time.isoformat())\
        .execute()

    # Count articles per hour
    scheduled_by_hour = {}
    for article in scheduled_result.data:
        if article['to_publish_at']:
            scheduled_time = datetime.fromisoformat(
                article['to_publish_at'].replace('Z', '+00:00')
            )
            hour_key = scheduled_time.replace(minute=0, second=0, microsecond=0)
            scheduled_by_hour[hour_key] = scheduled_by_hour.get(hour_key, 0) + 1

    # Define optimal hours (in UTC)
    optimal_hours = [9, 10, 11, 13, 14, 15, 18, 19, 20]

    # Find next available slot
    check_time = start_time.replace(minute=0, second=0, microsecond=0)
    backup_time = None

    while check_time <= end_time:
        # Check if this hour is optimal
        is_optimal = check_time.hour in optimal_hours

        # Check if this hour has capacity (max 2 articles/hour)
        current_count = scheduled_by_hour.get(check_time, 0)

        if is_optimal and current_count < 2:
            # Found a good slot, schedule at :00 or :30
            if current_count == 0:
                return check_time  # Schedule at :00
            else:
                return check_time + timedelta(minutes=30)  # Schedule at :30
        elif not is_optimal and current_count == 0:
            # Use non-optimal hour if necessary
            backup_time = check_time

        check_time += timedelta(hours=1)

    # If no optimal slot found, use the backup or start_time
    return backup_time if backup_time else start_time


# ============================================
# SCHEDULE PROPOSAL ENDPOINTS
# ============================================

# Configuration for schedule algorithm
TIMEZONE = "Europe/Madrid"
MIN_GAP_MINUTES = 10  # Minimum gap between any two publications

# Optimal hours per platform (hora Madrid, ordenadas por engagement)
# Basado en estudios de engagement por plataforma
PLATFORM_OPTIMAL_HOURS = {
    "wordpress": [7, 8, 9, 10],                    # SEO: mañana temprano, indexación Google
    "twitter": [9, 12, 17, 18, 21],                # Picos: mañana, mediodía, salida trabajo, noche
    "facebook": [13, 14, 19, 20, 21],              # Post-comida y tarde-noche
    "linkedin": [10, 11, 8, 9],                    # Mid-morning laboral (solo L-V)
    "instagram": [12, 13, 19, 20, 21, 11],         # Mediodía y noche
    "bluesky": [9, 12, 17, 18, 21],                # Similar a Twitter
    "tiktok": [19, 20, 21, 12, 13],                # Tarde-noche principalmente
}

# Fallback para plataformas no definidas
DEFAULT_OPTIMAL_HOURS = [9, 13, 19]


def _get_madrid_now() -> datetime:
    """Get current time in Europe/Madrid timezone."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(TIMEZONE))


def _to_utc(dt: datetime) -> datetime:
    """Convert datetime to UTC."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(TIMEZONE))
    return dt.astimezone(ZoneInfo("UTC"))


def _is_workday(dt: datetime) -> bool:
    """Check if datetime is a workday (Mon-Fri)."""
    return dt.weekday() < 5


def _next_workday(dt: datetime) -> datetime:
    """Get next workday from given datetime."""
    while dt.weekday() >= 5:  # Saturday=5, Sunday=6
        dt = dt + timedelta(days=1)
    return dt


def _find_next_optimal_slot(
    platform: str,
    min_time: datetime,
    taken_slots: list,
    check_workday: bool = False
) -> datetime:
    """Find next optimal publication slot for a platform.

    Args:
        platform: Platform type (wordpress, twitter, etc.)
        min_time: Minimum datetime (must be after this)
        taken_slots: List of already scheduled datetimes to avoid
        check_workday: If True, only schedule on workdays (for LinkedIn)

    Returns:
        Next optimal datetime for this platform
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    tz = ZoneInfo(TIMEZONE)
    if min_time.tzinfo is None:
        min_time = min_time.replace(tzinfo=tz)

    optimal_hours = PLATFORM_OPTIMAL_HOURS.get(platform, DEFAULT_OPTIMAL_HOURS)

    # Try today and next 7 days
    current_date = min_time.date()
    for day_offset in range(8):
        check_date = current_date + timedelta(days=day_offset)

        # Skip weekends for LinkedIn
        if check_workday:
            check_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=tz)
            if not _is_workday(check_dt):
                continue

        for hour in optimal_hours:
            candidate = datetime.combine(
                check_date,
                datetime.min.time().replace(hour=hour, minute=0),
                tzinfo=tz
            )

            # Must be in the future (at least min_time)
            if candidate <= min_time:
                continue

            # Check it doesn't conflict with taken slots (MIN_GAP_MINUTES apart)
            conflict = False
            for taken in taken_slots:
                if taken.tzinfo is None:
                    taken = taken.replace(tzinfo=tz)
                gap = abs((candidate - taken).total_seconds() / 60)
                if gap < MIN_GAP_MINUTES:
                    conflict = True
                    break

            if not conflict:
                return candidate

    # Fallback: just add 1 hour to min_time if no optimal slot found
    return min_time + timedelta(hours=1)


async def _get_last_scheduled_wp(company_id: str) -> Optional[datetime]:
    """Get the last scheduled WordPress publication for this company."""
    try:
        supabase = get_supabase_client()

        # Check scheduled_publications table first
        result = supabase.client.table("scheduled_publications")\
            .select("scheduled_for")\
            .eq("company_id", company_id)\
            .eq("platform_type", "wordpress")\
            .eq("status", "scheduled")\
            .gt("scheduled_for", datetime.utcnow().isoformat())\
            .order("scheduled_for", desc=True)\
            .limit(1)\
            .execute()

        if result.data:
            return datetime.fromisoformat(result.data[0]["scheduled_for"].replace("Z", "+00:00"))

        # Also check articles with to_publish_at (legacy)
        result = supabase.client.table("press_articles")\
            .select("to_publish_at")\
            .eq("company_id", company_id)\
            .eq("estado", "programado")\
            .gt("to_publish_at", datetime.utcnow().isoformat())\
            .order("to_publish_at", desc=True)\
            .limit(1)\
            .execute()

        if result.data and result.data[0].get("to_publish_at"):
            return datetime.fromisoformat(result.data[0]["to_publish_at"].replace("Z", "+00:00"))

        return None
    except Exception as e:
        logger.warn("get_last_scheduled_wp_error", error=str(e))
        return None


@router.get("/api/v1/scheduled-publications")
async def get_scheduled_publications(
    company_id: str = Depends(get_company_id_from_auth),
    status: Optional[str] = None,
    previous_hours: Optional[int] = None,
    previous_days: Optional[int] = None,
    limit: int = 50
) -> Dict:
    """Get all publications (scheduled + immediate) for the company.

    Returns publications from the specified time window.
    - Scheduled: filtered by scheduled_for >= from_time
    - Immediate: filtered by published_at >= from_time (scheduled_for is NULL)

    Args:
        status: Optional filter - 'scheduled', 'published', 'failed'
        previous_hours: Hours to look back. Default 24 if neither hours nor days specified.
        previous_days: Days to look back. Takes precedence over previous_hours.
        limit: Max results (default 50)
    """
    supabase = get_supabase_client()

    # Calculate time threshold (previous_days takes precedence)
    if previous_days is not None:
        hours_back = previous_days * 24
    elif previous_hours is not None:
        hours_back = previous_hours
    else:
        hours_back = 24  # Default

    from_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    from_time_iso = from_time.isoformat()

    # Build query with OR condition:
    # - scheduled_for >= from_time (scheduled publications)
    # - OR scheduled_for IS NULL AND published_at >= from_time (immediate publications)
    query = supabase.client.table("scheduled_publications")\
        .select("id, article_id, target_id, platform_type, scheduled_for, status, published_at, social_hook, error_message, publication_result, press_articles!inner(titulo)")\
        .eq("company_id", company_id)\
        .or_(f"scheduled_for.gte.{from_time_iso},and(scheduled_for.is.null,published_at.gte.{from_time_iso})")\
        .order("published_at", desc=True, nullsfirst=False)\
        .limit(limit)

    # Filter by status if provided
    if status:
        query = query.eq("status", status)

    pubs_result = query.execute()

    publications = []
    for pub in (pubs_result.data or []):
        publications.append({
            "id": pub['id'],
            "article_id": pub['article_id'],
            "article_titulo": pub.get('press_articles', {}).get('titulo'),
            "target_id": pub['target_id'],
            "platform_type": pub['platform_type'],
            "publication_type": "scheduled" if pub.get('scheduled_for') else "immediate",
            "scheduled_for": pub.get('scheduled_for'),
            "status": pub['status'],
            "published_at": pub.get('published_at'),
            "social_hook": pub.get('social_hook'),
            "error_message": pub.get('error_message'),
            "published_url": pub.get('publication_result', {}).get('url') if pub.get('publication_result') else None
        })

    # Summary counts (within same time window, same OR logic)
    all_pubs = supabase.client.table("scheduled_publications")\
        .select("status")\
        .eq("company_id", company_id)\
        .or_(f"scheduled_for.gte.{from_time_iso},and(scheduled_for.is.null,published_at.gte.{from_time_iso})")\
        .execute()

    total = len(all_pubs.data or [])
    scheduled_count = len([p for p in (all_pubs.data or []) if p['status'] == 'scheduled'])
    published_count = len([p for p in (all_pubs.data or []) if p['status'] == 'published'])
    failed_count = len([p for p in (all_pubs.data or []) if p['status'] == 'failed'])

    return {
        "summary": {
            "total": total,
            "scheduled": scheduled_count,
            "published": published_count,
            "failed": failed_count,
            "lookback_hours": hours_back,
            "lookback_days": hours_back / 24
        },
        "publications": publications
    }


@router.patch("/api/v1/scheduled-publications/{publication_id}")
async def update_scheduled_publication(
    publication_id: str,
    company_id: str = Depends(get_company_id_from_auth),
    scheduled_for: Optional[str] = None,
    social_hook: Optional[str] = None,
    status: Optional[str] = None
) -> Dict:
    """Update a scheduled publication.

    **Authentication**: Accepts either JWT or API Key

    Args:
        publication_id: UUID of the scheduled publication
        scheduled_for: New schedule time (ISO-8601 format, e.g., "2026-01-26T07:00:00+01:00")
        social_hook: New social media text/hook
        status: New status ('scheduled', 'cancelled')

    **Response**:
        {
            "id": "uuid",
            "scheduled_for": "2026-01-26T06:00:00+00:00",
            "status": "scheduled",
            "message": "Publication updated"
        }
    """
    supabase = get_supabase_client()

    # Verify publication exists and belongs to company
    pub_result = supabase.client.table("scheduled_publications")\
        .select("id, status, scheduled_for")\
        .eq("id", publication_id)\
        .eq("company_id", company_id)\
        .single()\
        .execute()

    if not pub_result.data:
        raise HTTPException(status_code=404, detail="Scheduled publication not found")

    current_status = pub_result.data.get('status')
    if current_status == 'published':
        raise HTTPException(status_code=400, detail="Cannot modify already published publication")

    # Build update data
    update_data = {"updated_at": datetime.now(timezone.utc).isoformat()}

    if scheduled_for is not None:
        # Parse and validate the datetime
        try:
            parsed_dt = datetime.fromisoformat(scheduled_for.replace('Z', '+00:00'))
            if parsed_dt <= datetime.now(timezone.utc):
                raise HTTPException(status_code=400, detail="scheduled_for must be in the future")
            update_data["scheduled_for"] = parsed_dt.isoformat()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid datetime format: {str(e)}")

    if social_hook is not None:
        update_data["social_hook"] = social_hook

    if status is not None:
        if status not in ['scheduled', 'cancelled']:
            raise HTTPException(status_code=400, detail="status must be 'scheduled' or 'cancelled'")
        update_data["status"] = status

    # Update
    result = supabase.client.table("scheduled_publications")\
        .update(update_data)\
        .eq("id", publication_id)\
        .execute()

    logger.info("scheduled_publication_updated",
        publication_id=publication_id,
        company_id=company_id,
        updates=list(update_data.keys())
    )

    return {
        "id": publication_id,
        "scheduled_for": update_data.get("scheduled_for", pub_result.data.get("scheduled_for")),
        "status": update_data.get("status", current_status),
        "message": "Publication updated"
    }


@router.delete("/api/v1/scheduled-publications/{publication_id}")
async def delete_scheduled_publication(
    publication_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """Delete/cancel a scheduled publication.

    **Authentication**: Accepts either JWT or API Key

    Note: This permanently deletes the publication record. Use PATCH with status='cancelled'
    to keep the record but prevent publication.

    **Response**:
        {
            "id": "uuid",
            "message": "Publication deleted"
        }
    """
    supabase = get_supabase_client()

    # Verify publication exists and belongs to company
    pub_result = supabase.client.table("scheduled_publications")\
        .select("id, status, platform_type, article_id")\
        .eq("id", publication_id)\
        .eq("company_id", company_id)\
        .single()\
        .execute()

    if not pub_result.data:
        raise HTTPException(status_code=404, detail="Scheduled publication not found")

    if pub_result.data.get('status') == 'published':
        raise HTTPException(status_code=400, detail="Cannot delete already published publication")

    # Delete
    supabase.client.table("scheduled_publications")\
        .delete()\
        .eq("id", publication_id)\
        .execute()

    logger.info("scheduled_publication_deleted",
        publication_id=publication_id,
        company_id=company_id,
        platform_type=pub_result.data.get('platform_type'),
        article_id=pub_result.data.get('article_id')
    )

    return {
        "id": publication_id,
        "message": "Publication deleted"
    }


@router.post("/api/v1/articles/{article_id}/propose-schedule")
async def propose_schedule(
    article_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Calculate optimal publication schedules for all available targets.

    **Authentication**: Accepts either JWT or API Key

    Returns proposed schedule times for each publication target,
    considering platform-specific optimal hours based on engagement data:
    - WordPress: 7-10h (SEO/indexación Google)
    - Twitter/Bluesky: 9, 12, 17-18, 21h (picos de actividad)
    - Facebook: 13-14, 19-21h (post-comida y noche)
    - LinkedIn: 8-11h solo días laborables
    - Instagram: 11-13, 19-21h (mediodía y noche)
    - TikTok: 12-13, 19-21h (tarde-noche)

    **Response**:
        {
            "schedules": [
                {"target_id": "uuid", "platform_type": "wordpress", "schedule_time": "2024-01-29T14:00:00Z"},
                {"target_id": "uuid", "platform_type": "twitter", "schedule_time": "2024-01-29T14:15:00Z"},
                ...
            ]
        }
    """
    try:
        supabase = get_supabase_client()

        # Verify article exists
        article_result = supabase.client.table("press_articles")\
            .select("id")\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .single()\
            .execute()

        if not article_result.data:
            raise HTTPException(status_code=404, detail="Article not found")

        # Get all active publication targets for this company
        targets_result = supabase.client.table("press_publication_targets")\
            .select("id, platform_type, name, is_default")\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .order("is_default", desc=True)\
            .order("created_at")\
            .execute()

        targets = targets_result.data or []

        if not targets:
            return {"schedules": []}

        # Get current time in Madrid (min 5 minutes from now)
        now_madrid = _get_madrid_now()
        min_start = now_madrid + timedelta(minutes=5)

        # Track already scheduled slots to avoid conflicts
        taken_slots = []

        # Get existing scheduled publications to avoid conflicts
        last_wp = await _get_last_scheduled_wp(company_id)
        if last_wp:
            taken_slots.append(last_wp)

        # Calculate optimal schedule for each target
        schedules = []

        # Sort targets: WordPress first (SEO needs early publication)
        sorted_targets = sorted(
            targets,
            key=lambda t: (0 if t["platform_type"] == "wordpress" else 1, t.get("name", ""))
        )

        for target in sorted_targets:
            platform = target["platform_type"]

            # LinkedIn only on workdays
            check_workday = (platform == "linkedin")

            # Find optimal slot for this platform
            schedule_time = _find_next_optimal_slot(
                platform=platform,
                min_time=min_start,
                taken_slots=taken_slots,
                check_workday=check_workday
            )

            schedules.append({
                "target_id": target["id"],
                "platform_type": platform,
                "name": target["name"],
                "schedule_time": _to_utc(schedule_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            })

            # Add to taken slots to avoid conflicts
            taken_slots.append(schedule_time)

        logger.info("schedule_proposed",
            article_id=article_id,
            company_id=company_id,
            targets_count=len(schedules)
        )

        return {"schedules": schedules}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("propose_schedule_error", error=str(e), article_id=article_id)
        raise HTTPException(status_code=500, detail="Failed to calculate schedule")


# ============================================
# EXECUTIONS & STYLES ENDPOINTS
# ============================================

@router.get("/api/v1/executions")
async def list_executions(
    auth: Dict = Depends(get_auth_context),
    limit: int = 20,
    offset: int = 0
) -> Dict:
    """
    Get paginated list of executions/sources.

    RLS automatically filters by company_id from JWT.
    """
    try:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")

        company_id = auth["company_id"]
        supabase = get_supabase_client()

        result = supabase.client.table("executions")\
            .select("*", count="exact")\
            .eq("company_id", company_id)\
            .order("timestamp", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()

        total = result.count if hasattr(result, 'count') else 0
        items = result.data or []

        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total
        }

    except Exception as e:
        logger.error("list_executions_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch executions: {str(e)}")


@router.get("/api/v1/styles")
async def list_styles(
    auth: Dict = Depends(get_auth_context)
) -> Dict:
    """
    Get list of available press styles.

    Returns active styles for the user's company.
    """
    try:
        company_id = auth["company_id"]
        supabase = get_supabase_client()

        result = supabase.client.table("press_styles")\
            .select("*")\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .order("created_at", desc=True)\
            .execute()

        return {
            "items": result.data or []
        }

    except Exception as e:
        logger.error("list_styles_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch styles: {str(e)}")
