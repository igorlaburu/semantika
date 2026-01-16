"""Twitter OAuth 1.0a integration endpoints."""

import os
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import HTMLResponse

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.supabase_auth import get_current_user_from_jwt
from utils.auth_dependencies import get_company_id_from_auth
from publishers.twitter_publisher import TwitterPublisher

logger = get_logger("api.oauth.twitter")
router = APIRouter(prefix="/oauth/twitter", tags=["oauth-twitter"])

# Request tokens cache (in production, use Redis)
_request_tokens_cache = {}

@router.get("/oauth/twitter/start")
async def twitter_oauth_start(
    token: Optional[str] = Query(None, description="JWT token (for popup flow)"),
    authorization: Optional[str] = Header(None)
) -> HTMLResponse:
    """
    Start Twitter OAuth flow (Step 1: Request Token).
    Opens in popup window for user authorization.

    Accepts authentication via:
    - Query param: ?token=JWT (for popup window)
    - Header: Authorization: Bearer JWT

    Returns:
        HTML page that redirects to Twitter authorization
    """
    # Extract company_id from token (query param or header)
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
        # Get Consumer Keys from environment
        consumer_key = os.getenv('TWITTER_CONSUMER_KEY')
        consumer_secret = os.getenv('TWITTER_CONSUMER_SECRET')
        
        if not consumer_key or not consumer_secret:
            logger.error("twitter_oauth_missing_credentials")
            return HTMLResponse(
                content="<html><body><h1>Error: Twitter credentials not configured</h1><script>window.close();</script></body></html>",
                status_code=500
            )
        
        # Generate callback URL
        callback_url = f"{os.getenv('API_BASE_URL', 'https://api.ekimen.ai')}/oauth/twitter/callback?company_id={company_id}"
        
        # Step 1: Get request token
        result = await TwitterPublisher.get_request_token(consumer_key, consumer_secret, callback_url)
        
        if not result.get('success'):
            logger.error("twitter_request_token_failed", error=result.get('error'))
            return HTMLResponse(
                content=f"<html><body><h1>Error: {result.get('error')}</h1><script>window.close();</script></body></html>",
                status_code=500
            )
        
        oauth_token = result['oauth_token']
        oauth_token_secret = result['oauth_token_secret']
        
        # Store request token temporarily in session/cache (simplified for demo)
        # In production, use Redis or session store
        request_tokens_cache = _request_tokens_cache
        request_tokens_cache[oauth_token] = {
            'secret': oauth_token_secret,
            'company_id': company_id,
            'timestamp': datetime.utcnow().timestamp()
        }
        
        
        # Step 2: Generate authorization URL
        auth_url = TwitterPublisher.get_authorization_url(oauth_token)
        
        logger.info("twitter_oauth_redirect", 
            company_id=company_id,
            oauth_token=oauth_token[:10] + "..."
        )
        
        # Return HTML that redirects to Twitter
        html_content = f"""
        <html>
        <head>
            <title>Connecting to Twitter...</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                .loading {{ color: #1da1f2; }}
            </style>
        </head>
        <body>
            <h2 class="loading">Redirecting to Twitter...</h2>
            <p>Please wait while we redirect you to Twitter to authorize the connection.</p>
            <script>
                // Redirect to Twitter authorization
                window.location.href = "{auth_url}";
            </script>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logger.error("twitter_oauth_start_error", company_id=company_id, error=str(e))
        return HTMLResponse(
            content=f"<html><body><h1>Error: {str(e)}</h1><script>window.close();</script></body></html>",
            status_code=500
        )


@router.get("/oauth/twitter/callback")
async def twitter_oauth_callback(
    oauth_token: str = Query(..., description="OAuth token from Twitter"),
    oauth_verifier: str = Query(..., description="OAuth verifier from Twitter"),
    company_id: str = Query(..., description="Company ID from initial request")
) -> HTMLResponse:
    """
    Handle Twitter OAuth callback (Step 3: Exchange for Access Token).
    
    Query Parameters:
        - oauth_token: Request token from Step 1
        - oauth_verifier: Verification code from Twitter
        - company_id: Company ID to associate the account
    
    Returns:
        HTML page that closes popup and notifies parent window
    """
    try:
        # Get Consumer Keys from environment
        consumer_key = os.getenv('TWITTER_CONSUMER_KEY')
        consumer_secret = os.getenv('TWITTER_CONSUMER_SECRET')
        
        if not consumer_key or not consumer_secret:
            logger.error("twitter_oauth_callback_missing_credentials")
            return HTMLResponse(
                content="<html><body><h1>Error: Twitter credentials not configured</h1><script>window.close();</script></body></html>",
                status_code=500
            )
        
        # Retrieve request token secret from temporary storage
        request_tokens_cache = _request_tokens_cache
        token_data = request_tokens_cache.get(oauth_token)
        
        if not token_data:
            logger.error("twitter_oauth_callback_token_not_found", oauth_token=oauth_token[:10] + "...")
            return HTMLResponse(
                content="<html><body><h1>Error: Invalid or expired token</h1><script>window.close();</script></body></html>",
                status_code=400
            )
        
        oauth_token_secret = token_data['secret']
        stored_company_id = token_data['company_id']
        
        # Verify company_id matches
        if company_id != stored_company_id:
            logger.error("twitter_oauth_callback_company_mismatch", 
                provided=company_id, 
                stored=stored_company_id
            )
            return HTMLResponse(
                content="<html><body><h1>Error: Company ID mismatch</h1><script>window.close();</script></body></html>",
                status_code=400
            )
        
        # Step 3: Exchange for access token
        result = await TwitterPublisher.get_access_token(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            oauth_token=oauth_token,
            oauth_token_secret=oauth_token_secret,
            oauth_verifier=oauth_verifier
        )
        
        if not result.get('success'):
            logger.error("twitter_access_token_failed", error=result.get('error'))
            return HTMLResponse(
                content=f"<html><body><h1>Error: {result.get('error')}</h1><script>window.close();</script></body></html>",
                status_code=500
            )
        
        access_token = result['oauth_token']
        access_token_secret = result['oauth_token_secret']
        twitter_user_id = result.get('user_id')
        twitter_username = result.get('screen_name')
        
        # Clean up temporary token
        del request_tokens_cache[oauth_token]
        
        # Store Twitter credentials in publication_targets table
        try:
            from utils.credential_manager import CredentialManager
            
            # Prepare credentials for encryption
            credentials = {
                'api_key': consumer_key,
                'api_secret': consumer_secret,
                'access_token': access_token,
                'access_token_secret': access_token_secret
            }
            
            # Encrypt credentials
            encrypted_credentials = CredentialManager.encrypt_credentials(credentials)
            
            # Save to press_publication_targets table
            supabase = get_supabase_client()
            
            # Check if Twitter target already exists for this company
            existing = supabase.client.table('press_publication_targets').select('*').eq('company_id', company_id).eq('platform_type', 'twitter').execute()
            
            target_data = {
                'company_id': company_id,
                'platform_type': 'twitter',
                'name': f'Twitter @{twitter_username}',
                'base_url': f'@{twitter_username}',
                'credentials_encrypted': encrypted_credentials.hex(),
                'is_active': True
            }
            
            if existing.data:
                # Update existing target
                target_id = existing.data[0]['id']
                supabase.client.table('press_publication_targets').update(target_data).eq('id', target_id).execute()
                logger.info("twitter_target_updated", 
                    company_id=company_id,
                    username=twitter_username,
                    target_id=target_id
                )
            else:
                # Create new target
                insert_result = supabase.client.table('press_publication_targets').insert(target_data).execute()
                target_id = insert_result.data[0]['id']
                logger.info("twitter_target_created", 
                    company_id=company_id,
                    username=twitter_username,
                    target_id=target_id
                )
            
        except Exception as e:
            logger.error("twitter_target_save_failed", 
                company_id=company_id,
                username=twitter_username,
                error=str(e)
            )
            return HTMLResponse(
                content=f"<html><body><h1>Error saving Twitter connection: {str(e)}</h1><script>window.close();</script></body></html>",
                status_code=500
            )
        
        logger.info("twitter_oauth_success", 
            company_id=company_id,
            username=twitter_username,
            user_id=twitter_user_id
        )
        
        # Return success HTML that closes popup
        html_content = f"""
        <html>
        <head>
            <title>Twitter Connected</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                .success {{ color: #1da1f2; }}
            </style>
        </head>
        <body>
            <h2 class="success">✅ Twitter Connected Successfully!</h2>
            <p>Connected as <strong>@{twitter_username}</strong></p>
            <p>This window will close automatically...</p>
            <script>
                // Notify parent window of success (if needed)
                try {{
                    if (window.opener) {{
                        window.opener.postMessage({{
                            type: 'twitter_oauth_success',
                            username: '{twitter_username}',
                            user_id: '{twitter_user_id}'
                        }}, '*');
                    }}
                }} catch(e) {{
                    console.log('Could not notify parent window:', e);
                }}
                
                // Close popup after 2 seconds
                setTimeout(() => {{
                    window.close();
                }}, 2000);
            </script>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logger.error("twitter_oauth_callback_error", 
            company_id=company_id,
            oauth_token=oauth_token[:10] + "..." if oauth_token else None,
            error=str(e)
        )
        return HTMLResponse(
            content=f"<html><body><h1>Error: {str(e)}</h1><script>window.close();</script></body></html>",
            status_code=500
        )


@router.get("/oauth/twitter/status")
async def twitter_oauth_status(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Check Twitter connection status for company.
    
    Requires: Authentication (JWT or API Key)
    
    Returns:
        {
            "connected": true/false,
            "username": "@username" (if connected),
            "user_id": "twitter_user_id" (if connected),
            "connected_at": "2025-01-10T..." (if connected)
        }
    """
    try:
        supabase = get_supabase_client()
        
        # Check for active Twitter publication target
        result = supabase.client.table('press_publication_targets').select('*').eq('company_id', company_id).eq('platform_type', 'twitter').eq('is_active', True).execute()
        
        if result.data:
            target = result.data[0]
            
            return {
                "connected": True,
                "username": target.get('base_url', ''),
                "target_id": target.get('id'),
                "name": target.get('name'),
                "created_at": target.get('created_at')
            }
        else:
            return {
                "connected": False
            }
            
    except Exception as e:
        logger.error("twitter_status_check_error", company_id=company_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to check Twitter status")


@router.delete("/oauth/twitter")
async def twitter_oauth_disconnect(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict:
    """
    Disconnect Twitter account for company.
    
    Requires: Authentication (JWT or API Key)
    
    Returns:
        {"success": true, "message": "Twitter account disconnected"}
    """
    try:
        supabase = get_supabase_client()
        
        # Deactivate Twitter publication target
        result = supabase.client.table('press_publication_targets').update({
            'is_active': False
        }).eq('company_id', company_id).eq('platform_type', 'twitter').execute()
        
        if result.data:
            logger.info("twitter_disconnected", company_id=company_id)
            return {
                "success": True,
                "message": "Twitter account disconnected successfully"
            }
        else:
            return {
                "success": False,
                "message": "No Twitter connection found"
            }
            
    except Exception as e:
        logger.error("twitter_disconnect_error", company_id=company_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to disconnect Twitter account")

