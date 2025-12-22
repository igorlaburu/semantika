"""Image generation using Fal.ai FLUX.1 [schnell] model.

Generates photorealistic, conceptual images from prompts.
Images are cached permanently in /app/cache/images/.
"""

import os
import fal_client
from pathlib import Path
from typing import Optional, Dict, Any
import aiohttp
import asyncio
from utils.logger import get_logger

logger = get_logger("image_generator")

FAL_API_KEY = os.getenv("FAL_AI_API_KEY")
CACHE_DIR = Path("/app/cache/images")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Configure fal_client with API key
if FAL_API_KEY:
    os.environ["FAL_KEY"] = FAL_API_KEY


async def generate_image_from_prompt(
    context_unit_id: str,
    image_prompt: str,
    force_regenerate: bool = False
) -> Dict[str, Any]:
    """Generate photorealistic image from prompt using Fal.ai FLUX.1 [schnell].
    
    Model: fal-ai/flux/schnell
    - Cost: $0.003/image
    - Speed: 1-2 seconds
    - Quality: Excellent for photorealistic objects
    - Resolution: 1024x576 (landscape 16:9)
    
    Args:
        context_unit_id: UUID of context unit
        image_prompt: English prompt for image generation (from LLM)
        force_regenerate: Regenerate even if cached
        
    Returns:
        Dict with:
        - success: bool
        - image_path: str (local path to cached image)
        - image_url: str (API URL to retrieve image)
        - cached: bool (was it already generated?)
        - generation_time_ms: float
        - error: Optional[str]
    """
    start_time = asyncio.get_event_loop().time()
    
    # Check API key
    if not FAL_API_KEY:
        logger.error("fal_api_key_missing")
        return {
            "success": False,
            "image_path": None,
            "image_url": None,
            "cached": False,
            "generation_time_ms": 0,
            "error": "FAL_AI_API_KEY not configured"
        }
    
    # Check cache
    cached_path = CACHE_DIR / f"{context_unit_id}.jpg"
    if cached_path.exists() and not force_regenerate:
        logger.info("image_cache_hit", 
            context_unit_id=context_unit_id,
            cached_path=str(cached_path)
        )
        return {
            "success": True,
            "image_path": str(cached_path),
            "image_url": f"/api/v1/context-units/{context_unit_id}/image",
            "cached": True,
            "generation_time_ms": 0
        }
    
    try:
        logger.info("image_generation_start",
            context_unit_id=context_unit_id,
            prompt_preview=image_prompt[:100],
            model="fal-ai/flux/schnell"
        )
        
        # Call Fal.ai API (synchronous, so wrap in asyncio.to_thread)
        result = await asyncio.to_thread(
            fal_client.subscribe,
            "fal-ai/flux/schnell",
            arguments={
                "prompt": image_prompt,
                "image_size": "landscape_16_9",  # 1024x576 (perfect for banners)
                "num_inference_steps": 4,  # Optimal for schnell
                "num_images": 1,
                "enable_safety_checker": True
            },
            with_logs=False
        )
        
        if not result or "images" not in result or len(result["images"]) == 0:
            raise Exception("No images returned from Fal.ai")
        
        # Download generated image
        image_url = result["images"][0]["url"]
        
        logger.debug("image_downloading",
            context_unit_id=context_unit_id,
            fal_image_url=image_url
        )
        
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    cached_path.write_bytes(image_data)
                    
                    generation_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                    
                    logger.info("image_generation_success",
                        context_unit_id=context_unit_id,
                        image_size_kb=round(len(image_data) / 1024, 2),
                        generation_time_ms=round(generation_time_ms, 2),
                        cached_path=str(cached_path)
                    )
                    
                    return {
                        "success": True,
                        "image_path": str(cached_path),
                        "image_url": f"/api/v1/context-units/{context_unit_id}/image",
                        "cached": False,
                        "generation_time_ms": round(generation_time_ms, 2)
                    }
                else:
                    raise Exception(f"Failed to download image: HTTP {response.status}")
        
    except Exception as e:
        generation_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        
        logger.error("image_generation_failed",
            context_unit_id=context_unit_id,
            error=str(e),
            generation_time_ms=round(generation_time_ms, 2)
        )
        
        return {
            "success": False,
            "image_path": None,
            "image_url": None,
            "cached": False,
            "generation_time_ms": round(generation_time_ms, 2),
            "error": str(e)
        }
