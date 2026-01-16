"""Authentication endpoints (Supabase Auth)."""

import os
import uuid as uuid_module
from datetime import datetime
from typing import Dict, Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.supabase_auth import get_current_user_from_jwt
from utils.auth_dependencies import get_company_id_from_auth

logger = get_logger("api.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Request model for login."""
    email: str
    password: str


class RefreshTokenRequest(BaseModel):
    """Request model for token refresh."""
    refresh_token: str


class SignupRequest(BaseModel):
    """Request model for user signup."""
    email: str
    password: str
    company_name: str
    cif: str  # Company tax ID (CIF in Spain)
    tier: str = "starter"  # starter, pro, unlimited

@router.post("/signup")
async def auth_signup(request: SignupRequest) -> Dict:
    """
    Sign up new user with a new company.

    Currently only allows creating new companies (1 user per company limit).

    Body:
        - email: User email
        - password: User password
        - company_name: Company name
        - cif: Company tax ID (CIF)
        - tier: Company tier (starter/pro/unlimited, default: starter)

    Returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "user": {...},
            "company": {...}
        }
    """
    try:
        # Validate tier
        valid_tiers = ["starter", "pro", "unlimited"]
        if request.tier not in valid_tiers:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier. Must be one of: {', '.join(valid_tiers)}"
            )

        # Normalize CIF (uppercase, remove spaces)
        cif_normalized = request.cif.upper().replace(" ", "")

        # Check if company with this CIF already exists
        supabase = get_supabase_client()
        existing_company = supabase.client.table("companies")\
            .select("id, company_code, company_name")\
            .eq("company_code", cif_normalized)\
            .maybe_single()\
            .execute()

        if existing_company and existing_company.data:
            logger.warn("signup_company_exists",
                cif=cif_normalized,
                company_name=existing_company.data["company_name"]
            )
            raise HTTPException(
                status_code=400,
                detail="Una empresa con este CIF ya está registrada. Por ahora solo permitimos nuevas empresas."
            )

        # Create company first
        logger.debug("creating_company", cif=cif_normalized, name=request.company_name)
        company_result = supabase.client.table("companies")\
            .insert({
                "company_code": cif_normalized,
                "company_name": request.company_name,
                "tier": request.tier,
                "is_active": True
            })\
            .execute()

        logger.debug("company_insert_result", result_type=str(type(company_result)), has_data=hasattr(company_result, 'data') if company_result else False)

        if not company_result or not company_result.data:
            logger.error("company_creation_failed", result=str(company_result))
            raise HTTPException(status_code=500, detail="Failed to create company")

        company = company_result.data[0]
        company_id = company["id"]

        logger.info("company_created",
            company_id=company_id,
            cif=cif_normalized,
            name=request.company_name
        )

        # Note: Manual source is created via CLI (python cli.py create-company)
        # NOT here, as signup is not used for production onboarding

        # Create user in Supabase Auth with company_id in metadata
        # Use supabase client's auth methods directly
        logger.debug("creating_auth_user", email=request.email, company_id=company_id)
        auth_response = supabase.client.auth.sign_up({
            "email": request.email,
            "password": request.password,
            "options": {
                "data": {
                    "company_id": company_id,
                    "name": request.email.split("@")[0]  # Default name from email
                }
            }
        })

        logger.debug("auth_signup_result", result_type=str(type(auth_response)), has_user=hasattr(auth_response, 'user') if auth_response else False)

        if not auth_response or not auth_response.user:
            # Rollback: delete company if user creation failed
            supabase.client.table("companies").delete().eq("id", company_id).execute()
            raise HTTPException(status_code=500, detail="Failed to create user")

        logger.info("user_created",
            email=request.email,
            user_id=auth_response.user.id,
            company_id=company_id
        )

        # Return JWT tokens
        return {
            "access_token": auth_response.session.access_token if auth_response.session else None,
            "refresh_token": auth_response.session.refresh_token if auth_response.session else None,
            "expires_in": auth_response.session.expires_in if auth_response.session else None,
            "user": {
                "id": auth_response.user.id,
                "email": auth_response.user.email,
                "created_at": auth_response.user.created_at
            },
            "company": {
                "id": company_id,
                "name": request.company_name,
                "cif": cif_normalized,
                "tier": request.tier
            },
            "message": "Usuario y empresa creados correctamente. Revisa tu email para confirmar la cuenta."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("signup_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")


@router.post("/login")
async def auth_login(request: LoginRequest) -> Dict:
    """
    Login with email and password using Supabase Auth.

    Returns JWT access token and refresh token.

    Body:
        - email: User email
        - password: User password

    Returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600,
            "user": {...}
        }
    """
    try:
        # Use Supabase auth to login
        supabase = get_supabase_client()

        response = supabase.client.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password
        })

        if not response or not response.session:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Get user from database to get company_id
        user_result = supabase.client.table("users")\
            .select("id, email, name, company_id, role")\
            .eq("auth_user_id", response.user.id)\
            .single()\
            .execute()

        if not user_result or not user_result.data:
            raise HTTPException(status_code=404, detail="User not found in database")

        user_data = user_result.data
        company_id = user_data.get("company_id")

        if not company_id:
            raise HTTPException(status_code=403, detail="User must be assigned to a company")

        # Get company info
        company_result = supabase.client.table("companies")\
            .select("id, company_name, company_code, tier")\
            .eq("id", company_id)\
            .single()\
            .execute()

        if not company_result or not company_result.data:
            raise HTTPException(status_code=404, detail="Company not found")

        logger.info("user_logged_in",
            email=request.email,
            user_id=response.user.id,
            company_id=company_id
        )

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in,
            "user": {
                "id": user_data["id"],
                "email": user_data["email"],
                "name": user_data.get("name"),
                "role": user_data.get("role")
            },
            "company": {
                "id": company_result.data["id"],
                "name": company_result.data["company_name"],
                "cif": company_result.data["company_code"],
                "tier": company_result.data["tier"]
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("login_error", error=str(e))
        raise HTTPException(status_code=500, detail="Login failed")


@router.post("/refresh")
async def auth_refresh(request: RefreshTokenRequest) -> Dict:
    """
    Refresh access token using refresh token.

    Body:
        - refresh_token: Valid refresh token

    Returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600
        }
    """
    try:
        supabase = get_supabase_client()

        response = supabase.client.auth.refresh_session(request.refresh_token)

        if not response or not response.session:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("refresh_token_error", error=str(e))
        raise HTTPException(status_code=500, detail="Token refresh failed")


@router.post("/logout")
async def auth_logout(authorization: Optional[str] = Header(None)) -> Dict:
    """
    Logout current user (invalidate token).

    Requires: Authorization header with Bearer token

    Returns:
        {"success": true}
    """
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header required")

        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization header")

        token = parts[1]

        supabase = get_supabase_client()
        supabase.client.auth.sign_out()

        logger.info("user_logged_out")

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("logout_error", error=str(e))
        raise HTTPException(status_code=500, detail="Logout failed")


@router.post("/forgot-password")
async def auth_forgot_password(data: Dict[str, Any]) -> Dict:
    """
    Request password reset email.

    Body:
        {"email": "user@example.com"}

    Returns:
        {"success": true, "message": "If the email exists, a reset link has been sent"}
    """
    try:
        email = data.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        supabase = get_supabase_client()

        # Get the frontend URL for the reset link
        redirect_url = os.getenv("FRONTEND_URL", "https://press.ekimen.ai") + "/reset-password"

        # Request password reset - Supabase will send the email
        supabase.client.auth.reset_password_email(
            email,
            options={"redirect_to": redirect_url}
        )

        logger.info("password_reset_requested", email=email[:3] + "***")

        # Always return success to prevent email enumeration
        return {
            "success": True,
            "message": "If the email exists, a reset link has been sent"
        }

    except Exception as e:
        logger.error("forgot_password_error", error=str(e))
        # Still return success to prevent email enumeration
        return {
            "success": True,
            "message": "If the email exists, a reset link has been sent"
        }


@router.post("/reset-password")
async def auth_reset_password(data: Dict[str, Any]) -> Dict:
    """
    Reset password using token from email link.

    Body:
        {"access_token": "token_from_url", "password": "new_password"}

    Returns:
        {"success": true, "message": "Password updated successfully"}
    """
    try:
        access_token = data.get("access_token") or data.get("token")
        new_password = data.get("password")

        if not access_token:
            raise HTTPException(status_code=400, detail="Access token is required")
        if not new_password:
            raise HTTPException(status_code=400, detail="New password is required")
        if len(new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

        supabase = get_supabase_client()

        # Set the session with the recovery token
        session = supabase.client.auth.set_session(access_token, "")

        if not session:
            raise HTTPException(status_code=400, detail="Invalid or expired token")

        # Update the password
        supabase.client.auth.update_user({"password": new_password})

        logger.info("password_reset_completed")

        return {
            "success": True,
            "message": "Password updated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("reset_password_error", error=str(e))
        raise HTTPException(status_code=400, detail="Failed to reset password. Token may be invalid or expired.")


@router.get("/user")
async def auth_get_user() -> Dict:
    """
    Get current authenticated user info (from JWT).

    Requires: Authorization header with Bearer token

    Returns:
        User information including company_id, role, etc.
    """
    from utils.supabase_auth import get_current_user_from_jwt

    user = await get_current_user_from_jwt()

    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name"),
        "company_id": user["company_id"],
        "organization_id": user.get("organization_id"),
        "role": user.get("role"),
        "is_active": user["is_active"]
    }
