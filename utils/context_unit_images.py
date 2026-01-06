"""Context unit image processing and caching."""

import os
import re
import base64
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
import imghdr
from PIL import Image, ImageFile

from utils.logger import get_logger

logger = get_logger("context_unit_images")

# Enable loading of truncated images
ImageFile.LOAD_TRUNCATED_IMAGES = True

class ContextUnitImageProcessor:
    """Process and cache images for context units."""
    
    # Supported image types
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    
    # Min/Max size constraints (pixels)
    MIN_WIDTH = 50
    MIN_HEIGHT = 50
    MAX_WIDTH = 4000
    MAX_HEIGHT = 4000
    
    # Max file size (bytes) - 5MB
    MAX_FILE_SIZE = 5 * 1024 * 1024
    
    # Max images per context unit
    MAX_IMAGES = 5
    
    @staticmethod
    def decode_base64_image(base64_data: str) -> bytes:
        """Decode base64 image data."""
        try:
            # Handle data URL format (data:image/jpeg;base64,...)
            if base64_data.startswith('data:image'):
                # Extract base64 part after comma
                base64_part = base64_data.split(',', 1)[1]
            else:
                base64_part = base64_data
            
            # Decode base64
            image_bytes = base64.b64decode(base64_part)
            
            # Check file size
            if len(image_bytes) > ContextUnitImageProcessor.MAX_FILE_SIZE:
                raise ValueError(f"Image too large: {len(image_bytes)} bytes (max: {ContextUnitImageProcessor.MAX_FILE_SIZE})")
            
            return image_bytes
            
        except Exception as e:
            raise ValueError(f"Invalid base64 image data: {str(e)}")
    
    @staticmethod
    def detect_image_format(image_data: bytes) -> Optional[str]:
        """Detect image format from binary data."""
        try:
            # Use imghdr for format detection
            with tempfile.NamedTemporaryFile() as tmp_file:
                tmp_file.write(image_data)
                tmp_file.flush()
                format_type = imghdr.what(tmp_file.name)
                
            if format_type:
                # Normalize extensions
                format_map = {
                    'jpeg': '.jpg',
                    'png': '.png', 
                    'gif': '.gif',
                    'webp': '.webp',
                    'bmp': '.bmp'
                }
                return format_map.get(format_type, f'.{format_type}')
            
            return None
            
        except Exception:
            return None
    
    @staticmethod
    def get_extension_from_filename(filename: str) -> Optional[str]:
        """Extract extension from filename."""
        if not filename:
            return None
            
        extension = Path(filename).suffix.lower()
        if extension in ContextUnitImageProcessor.IMAGE_EXTENSIONS:
            return extension
            
        return None
    
    @staticmethod
    def validate_image(image_data: bytes) -> bool:
        """Validate image dimensions and format."""
        try:
            with tempfile.NamedTemporaryFile() as tmp_file:
                tmp_file.write(image_data)
                tmp_file.flush()
                
                with Image.open(tmp_file.name) as img:
                    width, height = img.size
                    
                    # Check dimensions
                    if (width < ContextUnitImageProcessor.MIN_WIDTH or 
                        height < ContextUnitImageProcessor.MIN_HEIGHT):
                        logger.warn("image_too_small", width=width, height=height)
                        return False
                        
                    if (width > ContextUnitImageProcessor.MAX_WIDTH or 
                        height > ContextUnitImageProcessor.MAX_HEIGHT):
                        logger.warn("image_too_large", width=width, height=height)
                        return False
                    
                    return True
                    
        except Exception as e:
            logger.warn("image_validation_failed", error=str(e))
            return False
    
    @staticmethod
    async def save_context_unit_images(
        context_unit_id: str,
        images: List[Dict[str, str]]
    ) -> List[str]:
        """Save multiple images for a context unit.
        
        Args:
            context_unit_id: UUID of the context unit
            images: List of dicts with 'base64' and 'filename' keys
            
        Returns:
            List of cache file paths that were saved successfully
        """
        if not images:
            return []
        
        if len(images) > ContextUnitImageProcessor.MAX_IMAGES:
            logger.warn("too_many_images", 
                count=len(images), 
                max_allowed=ContextUnitImageProcessor.MAX_IMAGES,
                context_unit_id=context_unit_id
            )
            images = images[:ContextUnitImageProcessor.MAX_IMAGES]
        
        cache_dir = Path("/app/cache/images")
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        saved_paths = []
        
        for i, image_data in enumerate(images):
            try:
                # Validate input
                if not isinstance(image_data, dict):
                    logger.warn("invalid_image_format", index=i, context_unit_id=context_unit_id)
                    continue
                
                base64_data = image_data.get("base64")
                filename = image_data.get("filename", f"image_{i}")
                
                if not base64_data:
                    logger.warn("missing_base64_data", index=i, context_unit_id=context_unit_id)
                    continue
                
                # Decode image
                try:
                    image_bytes = ContextUnitImageProcessor.decode_base64_image(base64_data)
                except ValueError as e:
                    logger.warn("base64_decode_failed", index=i, context_unit_id=context_unit_id, error=str(e))
                    continue
                
                # Detect format
                extension = (ContextUnitImageProcessor.detect_image_format(image_bytes) or 
                           ContextUnitImageProcessor.get_extension_from_filename(filename) or 
                           ".jpg")
                
                if extension not in ContextUnitImageProcessor.IMAGE_EXTENSIONS:
                    logger.warn("unsupported_image_format", 
                        index=i, 
                        context_unit_id=context_unit_id,
                        extension=extension
                    )
                    continue
                
                # Validate image
                if not ContextUnitImageProcessor.validate_image(image_bytes):
                    logger.warn("image_validation_failed", index=i, context_unit_id=context_unit_id)
                    continue
                
                # Save to cache directory
                cache_filename = f"{context_unit_id}_{i}{extension}"
                cache_path = cache_dir / cache_filename
                
                with open(cache_path, "wb") as f:
                    f.write(image_bytes)
                
                saved_paths.append(str(cache_path))
                
                logger.info("image_saved", 
                    index=i,
                    context_unit_id=context_unit_id,
                    cache_path=str(cache_path),
                    size_bytes=len(image_bytes)
                )
                
            except Exception as e:
                logger.error("save_image_error", 
                    index=i, 
                    context_unit_id=context_unit_id,
                    error=str(e)
                )
                continue
        
        logger.info("context_unit_images_processed",
            context_unit_id=context_unit_id,
            total_images=len(images),
            saved_images=len(saved_paths),
            saved_paths=saved_paths
        )
        
        return saved_paths


def get_context_unit_image_path(context_unit_id: str, index: int = 0) -> Optional[Path]:
    """Get path to cached image for context unit.
    
    Args:
        context_unit_id: UUID of context unit
        index: Image index (0 = first image)
        
    Returns:
        Path to cached image file or None if not found
    """
    cache_dir = Path("/app/cache/images")
    
    # Try different extensions
    for ext in ContextUnitImageProcessor.IMAGE_EXTENSIONS:
        cache_path = cache_dir / f"{context_unit_id}_{index}{ext}"
        if cache_path.exists():
            return cache_path
    
    return None


def list_context_unit_images(context_unit_id: str) -> List[Path]:
    """List all cached images for a context unit.
    
    Args:
        context_unit_id: UUID of context unit
        
    Returns:
        List of paths to cached image files
    """
    cache_dir = Path("/app/cache/images")
    pattern = f"{context_unit_id}_*"
    
    # Find all matching files
    matching_files = []
    for file_path in cache_dir.glob(pattern):
        # Check if it's an image file
        if file_path.suffix.lower() in ContextUnitImageProcessor.IMAGE_EXTENSIONS:
            matching_files.append(file_path)
    
    # Sort by index (extract number after underscore)
    def get_index(path: Path) -> int:
        try:
            name_part = path.stem  # filename without extension
            index_part = name_part.split('_')[-1]  # part after last underscore
            return int(index_part)
        except (ValueError, IndexError):
            return 999  # Put malformed names at the end
    
    matching_files.sort(key=get_index)
    return matching_files