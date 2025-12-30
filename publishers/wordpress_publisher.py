"""WordPress publisher for semantika articles."""

import aiohttp
import asyncio
from typing import Dict, Any, Optional
import base64
import json
from urllib.parse import urljoin, urlparse

from .base_publisher import BasePublisher, PublicationResult
from utils.logger import get_logger

logger = get_logger("wordpress_publisher")


class WordPressPublisher(BasePublisher):
    """WordPress REST API publisher."""
    
    def get_platform_type(self) -> str:
        return "wordpress"
    
    def _get_api_url(self, endpoint: str) -> str:
        """Build WordPress REST API URL."""
        base = self.base_url.rstrip('/')
        return f"{base}/wp-json/wp/v2/{endpoint}"
    
    def _get_auth_header(self) -> str:
        """Get authentication header for WordPress (API Key or App Password)."""
        api_key = self.credentials.get('api_key')
        username = self.credentials.get('username')
        app_password = self.credentials.get('app_password')
        
        if api_key:
            # Use API Key authentication
            return f"Bearer {api_key}"
        elif username and app_password:
            # Use Application Password authentication
            credentials = f"{username}:{app_password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            return f"Basic {encoded_credentials}"
        else:
            raise ValueError("WordPress requires either 'api_key' OR ('username' + 'app_password') in credentials")
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test WordPress connection and authentication."""
        try:
            headers = {
                'Authorization': self._get_auth_header(),
                'Content-Type': 'application/json'
            }
            
            # Test by getting current user
            async with aiohttp.ClientSession() as session:
                url = self._get_api_url('users/me')
                
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        user_data = await response.json()
                        auth_method = "API Key" if self.credentials.get('api_key') else "Application Password"
                        return {
                            "success": True,
                            "message": f"Connected as {user_data.get('name', 'Unknown')} using {auth_method}",
                            "details": {
                                "user_id": user_data.get('id'),
                                "username": user_data.get('username'),
                                "capabilities": user_data.get('capabilities', {}),
                                "auth_method": auth_method
                            }
                        }
                    elif response.status == 401:
                        auth_method = "API key" if self.credentials.get('api_key') else "username/app password"
                        return {
                            "success": False,
                            "message": f"Authentication failed. Check your WordPress {auth_method}."
                        }
                    elif response.status == 403:
                        return {
                            "success": False,
                            "message": "Access forbidden. User may not have sufficient permissions."
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "message": f"Connection failed (HTTP {response.status}): {error_text[:200]}"
                        }
                        
        except aiohttp.ClientError as e:
            return {
                "success": False,
                "message": f"Network error: {str(e)}"
            }
        except Exception as e:
            logger.error("wordpress_test_connection_error", error=str(e))
            return {
                "success": False,
                "message": f"Unexpected error: {str(e)}"
            }
    
    async def _upload_featured_image(
        self, 
        session: aiohttp.ClientSession, 
        image_url: str,
        headers: Dict[str, str]
    ) -> Optional[int]:
        """Upload image to WordPress media library."""
        try:
            # Download image from semantika
            async with session.get(image_url) as img_response:
                if img_response.status != 200:
                    logger.warn("image_download_failed", 
                        image_url=image_url,
                        status=img_response.status
                    )
                    return None
                
                image_data = await img_response.read()
                content_type = img_response.headers.get('content-type', 'image/jpeg')
            
            # Extract filename from URL and ensure .jpg extension
            parsed_url = urlparse(image_url)
            filename = parsed_url.path.split('/')[-1] or 'article-image'
            if not filename.endswith('.jpg') and not filename.endswith('.jpeg'):
                filename = f"{filename}.jpg"
            
            # Upload to WordPress
            upload_headers = headers.copy()
            upload_headers['Content-Type'] = content_type
            upload_headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            upload_url = self._get_api_url('media')
            
            async with session.post(
                upload_url, 
                data=image_data, 
                headers=upload_headers
            ) as upload_response:
                if upload_response.status == 201:
                    media_data = await upload_response.json()
                    media_id = media_data.get('id')
                    
                    logger.info("wordpress_image_uploaded",
                        media_id=media_id,
                        filename=filename,
                        url=media_data.get('source_url')
                    )
                    
                    return media_id
                else:
                    error_text = await upload_response.text()
                    logger.warn("wordpress_image_upload_failed",
                        status=upload_response.status,
                        error=error_text[:200]
                    )
                    return None
                    
        except Exception as e:
            logger.error("wordpress_image_upload_error", error=str(e))
            return None
    
    async def publish_article(
        self,
        title: str,
        content: str,
        excerpt: Optional[str] = None,
        tags: Optional[list] = None,
        image_url: Optional[str] = None,
        status: str = "publish"
    ) -> PublicationResult:
        """Publish article to WordPress."""
        
        try:
            headers = {
                'Authorization': self._get_auth_header(),
                'Content-Type': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                featured_media_id = None
                
                # Upload featured image if provided
                if image_url:
                    featured_media_id = await self._upload_featured_image(
                        session, image_url, headers
                    )
                
                # Handle tags - get or create tag IDs
                tag_ids = []
                if tags:
                    tag_ids = await self._get_or_create_tags(session, tags, headers)
                
                # Prepare post data
                post_data = {
                    "title": title,
                    "content": self.sanitize_content(content),
                    "status": status,  # "draft" or "publish"
                }
                
                if excerpt:
                    post_data["excerpt"] = excerpt
                
                if featured_media_id:
                    post_data["featured_media"] = featured_media_id
                
                if tag_ids:
                    post_data["tags"] = tag_ids
                
                # Create post
                posts_url = self._get_api_url('posts')
                
                async with session.post(
                    posts_url,
                    json=post_data,
                    headers=headers
                ) as response:
                    
                    if response.status == 201:
                        post_data_response = await response.json()
                        post_id = post_data_response.get('id')
                        post_url = post_data_response.get('link')
                        
                        logger.info("wordpress_article_published",
                            post_id=post_id,
                            title=title[:50],
                            url=post_url,
                            status=status
                        )
                        
                        return PublicationResult(
                            success=True,
                            url=post_url,
                            external_id=str(post_id),
                            metadata={
                                "platform": "wordpress",
                                "post_id": post_id,
                                "featured_media_id": featured_media_id,
                                "tag_count": len(tag_ids) if tag_ids else 0
                            }
                        )
                    
                    else:
                        error_text = await response.text()
                        logger.error("wordpress_publish_failed",
                            status=response.status,
                            title=title[:50],
                            error=error_text[:200]
                        )
                        
                        return PublicationResult(
                            success=False,
                            error=f"WordPress API error (HTTP {response.status}): {error_text[:200]}"
                        )
                        
        except Exception as e:
            logger.error("wordpress_publish_error",
                title=title[:50],
                error=str(e)
            )
            
            return PublicationResult(
                success=False,
                error=f"Publication error: {str(e)}"
            )
    
    async def _get_or_create_tags(
        self,
        session: aiohttp.ClientSession,
        tags: list,
        headers: Dict[str, str]
    ) -> list:
        """Get existing tag IDs or create new tags."""
        tag_ids = []
        
        for tag_name in tags:
            # Search for existing tag
            search_url = self._get_api_url('tags')
            search_params = {'search': tag_name}
            
            try:
                async with session.get(
                    search_url,
                    params=search_params,
                    headers=headers
                ) as response:
                    
                    if response.status == 200:
                        existing_tags = await response.json()
                        
                        # Look for exact match
                        tag_id = None
                        for existing_tag in existing_tags:
                            if existing_tag.get('name', '').lower() == tag_name.lower():
                                tag_id = existing_tag.get('id')
                                break
                        
                        # Create tag if not found
                        if tag_id is None:
                            create_data = {'name': tag_name}
                            
                            async with session.post(
                                search_url,
                                json=create_data,
                                headers=headers
                            ) as create_response:
                                
                                if create_response.status == 201:
                                    new_tag = await create_response.json()
                                    tag_id = new_tag.get('id')
                                    
                                    logger.debug("wordpress_tag_created",
                                        tag_name=tag_name,
                                        tag_id=tag_id
                                    )
                        
                        if tag_id:
                            tag_ids.append(tag_id)
                            
            except Exception as e:
                logger.warn("wordpress_tag_processing_failed",
                    tag_name=tag_name,
                    error=str(e)
                )
                continue
        
        return tag_ids
    
    def sanitize_content(self, content: str) -> str:
        """Clean content for WordPress."""
        # WordPress accepts HTML, but we might want to do some cleanup
        # For now, return as-is since our content is already HTML
        return content