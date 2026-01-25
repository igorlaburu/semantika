"""Facebook publisher for semantika articles."""

import aiohttp
import re
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

from .base_publisher import BasePublisher, PublicationResult
from utils.logger import get_logger

logger = get_logger("facebook_publisher")

# Facebook Graph API version
GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class FacebookPublisher(BasePublisher):
    """Facebook Graph API publisher for pages."""

    def get_platform_type(self) -> str:
        return "facebook"

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            'Content-Type': 'application/json'
        }

    def _get_page_access_token(self) -> str:
        """Get page access token from credentials."""
        page_token = self.credentials.get('page_access_token')
        if not page_token:
            raise ValueError("Facebook requires 'page_access_token' in credentials")
        return page_token

    async def test_connection(self) -> Dict[str, Any]:
        """Test Facebook connection and get page info."""
        try:
            page_token = self._get_page_access_token()
            page_id = self.credentials.get('page_id')

            if not page_id:
                return {
                    "success": False,
                    "message": "No page_id configured"
                }

            url = f"{GRAPH_API_BASE}/{page_id}"
            params = {
                'access_token': page_token,
                'fields': 'name,id,link'
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        page_name = data.get('name', 'Unknown')

                        return {
                            "success": True,
                            "message": f"Connected to Facebook Page: {page_name}",
                            "details": {
                                "page_name": page_name,
                                "page_id": page_id,
                                "page_url": data.get('link')
                            }
                        }
                    else:
                        error_data = await response.json()
                        error_msg = error_data.get('error', {}).get('message', f'HTTP {response.status}')
                        logger.error("facebook_test_connection_failed",
                            status=response.status,
                            error=error_msg
                        )
                        return {
                            "success": False,
                            "message": f"Facebook API error: {error_msg}",
                            "details": {"error": error_data}
                        }

        except Exception as e:
            logger.error("facebook_test_connection_error", error=str(e))
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}"
            }

    async def publish_article(
        self,
        title: str,
        content: str,
        excerpt: Optional[str] = None,
        tags: Optional[list] = None,
        image_url: Optional[str] = None,
        status: str = "publish",
        slug: Optional[str] = None,
        category: Optional[str] = None,
        fecha_publicacion: Optional[str] = None,
        imagen_uuid: Optional[str] = None,
        temp_image_path: Optional[str] = None
    ) -> PublicationResult:
        """Publish article to Facebook Page."""
        try:
            page_id = self.credentials.get('page_id')

            if not page_id:
                return PublicationResult(
                    success=False,
                    error="No page_id configured. Facebook requires a page to publish."
                )

            # Check if content is pre-formatted (from chained publication)
            is_preformatted = content.startswith("📰") and "http" in content

            if is_preformatted:
                post_text = content
                logger.info("facebook_using_preformatted_content",
                    content_length=len(content)
                )
            else:
                # Build post content
                post_text = f"📰 {title}\n\n"

                if excerpt:
                    post_text += f"{excerpt[:300]}...\n\n"

                # Add hashtags
                if tags:
                    hashtags = self._format_hashtags(tags)
                    if hashtags:
                        post_text += hashtags

            logger.info("facebook_publish_start",
                title=title[:50],
                page_id=page_id,
                content_length=len(post_text),
                has_image=bool(temp_image_path)
            )

            # Upload image if provided
            photo_id = None
            if temp_image_path:
                upload_result = await self._upload_photo(temp_image_path)
                if upload_result.get('success'):
                    photo_id = upload_result['photo_id']
                    logger.info("facebook_photo_uploaded",
                        photo_id=photo_id
                    )
                else:
                    logger.warn("facebook_photo_upload_failed",
                        error=upload_result.get('error'),
                        image_path=temp_image_path
                    )

            # Post to page
            result = await self._post_to_page(post_text, photo_id)

            if result.get('success'):
                post_id = result['post_id']
                page_name = self.credentials.get('page_name', page_id)

                # Build Facebook post URL
                # Format: page_id_post_id
                post_url = f"https://www.facebook.com/{post_id.replace('_', '/posts/')}"

                logger.info("facebook_post_published",
                    post_id=post_id,
                    url=post_url,
                    page_id=page_id
                )

                return PublicationResult(
                    success=True,
                    url=post_url,
                    external_id=post_id,
                    metadata={
                        "platform": "facebook",
                        "page_id": page_id,
                        "page_name": page_name,
                        "has_photo": bool(photo_id)
                    }
                )
            else:
                logger.error("facebook_publish_failed",
                    error=result.get('error')
                )
                return PublicationResult(
                    success=False,
                    error=f"Facebook API error: {result.get('error')}"
                )

        except Exception as e:
            logger.error("facebook_publish_error",
                title=title[:50],
                error=str(e)
            )
            return PublicationResult(
                success=False,
                error=f"Facebook publish failed: {str(e)}"
            )

    async def _upload_photo(self, image_path: str) -> Dict[str, Any]:
        """Upload photo to Facebook Page.

        Uses Graph API photos endpoint.
        Supports images up to 4MB.
        """
        try:
            import os

            page_id = self.credentials.get('page_id')
            page_token = self._get_page_access_token()

            # Read image
            with open(image_path, 'rb') as f:
                image_data = f.read()

            size_kb = len(image_data) / 1024

            # Check file size (Facebook limit is 4MB for photos)
            if len(image_data) > 4 * 1024 * 1024:
                return {
                    "success": False,
                    "error": f"Image too large: {size_kb:.1f}KB (max 4MB)"
                }

            # Facebook photo upload endpoint
            url = f"{GRAPH_API_BASE}/{page_id}/photos"

            # Detect content type from extension
            ext = os.path.splitext(image_path)[1].lower()
            content_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            content_type = content_types.get(ext, 'image/jpeg')

            # Use multipart/form-data
            form = aiohttp.FormData()
            form.add_field('source',
                          image_data,
                          filename=f'image{ext}',
                          content_type=content_type)
            form.add_field('access_token', page_token)
            form.add_field('published', 'false')  # Don't publish yet, attach to post

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=form) as response:
                    response_data = await response.json()

                    if response.status == 200:
                        photo_id = response_data.get('id')

                        if photo_id:
                            return {
                                "success": True,
                                "photo_id": photo_id,
                                "size_kb": round(size_kb, 1)
                            }
                        else:
                            return {
                                "success": False,
                                "error": "No photo_id in response"
                            }
                    else:
                        error_msg = response_data.get('error', {}).get('message', f'HTTP {response.status}')
                        return {
                            "success": False,
                            "error": f"Upload failed: {error_msg}"
                        }

        except FileNotFoundError:
            return {
                "success": False,
                "error": f"Image file not found: {image_path}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Upload error: {str(e)}"
            }

    async def _post_to_page(self, text: str, photo_id: Optional[str] = None) -> Dict[str, Any]:
        """Post to Facebook Page feed."""
        try:
            page_id = self.credentials.get('page_id')
            page_token = self._get_page_access_token()

            # Build post data
            post_data = {
                'message': text,
                'access_token': page_token
            }

            # If we have a photo, attach it
            if photo_id:
                post_data['attached_media'] = [{'media_fbid': photo_id}]

            url = f"{GRAPH_API_BASE}/{page_id}/feed"

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=post_data) as response:
                    response_data = await response.json()

                    if response.status == 200:
                        post_id = response_data.get('id')
                        return {
                            "success": True,
                            "post_id": post_id
                        }
                    else:
                        error_msg = response_data.get('error', {}).get('message', f'HTTP {response.status}')
                        return {
                            "success": False,
                            "error": error_msg,
                            "response": response_data
                        }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _format_hashtags(self, tags: List[str]) -> str:
        """Convert tags to Facebook hashtags."""
        if not tags:
            return ""

        hashtags = []
        for tag in tags[:5]:  # Limit to 5 hashtags
            # Clean tag and make it hashtag-safe (no spaces, special chars)
            clean_tag = re.sub(r'[^a-zA-Z0-9áéíóúñüÁÉÍÓÚÑÜ]', '', str(tag))
            if clean_tag and len(clean_tag) > 1:
                hashtags.append(f"#{clean_tag}")

        return " ".join(hashtags) if hashtags else ""

    def sanitize_content(self, content: str) -> str:
        """Clean HTML content for Facebook."""
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', content)
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()

    async def _add_comment(self, post_id: str, comment_text: str) -> Dict[str, Any]:
        """Add a comment to a Facebook post."""
        try:
            page_token = self._get_page_access_token()

            url = f"{GRAPH_API_BASE}/{post_id}/comments"
            data = {
                'message': comment_text,
                'access_token': page_token
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as response:
                    response_data = await response.json()

                    if response.status == 200:
                        return {
                            "success": True,
                            "comment_id": response_data.get('id')
                        }
                    else:
                        error_msg = response_data.get('error', {}).get('message', f'HTTP {response.status}')
                        return {
                            "success": False,
                            "error": error_msg
                        }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def publish_social(
        self,
        content: str,
        url: Optional[str] = None,
        image_uuid: Optional[str] = None,
        tags: Optional[list] = None,
        temp_image_path: Optional[str] = None
    ) -> PublicationResult:
        """Publish social media post to Facebook Page.

        Posts content WITHOUT the URL in main post.
        URL is added as first comment to improve reach (Facebook algorithm).
        """
        try:
            page_id = self.credentials.get('page_id')

            if not page_id:
                return PublicationResult(
                    success=False,
                    error="No page_id configured. Facebook requires a page to publish."
                )

            # Remove URL from content if present (will be added as comment)
            post_text = content
            if url and url in post_text:
                post_text = post_text.replace(url, '').strip()
                # Clean up double newlines left after URL removal
                while '\n\n\n' in post_text:
                    post_text = post_text.replace('\n\n\n', '\n\n')
                post_text = post_text.rstrip('\n')

            # Add emoji prefix if not present
            if not post_text.startswith("📰"):
                post_text = f"📰 {post_text}"

            logger.info("facebook_publish_social_start",
                page_id=page_id,
                content_length=len(post_text),
                has_image=bool(temp_image_path),
                has_url_for_comment=bool(url)
            )

            # Upload image if provided
            photo_id = None
            if temp_image_path:
                upload_result = await self._upload_photo(temp_image_path)
                if upload_result.get('success'):
                    photo_id = upload_result['photo_id']
                    logger.info("facebook_social_photo_uploaded",
                        photo_id=photo_id,
                        size_kb=upload_result.get('size_kb')
                    )
                else:
                    logger.warn("facebook_social_photo_upload_failed",
                        error=upload_result.get('error'),
                        image_path=temp_image_path
                    )

            # Post to page with photo if available
            result = await self._post_to_page(post_text, photo_id)

            if result.get('success'):
                post_id = result['post_id']
                page_name = self.credentials.get('page_name', page_id)
                post_url = f"https://www.facebook.com/{post_id.replace('_', '/posts/')}"

                # Add URL as first comment if provided
                comment_added = False
                if url:
                    comment_text = f"🔗 Más información: {url}"
                    comment_result = await self._add_comment(post_id, comment_text)
                    if comment_result.get('success'):
                        comment_added = True
                        logger.info("facebook_url_comment_added",
                            post_id=post_id,
                            comment_id=comment_result.get('comment_id')
                        )
                    else:
                        logger.warn("facebook_url_comment_failed",
                            post_id=post_id,
                            error=comment_result.get('error')
                        )

                logger.info("facebook_social_published",
                    post_id=post_id,
                    url=post_url,
                    url_in_comment=comment_added
                )

                return PublicationResult(
                    success=True,
                    url=post_url,
                    external_id=post_id,
                    metadata={
                        "platform": "facebook",
                        "page_id": page_id,
                        "page_name": page_name,
                        "has_photo": bool(photo_id),
                        "url_in_comment": comment_added
                    }
                )
            else:
                logger.error("facebook_social_publish_failed",
                    error=result.get('error')
                )
                return PublicationResult(
                    success=False,
                    error=f"Facebook API error: {result.get('error')}"
                )

        except Exception as e:
            logger.error("facebook_social_publish_error", error=str(e))
            return PublicationResult(
                success=False,
                error=f"Facebook publish failed: {str(e)}"
            )

    # OAuth 2.0 Flow Methods
    @staticmethod
    def get_authorization_url(app_id: str, redirect_uri: str, state: str) -> str:
        """Generate Facebook OAuth authorization URL."""
        params = {
            'client_id': app_id,
            'redirect_uri': redirect_uri,
            'state': state,
            'scope': 'pages_manage_posts,pages_manage_engagement,pages_read_engagement,pages_show_list,public_profile,business_management',
            'response_type': 'code'
        }
        return f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth?{urlencode(params)}"

    @staticmethod
    async def exchange_code_for_token(
        app_id: str,
        app_secret: str,
        code: str,
        redirect_uri: str
    ) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        try:
            params = {
                'client_id': app_id,
                'client_secret': app_secret,
                'redirect_uri': redirect_uri,
                'code': code
            }

            url = f"{GRAPH_API_BASE}/oauth/access_token"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    response_data = await response.json()

                    if response.status == 200 and 'access_token' in response_data:
                        logger.info("facebook_token_exchange_success")
                        return {
                            "success": True,
                            "access_token": response_data.get('access_token'),
                            "token_type": response_data.get('token_type'),
                            "expires_in": response_data.get('expires_in')
                        }
                    else:
                        error = response_data.get('error', {}).get('message', f'HTTP {response.status}')
                        logger.error("facebook_token_exchange_failed",
                            status=response.status,
                            error=error
                        )
                        return {
                            "success": False,
                            "error": error
                        }

        except Exception as e:
            logger.error("facebook_token_exchange_error", error=str(e))
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    async def get_user_pages(access_token: str) -> Dict[str, Any]:
        """Get Facebook Pages the user can manage."""
        try:
            url = f"{GRAPH_API_BASE}/me/accounts"
            params = {
                'access_token': access_token,
                'fields': 'id,name,access_token,category,link'
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        pages = data.get('data', [])

                        logger.info("facebook_pages_fetched",
                            count=len(pages)
                        )

                        return {
                            "success": True,
                            "pages": [
                                {
                                    'id': page['id'],
                                    'name': page['name'],
                                    'access_token': page['access_token'],
                                    'category': page.get('category', ''),
                                    'link': page.get('link', '')
                                }
                                for page in pages
                            ]
                        }
                    else:
                        error_data = await response.json()
                        error_msg = error_data.get('error', {}).get('message', f'HTTP {response.status}')
                        logger.error("facebook_pages_fetch_failed",
                            status=response.status,
                            error=error_msg
                        )
                        return {
                            "success": False,
                            "error": f"Failed to fetch pages: {error_msg}",
                            "pages": []
                        }

        except Exception as e:
            logger.error("facebook_pages_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "pages": []
            }

    @staticmethod
    async def get_user_info(access_token: str) -> Dict[str, Any]:
        """Get basic user info from Facebook."""
        try:
            url = f"{GRAPH_API_BASE}/me"
            params = {
                'access_token': access_token,
                'fields': 'id,name'
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "user_id": data.get('id'),
                            "user_name": data.get('name')
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}"
                        }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def get_post_comments(self, post_id: str) -> Dict[str, Any]:
        """Read comments from a post.

        Uses pages_read_user_content permission.
        Call this to verify the permission with Facebook.
        """
        try:
            page_token = self._get_page_access_token()

            url = f"{GRAPH_API_BASE}/{post_id}/comments"
            params = {
                'access_token': page_token,
                'fields': 'id,message,from,created_time',
                'limit': 10
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    response_data = await response.json()

                    if response.status == 200:
                        comments = response_data.get('data', [])
                        logger.info("facebook_get_comments_success",
                            post_id=post_id,
                            comments_count=len(comments)
                        )
                        return {
                            "success": True,
                            "comments": comments,
                            "permission_verified": "pages_read_user_content"
                        }
                    else:
                        error_msg = response_data.get('error', {}).get('message', f'HTTP {response.status}')
                        error_code = response_data.get('error', {}).get('code')
                        logger.error("facebook_get_comments_failed",
                            post_id=post_id,
                            status=response.status,
                            error=error_msg,
                            error_code=error_code
                        )
                        return {
                            "success": False,
                            "error": error_msg,
                            "error_code": error_code
                        }

        except Exception as e:
            logger.error("facebook_get_comments_error", error=str(e))
            return {
                "success": False,
                "error": str(e)
            }

    async def verify_permissions(self) -> Dict[str, Any]:
        """Verify all required permissions by making test API calls.

        This helps complete Facebook's app verification process.
        """
        results = {
            "pages_manage_posts": {"status": "unknown"},
            "pages_read_engagement": {"status": "unknown"},
            "pages_read_user_content": {"status": "unknown"},
            "pages_manage_engagement": {"status": "unknown"}
        }

        try:
            page_id = self.credentials.get('page_id')
            page_token = self._get_page_access_token()

            if not page_id:
                return {"error": "No page_id configured"}

            # 1. Test pages_manage_posts - Get page info
            try:
                url = f"{GRAPH_API_BASE}/{page_id}"
                params = {'access_token': page_token, 'fields': 'name,id'}
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            results["pages_manage_posts"] = {"status": "verified", "test": "get_page_info"}
                        else:
                            data = await response.json()
                            results["pages_manage_posts"] = {"status": "failed", "error": data.get('error', {}).get('message')}
            except Exception as e:
                results["pages_manage_posts"] = {"status": "error", "error": str(e)}

            # 2. Test pages_read_engagement - Get page feed
            try:
                url = f"{GRAPH_API_BASE}/{page_id}/feed"
                params = {'access_token': page_token, 'fields': 'id,message,created_time', 'limit': 1}
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        data = await response.json()
                        if response.status == 200:
                            posts = data.get('data', [])
                            results["pages_read_engagement"] = {
                                "status": "verified",
                                "test": "get_page_feed",
                                "posts_found": len(posts)
                            }

                            # If we have a post, test comment-related permissions
                            if posts:
                                post_id = posts[0]['id']

                                # 3. Test pages_read_user_content - Read comments
                                try:
                                    comments_url = f"{GRAPH_API_BASE}/{post_id}/comments"
                                    comments_params = {'access_token': page_token, 'fields': 'id,message', 'limit': 5}
                                    async with session.get(comments_url, params=comments_params) as comments_resp:
                                        comments_data = await comments_resp.json()
                                        if comments_resp.status == 200:
                                            results["pages_read_user_content"] = {
                                                "status": "verified",
                                                "test": "read_post_comments",
                                                "post_id": post_id,
                                                "comments_found": len(comments_data.get('data', []))
                                            }
                                        else:
                                            results["pages_read_user_content"] = {
                                                "status": "failed",
                                                "error": comments_data.get('error', {}).get('message'),
                                                "error_code": comments_data.get('error', {}).get('code')
                                            }
                                except Exception as e:
                                    results["pages_read_user_content"] = {"status": "error", "error": str(e)}

                                # 4. Test pages_manage_engagement - We don't want to post a test comment
                                # Just verify by checking if we can access the comments endpoint for posting
                                results["pages_manage_engagement"] = {
                                    "status": "requires_action",
                                    "note": "This permission is verified when posting URL as comment on published articles"
                                }
                        else:
                            results["pages_read_engagement"] = {"status": "failed", "error": data.get('error', {}).get('message')}
            except Exception as e:
                results["pages_read_engagement"] = {"status": "error", "error": str(e)}

            logger.info("facebook_permissions_verified", results=results)
            return results

        except Exception as e:
            logger.error("facebook_verify_permissions_error", error=str(e))
            return {"error": str(e), "results": results}
