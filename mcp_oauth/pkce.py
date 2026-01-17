"""PKCE (Proof Key for Code Exchange) utilities.

Implements RFC 7636 for OAuth 2.1 security.
Only S256 method is supported (plain is insecure and rejected).
"""

import hashlib
import base64
import secrets


def generate_code_verifier(length: int = 64) -> str:
    """Generate a cryptographically random code verifier.

    Args:
        length: Length of the verifier (43-128 chars, default 64)

    Returns:
        Random URL-safe string
    """
    # Use 48 bytes to get 64 base64url characters
    random_bytes = secrets.token_bytes(48)
    return base64.urlsafe_b64encode(random_bytes).decode("ascii").rstrip("=")


def generate_code_challenge(code_verifier: str) -> str:
    """Generate S256 code challenge from code verifier.

    Args:
        code_verifier: The code verifier string

    Returns:
        Base64url-encoded SHA256 hash (43 characters)
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_code_challenge(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """Verify that code_verifier matches code_challenge.

    Args:
        code_verifier: The original code verifier
        code_challenge: The code challenge to verify against
        method: Challenge method (only "S256" supported)

    Returns:
        True if verification passes, False otherwise

    Raises:
        ValueError: If method is not S256
    """
    if method != "S256":
        raise ValueError("Only S256 code_challenge_method is supported")

    # Calculate the expected challenge from the verifier
    expected_challenge = generate_code_challenge(code_verifier)

    # Use constant-time comparison to prevent timing attacks
    return secrets.compare_digest(expected_challenge, code_challenge)


def generate_authorization_code() -> str:
    """Generate a secure random authorization code.

    Returns:
        Random URL-safe string (64 characters)
    """
    return secrets.token_urlsafe(48)


# For testing/debugging
if __name__ == "__main__":
    # Generate a test PKCE pair
    verifier = generate_code_verifier()
    challenge = generate_code_challenge(verifier)

    print(f"Code Verifier: {verifier}")
    print(f"Code Challenge: {challenge}")
    print(f"Verification: {verify_code_challenge(verifier, challenge)}")
