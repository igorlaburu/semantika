#!/usr/bin/env python3
"""
Script para configurar la API key de Perplexity en la fuente Medios Generalistas.

Uso:
    python scripts/configure_perplexity_api.py --api-key "pplx-xxxxx"
"""

import asyncio
import argparse
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.supabase_client import get_supabase_client
from utils.logger import get_logger

logger = get_logger("configure_perplexity")


async def configure_perplexity_api_key(api_key: str) -> bool:
    """
    Configure Perplexity API key for Medios Generalistas source.
    
    Args:
        api_key: Perplexity API key
        
    Returns:
        Success status
    """
    try:
        supabase = get_supabase_client()
        
        # Find the Medios Generalistas source
        result = supabase.client.table("sources")\
            .select("source_id, config")\
            .eq("source_code", "medios_generalistas")\
            .single()\
            .execute()
        
        if not result.data:
            logger.error("medios_generalistas_source_not_found")
            return False
        
        source_id = result.data["source_id"]
        current_config = result.data["config"]
        
        # Update config with real API key
        updated_config = {**current_config, "perplexity_api_key": api_key}
        
        # Update the source
        update_result = supabase.client.table("sources")\
            .update({"config": updated_config})\
            .eq("source_id", source_id)\
            .execute()
        
        if update_result.data:
            logger.info("perplexity_api_key_configured", 
                source_id=source_id,
                api_key_prefix=api_key[:10] + "..."
            )
            return True
        else:
            logger.error("failed_to_update_source")
            return False
            
    except Exception as e:
        logger.error("configure_api_key_error", error=str(e))
        return False


async def test_perplexity_connection(api_key: str) -> bool:
    """
    Test Perplexity API connection.
    
    Args:
        api_key: Perplexity API key
        
    Returns:
        Connection success
    """
    try:
        from sources.perplexity_news_connector import PerplexityNewsConnector
        
        connector = PerplexityNewsConnector(api_key)
        news_items = await connector.fetch_news("Madrid", 1)
        
        if news_items:
            logger.info("perplexity_connection_test_success", items_count=len(news_items))
            return True
        else:
            logger.warn("perplexity_connection_test_no_results")
            return False
            
    except Exception as e:
        logger.error("perplexity_connection_test_error", error=str(e))
        return False


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Configure Perplexity API key")
    parser.add_argument("--api-key", required=True, help="Perplexity API key")
    parser.add_argument("--test", action="store_true", help="Test API connection")
    
    args = parser.parse_args()
    
    if args.test:
        print("Testing Perplexity API connection...")
        success = await test_perplexity_connection(args.api_key)
        if success:
            print("✅ API connection test successful")
        else:
            print("❌ API connection test failed")
            sys.exit(1)
    
    print("Configuring Perplexity API key...")
    success = await configure_perplexity_api_key(args.api_key)
    
    if success:
        print("✅ Perplexity API key configured successfully")
        print("📰 The 'Medios Generalistas' source will now fetch news daily at 9:00 AM")
    else:
        print("❌ Failed to configure API key")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())