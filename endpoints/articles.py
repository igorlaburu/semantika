"""Articles endpoints for Press module.

Handles article CRUD, publishing to platforms, and related articles.
"""

from datetime import datetime, timedelta
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

        # Extract image_prompt from working_json for each article
        for article in items:
            if article.get("working_json") and isinstance(article["working_json"], dict):
                if "image_prompt" in article["working_json"]:
                    article["image_prompt"] = article["working_json"]["image_prompt"]

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

        # Extract image_prompt from working_json if available
        article = result.data
        if article.get("working_json") and isinstance(article["working_json"], dict):
            if "image_prompt" in article["working_json"]:
                article["image_prompt"] = article["working_json"]["image_prompt"]

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

        # Extract image_prompt from working_json if available
        article = result.data
        if article.get("working_json") and isinstance(article["working_json"], dict):
            if "image_prompt" in article["working_json"]:
                article["image_prompt"] = article["working_json"]["image_prompt"]

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

            # Format hashtags from tags
            hashtags = ""
            if tags:
                import re
                formatted_tags = []
                for tag in tags[:5]:  # Limit to 5 hashtags
                    clean_tag = re.sub(r'[^a-zA-Z0-9áéíóúñüÁÉÍÓÚÑÜ]', '', str(tag))
                    if clean_tag and len(clean_tag) > 1:
                        formatted_tags.append(f"#{clean_tag}")
                hashtags = " ".join(formatted_tags)

            # Build social media content (max 280 chars for Twitter)
            # Format: title + url + hashtags (NO excerpt, hashtags only if they fit, title truncated if needed)
            MAX_TWEET_LENGTH = 280

            # Get URL: published article URL or fallback to WordPress base URL
            # Priority: 1) Just published WP URL, 2) Previously published URL, 3) WP base URL
            tweet_url = wordpress_url

            # Check for previously published URL if not publishing to WP now
            if not tweet_url and article.get('published_url'):
                tweet_url = article['published_url']
                logger.info("social_using_previous_published_url",
                    article_id=article['id'],
                    published_url=tweet_url
                )

            if not tweet_url and wordpress_targets:
                # Use first WordPress target's base_url as fallback
                tweet_url = wordpress_targets[0].get('base_url', '')
                logger.info("social_using_fallback_base_url",
                    article_id=article['id'],
                    fallback_url=tweet_url
                )

            # If still no URL, try to get default WordPress from company
            if not tweet_url:
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
                        tweet_url = default_wp.data[0].get('base_url', '')
                        logger.info("social_using_default_wordpress_url",
                            article_id=article['id'],
                            default_url=tweet_url
                        )
                except Exception as e:
                    logger.warn("social_failed_to_get_default_wordpress",
                        article_id=article['id'],
                        error=str(e)
                    )

            # Calculate available space for title
            # Format: "title\n\nurl\n\nhashtags" or "title\n\nurl" if hashtags don't fit
            url_length = len(tweet_url) if tweet_url else 23  # Twitter shortens URLs to 23 chars
            base_length = url_length + 4  # 4 = two "\n\n" separators

            # Try with hashtags first
            if hashtags:
                available_for_title = MAX_TWEET_LENGTH - base_length - len(hashtags) - 2  # -2 for extra \n\n
                if available_for_title < 50:  # If not enough space, drop hashtags
                    hashtags = ""
                    available_for_title = MAX_TWEET_LENGTH - base_length
            else:
                available_for_title = MAX_TWEET_LENGTH - base_length

            # Truncate title if needed
            truncated_title = title
            if len(title) > available_for_title:
                truncated_title = title[:available_for_title - 3] + "..."

            # Build final tweet content
            if hashtags:
                social_content = f"{truncated_title}\n\n{tweet_url}\n\n{hashtags}"
            else:
                social_content = f"{truncated_title}\n\n{tweet_url}"

            logger.info("social_content_prepared",
                article_id=article['id'],
                content_length=len(social_content),
                has_hashtags=bool(hashtags),
                truncated=len(title) > available_for_title
            )

            for target in social_targets:
                target_id = target['id']

                try:
                    publisher = PublisherFactory.create_publisher(
                        target['platform_type'],
                        target.get('base_url', ''),
                        target['credentials_encrypted']
                    )

                    # Social media publish - different method than WordPress
                    result = await publisher.publish_social(
                        content=social_content,
                        url=tweet_url,
                        image_uuid=imagen_uuid,
                        tags=tags[:5] if tags else [],
                        temp_image_path=temp_image_path
                    )

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

                    logger.info("article_published_to_social",
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
                        "error": f"Social publication error: {str(e)}"
                    }

                    logger.error("social_platform_publication_failed",
                        article_id=article['id'],
                        target_id=target_id,
                        platform=target['platform_type'],
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

    If publish_now=true, publishes immediately to all specified targets.
    If schedule_time is provided, schedules for that time.
    If neither, backend calculates optimal schedule time.

    **Authentication**: Accepts either JWT or API Key

    **Body**:
        {
            "publish_now": false,               // optional, default false
            "preserve_original_date": false,    // optional, mantener fecha de publicación original
            "schedule_time": null,              // optional ISO datetime, null = auto-schedule
            "targets": ["uuid1", "uuid2"],      // optional, publication target IDs. If empty, uses default targets, then first available target
            "publish_as_draft": false           // optional, if true: publish to WordPress as draft, skip RRSS
        }

    **Returns**:
        {
            "success": true,
            "article_id": "xxx",
            "status": "programado",
            "scheduled_for": "2024-12-27T10:00:00Z",
            "publication_results": {
                "uuid1": {"success": true, "url": "https://...", "platform": "wordpress"},
                "uuid2": {"success": false, "error": "Connection failed"}
            }
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

        # Determine publication strategy first
        publish_now = request.get('publish_now', False)
        preserve_original_date = request.get('preserve_original_date', False)

        # Check article state - allow programado articles to be published immediately
        if article['estado'] == 'borrador':
            # Draft articles can be published/scheduled
            pass
        elif article['estado'] == 'programado' and publish_now:
            # Scheduled articles can be published immediately (used by scheduler)
            pass
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Article cannot be processed. Current state: {article['estado']}, publish_now: {publish_now}"
            )
        schedule_time = request.get('schedule_time')
        publication_results = {}

        # Handle multi-platform publication if immediate
        publish_as_draft = request.get('publish_as_draft', False)

        if publish_now:
            publication_results = await publish_to_platforms(
                article,
                company_id,
                request.get('targets', []),
                publish_as_draft=publish_as_draft
            )

        if publish_now:
            # Determine publication date
            existing_date = article.get('fecha_publicacion')

            if preserve_original_date and existing_date:
                # Mantener fecha original
                publication_date = existing_date
                logger.info("preserving_original_publication_date",
                    article_id=article_id,
                    original_date=existing_date)
            else:
                # Nueva fecha de publicación
                publication_date = datetime.utcnow().isoformat()
                if existing_date:
                    logger.info("updating_publication_date",
                        article_id=article_id,
                        old_date=existing_date,
                        new_date=publication_date)

            # Merge publication results with existing publication_status (additive)
            existing_status = article.get('publication_status') or {}
            for target_id, result in publication_results.items():
                existing_status[target_id] = {
                    **result,
                    "published_at": datetime.utcnow().isoformat()
                }

            # Determine published_url: prioritize WordPress, keep existing if set
            current_published_url = article.get('published_url')
            new_published_url = current_published_url  # Keep existing by default

            # Only update published_url if:
            # 1. It's not set yet, OR
            # 2. New publication is WordPress (prioritize WP URLs for SEO)
            for target_id, result in publication_results.items():
                if result.get("success") and result.get("url"):
                    is_wordpress = result.get("platform") == "wordpress"
                    if not new_published_url or is_wordpress:
                        new_published_url = result["url"]
                        if is_wordpress:
                            break  # WordPress URL found, use it as primary

            # Publish immediately
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
            # Schedule for later
            if schedule_time:
                # Use provided schedule time
                try:
                    scheduled_datetime = datetime.fromisoformat(
                        schedule_time.replace('Z', '+00:00')
                    )
                    if scheduled_datetime <= datetime.utcnow():
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
                # Calculate optimal schedule time
                scheduled_datetime = await calculate_optimal_schedule_time(company_id)

            update_data = {
                "estado": "borrador",
                "to_publish_at": scheduled_datetime.isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            scheduled_for = scheduled_datetime.isoformat()
            new_status = "programado"

        # Update article
        update_result = supabase.client.table("press_articles")\
            .update(update_data)\
            .eq("id", article_id)\
            .eq("company_id", company_id)\
            .execute()

        if not update_result.data:
            raise HTTPException(status_code=500, detail="Failed to update article")

        logger.info("article_published",
            article_id=article_id,
            company_id=company_id,
            new_status=new_status,
            scheduled_for=scheduled_for,
            publish_as_draft=publish_as_draft if publish_now else None
        )

        response = {
            "success": True,
            "article_id": article_id,
            "status": new_status,
            "scheduled_for": scheduled_for,
            "message": f"Article {'published as draft' if (publish_now and publish_as_draft) else 'published' if publish_now else 'scheduled for publication'}",
            "published_as_draft": publish_as_draft if publish_now else None
        }

        # Add publication results if we published immediately
        if publish_now and publication_results:
            response["publication_results"] = publication_results

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("publish_article_error",
            error=str(e),
            article_id=article_id
        )
        raise HTTPException(status_code=500, detail="Failed to publish article")


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
