"""OAuth 2.1 routes for MCP authentication.

Endpoints:
- /.well-known/oauth-authorization-server - Server metadata
- /.well-known/oauth-protected-resource - Resource metadata
- /oauth/register - Dynamic Client Registration
- /oauth/authorize - Authorization endpoint
- /oauth/token - Token endpoint
- /oauth/login - Login form (POST)
- /oauth/consent - Consent form (POST)
"""

import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from utils.logger import get_logger
from utils.config import settings
from utils.supabase_client import get_supabase_client

from .models import (
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    TokenRequest,
    TokenResponse,
    TokenErrorResponse,
    OAuthServerMetadata,
    ResourceServerMetadata,
)
from .pkce import verify_code_challenge, generate_authorization_code
from .tokens import (
    generate_client_credentials,
    verify_client_secret,
    generate_access_token,
    generate_refresh_token,
    hash_token,
    calculate_expiry,
    is_expired,
    login_sessions,
)

logger = get_logger("mcp_oauth")

oauth_router = APIRouter(tags=["OAuth"])


# ============================================
# CONFIGURATION
# ============================================

def get_issuer() -> str:
    """Get the OAuth issuer URL."""
    return getattr(settings, "mcp_oauth_issuer", "https://api.ekimen.ai/mcp")


def get_access_token_expiry() -> int:
    """Get access token expiry in seconds."""
    return getattr(settings, "mcp_oauth_access_token_expiry", 3600)


def get_refresh_token_expiry() -> int:
    """Get refresh token expiry in seconds."""
    return getattr(settings, "mcp_oauth_refresh_token_expiry", 2592000)


def get_code_expiry() -> int:
    """Get authorization code expiry in seconds."""
    return getattr(settings, "mcp_oauth_code_expiry", 600)


# ============================================
# DISCOVERY ENDPOINTS
# ============================================

@oauth_router.get("/.well-known/oauth-authorization-server")
async def oauth_server_metadata():
    """OAuth Authorization Server Metadata (RFC 8414)."""
    issuer = get_issuer()

    return OAuthServerMetadata(
        issuer=issuer,
        authorization_endpoint=f"{issuer}/oauth/authorize",
        token_endpoint=f"{issuer}/oauth/token",
        registration_endpoint=f"{issuer}/oauth/register",
        scopes_supported=["mcp:read", "mcp:write"],
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=["client_secret_post", "none"],
    )


@oauth_router.get("/.well-known/oauth-protected-resource")
async def oauth_resource_metadata():
    """OAuth Protected Resource Metadata (RFC 8707)."""
    issuer = get_issuer()

    return ResourceServerMetadata(
        resource=issuer,
        authorization_servers=[issuer],
        scopes_supported=["mcp:read", "mcp:write"],
        bearer_methods_supported=["header"],
    )


# ============================================
# DYNAMIC CLIENT REGISTRATION (DCR)
# ============================================

@oauth_router.post("/oauth/register")
async def register_client(request: ClientRegistrationRequest):
    """
    Dynamic Client Registration (RFC 7591).

    Creates a new OAuth client with credentials.
    """
    supabase = get_supabase_client()

    # Generate credentials
    client_id, client_secret, secret_hash = generate_client_credentials()

    try:
        # Insert into database
        result = supabase.client.table("mcp_oauth_clients").insert({
            "client_id": client_id,
            "client_secret_hash": secret_hash,
            "client_name": request.client_name,
            "redirect_uris": request.redirect_uris,
            "grant_types": request.grant_types,
            "scope": request.scope,
            "is_active": True,
        }).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to register client")

        logger.info("oauth_client_registered",
            client_id=client_id,
            client_name=request.client_name
        )

        return ClientRegistrationResponse(
            client_id=client_id,
            client_secret=client_secret,  # Only returned once!
            client_name=request.client_name,
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            scope=request.scope,
            client_id_issued_at=int(time.time()),
        )

    except Exception as e:
        logger.error("oauth_client_registration_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Registration failed")


# ============================================
# AUTHORIZATION ENDPOINT
# ============================================

@oauth_router.get("/oauth/authorize")
async def authorize(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    scope: Optional[str] = "mcp:read mcp:write",
    state: Optional[str] = None,
):
    """
    Authorization endpoint - displays login form.

    This is the entry point for the OAuth flow.
    """
    # Validate required params
    if response_type != "code":
        return _redirect_error(redirect_uri, "unsupported_response_type", state)

    if code_challenge_method != "S256":
        return _redirect_error(redirect_uri, "invalid_request", state, "Only S256 supported")

    # Validate client
    supabase = get_supabase_client()
    client_result = supabase.client.table("mcp_oauth_clients")\
        .select("*")\
        .eq("client_id", client_id)\
        .eq("is_active", True)\
        .maybe_single()\
        .execute()

    if not client_result.data:
        return _redirect_error(redirect_uri, "invalid_client", state)

    client = client_result.data

    # Validate redirect_uri
    if redirect_uri not in client["redirect_uris"]:
        # Don't redirect - show error directly (security)
        raise HTTPException(
            status_code=400,
            detail="Invalid redirect_uri"
        )

    # Build login page with preserved OAuth params
    return _render_login_page(
        client_id=client_id,
        client_name=client["client_name"],
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )


@oauth_router.post("/oauth/login")
async def handle_login(
    email: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    scope: str = Form(default="mcp:read mcp:write"),
    state: Optional[str] = Form(default=None),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(default="S256"),
):
    """
    Handle login form submission.

    Validates credentials against Supabase Auth.
    """
    supabase = get_supabase_client()

    # Authenticate with Supabase Auth
    try:
        auth_response = supabase.client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        if not auth_response.user:
            return _render_login_page(
                client_id=client_id,
                client_name="MCP Client",
                redirect_uri=redirect_uri,
                scope=scope,
                state=state,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                error="Invalid email or password",
            )

        auth_user_id = auth_response.user.id

    except Exception as e:
        logger.warn("oauth_login_failed", email=email, error=str(e))
        return _render_login_page(
            client_id=client_id,
            client_name="MCP Client",
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            error="Invalid email or password",
        )

    # Look up user in public.users to get company_id
    user_result = supabase.client.table("users")\
        .select("id, company_id, email, name")\
        .eq("auth_user_id", str(auth_user_id))\
        .eq("is_active", True)\
        .maybe_single()\
        .execute()

    if not user_result.data or not user_result.data.get("company_id"):
        logger.warn("oauth_user_no_company", auth_user_id=str(auth_user_id))
        return _render_login_page(
            client_id=client_id,
            client_name="MCP Client",
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            error="User has no company assigned",
        )

    user = user_result.data

    # Create session for consent flow
    session_token = login_sessions.create(
        user_id=user["id"],
        company_id=user["company_id"],
        email=user["email"],
        oauth_params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }
    )

    logger.info("oauth_login_success",
        user_id=user["id"],
        company_id=user["company_id"]
    )

    # Get client name for consent page
    client_result = supabase.client.table("mcp_oauth_clients")\
        .select("client_name")\
        .eq("client_id", client_id)\
        .maybe_single()\
        .execute()

    client_name = client_result.data["client_name"] if client_result.data else "MCP Client"

    # Show consent page
    return _render_consent_page(
        session_token=session_token,
        user_email=user["email"],
        client_name=client_name,
        scope=scope,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )


@oauth_router.post("/oauth/consent")
async def handle_consent(
    consent: str = Form(...),
    session_token: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    scope: str = Form(default="mcp:read mcp:write"),
    state: Optional[str] = Form(default=None),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(default="S256"),
):
    """
    Handle consent form submission.

    If approved, generates authorization code and redirects.
    """
    # Validate session
    session = login_sessions.get(session_token)
    if not session:
        raise HTTPException(status_code=400, detail="Invalid or expired session")

    # Delete session (single use)
    login_sessions.delete(session_token)

    # Check consent
    if consent != "approve":
        return _redirect_error(redirect_uri, "access_denied", state)

    # Generate authorization code
    code = generate_authorization_code()
    expires_at = calculate_expiry(get_code_expiry())

    # Store code in database
    supabase = get_supabase_client()

    try:
        supabase.client.table("mcp_oauth_codes").insert({
            "code": code,
            "client_id": client_id,
            "user_id": session["user_id"],
            "company_id": session["company_id"],
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "scope": scope,
            "redirect_uri": redirect_uri,
            "expires_at": expires_at.isoformat(),
        }).execute()

        logger.info("oauth_code_issued",
            user_id=session["user_id"],
            company_id=session["company_id"],
            client_id=client_id
        )

    except Exception as e:
        logger.error("oauth_code_creation_failed", error=str(e))
        return _redirect_error(redirect_uri, "server_error", state)

    # Redirect with code
    params = {"code": code}
    if state:
        params["state"] = state

    redirect_url = f"{redirect_uri}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url, status_code=302)


# ============================================
# TOKEN ENDPOINT
# ============================================

@oauth_router.post("/oauth/token")
async def token_endpoint(
    grant_type: str = Form(...),
    code: Optional[str] = Form(default=None),
    redirect_uri: Optional[str] = Form(default=None),
    code_verifier: Optional[str] = Form(default=None),
    refresh_token: Optional[str] = Form(default=None),
    client_id: str = Form(...),
    client_secret: Optional[str] = Form(default=None),
):
    """
    Token endpoint - exchanges code for tokens.

    Supports:
    - authorization_code grant (with PKCE)
    - refresh_token grant
    """
    supabase = get_supabase_client()

    # Validate client
    client_result = supabase.client.table("mcp_oauth_clients")\
        .select("*")\
        .eq("client_id", client_id)\
        .eq("is_active", True)\
        .maybe_single()\
        .execute()

    if not client_result.data:
        return _token_error("invalid_client", "Unknown client")

    client = client_result.data

    # Verify client secret if provided
    if client_secret and client["client_secret_hash"]:
        if not verify_client_secret(client_secret, client["client_secret_hash"]):
            return _token_error("invalid_client", "Invalid client credentials")

    # Handle grant type
    if grant_type == "authorization_code":
        return await _handle_authorization_code_grant(
            supabase, client, code, redirect_uri, code_verifier
        )
    elif grant_type == "refresh_token":
        return await _handle_refresh_token_grant(
            supabase, client, refresh_token
        )
    else:
        return _token_error("unsupported_grant_type")


async def _handle_authorization_code_grant(
    supabase,
    client: dict,
    code: Optional[str],
    redirect_uri: Optional[str],
    code_verifier: Optional[str],
):
    """Handle authorization_code grant."""
    if not code or not redirect_uri or not code_verifier:
        return _token_error("invalid_request", "Missing required parameters")

    # Look up code
    code_result = supabase.client.table("mcp_oauth_codes")\
        .select("*")\
        .eq("code", code)\
        .eq("client_id", client["client_id"])\
        .is_("used_at", "null")\
        .maybe_single()\
        .execute()

    if not code_result.data:
        return _token_error("invalid_grant", "Invalid or expired code")

    code_data = code_result.data

    # Check expiry
    expires_at = datetime.fromisoformat(code_data["expires_at"].replace("Z", "+00:00"))
    if is_expired(expires_at):
        return _token_error("invalid_grant", "Code expired")

    # Verify redirect_uri matches
    if code_data["redirect_uri"] != redirect_uri:
        return _token_error("invalid_grant", "Redirect URI mismatch")

    # Verify PKCE
    try:
        if not verify_code_challenge(
            code_verifier,
            code_data["code_challenge"],
            code_data["code_challenge_method"]
        ):
            return _token_error("invalid_grant", "Code verifier mismatch")
    except ValueError as e:
        return _token_error("invalid_request", str(e))

    # Mark code as used
    supabase.client.table("mcp_oauth_codes")\
        .update({"used_at": datetime.now(timezone.utc).isoformat()})\
        .eq("id", code_data["id"])\
        .execute()

    # Generate tokens
    access_token, access_token_hash = generate_access_token()
    refresh_token, refresh_token_hash = generate_refresh_token()

    access_expiry = calculate_expiry(get_access_token_expiry())
    refresh_expiry = calculate_expiry(get_refresh_token_expiry())

    # Store tokens
    try:
        supabase.client.table("mcp_oauth_tokens").insert({
            "access_token_hash": access_token_hash,
            "refresh_token_hash": refresh_token_hash,
            "client_id": client["client_id"],
            "user_id": code_data["user_id"],
            "company_id": code_data["company_id"],
            "scope": code_data["scope"],
            "access_token_expires_at": access_expiry.isoformat(),
            "refresh_token_expires_at": refresh_expiry.isoformat(),
        }).execute()

        logger.info("oauth_token_issued",
            user_id=code_data["user_id"],
            company_id=code_data["company_id"],
            client_id=client["client_id"]
        )

    except Exception as e:
        logger.error("oauth_token_creation_failed", error=str(e))
        return _token_error("server_error")

    return TokenResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=get_access_token_expiry(),
        refresh_token=refresh_token,
        scope=code_data["scope"] or "mcp:read mcp:write",
    )


async def _handle_refresh_token_grant(
    supabase,
    client: dict,
    refresh_token: Optional[str],
):
    """Handle refresh_token grant."""
    if not refresh_token:
        return _token_error("invalid_request", "Missing refresh_token")

    # Look up token by hash
    token_hash = hash_token(refresh_token)

    token_result = supabase.client.table("mcp_oauth_tokens")\
        .select("*")\
        .eq("refresh_token_hash", token_hash)\
        .eq("client_id", client["client_id"])\
        .is_("revoked_at", "null")\
        .maybe_single()\
        .execute()

    if not token_result.data:
        return _token_error("invalid_grant", "Invalid refresh token")

    token_data = token_result.data

    # Check refresh token expiry
    refresh_expires = datetime.fromisoformat(
        token_data["refresh_token_expires_at"].replace("Z", "+00:00")
    )
    if is_expired(refresh_expires):
        return _token_error("invalid_grant", "Refresh token expired")

    # Revoke old token
    supabase.client.table("mcp_oauth_tokens")\
        .update({"revoked_at": datetime.now(timezone.utc).isoformat()})\
        .eq("id", token_data["id"])\
        .execute()

    # Generate new tokens
    new_access_token, new_access_hash = generate_access_token()
    new_refresh_token, new_refresh_hash = generate_refresh_token()

    access_expiry = calculate_expiry(get_access_token_expiry())
    refresh_expiry = calculate_expiry(get_refresh_token_expiry())

    # Store new tokens
    try:
        supabase.client.table("mcp_oauth_tokens").insert({
            "access_token_hash": new_access_hash,
            "refresh_token_hash": new_refresh_hash,
            "client_id": client["client_id"],
            "user_id": token_data["user_id"],
            "company_id": token_data["company_id"],
            "scope": token_data["scope"],
            "access_token_expires_at": access_expiry.isoformat(),
            "refresh_token_expires_at": refresh_expiry.isoformat(),
        }).execute()

        logger.info("oauth_token_refreshed",
            user_id=token_data["user_id"],
            company_id=token_data["company_id"],
            client_id=client["client_id"]
        )

    except Exception as e:
        logger.error("oauth_token_refresh_failed", error=str(e))
        return _token_error("server_error")

    return TokenResponse(
        access_token=new_access_token,
        token_type="Bearer",
        expires_in=get_access_token_expiry(),
        refresh_token=new_refresh_token,
        scope=token_data["scope"] or "mcp:read mcp:write",
    )


# ============================================
# TOKEN VALIDATION (for resource server)
# ============================================

async def validate_bearer_token(token: str) -> Optional[dict]:
    """
    Validate a Bearer token and return user info.

    Args:
        token: Bearer token (mcp_at_xxx)

    Returns:
        Dict with user_id, company_id, scope or None if invalid
    """
    if not token.startswith("mcp_at_"):
        return None

    supabase = get_supabase_client()
    token_hash = hash_token(token)

    result = supabase.client.table("mcp_oauth_tokens")\
        .select("user_id, company_id, scope, access_token_expires_at")\
        .eq("access_token_hash", token_hash)\
        .is_("revoked_at", "null")\
        .maybe_single()\
        .execute()

    if not result.data:
        return None

    # Check expiry
    expires_at = datetime.fromisoformat(
        result.data["access_token_expires_at"].replace("Z", "+00:00")
    )
    if is_expired(expires_at):
        return None

    return {
        "user_id": result.data["user_id"],
        "company_id": result.data["company_id"],
        "scope": result.data["scope"],
    }


# ============================================
# HELPER FUNCTIONS
# ============================================

def _redirect_error(
    redirect_uri: str,
    error: str,
    state: Optional[str] = None,
    description: Optional[str] = None,
) -> RedirectResponse:
    """Redirect with OAuth error parameters."""
    params = {"error": error}
    if description:
        params["error_description"] = description
    if state:
        params["state"] = state

    return RedirectResponse(
        url=f"{redirect_uri}?{urlencode(params)}",
        status_code=302
    )


def _token_error(
    error: str,
    description: Optional[str] = None,
) -> JSONResponse:
    """Return OAuth token error response."""
    content = {"error": error}
    if description:
        content["error_description"] = description

    return JSONResponse(content=content, status_code=400)


def _render_login_page(
    client_id: str,
    client_name: str,
    redirect_uri: str,
    scope: str,
    state: Optional[str],
    code_challenge: str,
    code_challenge_method: str,
    error: Optional[str] = None,
) -> HTMLResponse:
    """Render the login HTML page."""
    error_html = ""
    if error:
        error_html = f'<div class="error">{error}</div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sign in - Semantika MCP</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            padding: 40px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .logo {{
            text-align: center;
            margin-bottom: 24px;
        }}
        .logo h1 {{
            font-size: 24px;
            color: #333;
        }}
        .logo p {{
            color: #666;
            margin-top: 8px;
        }}
        .client-info {{
            background: #f5f5f5;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 24px;
            text-align: center;
        }}
        .client-info p {{
            color: #666;
            font-size: 14px;
        }}
        .client-info strong {{
            color: #333;
        }}
        .error {{
            background: #fee;
            border: 1px solid #fcc;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 16px;
            color: #c00;
            text-align: center;
        }}
        .form-group {{
            margin-bottom: 16px;
        }}
        label {{
            display: block;
            margin-bottom: 6px;
            font-weight: 500;
            color: #333;
        }}
        input[type="email"],
        input[type="password"] {{
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.2s;
        }}
        input:focus {{
            outline: none;
            border-color: #667eea;
        }}
        button {{
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            border-radius: 8px;
            color: white;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }}
        .footer {{
            text-align: center;
            margin-top: 24px;
            color: #999;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <h1>Semantika</h1>
            <p>Sign in to continue</p>
        </div>

        <div class="client-info">
            <p><strong>{client_name}</strong> wants to access your account</p>
        </div>

        {error_html}

        <form method="POST" action="/mcp/oauth/login">
            <div class="form-group">
                <label for="email">Email</label>
                <input type="email" id="email" name="email" required autofocus>
            </div>

            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>

            <input type="hidden" name="client_id" value="{client_id}">
            <input type="hidden" name="redirect_uri" value="{redirect_uri}">
            <input type="hidden" name="scope" value="{scope or ''}">
            <input type="hidden" name="state" value="{state or ''}">
            <input type="hidden" name="code_challenge" value="{code_challenge}">
            <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">

            <button type="submit">Sign In</button>
        </form>

        <div class="footer">
            Secured by Semantika OAuth 2.1
        </div>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)


def _render_consent_page(
    session_token: str,
    user_email: str,
    client_name: str,
    scope: str,
    client_id: str,
    redirect_uri: str,
    state: Optional[str],
    code_challenge: str,
    code_challenge_method: str,
) -> HTMLResponse:
    """Render the consent HTML page."""
    # Parse scopes for display
    scopes = scope.split() if scope else ["mcp:read", "mcp:write"]
    scope_items = ""
    for s in scopes:
        if s == "mcp:read":
            scope_items += '<li>Read your news and articles</li>'
        elif s == "mcp:write":
            scope_items += '<li>Create and modify articles</li>'
        else:
            scope_items += f'<li>{s}</li>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authorize - Semantika MCP</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            padding: 40px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .header {{
            text-align: center;
            margin-bottom: 24px;
        }}
        .header h1 {{
            font-size: 24px;
            color: #333;
        }}
        .user-info {{
            background: #f5f5f5;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 24px;
            text-align: center;
        }}
        .user-info p {{
            color: #666;
            font-size: 14px;
        }}
        .permissions {{
            margin-bottom: 24px;
        }}
        .permissions h2 {{
            font-size: 16px;
            color: #333;
            margin-bottom: 12px;
        }}
        .permissions ul {{
            list-style: none;
            padding: 0;
        }}
        .permissions li {{
            padding: 10px 12px;
            background: #f9f9f9;
            border-radius: 6px;
            margin-bottom: 8px;
            color: #555;
        }}
        .permissions li:before {{
            content: "\\2713";
            color: #667eea;
            margin-right: 10px;
            font-weight: bold;
        }}
        .buttons {{
            display: flex;
            gap: 12px;
        }}
        button {{
            flex: 1;
            padding: 14px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }}
        .approve {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .deny {{
            background: #e0e0e0;
            color: #666;
        }}
        button:hover {{
            transform: translateY(-2px);
        }}
        .footer {{
            text-align: center;
            margin-top: 24px;
            color: #999;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Authorize {client_name}</h1>
        </div>

        <div class="user-info">
            <p>Signed in as <strong>{user_email}</strong></p>
        </div>

        <div class="permissions">
            <h2>This application will be able to:</h2>
            <ul>
                {scope_items}
            </ul>
        </div>

        <div class="buttons">
            <form method="POST" action="/mcp/oauth/consent" style="flex: 1;">
                <input type="hidden" name="consent" value="deny">
                <input type="hidden" name="session_token" value="{session_token}">
                <input type="hidden" name="client_id" value="{client_id}">
                <input type="hidden" name="redirect_uri" value="{redirect_uri}">
                <input type="hidden" name="scope" value="{scope or ''}">
                <input type="hidden" name="state" value="{state or ''}">
                <input type="hidden" name="code_challenge" value="{code_challenge}">
                <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
                <button type="submit" class="deny">Deny</button>
            </form>

            <form method="POST" action="/mcp/oauth/consent" style="flex: 1;">
                <input type="hidden" name="consent" value="approve">
                <input type="hidden" name="session_token" value="{session_token}">
                <input type="hidden" name="client_id" value="{client_id}">
                <input type="hidden" name="redirect_uri" value="{redirect_uri}">
                <input type="hidden" name="scope" value="{scope or ''}">
                <input type="hidden" name="state" value="{state or ''}">
                <input type="hidden" name="code_challenge" value="{code_challenge}">
                <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
                <button type="submit" class="approve">Authorize</button>
            </form>
        </div>

        <div class="footer">
            Secured by Semantika OAuth 2.1
        </div>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)
