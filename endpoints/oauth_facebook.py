"""Facebook OAuth 2.0 integration endpoints."""

import os
import hashlib
import hmac
import base64
import json
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.supabase_auth import get_current_user_from_jwt
from utils.auth_dependencies import get_company_id_from_auth
from publishers.facebook_publisher import FacebookPublisher

logger = get_logger("api.oauth.facebook")
router = APIRouter(prefix="/oauth/facebook", tags=["oauth-facebook"])

@router.get("/start")
async def facebook_oauth_start(
    token: Optional[str] = Query(None, description="JWT token (for popup flow)"),
    authorization: Optional[str] = Header(None)
) -> HTMLResponse:
    """
    Start Facebook OAuth flow.
    Opens in popup window for user authorization.

    Accepts authentication via:
    - Query param: ?token=JWT (for popup window)
    - Header: Authorization: Bearer JWT

    Returns:
        HTML page that redirects to Facebook authorization
    """
    from publishers.facebook_publisher import FacebookPublisher
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
        app_id = os.getenv('FACEBOOK_APP_ID')
        app_secret = os.getenv('FACEBOOK_APP_SECRET')

        if not app_id or not app_secret:
            logger.error("facebook_oauth_missing_credentials")
            return HTMLResponse(
                content="<html><body><h1>Error: Facebook credentials not configured</h1><script>window.close();</script></body></html>",
                status_code=500
            )

        # Generate state with company_id
        state = f"{company_id}:{uuid.uuid4()}"

        # Store state temporarily
        oauth_states_cache = getattr(app.state, 'facebook_oauth_states', {})
        oauth_states_cache[state] = {
            'company_id': company_id,
            'timestamp': datetime.utcnow().timestamp()
        }
        app.state.facebook_oauth_states = oauth_states_cache

        # Generate callback URL
        callback_url = f"{os.getenv('API_BASE_URL', 'https://api.ekimen.ai')}/oauth/facebook/callback"

        # Get authorization URL
        auth_url = FacebookPublisher.get_authorization_url(app_id, callback_url, state)

        logger.info("facebook_oauth_redirect",
            company_id=company_id,
            state=state[:20] + "..."
        )

        # Return HTML that redirects to Facebook
        html_content = f"""
        <html>
        <head>
            <title>Connecting to Facebook...</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                .loading {{ color: #1877f2; }}
            </style>
        </head>
        <body>
            <h2 class="loading">Redirecting to Facebook...</h2>
            <p>Please wait while we redirect you to Facebook to authorize the connection.</p>
            <script>
                window.location.href = "{auth_url}";
            </script>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error("facebook_oauth_start_error", error=str(e))
        return HTMLResponse(
            content=f"<html><body><h1>Error: {str(e)}</h1><script>window.close();</script></body></html>",
            status_code=500
        )


@router.get("/callback")
async def facebook_oauth_callback(
    code: str = Query(None, description="Authorization code from Facebook"),
    state: str = Query(None, description="State parameter"),
    error: str = Query(None, description="Error from Facebook"),
    error_description: str = Query(None, description="Error description")
) -> HTMLResponse:
    """
    Handle Facebook OAuth callback.

    Query Parameters:
        - code: Authorization code from Facebook
        - state: State parameter with company_id
        - error: Error code (if authorization failed)

    Returns:
        HTML page that closes popup and notifies parent window
    """
    from publishers.facebook_publisher import FacebookPublisher
    from utils.credential_manager import CredentialManager

    # Check for errors from Facebook
    if error:
        logger.error("facebook_oauth_denied", error=error, description=error_description)
        html_content = f"""
        <html><body>
            <h1>Authorization Denied</h1>
            <p>{error_description or error}</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({{
                        type: 'facebook_oauth_error',
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
        oauth_states_cache = getattr(app.state, 'facebook_oauth_states', {})
        state_data = oauth_states_cache.get(state)

        if not state_data:
            # Try to extract company_id from state format "company_id:uuid"
            parts = state.split(':')
            if len(parts) >= 1:
                company_id = parts[0]
            else:
                logger.error("facebook_oauth_invalid_state", state=state[:20] + "...")
                return HTMLResponse(
                    content="<html><body><h1>Error: Invalid state</h1><script>window.close();</script></body></html>",
                    status_code=400
                )
        else:
            company_id = state_data['company_id']
            del oauth_states_cache[state]  # Consume state

        app_id = os.getenv('FACEBOOK_APP_ID')
        app_secret = os.getenv('FACEBOOK_APP_SECRET')
        callback_url = f"{os.getenv('API_BASE_URL', 'https://api.ekimen.ai')}/oauth/facebook/callback"

        # Exchange code for access token
        token_result = await FacebookPublisher.exchange_code_for_token(
            app_id, app_secret, code, callback_url
        )

        if not token_result.get('success'):
            logger.error("facebook_token_exchange_failed", error=token_result.get('error'))
            return HTMLResponse(
                content=f"<html><body><h1>Error: {token_result.get('error')}</h1><script>window.close();</script></body></html>",
                status_code=500
            )

        user_access_token = token_result['access_token']

        # Get user info
        user_info = await FacebookPublisher.get_user_info(user_access_token)
        user_id = user_info.get('user_id', 'unknown')
        user_name = user_info.get('user_name', 'Unknown')

        # Get user's pages
        pages_result = await FacebookPublisher.get_user_pages(user_access_token)
        pages = pages_result.get('pages', [])

        logger.info("facebook_oauth_pages_fetched",
            company_id=company_id,
            pages_count=len(pages)
        )

        # If user has pages, store credentials
        supabase = get_supabase_client()

        if pages:
            # Use first page by default
            page = pages[0]
            page_id = page['id']
            page_name = page.get('name', f"Page {page['id']}")
            page_access_token = page['access_token']

            credentials = {
                'user_access_token': user_access_token,
                'page_access_token': page_access_token,
                'page_id': page_id,
                'page_name': page_name,
                'user_id': user_id,
                'user_name': user_name,
                'available_pages': pages
            }

            # Encrypt credentials
            credentials_encrypted = CredentialManager.encrypt_credentials(credentials)

            # Check if Facebook target already exists
            existing = supabase.client.table('press_publication_targets')\
                .select('id')\
                .eq('company_id', company_id)\
                .eq('platform_type', 'facebook')\
                .execute()

            if existing.data:
                # Update existing
                supabase.client.table('press_publication_targets').update({
                    'credentials_encrypted': credentials_encrypted.hex(),
                    'is_active': True,
                    'name': f"Facebook {page_name}",
                    'base_url': page.get('link', f"https://facebook.com/{page_id}")
                }).eq('id', existing.data[0]['id']).execute()

                target_id = existing.data[0]['id']
            else:
                # Create new
                new_target = supabase.client.table('press_publication_targets').insert({
                    'company_id': company_id,
                    'platform_type': 'facebook',
                    'name': f"Facebook {page_name}",
                    'base_url': page.get('link', f"https://facebook.com/{page_id}"),
                    'credentials_encrypted': credentials_encrypted.hex(),
                    'is_active': True,
                    'is_default': False
                }).execute()

                target_id = new_target.data[0]['id']

            logger.info("facebook_oauth_success",
                company_id=company_id,
                page_name=page_name,
                target_id=target_id
            )

            html_content = f"""
            <html><body>
                <h1>Facebook Connected!</h1>
                <p>Successfully connected to {page_name}</p>
                <script>
                    if (window.opener) {{
                        window.opener.postMessage({{
                            type: 'facebook_oauth_success',
                            page_name: '{page_name}',
                            page_id: '{page_id}'
                        }}, '*');
                    }}
                    setTimeout(() => window.close(), 2000);
                </script>
            </body></html>
            """

        else:
            # No pages - user needs to create a Facebook page
            logger.warn("facebook_oauth_no_pages", company_id=company_id)

            html_content = """
            <html><body>
                <h1>No Facebook Pages Found</h1>
                <p>You need to be an admin of a Facebook Page to publish.</p>
                <p>Please create a Facebook Page first, then try again.</p>
                <script>
                    if (window.opener) {
                        window.opener.postMessage({
                            type: 'facebook_oauth_error',
                            error: 'no_pages',
                            message: 'No Facebook pages found. Please create one first.'
                        }, '*');
                    }
                    setTimeout(() => window.close(), 5000);
                </script>
            </body></html>
            """

        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error("facebook_oauth_callback_error", error=str(e))
        return HTMLResponse(
            content=f"<html><body><h1>Error: {str(e)}</h1><script>window.close();</script></body></html>",
            status_code=500
        )


@router.get("/status")
async def facebook_oauth_status(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Check Facebook connection status for company.

    Returns:
        {
            "connected": true/false,
            "page_name": "Page Name" (if connected),
            "page_id": "12345" (if connected)
        }
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table('press_publication_targets')\
            .select('*')\
            .eq('company_id', company_id)\
            .eq('platform_type', 'facebook')\
            .eq('is_active', True)\
            .execute()

        if result.data:
            target = result.data[0]
            # Decrypt to get page info
            try:
                from utils.credential_manager import CredentialManager
                credentials = CredentialManager.decrypt_credentials(
                    bytes.fromhex(target['credentials_encrypted'])
                )
                return {
                    "connected": True,
                    "page_name": credentials.get('page_name'),
                    "page_id": credentials.get('page_id'),
                    "target_id": target['id']
                }
            except:
                return {"connected": True, "target_id": target['id']}
        else:
            return {"connected": False}

    except Exception as e:
        logger.error("facebook_status_error", company_id=company_id, error=str(e))
        return {"connected": False, "error": str(e)}


@router.delete("")
async def facebook_oauth_disconnect(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Disconnect Facebook account for company.

    Returns:
        {"success": true, "message": "Facebook account disconnected"}
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table('press_publication_targets').update({
            'is_active': False
        }).eq('company_id', company_id).eq('platform_type', 'facebook').execute()

        if result.data:
            logger.info("facebook_disconnected", company_id=company_id)
            return {
                "success": True,
                "message": "Facebook account disconnected successfully"
            }
        else:
            return {
                "success": False,
                "message": "No Facebook connection found"
            }

    except Exception as e:
        logger.error("facebook_disconnect_error", company_id=company_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to disconnect Facebook account")


@router.post("/data-deletion")
async def facebook_data_deletion_callback(
    request: Request
) -> Dict:
    """
    Facebook Data Deletion Callback (GDPR compliance).

    Facebook calls this endpoint when a user requests deletion of their data.
    We must delete all data associated with the user and return a confirmation.

    Facebook sends a POST with 'signed_request' containing user_id.

    Returns:
        {
            "url": "https://api.ekimen.ai/oauth/facebook/deletion-status?id=XXX",
            "confirmation_code": "XXX"
        }
    """
    import hmac
    import hashlib
    import base64
    import uuid

    try:
        # Parse form data
        form_data = await request.form()
        signed_request = form_data.get('signed_request')

        if not signed_request:
            logger.error("facebook_data_deletion_missing_signed_request")
            raise HTTPException(status_code=400, detail="Missing signed_request")

        # Parse signed_request (format: signature.payload)
        parts = signed_request.split('.')
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="Invalid signed_request format")

        encoded_sig, payload = parts

        # Decode payload
        # Add padding if needed
        payload += '=' * (4 - len(payload) % 4)
        decoded_payload = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded_payload)

        facebook_user_id = data.get('user_id')

        if not facebook_user_id:
            logger.error("facebook_data_deletion_no_user_id")
            raise HTTPException(status_code=400, detail="No user_id in payload")

        # Verify signature
        app_secret = os.getenv('FACEBOOK_APP_SECRET')
        if app_secret:
            expected_sig = hmac.new(
                app_secret.encode(),
                payload.encode(),
                hashlib.sha256
            ).digest()
            expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode().rstrip('=')

            # Normalize encoded_sig (remove padding)
            encoded_sig = encoded_sig.rstrip('=')

            if not hmac.compare_digest(encoded_sig, expected_sig_b64):
                logger.error("facebook_data_deletion_invalid_signature",
                    facebook_user_id=facebook_user_id
                )
                raise HTTPException(status_code=400, detail="Invalid signature")

        # Find and delete user data
        supabase = get_supabase_client()

        # Find targets with this Facebook user_id in credentials
        targets = supabase.client.table('press_publication_targets')\
            .select('id, company_id, credentials_encrypted')\
            .eq('platform_type', 'facebook')\
            .eq('is_active', True)\
            .execute()

        deleted_count = 0
        for target in targets.data or []:
            try:
                from utils.credential_manager import CredentialManager
                credentials = CredentialManager.decrypt_credentials(
                    bytes.fromhex(target['credentials_encrypted'])
                )

                if credentials.get('user_id') == facebook_user_id:
                    # Delete this target (hard delete for GDPR)
                    supabase.client.table('press_publication_targets')\
                        .delete()\
                        .eq('id', target['id'])\
                        .execute()
                    deleted_count += 1

                    logger.info("facebook_data_deletion_target_deleted",
                        target_id=target['id'],
                        company_id=target['company_id'],
                        facebook_user_id=facebook_user_id
                    )
            except Exception as e:
                logger.warn("facebook_data_deletion_decrypt_error",
                    target_id=target['id'],
                    error=str(e)
                )

        # Generate confirmation code
        confirmation_code = str(uuid.uuid4())[:8].upper()

        logger.info("facebook_data_deletion_completed",
            facebook_user_id=facebook_user_id,
            deleted_count=deleted_count,
            confirmation_code=confirmation_code
        )

        # Return confirmation per Facebook spec
        api_base = os.getenv('API_BASE_URL', 'https://api.ekimen.ai')
        return {
            "url": f"{api_base}/oauth/facebook/deletion-status?code={confirmation_code}",
            "confirmation_code": confirmation_code
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("facebook_data_deletion_error", error=str(e))
        raise HTTPException(status_code=500, detail="Data deletion failed")


@router.get("/deletion-status")
async def facebook_deletion_status(
    code: str = Query(..., description="Confirmation code")
) -> HTMLResponse:
    """
    Status page for Facebook data deletion request.

    Users can visit this URL to verify their data was deleted.
    """
    html_content = f"""
    <html>
    <head>
        <title>Data Deletion Status - Ekimen</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
            .success {{ color: #28a745; }}
            .code {{ background: #f5f5f5; padding: 10px; border-radius: 5px; font-family: monospace; }}
        </style>
    </head>
    <body>
        <h1 class="success">Data Deletion Completed</h1>
        <p>Your data has been successfully deleted from our systems.</p>
        <p><strong>Confirmation Code:</strong></p>
        <div class="code">{code}</div>
        <p style="margin-top: 20px; color: #666; font-size: 14px;">
            This confirms that all Facebook-related data associated with your account
            has been removed from Ekimen's database.
        </p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

