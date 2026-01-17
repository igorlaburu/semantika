"""Pydantic models for OAuth 2.1 requests and responses."""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
import re


class ClientRegistrationRequest(BaseModel):
    """Dynamic Client Registration request (RFC 7591)."""

    redirect_uris: List[str] = Field(
        ...,
        description="List of redirect URIs for the client",
        min_length=1
    )
    client_name: str = Field(
        default="MCP Client",
        description="Human-readable name of the client",
        max_length=255
    )
    grant_types: List[str] = Field(
        default=["authorization_code", "refresh_token"],
        description="Grant types the client will use"
    )
    scope: str = Field(
        default="mcp:read mcp:write",
        description="Space-separated scope string"
    )

    @field_validator("redirect_uris")
    @classmethod
    def validate_redirect_uris(cls, v):
        """Validate redirect URIs are valid URLs."""
        for uri in v:
            if not uri.startswith(("http://", "https://")):
                raise ValueError(f"Invalid redirect URI: {uri}")
        return v

    @field_validator("grant_types")
    @classmethod
    def validate_grant_types(cls, v):
        """Only allow supported grant types."""
        allowed = {"authorization_code", "refresh_token"}
        for grant_type in v:
            if grant_type not in allowed:
                raise ValueError(f"Unsupported grant type: {grant_type}")
        return v


class ClientRegistrationResponse(BaseModel):
    """Dynamic Client Registration response."""

    client_id: str
    client_secret: Optional[str] = None  # Only returned once at registration
    client_name: str
    redirect_uris: List[str]
    grant_types: List[str]
    scope: str
    client_id_issued_at: int  # Unix timestamp


class AuthorizeRequest(BaseModel):
    """Authorization endpoint request parameters."""

    response_type: str = Field(..., description="Must be 'code'")
    client_id: str = Field(..., description="Client identifier")
    redirect_uri: str = Field(..., description="Redirect URI")
    scope: Optional[str] = Field(default="mcp:read mcp:write", description="Requested scope")
    state: Optional[str] = Field(default=None, description="Opaque state value")
    code_challenge: str = Field(..., description="PKCE code challenge")
    code_challenge_method: str = Field(default="S256", description="Must be 'S256'")

    @field_validator("response_type")
    @classmethod
    def validate_response_type(cls, v):
        if v != "code":
            raise ValueError("response_type must be 'code'")
        return v

    @field_validator("code_challenge_method")
    @classmethod
    def validate_code_challenge_method(cls, v):
        if v != "S256":
            raise ValueError("code_challenge_method must be 'S256' (plain not supported)")
        return v

    @field_validator("code_challenge")
    @classmethod
    def validate_code_challenge(cls, v):
        # PKCE code_challenge should be base64url-encoded SHA256 (43 chars)
        if not re.match(r'^[A-Za-z0-9_-]{43}$', v):
            raise ValueError("Invalid code_challenge format")
        return v


class TokenRequest(BaseModel):
    """Token endpoint request."""

    grant_type: str = Field(..., description="'authorization_code' or 'refresh_token'")
    code: Optional[str] = Field(default=None, description="Authorization code")
    redirect_uri: Optional[str] = Field(default=None, description="Redirect URI (for auth code)")
    code_verifier: Optional[str] = Field(default=None, description="PKCE code verifier")
    refresh_token: Optional[str] = Field(default=None, description="Refresh token")
    client_id: str = Field(..., description="Client identifier")
    client_secret: Optional[str] = Field(default=None, description="Client secret")

    @field_validator("grant_type")
    @classmethod
    def validate_grant_type(cls, v):
        if v not in ("authorization_code", "refresh_token"):
            raise ValueError("grant_type must be 'authorization_code' or 'refresh_token'")
        return v


class TokenResponse(BaseModel):
    """Token endpoint response."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int  # Seconds until expiration
    refresh_token: Optional[str] = None
    scope: str


class TokenErrorResponse(BaseModel):
    """OAuth error response (RFC 6749 Section 5.2)."""

    error: str  # e.g., "invalid_request", "invalid_grant"
    error_description: Optional[str] = None
    error_uri: Optional[str] = None


class LoginRequest(BaseModel):
    """Login form submission."""

    email: str = Field(..., description="User email")
    password: str = Field(..., description="User password")

    # OAuth params preserved from authorize
    client_id: str
    redirect_uri: str
    scope: Optional[str] = None
    state: Optional[str] = None
    code_challenge: str
    code_challenge_method: str = "S256"


class ConsentRequest(BaseModel):
    """Consent form submission."""

    consent: str = Field(..., description="'approve' or 'deny'")

    # Session data
    session_token: str = Field(..., description="Session token from login")
    client_id: str
    redirect_uri: str
    scope: Optional[str] = None
    state: Optional[str] = None
    code_challenge: str
    code_challenge_method: str = "S256"


# OAuth Server Metadata (RFC 8414)
class OAuthServerMetadata(BaseModel):
    """OAuth Authorization Server Metadata."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str] = None
    scopes_supported: List[str]
    response_types_supported: List[str]
    grant_types_supported: List[str]
    code_challenge_methods_supported: List[str]
    token_endpoint_auth_methods_supported: List[str]


# Resource Server Metadata (RFC 8707)
class ResourceServerMetadata(BaseModel):
    """OAuth Resource Server Metadata."""

    resource: str
    authorization_servers: List[str]
    scopes_supported: Optional[List[str]] = None
    bearer_methods_supported: Optional[List[str]] = None
