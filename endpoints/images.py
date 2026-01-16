"""Image generation, retrieval, and upload endpoints."""

import re
import ssl
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import aiohttp
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_company_id_from_auth

logger = get_logger("api.images")
router = APIRouter(tags=["images"])

# Initialize supabase client
supabase_client = get_supabase_client()


# ============================================
# PYDANTIC MODELS
# ============================================

class GenerateImageRequest(BaseModel):
    image_prompt: str = Field(..., description="Image generation prompt in English")
    force_regenerate: bool = Field(default=False, description="Force regeneration even if cached")


class ImageUploadRequest(BaseModel):
    """Request model for base64 image upload."""
    base64: str = Field(..., description="Base64 encoded image data (with or without data URI prefix)")
    filename: Optional[str] = Field(None, description="Original filename (optional, used for extension detection)")


# ============================================
# HELPER FUNCTIONS
# ============================================

def generate_placeholder_image() -> bytes:
    """Generate SVG placeholder image with 1.91:1 aspect ratio.

    Returns:
        SVG bytes for placeholder (600×314px, scales to any size)
    """
    svg = """<svg width="600" height="314" xmlns="http://www.w3.org/2000/svg">
  <rect width="600" height="314" fill="#f0f0f0"/>
  <text x="50%" y="50%" font-family="Arial, sans-serif" font-size="18"
        fill="#999" text-anchor="middle" dominant-baseline="middle">
    Sin imagen
  </text>
</svg>"""
    return svg.encode('utf-8')


# ============================================
# IMAGE GENERATION ENDPOINTS
# ============================================

@router.post("/api/v1/articles/{article_id}/generate-image")
async def generate_image_for_article(
    article_id: str,
    request: GenerateImageRequest,
    company_id: str = Depends(get_company_id_from_auth)
):
    """Generate photorealistic AI image for article from prompt.

    Uses Fal.ai FLUX.1 [schnell] model to generate conceptual, photorealistic
    images from a prompt provided by the frontend.

    Model specs:
    - Cost: $0.003/image
    - Speed: 1-2 seconds
    - Resolution: 1024x576 (landscape 16:9)
    - Quality: Excellent for simple photorealistic objects

    Generated images are:
    - Cached permanently in /app/cache/images/{article_id}.jpg
    - Served via GET /api/v1/images/{article_id} (unified endpoint)

    **Authentication**: Accepts JWT or API Key

    Args:
        article_id: Article UUID
        request.image_prompt: Image generation prompt (from frontend)
        request.force_regenerate: Force regeneration even if cached
        company_id: Company ID from auth

    Returns:
        Image generation result with URL and metadata

    Example:
        POST /api/v1/articles/uuid-123/generate-image
        Body: {
            "image_prompt": "A sleek medical device on sterile table...",
            "force_regenerate": false
        }
        Response: {
            "article_id": "uuid-123",
            "image_prompt": "A sleek medical device on sterile table...",
            "image_url": "/api/v1/articles/uuid-123/image",
            "status": "generated",
            "generated_at": "2025-12-18T14:30:00Z",
            "generation_time_ms": 1234.56
        }

    Raises:
        HTTPException: 404 if article not found
        HTTPException: 400 if image_prompt is empty
        HTTPException: 500 if image generation fails
    """
    try:
        logger.info("generate_image_request",
            article_id=article_id,
            company_id=company_id,
            force_regenerate=request.force_regenerate,
            prompt_preview=request.image_prompt[:100]
        )

        # Verify article exists and belongs to company
        result = supabase_client.client.table("press_articles").select(
            "id, company_id"
        ).eq("id", article_id).eq("company_id", company_id).maybe_single().execute()

        if not result.data:
            logger.warn("article_not_found_for_image_generation",
                article_id=article_id,
                company_id=company_id
            )
            raise HTTPException(status_code=404, detail="Article not found")

        # Validate image_prompt
        image_prompt = request.image_prompt.strip()
        if not image_prompt:
            logger.warn("empty_image_prompt",
                article_id=article_id
            )
            raise HTTPException(status_code=400, detail="image_prompt cannot be empty")

        # Generate image using Fal.ai with unique UUID
        import uuid
        from utils.image_generator import generate_image_from_prompt

        # Generate unique UUID for this image (allows multiple generations)
        image_uuid = str(uuid.uuid4())

        gen_result = await generate_image_from_prompt(
            context_unit_id=image_uuid,  # Use unique UUID as cache key
            image_prompt=image_prompt,
            force_regenerate=request.force_regenerate
        )

        if gen_result["success"]:
            logger.info("image_generation_success_endpoint",
                article_id=article_id,
                image_uuid=image_uuid,
                cached=gen_result["cached"],
                generation_time_ms=gen_result["generation_time_ms"]
            )

            # Return image UUID - frontend decides whether to assign it to article
            return {
                "article_id": article_id,
                "image_uuid": image_uuid,
                "image_url": f"/api/v1/images/{image_uuid}",
                "image_prompt": image_prompt,
                "status": "cached" if gen_result["cached"] else "generated",
                "generated_at": datetime.utcnow().isoformat(),
                "generation_time_ms": gen_result["generation_time_ms"]
            }
        else:
            logger.error("image_generation_failed_endpoint",
                article_id=article_id,
                error=gen_result.get("error")
            )
            raise HTTPException(
                status_code=500,
                detail=f"Image generation failed: {gen_result.get('error', 'Unknown error')}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("generate_image_error",
            article_id=article_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/articles/{article_id}/image")
async def get_article_image(
    article_id: str,
    company_id: str = Depends(get_company_id_from_auth)
):
    """Get image for article with fallback to placeholder.

    Image priority:
    1. Cached image (from POST /generate-image) - X-Image-Source: "cached"
    2. Placeholder SVG - X-Image-Source: "placeholder"

    Images are cached in /app/cache/images/{article_id}.jpg

    Args:
        article_id: Article UUID
        company_id: Company ID from auth

    Returns:
        Image bytes (JPEG or SVG placeholder)

    Response Headers:
        - Content-Type: image/jpeg or image/svg+xml
        - Cache-Control: public, max-age=86400 (24 hours)
        - X-Image-Source: "cached" | "placeholder"

    Expected aspect ratio: 16:9 (1024x576) for generated

    Raises:
        HTTPException: 404 if article not found
    """
    try:
        # Check unified cache
        cache_dir = Path("/app/cache/images")
        cache_file = cache_dir / f"{article_id}.jpg"

        if cache_file.exists():
            logger.debug("article_image_cache_hit",
                article_id=article_id,
                cache_file=str(cache_file)
            )

            return Response(
                content=cache_file.read_bytes(),
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "X-Image-Source": "cached",
                    "X-Image-Cache": "hit"
                }
            )

        # Fallback: Return placeholder
        logger.debug("article_image_cache_miss", article_id=article_id)

        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Image-Source": "placeholder"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("image_proxy_error", article_id=article_id, error=str(e))
        # Return placeholder on any error
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Image-Source": "placeholder"
            }
        )


# ============================================
# CONTEXT UNIT IMAGE ENDPOINTS
# ============================================

@router.get("/api/v1/context-units/{context_unit_id}/image")
async def get_context_unit_image(
    context_unit_id: str,
    index: int = Query(0, ge=0, le=10, description="Image index (0 = first image)")
):
    """Get featured or manual image for context unit.

    Args:
        context_unit_id: UUID of context unit
        index: Image index (0 = first image, 1 = second, etc.)

    Returns:
        Image file or placeholder.

    Sources (in priority order):
        1. Manual uploaded images (index-based: {context_unit_id}_{index}.ext)
        2. Legacy format (backward compatibility: {context_unit_id}.ext - index=0 only)
        3. Featured images from scraping (index=0 only)
        4. Placeholder SVG
    """
    try:
        # Fetch context unit (allow pool access)
        pool_company_id = "99999999-9999-9999-9999-999999999999"

        result = supabase_client.client.table("press_context_units").select(
            "id, source_metadata, company_id"
        ).eq("id", context_unit_id).maybe_single().execute()

        if not result.data:
            logger.debug("context_unit_not_found_for_image", context_unit_id=context_unit_id)
            raise HTTPException(status_code=404, detail="Context unit not found")

        context_unit = result.data
        source_metadata = context_unit.get("source_metadata") or {}

        # Priority 1: Check for manual uploaded images (indexed)
        cache_dir = Path("/app/cache/images")
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Try manual images with index: {context_unit_id}_{index}.ext
        for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]:
            indexed_cache_file = cache_dir / f"{context_unit_id}_{index}{ext}"
            if indexed_cache_file.exists():
                # Determine media type from extension
                media_type_map = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                    ".bmp": "image/bmp"
                }
                media_type = media_type_map.get(ext, "image/jpeg")

                logger.debug("manual_image_cache_hit",
                    context_unit_id=context_unit_id,
                    index=index,
                    cache_file=str(indexed_cache_file)
                )

                return Response(
                    content=indexed_cache_file.read_bytes(),
                    media_type=media_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "X-Image-Source": "manual_upload",
                        "X-Image-Index": str(index)
                    }
                )

        # Priority 2: For index=0, try old format without index (backward compatibility)
        if index == 0:
            for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]:
                legacy_cache_file = cache_dir / f"{context_unit_id}{ext}"
                if legacy_cache_file.exists():
                    # Determine media type from extension
                    media_type_map = {
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".png": "image/png",
                        ".webp": "image/webp",
                        ".gif": "image/gif",
                        ".bmp": "image/bmp"
                    }
                    media_type = media_type_map.get(ext, "image/jpeg")

                    logger.debug("legacy_image_cache_hit",
                        context_unit_id=context_unit_id,
                        cache_file=str(legacy_cache_file),
                        extension=ext
                    )
                    return Response(
                        content=legacy_cache_file.read_bytes(),
                        media_type=media_type,
                        headers={
                            "Cache-Control": "public, max-age=86400",
                            "X-Image-Source": "legacy_format",
                            "X-Image-Cache": "hit"
                        }
                    )

        # Priority 3: For index=0, try featured image from scraping
        if index == 0:
            featured_image = source_metadata.get("featured_image")
            if featured_image and featured_image.get("url"):
                image_url = featured_image["url"]

                # Skip file:// URLs (should be cached already)
                if image_url.startswith("file://"):
                    logger.warn("file_url_without_cache",
                        context_unit_id=context_unit_id,
                        file_url=image_url
                    )
                    # Fall through to placeholder
                else:
                    # Try to fetch and cache featured image
                    try:
                        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE

                        connector = aiohttp.TCPConnector(ssl=ssl_context)
                        async with aiohttp.ClientSession(connector=connector) as session:
                            async with session.get(
                                image_url,
                                headers={
                                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                    'Accept': 'image/*',
                                    'Referer': source_metadata.get("url", "https://ekimen.ai")
                                },
                                timeout=aiohttp.ClientTimeout(total=10)
                            ) as response:

                                if response.status == 200:
                                    image_bytes = await response.read()
                                    content_type = response.headers.get("Content-Type", "image/jpeg")

                                    # Try to cache to disk (optional - don't fail if this fails)
                                    try:
                                        # Determine extension from content type
                                        ext_map = {
                                            "image/jpeg": ".jpg",
                                            "image/png": ".png",
                                            "image/webp": ".webp",
                                            "image/gif": ".gif",
                                            "image/bmp": ".bmp"
                                        }
                                        ext = ext_map.get(content_type, ".jpg")
                                        cache_file = cache_dir / f"{context_unit_id}_{index}{ext}"

                                        cache_file.write_bytes(image_bytes)
                                        logger.info("featured_image_cached",
                                            context_unit_id=context_unit_id,
                                            size_bytes=len(image_bytes),
                                            cache_path=str(cache_file)
                                        )
                                    except Exception as e:
                                        logger.warn("featured_image_cache_write_failed",
                                            context_unit_id=context_unit_id,
                                            error=str(e)
                                        )

                                    return Response(
                                        content=image_bytes,
                                        media_type=content_type,
                                        headers={
                                            "Cache-Control": "public, max-age=86400",
                                            "X-Image-Source": "featured_image",
                                            "X-Image-Extraction": featured_image.get("source", "unknown")
                                        }
                                    )
                                else:
                                    logger.warn("featured_image_fetch_failed",
                                        context_unit_id=context_unit_id,
                                        status=response.status,
                                        url=image_url
                                    )
                    except Exception as e:
                        logger.warn("featured_image_proxy_error",
                            context_unit_id=context_unit_id,
                            error=str(e),
                            url=image_url
                        )

        # Priority 4: Return 400 error (no image available)
        logger.debug("image_not_found_return_400",
            context_unit_id=context_unit_id,
            index=index
        )
        raise HTTPException(status_code=400, detail=f"No image available for context unit {context_unit_id} at index {index}")

    except HTTPException:
        # Re-raise HTTP exceptions (404, 400) without placeholder
        raise
    except Exception as e:
        logger.error("get_context_unit_image_error", context_unit_id=context_unit_id, index=index, error=str(e))
        raise HTTPException(status_code=500, detail="Internal error while fetching image")


@router.get("/api/v1/context-units/{context_unit_id}/email-images")
async def get_context_unit_email_images(
    context_unit_id: str,
    company_id: str = Depends(get_company_id_from_auth)
):
    """Get cached email images for context unit."""
    try:
        # Get context unit with cached images metadata
        pool_company_id = "99999999-9999-9999-9999-999999999999"

        result = supabase_client.client.table("press_context_units").select(
            "id, source_metadata, source_type"
        ).eq("id", context_unit_id).in_("company_id", [company_id, pool_company_id]).maybe_single().execute()

        if not result.data or result.data.get("source_type") != "email":
            return {"images": []}

        cached_images = result.data.get("source_metadata", {}).get("connector_specific", {}).get("cached_images", [])

        # Filter existing images and add access URLs
        available_images = []
        for img in cached_images:
            cache_path = Path(img["cache_path"])
            if cache_path.exists():
                available_images.append({
                    "url": f"/api/v1/context-units/{context_unit_id}/email-image/{cache_path.name}",
                    "source": img["source"],
                    "filename": img.get("original_filename"),
                    "size_bytes": img.get("size_bytes")
                })

        return {"images": available_images}

    except Exception as e:
        logger.error("get_email_images_error", error=str(e))
        return {"images": []}


@router.get("/api/v1/context-units/{context_unit_id}/email-image/{image_filename}")
async def serve_cached_email_image(
    context_unit_id: str,
    image_filename: str,
    company_id: str = Depends(get_company_id_from_auth)
):
    """Serve cached email image."""
    try:
        # Security: validate filename format
        if not re.match(r'^[a-f0-9\-]+(\_img\_\d+)\.(jpg|png|webp|gif)$', image_filename):
            raise HTTPException(status_code=400, detail="Invalid image filename")

        # Verify context unit belongs to user
        pool_company_id = "99999999-9999-9999-9999-999999999999"
        result = supabase_client.client.table("press_context_units").select(
            "id"
        ).eq("id", context_unit_id).in_("company_id", [company_id, pool_company_id]).maybe_single().execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Context unit not found")

        # Serve image
        image_path = Path(f"/app/cache/email_images/{image_filename}")
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Determine content type
        ext = image_path.suffix.lower()
        content_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif"
        }
        content_type = content_type_map.get(ext, "image/jpeg")

        return Response(
            content=image_path.read_bytes(),
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=2592000",  # 30 days
                "X-Image-Source": "email_cache"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("serve_email_image_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to serve image")


# ============================================
# UNIFIED IMAGE ENDPOINT (PUBLIC)
# ============================================

@router.get("/api/v1/images/{image_id}")
async def get_image_unified(image_id: str):
    """Unified public image endpoint.

    Serves cached images from /app/cache/images/{uuid}.{ext}
    No authentication required - knowing the UUID is the protection.

    Images can be:
    1. AI-generated (from POST /articles/{id}/generate-image) - typically .jpg
    2. Featured images (cached from GET /context-units/{id}/image) - .jpg, .png, .gif, .webp, .bmp

    Args:
        image_id: UUID of article or context unit

    Returns:
        - Image if cached (JPEG/PNG/GIF/WebP/BMP) (X-Image-Source: "cached")
        - SVG placeholder if not found (X-Image-Source: "placeholder")

    Headers:
        - Cache-Control: public, max-age=86400 (24h)
        - X-Image-Source: "cached" | "placeholder"
    """
    try:
        cache_dir = Path("/app/cache/images")

        # Check for cached image with multiple extensions
        extensions = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]

        for ext in extensions:
            cache_file = cache_dir / f"{image_id}{ext}"
            if cache_file.exists():
                # Determine media type from extension
                media_type_map = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                    ".bmp": "image/bmp"
                }
                media_type = media_type_map.get(ext, "image/jpeg")

                logger.debug("unified_image_cache_hit",
                    image_id=image_id,
                    extension=ext,
                    media_type=media_type
                )
                return Response(
                    content=cache_file.read_bytes(),
                    media_type=media_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "X-Image-Source": "cached"
                    }
                )

        # Not cached - return placeholder
        logger.debug("unified_image_not_found", image_id=image_id)
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Image-Source": "placeholder"
            }
        )

    except Exception as e:
        logger.error("unified_image_error", image_id=image_id, error=str(e))
        placeholder = generate_placeholder_image()
        return Response(
            content=placeholder,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Image-Source": "placeholder"
            }
        )


# ============================================
# IMAGE UPLOAD ENDPOINTS
# ============================================

@router.put("/api/v1/images")
async def upload_image(
    image_file: Optional[UploadFile] = File(None),
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """
    Upload an independent image and get a UUID to retrieve it later.

    Supports two methods:
    1. Multipart form upload: PUT /api/v1/images with file in 'image_file' field
    2. Base64 JSON: PUT /api/v1/images with JSON body containing base64 data

    **Authentication**: Accepts either JWT or API Key

    Returns:
        {
            "success": true,
            "image_id": "uuid-generated",
            "size_bytes": 1024,
            "format": "png",
            "url": "/api/v1/images/uuid-generated"
        }
    """
    import uuid
    from utils.context_unit_images import ContextUnitImageProcessor

    try:
        # Generate unique UUID for this image
        image_uuid = str(uuid.uuid4())

        if image_file:
            # Method 1: Multipart file upload
            if not image_file.content_type or not image_file.content_type.startswith('image/'):
                raise HTTPException(status_code=400, detail="File must be an image")

            # Read file content
            image_data = await image_file.read()

            # Validate size
            if len(image_data) > ContextUnitImageProcessor.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"Image too large. Max size: {ContextUnitImageProcessor.MAX_FILE_SIZE} bytes"
                )

            # Validate image format and dimensions
            if not ContextUnitImageProcessor.validate_image(image_data):
                raise HTTPException(status_code=400, detail="Invalid image format or dimensions")

            # Detect format
            extension = ContextUnitImageProcessor.detect_image_format(image_data)
            if not extension:
                # Fallback to filename extension
                extension = ContextUnitImageProcessor.get_extension_from_filename(image_file.filename or "")
                if not extension:
                    extension = ".jpg"  # Default

        else:
            # Method 2: JSON request with base64 (read from request body)
            raise HTTPException(
                status_code=400,
                detail="Multipart file upload required. Send image as 'image_file' field."
            )

        # Save to cache directory with UUID
        cache_dir = Path("/app/cache/images")
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_filename = f"{image_uuid}{extension}"
        cache_path = cache_dir / cache_filename

        # Write to disk
        with open(cache_path, "wb") as f:
            f.write(image_data)

        logger.info("independent_image_uploaded",
            image_uuid=image_uuid,
            filename=cache_filename,
            size_bytes=len(image_data),
            content_type=image_file.content_type if image_file else "unknown",
            company_id=company_id
        )

        return {
            "success": True,
            "image_id": image_uuid,
            "size_bytes": len(image_data),
            "format": extension[1:],  # Remove dot from extension
            "url": f"/api/v1/images/{image_uuid}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_image_error", error=str(e), company_id=company_id)
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")


@router.post("/api/v1/images")
async def upload_image_base64(
    request: ImageUploadRequest,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """
    Upload an image using base64 encoding.

    **Authentication**: Accepts either JWT or API Key

    Body:
        {
            "base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
            "filename": "my-image.png"  // optional
        }

    Returns:
        {
            "success": true,
            "image_id": "uuid-generated",
            "size_bytes": 1024,
            "format": "png",
            "url": "/api/v1/images/uuid-generated"
        }
    """
    import uuid
    from utils.context_unit_images import ContextUnitImageProcessor

    try:
        # Generate unique UUID for this image
        image_uuid = str(uuid.uuid4())

        # Decode base64 image
        try:
            image_data = ContextUnitImageProcessor.decode_base64_image(request.base64)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Validate image format and dimensions
        if not ContextUnitImageProcessor.validate_image(image_data):
            raise HTTPException(status_code=400, detail="Invalid image format or dimensions")

        # Detect format
        extension = ContextUnitImageProcessor.detect_image_format(image_data)
        if not extension:
            # Fallback to filename extension
            extension = ContextUnitImageProcessor.get_extension_from_filename(request.filename or "")
            if not extension:
                extension = ".jpg"  # Default

        # Save to cache directory with UUID
        cache_dir = Path("/app/cache/images")
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_filename = f"{image_uuid}{extension}"
        cache_path = cache_dir / cache_filename

        # Write to disk
        with open(cache_path, "wb") as f:
            f.write(image_data)

        logger.info("independent_image_uploaded_base64",
            image_uuid=image_uuid,
            filename=cache_filename,
            size_bytes=len(image_data),
            original_filename=request.filename,
            company_id=company_id
        )

        return {
            "success": True,
            "image_id": image_uuid,
            "size_bytes": len(image_data),
            "format": extension[1:],  # Remove dot from extension
            "url": f"/api/v1/images/{image_uuid}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_image_base64_error", error=str(e), company_id=company_id)
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")
