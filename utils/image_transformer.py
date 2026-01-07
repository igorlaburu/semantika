"""Image transformation pipeline for publication.

Applies brand consistency and uniqueness transformations to all images
before publishing to external platforms.
"""

import io
import os
import hashlib
import tempfile
from typing import Tuple, Optional
from PIL import Image, ImageEnhance, ImageFilter
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("image_transformer")


class ImageTransformer:
    """Transforms images for publication with brand consistency and uniqueness."""
    
    # Brand consistency settings
    BRAND_SETTINGS = {
        "temperature_shift": 100,      # +100K warmer
        "saturation_boost": 1.05,      # +5% more vibrant
        "contrast_boost": 1.02,        # +2% more defined
        "brightness_adjust": 1.01,     # +1% brighter
        "sharpening": True,            # Subtle web sharpening
    }
    
    # Platform-specific output settings (extensible for future)
    PLATFORM_SETTINGS = {
        "wordpress": {
            "format": "webp",
            "quality": 90,
            "max_width": 1200,
            "max_height": 630,
        },
        "default": {
            "format": "webp", 
            "quality": 90,
            "max_width": 1200,
            "max_height": 630,
        }
    }
    
    @staticmethod
    def transform_for_publication(
        image_data: bytes,
        platform: str = "wordpress", 
        image_uuid: str = None
    ) -> str:
        """
        Transform image for publication with brand consistency and uniqueness.
        
        Args:
            image_data: Raw image bytes
            platform: Target platform ("wordpress", "twitter", etc.)
            image_uuid: Image UUID for deterministic transformations
            
        Returns:
            Path to temporary file containing transformed image.
            Caller is responsible for cleaning up the temp file.
        """
        try:
            logger.info("image_transformation_start",
                platform=platform,
                image_uuid=image_uuid,
                input_size_kb=round(len(image_data) / 1024, 2)
            )
            
            # Load image
            with Image.open(io.BytesIO(image_data)) as img:
                # Convert to RGB if necessary (handles RGBA, P, etc.)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Get platform settings
                settings = ImageTransformer.PLATFORM_SETTINGS.get(
                    platform, 
                    ImageTransformer.PLATFORM_SETTINGS["default"]
                )
                
                # Apply transformations
                transformed_img = ImageTransformer._apply_brand_transformations(img, image_uuid)
                transformed_img = ImageTransformer._apply_uniqueness_transformations(transformed_img, image_uuid)
                transformed_img = ImageTransformer._resize_for_platform(transformed_img, settings)
                
                # Create temporary file
                file_extension = f".{settings['format'].lower()}"
                temp_file = tempfile.NamedTemporaryFile(
                    suffix=file_extension,
                    delete=False  # Don't auto-delete, caller will handle cleanup
                )
                temp_path = temp_file.name
                temp_file.close()  # Close handle so PIL can write to it
                
                # Save to temporary file
                save_kwargs = {
                    "format": settings["format"].upper(),
                    "quality": settings["quality"],
                    "optimize": True,
                }
                
                # WebP specific optimizations
                if settings["format"].lower() == "webp":
                    save_kwargs["method"] = 6  # Best compression method
                    save_kwargs["lossless"] = False
                
                transformed_img.save(temp_path, **save_kwargs)
                
                # Get file size for logging
                temp_size_kb = round(os.path.getsize(temp_path) / 1024, 2)
                
                logger.info("image_transformation_success",
                    platform=platform,
                    image_uuid=image_uuid,
                    input_size_kb=round(len(image_data) / 1024, 2),
                    output_size_kb=temp_size_kb,
                    compression_ratio=round(len(image_data) / (temp_size_kb * 1024), 2) if temp_size_kb > 0 else 0,
                    output_format=settings["format"],
                    temp_file_path=temp_path
                )
                
                return temp_path
                
        except Exception as e:
            logger.error("image_transformation_failed",
                platform=platform,
                image_uuid=image_uuid,
                error=str(e)
            )
            # Fallback: create temporary file with original image
            try:
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                temp_file.write(image_data)
                temp_file.close()
                return temp_file.name
            except:
                # Last resort: return None to indicate failure
                return None
    
    @staticmethod
    def _apply_brand_transformations(img: Image.Image, image_uuid: str = None) -> Image.Image:
        """Apply brand consistency transformations."""
        settings = ImageTransformer.BRAND_SETTINGS
        
        # Brightness adjustment
        if settings["brightness_adjust"] != 1.0:
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(settings["brightness_adjust"])
        
        # Contrast boost
        if settings["contrast_boost"] != 1.0:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(settings["contrast_boost"])
        
        # Saturation boost
        if settings["saturation_boost"] != 1.0:
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(settings["saturation_boost"])
        
        # Subtle sharpening for web
        if settings["sharpening"]:
            img = img.filter(ImageFilter.UnsharpMask(radius=0.5, percent=50, threshold=3))
        
        return img
    
    @staticmethod
    def _apply_uniqueness_transformations(img: Image.Image, image_uuid: str = None) -> Image.Image:
        """Apply subtle transformations to make image unique (for SEO)."""
        if not image_uuid:
            return img
        
        # Use UUID hash to generate deterministic but unique variations
        hash_value = int(hashlib.md5(image_uuid.encode()).hexdigest()[:8], 16)
        
        # Micro-rotation: ±0.2 degrees (imperceptible)
        rotation_angle = ((hash_value % 40) / 100.0) - 0.2  # Range: -0.2 to +0.2
        if abs(rotation_angle) > 0.05:  # Only apply if significant enough
            img = img.rotate(rotation_angle, expand=False, fillcolor=(255, 255, 255))
        
        # Subtle brightness variation: ±1%
        brightness_variation = 0.99 + ((hash_value % 20) / 1000.0)  # Range: 0.99 to 1.01
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(brightness_variation)
        
        return img
    
    @staticmethod
    def _resize_for_platform(img: Image.Image, settings: dict) -> Image.Image:
        """Resize image according to platform requirements."""
        max_width = settings.get("max_width", 1200)
        max_height = settings.get("max_height", 630)
        
        # Get current dimensions
        width, height = img.size
        
        # Calculate if resize is needed
        if width <= max_width and height <= max_height:
            return img  # No resize needed
        
        # Calculate aspect ratio preserving resize
        width_ratio = max_width / width
        height_ratio = max_height / height
        resize_ratio = min(width_ratio, height_ratio)
        
        new_width = int(width * resize_ratio)
        new_height = int(height * resize_ratio)
        
        # High quality resize
        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    @staticmethod
    def get_cache_path(image_uuid: str) -> Optional[Path]:
        """Get the cache path for an image UUID."""
        cache_dir = Path("/app/cache/images")
        
        # Try different extensions
        for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
            cache_path = cache_dir / f"{image_uuid}{ext}"
            if cache_path.exists():
                return cache_path
        
        return None
    
    @staticmethod
    def read_cached_image(image_uuid: str) -> Optional[bytes]:
        """Read image from cache."""
        cache_path = ImageTransformer.get_cache_path(image_uuid)
        
        if cache_path and cache_path.exists():
            try:
                return cache_path.read_bytes()
            except Exception as e:
                logger.error("cache_read_failed",
                    image_uuid=image_uuid,
                    cache_path=str(cache_path),
                    error=str(e)
                )
        
        return None