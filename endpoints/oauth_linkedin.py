"""LinkedIn OAuth 2.0 integration endpoints."""

import os
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import HTMLResponse

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.supabase_auth import get_current_user_from_jwt
from utils.auth_dependencies import get_company_id_from_auth
from publishers.linkedin_publisher import LinkedInPublisher

logger = get_logger("api.oauth.linkedin")
router = APIRouter(prefix="/oauth/linkedin", tags=["oauth-linkedin"])

# Module-level cache for OAuth state tokens (temporary, for the OAuth flow)
_oauth_states_cache = {}

@router.get("/start")
async def linkedin_oauth_start(
    token: Optional[str] = Query(None, description="JWT token (for popup flow)"),
    authorization: Optional[str] = Header(None)
) -> HTMLResponse:
    """
    Start LinkedIn OAuth flow.
    Opens in popup window for user authorization.

    Accepts authentication via:
    - Query param: ?token=JWT (for popup window)
    - Header: Authorization: Bearer JWT

    Returns:
        HTML page that redirects to LinkedIn authorization
    """
    from publishers.linkedin_publisher import LinkedInPublisher
    import uuid

    # Extract company_id from token
    jwt_token = token or (authorization[7:] if authorization and authorization.startswith("Bearer ") else authorization)

    if not jwt_token:
        return HTMLResponse(
            content="<html><body><h1>Error: Authentication required</h1><script>window.close();</script></body></html>",
            status_code=401
        )

    try:
        user = await get_current_user_from_jwt(f"Bearer {jwt_token}")
        company_id = user.get("company_id")
        if not company_id:
            raise HTTPException(status_code=401, detail="No company_id in token")
    except Exception as e:
        return HTMLResponse(
            content=f"<html><body><h1>Error: Invalid token</h1><script>window.close();</script></body></html>",
            status_code=401
        )

    try:
        client_id = os.getenv('LINKEDIN_CLIENT_ID')
        client_secret = os.getenv('LINKEDIN_CLIENT_SECRET')

        if not client_id or not client_secret:
            logger.error("linkedin_oauth_missing_credentials")
            return HTMLResponse(
                content="<html><body><h1>Error: LinkedIn credentials not configured</h1><script>window.close();</script></body></html>",
                status_code=500
            )

        # Generate state with company_id
        state = f"{company_id}:{uuid.uuid4()}"

        # Store state temporarily
        _oauth_states_cache[state] = {
            'company_id': company_id,
            'timestamp': datetime.utcnow().timestamp()
        }

        # Generate callback URL
        callback_url = f"{os.getenv('API_BASE_URL', 'https://api.ekimen.ai')}/oauth/linkedin/callback"

        # Get authorization URL
        auth_url = LinkedInPublisher.get_authorization_url(client_id, callback_url, state)

        logger.info("linkedin_oauth_redirect",
            company_id=company_id,
            state=state[:20] + "..."
        )

        # Return HTML that redirects to LinkedIn
        html_content = f"""
        <html>
        <head>
            <title>Connecting to LinkedIn...</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                .loading {{ color: #0077b5; }}
            </style>
        </head>
        <body>
            <h2 class="loading">Redirecting to LinkedIn...</h2>
            <p>Please wait while we redirect you to LinkedIn to authorize the connection.</p>
            <script>
                window.location.href = "{auth_url}";
            </script>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error("linkedin_oauth_start_error", error=str(e))
        return HTMLResponse(
            content=f"<html><body><h1>Error: {str(e)}</h1><script>window.close();</script></body></html>",
            status_code=500
        )


@router.get("/callback")
async def linkedin_oauth_callback(
    code: str = Query(None, description="Authorization code from LinkedIn"),
    state: str = Query(None, description="State parameter"),
    error: str = Query(None, description="Error from LinkedIn"),
    error_description: str = Query(None, description="Error description")
) -> HTMLResponse:
    """
    Handle LinkedIn OAuth callback.

    Query Parameters:
        - code: Authorization code from LinkedIn
        - state: State parameter with company_id
        - error: Error code (if authorization failed)

    Returns:
        HTML page that closes popup and notifies parent window
    """
    from publishers.linkedin_publisher import LinkedInPublisher
    from utils.credential_manager import CredentialManager

    # Check for errors from LinkedIn
    if error:
        logger.error("linkedin_oauth_denied", error=error, description=error_description)
        html_content = f"""
        <html><body>
            <h1>Authorization Denied</h1>
            <p>{error_description or error}</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({{
                        type: 'linkedin_oauth_error',
                        error: '{error}'
                    }}, '*');
                }}
                setTimeout(() => window.close(), 3000);
            </script>
        </body></html>
        """
        return HTMLResponse(content=html_content, status_code=400)

    if not code or not state:
        return HTMLResponse(
            content="<html><body><h1>Error: Missing code or state</h1><script>window.close();</script></body></html>",
            status_code=400
        )

    try:
        # Validate state
        state_data = _oauth_states_cache.get(state)

        if not state_data:
            # Try to extract company_id from state format "company_id:uuid"
            parts = state.split(':')
            if len(parts) >= 1:
                company_id = parts[0]
            else:
                logger.error("linkedin_oauth_invalid_state", state=state[:20] + "...")
                return HTMLResponse(
                    content="<html><body><h1>Error: Invalid state</h1><script>window.close();</script></body></html>",
                    status_code=400
                )
        else:
            company_id = state_data['company_id']
            del _oauth_states_cache[state]  # Consume state

        client_id = os.getenv('LINKEDIN_CLIENT_ID')
        client_secret = os.getenv('LINKEDIN_CLIENT_SECRET')
        callback_url = f"{os.getenv('API_BASE_URL', 'https://api.ekimen.ai')}/oauth/linkedin/callback"

        # Exchange code for access token
        token_result = await LinkedInPublisher.exchange_code_for_token(
            client_id, client_secret, code, callback_url
        )

        if not token_result.get('success'):
            logger.error("linkedin_token_exchange_failed", error=token_result.get('error'))
            return HTMLResponse(
                content=f"<html><body><h1>Error: {token_result.get('error')}</h1><script>window.close();</script></body></html>",
                status_code=500
            )

        access_token = token_result['access_token']
        expires_in = token_result.get('expires_in', 5184000)  # Default 60 days

        # Get user's organizations (company pages)
        orgs_result = await LinkedInPublisher.get_user_organizations(access_token)
        organizations = orgs_result.get('organizations', [])

        logger.info("linkedin_oauth_orgs_fetched",
            company_id=company_id,
            organizations_count=len(organizations)
        )

        # If user has organizations, we'll let them choose via frontend
        # For now, store the token and first organization if available
        supabase = get_supabase_client()

        if organizations:
            # Use first organization by default
            org = organizations[0]
            organization_id = org['id']
            organization_name = org.get('name', f"Organization {org['id']}")

            credentials = {
                'access_token': access_token,
                'expires_in': expires_in,
                'organization_id': organization_id,
                'organization_name': organization_name,
                'available_organizations': organizations
            }

            # Encrypt credentials
            credentials_encrypted = CredentialManager.encrypt_credentials(credentials)

            # Check if LinkedIn target already exists
            existing = supabase.client.table('press_publication_targets')\
                .select('id')\
                .eq('company_id', company_id)\
                .eq('platform_type', 'linkedin')\
                .execute()

            if existing.data:
                # Update existing
                supabase.client.table('press_publication_targets').update({
                    'credentials_encrypted': credentials_encrypted.hex(),
                    'is_active': True,
                    'name': f"LinkedIn {organization_name}",
                    'base_url': f"https://linkedin.com/company/{org.get('vanity_name', organization_id)}"
                }).eq('id', existing.data[0]['id']).execute()

                target_id = existing.data[0]['id']
            else:
                # Create new
                new_target = supabase.client.table('press_publication_targets').insert({
                    'company_id': company_id,
                    'platform_type': 'linkedin',
                    'name': f"LinkedIn {organization_name}",
                    'base_url': f"https://linkedin.com/company/{org.get('vanity_name', organization_id)}",
                    'credentials_encrypted': credentials_encrypted.hex(),
                    'is_active': True,
                    'is_default': False
                }).execute()

                target_id = new_target.data[0]['id']

            logger.info("linkedin_oauth_success",
                company_id=company_id,
                organization_name=organization_name,
                target_id=target_id
            )

            html_content = f"""
            <html><body>
                <h1>LinkedIn Connected!</h1>
                <p>Successfully connected to {organization_name}</p>
                <script>
                    if (window.opener) {{
                        window.opener.postMessage({{
                            type: 'linkedin_oauth_success',
                            organization_name: '{organization_name}',
                            organization_id: '{organization_id}'
                        }}, '*');
                    }}
                    setTimeout(() => window.close(), 2000);
                </script>
            </body></html>
            """

        else:
            # No organizations - user needs to create a company page
            logger.warn("linkedin_oauth_no_organizations", company_id=company_id)

            html_content = """
            <html><body>
                <h1>No Company Pages Found</h1>
                <p>You need to be an admin of a LinkedIn Company Page to publish.</p>
                <p>Please create a Company Page on LinkedIn first, then try again.</p>
                <script>
                    if (window.opener) {
                        window.opener.postMessage({
                            type: 'linkedin_oauth_error',
                            error: 'no_organizations',
                            message: 'No company pages found. Please create one first.'
                        }, '*');
                    }
                    setTimeout(() => window.close(), 5000);
                </script>
            </body></html>
            """

        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error("linkedin_oauth_callback_error", error=str(e))
        return HTMLResponse(
            content=f"<html><body><h1>Error: {str(e)}</h1><script>window.close();</script></body></html>",
            status_code=500
        )


@router.get("/status")
async def linkedin_oauth_status(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Check LinkedIn connection status for company.

    Returns:
        {
            "connected": true/false,
            "organization_name": "Company Name" (if connected),
            "organization_id": "12345" (if connected)
        }
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table('press_publication_targets')\
            .select('*')\
            .eq('company_id', company_id)\
            .eq('platform_type', 'linkedin')\
            .eq('is_active', True)\
            .execute()

        if result.data:
            target = result.data[0]
            # Decrypt to get org info
            try:
                from utils.credential_manager import CredentialManager
                credentials = CredentialManager.decrypt_credentials(
                    bytes.fromhex(target['credentials_encrypted'])
                )
                return {
                    "connected": True,
                    "organization_name": credentials.get('organization_name'),
                    "organization_id": credentials.get('organization_id'),
                    "target_id": target['id']
                }
            except:
                return {"connected": True, "target_id": target['id']}
        else:
            return {"connected": False}

    except Exception as e:
        logger.error("linkedin_status_error", company_id=company_id, error=str(e))
        return {"connected": False, "error": str(e)}


@router.delete("")
async def linkedin_oauth_disconnect(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Disconnect LinkedIn account for company.

    Returns:
        {"success": true, "message": "LinkedIn account disconnected"}
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table('press_publication_targets').update({
            'is_active': False
        }).eq('company_id', company_id).eq('platform_type', 'linkedin').execute()

        if result.data:
            logger.info("linkedin_disconnected", company_id=company_id)
            return {
                "success": True,
                "message": "LinkedIn account disconnected successfully"
            }
        else:
            return {
                "success": False,
                "message": "No LinkedIn connection found"
            }

    except Exception as e:
        logger.error("linkedin_disconnect_error", company_id=company_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to disconnect LinkedIn account")


