"""Factory for creating platform publishers."""

import json
from typing import Dict, Any, Optional
from .base_publisher import BasePublisher
from .wordpress_publisher import WordPressPublisher
from utils.logger import get_logger
from utils.config import settings

logger = get_logger("publisher_factory")


class PublisherFactory:
    """Factory to create publisher instances."""
    
    @staticmethod
    def create_publisher(
        platform_type: str,
        base_url: str,
        credentials_encrypted: bytes
    ) -> BasePublisher:
        """Create a publisher instance for the given platform.
        
        Args:
            platform_type: Platform identifier (wordpress, medium, etc.)
            base_url: Base URL for the platform
            credentials_encrypted: Encrypted credentials from database
            
        Returns:
            BasePublisher instance
            
        Raises:
            ValueError: If platform not supported or decryption fails
        """
        
        # Decrypt credentials
        try:
            from utils.supabase_client import get_supabase_client
            supabase = get_supabase_client()
            
            # Use PostgreSQL to decrypt
            decrypt_query = f"""
                SELECT pgp_sym_decrypt($1::bytea, '{settings.credentials_encryption_key}') as decrypted
            """
            
            result = supabase.client.rpc('execute_sql', {
                'query': decrypt_query,
                'params': [credentials_encrypted.hex()]
            }).execute()
            
            if not result.data:
                raise ValueError("Failed to decrypt credentials")
            
            decrypted_str = result.data[0]['decrypted']
            credentials = json.loads(decrypted_str)
            
        except Exception as e:
            logger.error("credential_decryption_failed", error=str(e))
            raise ValueError(f"Failed to decrypt credentials: {str(e)}")
        
        # Create publisher based on platform type
        if platform_type == "wordpress":
            return WordPressPublisher(credentials, base_url)
        # elif platform_type == "medium":
        #     return MediumPublisher(credentials, base_url)
        # elif platform_type == "substack":
        #     return SubstackPublisher(credentials, base_url)
        else:
            raise ValueError(f"Unsupported platform type: {platform_type}")
    
    @staticmethod
    def get_supported_platforms() -> list:
        """Get list of supported platform types."""
        return ["wordpress"]  # Add more as we implement them