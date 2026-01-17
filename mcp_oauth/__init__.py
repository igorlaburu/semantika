"""MCP OAuth 2.1 Authentication Module.

Provides OAuth 2.1 authentication with PKCE for the MCP server,
enabling Claude.ai and other MCP clients to authenticate securely.

Components:
- models: Pydantic models for OAuth requests/responses
- pkce: PKCE (S256) utilities
- tokens: Token generation and validation
- routes: FastAPI router with OAuth endpoints
"""

from .routes import oauth_router

__all__ = ["oauth_router"]
