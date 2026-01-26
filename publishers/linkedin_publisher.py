"""LinkedIn publisher for semantika articles."""

import aiohttp
import re
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

from .base_publisher import BasePublisher, PublicationResult
from utils.logger import get_logger

logger = get_logger("linkedin_publisher")


class LinkedInPublisher(BasePublisher):
    """LinkedIn API publisher for company pages."""

    def get_platform_type(self) -> str:
        return "linkedin"

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        access_token = self.credentials.get('access_token')
        if not access_token:
            raise ValueError("LinkedIn requires 'access_token' in credentials")

        return {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'X-Restli-Protocol-Version': '2.0.0',
            'LinkedIn-Version': '202401'
        }

    async def test_connection(self) -> Dict[str, Any]:
        """Test LinkedIn connection and get user profile."""
        try:
            headers = self._get_headers()

            async with aiohttp.ClientSession() as session:
                # Get user profile to verify token
                async with session.get(
                    'https://api.linkedin.com/v2/userinfo',
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        name = data.get('name', 'Unknown')

                        # Check if we have organization access
                        organization_id = self.credentials.get('organization_id')
                        org_name = self.credentials.get('organization_name', 'Unknown')

                        return {
                            "success": True,
                            "message": f"Connected to LinkedIn as {name}" + (f" (Page: {org_name})" if organization_id else ""),
                            "details": {
                                "user_name": name,
                                "organization_id": organization_id,
                                "organization_name": org_name
                            }
                        }
                    else:
                        error_text = await response.text()
                        logger.error("linkedin_test_connection_failed",
                            status=response.status,
                            error=error_text
                        )
                        return {
                            "success": False,
                            "message": f"LinkedIn API returned status {response.status}",
                            "details": {"error": error_text}
                        }

        except Exception as e:
            logger.error("linkedin_test_connection_error", error=str(e))
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
        """Publish article to LinkedIn as a post."""
        try:
            # Determine author URN (organization or personal profile)
            post_as = self.credentials.get('post_as', 'organization')

            if post_as == 'member':
                # Personal profile
                member_urn = self.credentials.get('member_urn')
                if not member_urn:
                    return PublicationResult(
                        success=False,
                        error="No member_urn configured for personal profile posting."
                    )
                author_urn = member_urn
                logger.info("linkedin_posting_as_member", member_urn=member_urn)
            else:
                # Organization (company page)
                organization_id = self.credentials.get('organization_id')
                if not organization_id:
                    return PublicationResult(
                        success=False,
                        error="No organization_id configured. LinkedIn requires a company page to publish."
                    )
                author_urn = f"urn:li:organization:{organization_id}"
                logger.info("linkedin_posting_as_organization", organization_id=organization_id)

            # Check if content is pre-formatted (from chained publication)
            is_preformatted = content.startswith("📰") and "http" in content

            if is_preformatted:
                post_text = content
                logger.info("linkedin_using_preformatted_content",
                    content_length=len(content)
                )
            else:
                # Build post content
                post_text = f"📰 {title}\n\n"

                if excerpt:
                    post_text += f"{excerpt[:200]}...\n\n"

                # Add hashtags
                if tags:
                    hashtags = self._format_hashtags(tags)
                    if hashtags:
                        post_text += hashtags

            # Build the post payload for LinkedIn API
            post_data = {
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {
                            "text": post_text
                        },
                        "shareMediaCategory": "NONE"
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                }
            }

            headers = self._get_headers()

            logger.info("linkedin_publish_start",
                title=title[:50],
                organization_id=organization_id,
                content_length=len(post_text)
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.linkedin.com/v2/ugcPosts',
                    headers=headers,
                    json=post_data
                ) as response:
                    response_data = await response.json() if response.content_length else {}

                    if response.status == 201:
                        post_id = response_data.get('id', '')
                        # Extract the activity ID for the URL
                        # Format: urn:li:share:1234567890
                        activity_id = post_id.split(':')[-1] if post_id else ''

                        post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else None

                        logger.info("linkedin_post_published",
                            post_id=post_id,
                            url=post_url,
                            organization_id=organization_id
                        )

                        return PublicationResult(
                            success=True,
                            url=post_url,
                            external_id=post_id,
                            metadata={
                                "platform": "linkedin",
                                "organization_id": organization_id,
                                "post_type": "share"
                            }
                        )
                    else:
                        error_msg = response_data.get('message', f'HTTP {response.status}')
                        logger.error("linkedin_publish_failed",
                            status=response.status,
                            error=error_msg,
                            response=response_data
                        )
                        return PublicationResult(
                            success=False,
                            error=f"LinkedIn API error: {error_msg}"
                        )

        except Exception as e:
            logger.error("linkedin_publish_error",
                title=title[:50],
                error=str(e)
            )
            return PublicationResult(
                success=False,
                error=f"LinkedIn publish failed: {str(e)}"
            )

    def _format_hashtags(self, tags: List[str]) -> str:
        """Convert tags to LinkedIn hashtags."""
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
        """Clean HTML content for LinkedIn."""
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', content)
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()

    # OAuth 2.0 Flow Methods
    @staticmethod
    def get_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
        """Generate LinkedIn OAuth authorization URL."""
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'state': state,
            # Basic scopes - only w_member_social needed for posting
            # Share on LinkedIn product must be enabled in Developer Console
            'scope': 'w_member_social'
        }
        return f"https://www.linkedin.com/oauth/v2/authorization?{urlencode(params)}"

    @staticmethod
    async def exchange_code_for_token(
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str
    ) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        try:
            data = {
                'grant_type': 'authorization_code',
                'code': code,
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': redirect_uri
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://www.linkedin.com/oauth/v2/accessToken',
                    data=data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'}
                ) as response:
                    response_data = await response.json()

                    if response.status == 200:
                        logger.info("linkedin_token_exchange_success")
                        return {
                            "success": True,
                            "access_token": response_data.get('access_token'),
                            "expires_in": response_data.get('expires_in'),
                            "refresh_token": response_data.get('refresh_token'),
                            "scope": response_data.get('scope')
                        }
                    else:
                        error = response_data.get('error_description', f'HTTP {response.status}')
                        logger.error("linkedin_token_exchange_failed",
                            status=response.status,
                            error=error
                        )
                        return {
                            "success": False,
                            "error": error
                        }

        except Exception as e:
            logger.error("linkedin_token_exchange_error", error=str(e))
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    async def get_user_profile(access_token: str) -> Dict[str, Any]:
        """Get authenticated user's profile info using /me endpoint."""
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-Restli-Protocol-Version': '2.0.0'
            }

            async with aiohttp.ClientSession() as session:
                # Get user info from /me endpoint (works with w_member_social)
                async with session.get(
                    'https://api.linkedin.com/v2/me',
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Extract name from localized fields
                        first_name = ""
                        last_name = ""
                        if 'localizedFirstName' in data:
                            first_name = data['localizedFirstName']
                        if 'localizedLastName' in data:
                            last_name = data['localizedLastName']

                        full_name = f"{first_name} {last_name}".strip() or "LinkedIn User"
                        member_id = data.get('id', '')

                        return {
                            "success": True,
                            "sub": f"urn:li:person:{member_id}",
                            "name": full_name,
                            "given_name": first_name,
                            "family_name": last_name,
                            "member_id": member_id
                        }
                    else:
                        error_text = await response.text()
                        logger.error("linkedin_me_failed",
                            status=response.status,
                            error=error_text[:200]
                        )
                        return {"success": False, "error": f"HTTP {response.status}"}

        except Exception as e:
            logger.error("linkedin_me_error", error=str(e))
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_user_organizations(access_token: str) -> Dict[str, Any]:
        """Get organizations (company pages) the user can post to."""
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-Restli-Protocol-Version': '2.0.0',
                'LinkedIn-Version': '202401'
            }

            async with aiohttp.ClientSession() as session:
                # Get organization access control
                async with session.get(
                    'https://api.linkedin.com/v2/organizationAcls?q=roleAssignee',
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        elements = data.get('elements', [])

                        organizations = []
                        for element in elements:
                            org_urn = element.get('organization')
                            if org_urn:
                                org_id = org_urn.split(':')[-1]
                                role = element.get('role', 'UNKNOWN')

                                # Only include if user can post (ADMINISTRATOR or CONTENT_ADMIN)
                                if role in ['ADMINISTRATOR', 'CONTENT_ADMIN']:
                                    organizations.append({
                                        'id': org_id,
                                        'urn': org_urn,
                                        'role': role
                                    })

                        # Get organization details
                        for org in organizations:
                            org_details = await LinkedInPublisher._get_organization_details(
                                access_token, org['id']
                            )
                            if org_details:
                                org['name'] = org_details.get('name', f"Organization {org['id']}")
                                org['vanity_name'] = org_details.get('vanityName', '')

                        logger.info("linkedin_organizations_fetched",
                            count=len(organizations)
                        )

                        return {
                            "success": True,
                            "organizations": organizations
                        }
                    else:
                        error_text = await response.text()
                        logger.error("linkedin_organizations_fetch_failed",
                            status=response.status,
                            error=error_text
                        )
                        return {
                            "success": False,
                            "error": f"Failed to fetch organizations: {error_text}",
                            "organizations": []
                        }

        except Exception as e:
            logger.error("linkedin_organizations_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "organizations": []
            }

    @staticmethod
    async def _get_organization_details(access_token: str, org_id: str) -> Optional[Dict]:
        """Get details of a specific organization."""
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-Restli-Protocol-Version': '2.0.0',
                'LinkedIn-Version': '202401'
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f'https://api.linkedin.com/v2/organizations/{org_id}',
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            'name': data.get('localizedName', ''),
                            'vanityName': data.get('vanityName', '')
                        }
        except Exception as e:
            logger.warn("linkedin_org_details_error", org_id=org_id, error=str(e))

        return None
