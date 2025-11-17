"""Supabase authentication utilities for JWT validation.

Handles user authentication via Supabase Auth JWT tokens.
Supports both API key authentication (for backend integrations)
and JWT authentication (for web users).
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException, Header
import jwt
from jwt import PyJWKClient

from utils.config import settings
from utils.supabase_client import get_supabase_client
from utils.logger import get_logger

logger = get_logger("supabase_auth")


class SupabaseAuth:
    """Supabase authentication handler."""

    def __init__(self):
        """Initialize Supabase auth with JWT configuration."""
        # Supabase JWT settings
        self.jwt_secret = settings.supabase_jwt_secret
        self.supabase_url = settings.supabase_url

        # JWK client for RS256 verification (if using)
        self.jwks_url = f"{self.supabase_url}/auth/v1/jwks"

        logger.info("supabase_auth_initialized")

    def verify_jwt(self, token: str) -> Dict[str, Any]:
        """Verify Supabase JWT token.

        Args:
            token: JWT token from Authorization header

        Returns:
            Decoded JWT payload with user info

        Raises:
            HTTPException: If token is invalid
        """
        try:
            # Supabase uses HS256 by default (with JWT secret)
            # If you're using RS256, use PyJWKClient instead
            decoded = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                audience="authenticated"
            )

            return decoded

        except jwt.ExpiredSignatureError:
            logger.warn("jwt_token_expired")
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError as e:
            logger.warn("jwt_token_invalid", error=str(e))
            raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error("jwt_verification_error", error=str(e))
            raise HTTPException(status_code=401, detail="Authentication failed")

    def get_user_from_token(self, token: str) -> Dict[str, Any]:
        """Get user information from JWT token.

        Args:
            token: JWT token

        Returns:
            User data including auth_user_id, email, company_id

        Raises:
            HTTPException: If user not found or invalid
        """
        # Verify JWT
        payload = self.verify_jwt(token)

        auth_user_id = payload.get("sub")
        if not auth_user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        # Get user from database
        supabase = get_supabase_client()
        result = supabase.client.table("users")\
            .select("id, auth_user_id, email, name, company_id, organization_id, role, is_active")\
            .eq("auth_user_id", auth_user_id)\
            .maybe_single()\
            .execute()

        if not result.data:
            logger.warn("user_not_found_for_jwt", auth_user_id=auth_user_id)
            raise HTTPException(status_code=404, detail="User not found")

        user = result.data

        if not user.get("is_active"):
            raise HTTPException(status_code=403, detail="User account is inactive")

        if not user.get("company_id"):
            logger.warn("user_without_company", user_id=user["id"])
            raise HTTPException(status_code=403, detail="User must be assigned to a company")

        logger.debug("user_authenticated",
            user_id=user["id"],
            email=user["email"],
            company_id=user["company_id"]
        )

        return user


# Global auth instance
_supabase_auth: Optional[SupabaseAuth] = None


def get_supabase_auth() -> SupabaseAuth:
    """Get or create Supabase auth singleton.

    Returns:
        SupabaseAuth instance
    """
    global _supabase_auth
    if _supabase_auth is None:
        _supabase_auth = SupabaseAuth()
    return _supabase_auth


async def get_current_user_from_jwt(
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """FastAPI dependency to get current user from JWT.

    Args:
        authorization: Authorization header (Bearer <token>)

    Returns:
        User dict

    Raises:
        HTTPException: If authentication fails
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]

    auth = get_supabase_auth()
    return auth.get_user_from_token(token)
