"""Authentication dependencies for FastAPI endpoints.

Provides unified authentication supporting both JWT tokens and API keys.
"""

from typing import Dict, Optional
from fastapi import Header, HTTPException, Depends

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.supabase_auth import get_current_user_from_jwt

logger = get_logger("auth")

# Get supabase client singleton
_supabase_client = get_supabase_client()


async def get_api_key(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
) -> str:
    """Extract API key from X-API-Key or Authorization Bearer header."""
    if x_api_key:
        return x_api_key

    if authorization:
        if authorization.startswith("Bearer "):
            return authorization[7:]
        return authorization

    logger.warn("missing_api_key")
    raise HTTPException(status_code=401, detail="Missing API Key")


async def get_current_client(api_key: str = Depends(get_api_key)) -> Dict:
    """
    Get current authenticated client from API key.

    Args:
        api_key: API key from header

    Returns:
        Client data

    Raises:
        HTTPException: If API key is invalid
    """
    client = await _supabase_client.get_client_by_api_key(api_key)

    if not client:
        logger.warn("invalid_api_key", api_key_prefix=api_key[:10])
        raise HTTPException(status_code=403, detail="Invalid API Key")

    logger.debug("client_authenticated", client_id=client["client_id"])
    return client


async def get_current_user_from_jwt_optional(authorization: Optional[str] = Header(None)) -> Optional[Dict]:
    """Optional version of get_current_user_from_jwt - returns None if no token."""
    if not authorization:
        return None
    try:
        return await get_current_user_from_jwt(authorization)
    except HTTPException:
        return None


async def get_current_client_optional(x_api_key: Optional[str] = Header(None)) -> Optional[Dict]:
    """Optional version of get_current_client - returns None if no API key."""
    if not x_api_key:
        return None
    try:
        client = await _supabase_client.get_client_by_api_key(x_api_key)
        if client:
            logger.debug("client_authenticated", client_id=client["client_id"])
        return client
    except Exception:
        return None


async def get_company_id_from_auth(
    user: Optional[Dict] = Depends(get_current_user_from_jwt_optional),
    client: Optional[Dict] = Depends(get_current_client_optional)
) -> str:
    """
    Get company_id from either JWT or API Key (whichever is provided).

    Allows endpoints to accept both authentication methods.
    Useful for testing with API Key while frontend uses JWT.

    Args:
        user: User from JWT (optional)
        client: Client from API Key (optional)

    Returns:
        company_id string

    Raises:
        HTTPException: If neither auth method provided
    """
    if user:
        logger.debug("auth_via_jwt", user_id=user.get("sub"), company_id=user["company_id"])
        return user["company_id"]
    elif client:
        logger.debug("auth_via_api_key", client_id=client["client_id"], company_id=client["company_id"])
        return client["company_id"]
    else:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide either JWT token (Authorization: Bearer) or API Key (X-API-Key)"
        )


async def get_auth_context(
    user: Optional[Dict] = Depends(get_current_user_from_jwt_optional),
    client: Optional[Dict] = Depends(get_current_client_optional)
) -> Dict:
    """
    Get unified auth context from either JWT or API Key.

    This is the primary authentication dependency for endpoints that need
    both client_id and company_id. Accepts either authentication method.

    Args:
        user: User from JWT (optional)
        client: Client from API Key (optional)

    Returns:
        Dict with:
            - client_id: str (from client or looked up by company_id)
            - company_id: str
            - auth_type: "jwt" or "api_key"
            - user_id: str or None (only for JWT)
            - email: str or None (only for JWT)
            - client_name: str or None (only for API Key)

    Raises:
        HTTPException: If neither auth method provided or no client found
    """
    if client:
        # API Key auth - use client data directly
        logger.debug("auth_context_api_key",
            client_id=client["client_id"],
            company_id=client["company_id"]
        )
        return {
            "client_id": client["client_id"],
            "company_id": client["company_id"],
            "auth_type": "api_key",
            "user_id": None,
            "email": None,
            "client_name": client.get("client_name"),
            "is_active": client.get("is_active"),
            "created_at": client.get("created_at")
        }
    elif user:
        # JWT auth - look up client by company_id
        company_id = user["company_id"]
        supabase = get_supabase_client()

        # Find client associated with this company
        result = supabase.client.table("clients")\
            .select("client_id, client_name, is_active, created_at")\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .limit(1)\
            .execute()

        if not result.data:
            logger.warn("no_client_for_company", company_id=company_id, user_email=user.get("email"))
            raise HTTPException(
                status_code=403,
                detail=f"No active client found for company. Please contact support."
            )

        client_data = result.data[0]
        logger.debug("auth_context_jwt",
            user_id=user.get("id"),
            company_id=company_id,
            client_id=client_data["client_id"]
        )

        return {
            "client_id": client_data["client_id"],
            "company_id": company_id,
            "auth_type": "jwt",
            "user_id": user.get("id"),
            "email": user.get("email"),
            "client_name": client_data.get("client_name"),
            "is_active": client_data.get("is_active"),
            "created_at": client_data.get("created_at")
        }
    else:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Use Bearer token or X-API-Key header."
        )
