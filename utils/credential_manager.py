"""Credential encryption/decryption utilities for publication targets."""

import json
from typing import Dict, Any
from utils.supabase_client import get_supabase_client
from utils.config import settings
from utils.logger import get_logger

logger = get_logger("credential_manager")


class CredentialManager:
    """Manages encrypted credentials for publication targets."""
    
    @staticmethod
    def encrypt_credentials(credentials: Dict[str, Any]) -> bytes:
        """Encrypt credentials using PostgreSQL pgcrypto.
        
        Args:
            credentials: Dictionary with platform credentials
            
        Returns:
            Encrypted bytes for database storage
        """
        try:
            supabase = get_supabase_client()
            
            # Convert to JSON string
            credentials_json = json.dumps(credentials)
            
            # Use PostgreSQL pgcrypto to encrypt
            encrypt_result = supabase.client.rpc('encrypt_credentials', {
                'data': credentials_json,
                'key': settings.credentials_encryption_key
            }).execute()
            
            if not encrypt_result.data:
                raise ValueError("Encryption failed")
            
            # Return as bytes (PostgreSQL returns hex string)
            encrypted_hex = encrypt_result.data
            return bytes.fromhex(encrypted_hex)
            
        except Exception as e:
            logger.error("credential_encryption_failed", error=str(e))
            raise ValueError(f"Failed to encrypt credentials: {str(e)}")
    
    @staticmethod
    def decrypt_credentials(credentials_encrypted: bytes) -> Dict[str, Any]:
        """Decrypt credentials using PostgreSQL pgcrypto.
        
        Args:
            credentials_encrypted: Encrypted bytes from database
            
        Returns:
            Decrypted credentials dictionary
        """
        try:
            supabase = get_supabase_client()
            
            # Convert bytes to hex string for PostgreSQL
            encrypted_hex = credentials_encrypted.hex()
            
            # Use PostgreSQL pgcrypto to decrypt
            decrypt_result = supabase.client.rpc('decrypt_credentials', {
                'encrypted_data': encrypted_hex,
                'key': settings.credentials_encryption_key
            }).execute()
            
            if not decrypt_result.data:
                raise ValueError("Decryption failed")
            
            decrypted_json = decrypt_result.data
            return json.loads(decrypted_json)
            
        except Exception as e:
            logger.error("credential_decryption_failed", error=str(e))
            raise ValueError(f"Failed to decrypt credentials: {str(e)}")
    
    @staticmethod
    def mask_credentials_for_logging(credentials: Dict[str, Any]) -> Dict[str, str]:
        """Mask sensitive data for safe logging.
        
        Args:
            credentials: Raw credentials dictionary
            
        Returns:
            Dictionary with masked values
        """
        masked = {}
        
        for key, value in credentials.items():
            if key in ['password', 'app_password', 'api_key', 'token', 'secret']:
                # Show only first 4 characters
                masked[key] = f"{str(value)[:4]}***masked***"
            else:
                masked[key] = value
        
        return masked