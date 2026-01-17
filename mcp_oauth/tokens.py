"""Token generation and validation utilities.

Handles:
- Access token generation (opaque, prefixed with mcp_at_)
- Refresh token generation (opaque, prefixed with mcp_rt_)
- Token hashing for storage (SHA256)
- Client secret hashing (bcrypt)
- Session token generation for login flow
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any

from passlib.context import CryptContext

# bcrypt context for client secrets
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Token prefixes for easy identification
ACCESS_TOKEN_PREFIX = "mcp_at_"
REFRESH_TOKEN_PREFIX = "mcp_rt_"
CLIENT_ID_PREFIX = "mcp_"
SESSION_TOKEN_PREFIX = "mcp_session_"


def generate_client_credentials() -> Tuple[str, str, str]:
    """Generate client_id and client_secret for DCR.

    Returns:
        Tuple of (client_id, client_secret, client_secret_hash)
    """
    # Client ID: mcp_ + 32 random chars
    client_id = CLIENT_ID_PREFIX + secrets.token_urlsafe(24)

    # Client secret: 48 random chars (strong enough for public clients)
    client_secret = secrets.token_urlsafe(36)

    # Hash the secret for storage
    client_secret_hash = hash_client_secret(client_secret)

    return client_id, client_secret, client_secret_hash


def hash_client_secret(client_secret: str) -> str:
    """Hash a client secret using bcrypt.

    Args:
        client_secret: Plain text client secret

    Returns:
        Bcrypt hash string
    """
    return pwd_context.hash(client_secret)


def verify_client_secret(plain_secret: str, hashed_secret: str) -> bool:
    """Verify a client secret against its hash.

    Args:
        plain_secret: Plain text secret to verify
        hashed_secret: Stored bcrypt hash

    Returns:
        True if secret matches, False otherwise
    """
    return pwd_context.verify(plain_secret, hashed_secret)


def generate_access_token() -> Tuple[str, str]:
    """Generate an opaque access token.

    Returns:
        Tuple of (token, token_hash)
    """
    token = ACCESS_TOKEN_PREFIX + secrets.token_urlsafe(48)
    token_hash = hash_token(token)
    return token, token_hash


def generate_refresh_token() -> Tuple[str, str]:
    """Generate an opaque refresh token.

    Returns:
        Tuple of (token, token_hash)
    """
    token = REFRESH_TOKEN_PREFIX + secrets.token_urlsafe(48)
    token_hash = hash_token(token)
    return token, token_hash


def hash_token(token: str) -> str:
    """Hash a token using SHA256 for storage.

    Args:
        token: Plain text token

    Returns:
        Hex-encoded SHA256 hash
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    """Generate a temporary session token for the login flow.

    Returns:
        Session token string
    """
    return SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)


def calculate_expiry(seconds: int) -> datetime:
    """Calculate expiry timestamp from now.

    Args:
        seconds: Number of seconds until expiry

    Returns:
        Datetime with timezone (UTC)
    """
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def is_expired(expiry: datetime) -> bool:
    """Check if a timestamp has expired.

    Args:
        expiry: Expiry datetime (should be timezone-aware)

    Returns:
        True if expired, False otherwise
    """
    now = datetime.now(timezone.utc)

    # Handle timezone-naive datetimes (treat as UTC)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    return now > expiry


class SessionStore:
    """In-memory session store for the login flow.

    Stores temporary session data between login and consent.
    Sessions expire after 10 minutes.
    """

    def __init__(self, expiry_seconds: int = 600):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._expiry_seconds = expiry_seconds

    def create(self, user_id: str, company_id: str, email: str, oauth_params: dict) -> str:
        """Create a new session.

        Args:
            user_id: Authenticated user ID
            company_id: User's company ID
            email: User's email
            oauth_params: OAuth parameters to preserve

        Returns:
            Session token
        """
        self._cleanup_expired()

        token = generate_session_token()
        self._sessions[token] = {
            "user_id": user_id,
            "company_id": company_id,
            "email": email,
            "oauth_params": oauth_params,
            "created_at": datetime.now(timezone.utc),
            "expires_at": calculate_expiry(self._expiry_seconds)
        }
        return token

    def get(self, token: str) -> Optional[Dict[str, Any]]:
        """Get session data if valid.

        Args:
            token: Session token

        Returns:
            Session data dict or None if invalid/expired
        """
        self._cleanup_expired()

        session = self._sessions.get(token)
        if session and not is_expired(session["expires_at"]):
            return session
        return None

    def delete(self, token: str) -> bool:
        """Delete a session.

        Args:
            token: Session token

        Returns:
            True if session existed and was deleted
        """
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False

    def _cleanup_expired(self):
        """Remove expired sessions."""
        now = datetime.now(timezone.utc)
        expired = [
            token for token, session in self._sessions.items()
            if is_expired(session["expires_at"])
        ]
        for token in expired:
            del self._sessions[token]


# Global session store instance
login_sessions = SessionStore()
