"""Email image extraction and caching for semantika."""

import os
import re
import base64
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from email.message import Message
import aiohttp
import ssl
from urllib.parse import urljoin

from utils.logger import get_logger
from utils.image_extractor import is_valid_image_url

logger = get_logger("email_image_processor")

class EmailImageProcessor:
    """Process and cache images from emails."""
    
    # Supported image types
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    
    # Min size to avoid signatures/icons (pixels)
    MIN_WIDTH = 200
    MIN_HEIGHT = 150
    
    # Max images to process per email
    MAX_IMAGES = 3
    
    def __init__(self, cache_dir: str = "/app/cache/email_images"):
        """Initialize with cache directory."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    async def process_email_images(
        self, 
        message: Message, 
        context_unit_id: str,
        source_metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract and cache images from email.
        
        Returns:
            List of cached image metadata up to MAX_IMAGES
        """
        cached_images = []
        
        # 1. Extract inline images (data: URIs in HTML)
        inline_images = self._extract_inline_images(message)
        
        # 2. Extract image attachments
        attachment_images = self._extract_attachment_images(message)
        
        # 3. Combine and prioritize (attachments first, then inline)
        all_images = attachment_images + inline_images
        
        # 4. Process and cache up to MAX_IMAGES
        for i, image_data in enumerate(all_images[:self.MAX_IMAGES]):
            try:
                cached_path = await self._cache_image(
                    image_data, 
                    context_unit_id, 
                    f"img_{i+1}"
                )
                
                if cached_path:
                    cached_images.append({
                        "cache_path": str(cached_path),
                        "source": image_data["source"],
                        "original_filename": image_data.get("filename"),
                        "content_type": image_data.get("content_type"),
                        "size_bytes": image_data.get("size_bytes")
                    })
                    
            except Exception as e:
                logger.error("image_cache_error", 
                    context_unit_id=context_unit_id,
                    image_index=i,
                    error=str(e)
                )
        
        logger.info("email_images_processed",
            context_unit_id=context_unit_id,
            total_found=len(all_images),
            cached_count=len(cached_images)
        )
        
        return cached_images
    
    def _extract_inline_images(self, message: Message) -> List[Dict[str, Any]]:
        """Extract data: URIs from HTML email body."""
        inline_images = []
        
        try:
            # Get HTML body
            html_body = None
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/html":
                        html_body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                if message.get_content_type() == "text/html":
                    html_body = message.get_payload(decode=True).decode("utf-8", errors="ignore")
            
            if not html_body:
                return []
            
            # Find data: URIs - src="data:image/jpeg;base64,..."
            data_uri_pattern = r'src=["\']data:image/([^;]+);base64,([^"\']+)["\']'
            matches = re.finditer(data_uri_pattern, html_body, re.IGNORECASE)
            
            for match in matches:
                image_format = match.group(1).lower()  # jpeg, png, etc.
                base64_data = match.group(2)
                
                if image_format in ["jpeg", "jpg", "png", "webp", "gif"]:
                    try:
                        image_bytes = base64.b64decode(base64_data)
                        
                        # Basic size filter (decode would be expensive)
                        if len(image_bytes) > 5000:  # > 5KB likely not icon
                            inline_images.append({
                                "source": "inline_html",
                                "content_type": f"image/{image_format}",
                                "data": image_bytes,
                                "size_bytes": len(image_bytes),
                                "filename": f"inline_image.{image_format}"
                            })
                            
                    except Exception as e:
                        logger.debug("inline_image_decode_error", error=str(e))
                        continue
            
            logger.debug("inline_images_extracted", count=len(inline_images))
            return inline_images
            
        except Exception as e:
            logger.error("inline_image_extraction_error", error=str(e))
            return []
    
    def _extract_attachment_images(self, message: Message) -> List[Dict[str, Any]]:
        """Extract image attachments."""
        attachment_images = []
        
        try:
            if not message.is_multipart():
                return []
            
            for part in message.walk():
                # Skip multipart containers
                if part.get_content_maintype() == "multipart":
                    continue
                
                # Must be attachment
                disposition = part.get("Content-Disposition", "")
                if "attachment" not in disposition:
                    continue
                
                filename = part.get_filename()
                if not filename:
                    continue
                
                # Must be image
                content_type = part.get_content_type() or ""
                extension = os.path.splitext(filename)[1].lower()
                
                if not (content_type.startswith("image/") or extension in self.IMAGE_EXTENSIONS):
                    continue
                
                try:
                    data = part.get_payload(decode=True)
                    
                    # Size filter - must be substantial (not icon/signature)
                    if len(data) > 10000:  # > 10KB
                        attachment_images.append({
                            "source": "attachment",
                            "filename": filename,
                            "content_type": content_type,
                            "data": data,
                            "size_bytes": len(data)
                        })
                        
                except Exception as e:
                    logger.debug("attachment_decode_error", filename=filename, error=str(e))
                    continue
            
            logger.debug("attachment_images_extracted", count=len(attachment_images))
            return attachment_images
            
        except Exception as e:
            logger.error("attachment_image_extraction_error", error=str(e))
            return []
    
    async def _cache_image(
        self, 
        image_data: Dict[str, Any], 
        context_unit_id: str, 
        suffix: str
    ) -> Optional[Path]:
        """Cache image to disk."""
        try:
            # Determine file extension
            if image_data.get("filename"):
                ext = os.path.splitext(image_data["filename"])[1].lower()
            elif image_data.get("content_type"):
                type_map = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png", 
                    "image/webp": ".webp",
                    "image/gif": ".gif"
                }
                ext = type_map.get(image_data["content_type"], ".jpg")
            else:
                ext = ".jpg"
            
            # Create cache file path
            cache_filename = f"{context_unit_id}_{suffix}{ext}"
            cache_path = self.cache_dir / cache_filename
            
            # Write to disk
            cache_path.write_bytes(image_data["data"])
            
            logger.debug("image_cached",
                cache_path=str(cache_path),
                size_bytes=len(image_data["data"]),
                source=image_data["source"]
            )
            
            return cache_path
            
        except Exception as e:
            logger.error("image_cache_write_error", error=str(e))
            return None