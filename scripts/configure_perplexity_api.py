#!/usr/bin/env python3
"""
Script para probar la conexión con Perplexity API.

La API key se lee desde la variable de entorno PERPLEXITY_API_KEY.

Uso:
    python scripts/configure_perplexity_api.py --test
"""

import asyncio
import argparse
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import settings
from utils.logger import get_logger

logger = get_logger("test_perplexity")


async def test_perplexity_connection() -> bool:
    """
    Test Perplexity API connection using environment variable.
        
    Returns:
        Connection success
    """
    try:
        api_key = settings.perplexity_api_key
        if not api_key:
            logger.error("missing_perplexity_api_key_env")
            return False
            
        from sources.perplexity_news_connector import PerplexityNewsConnector
        
        connector = PerplexityNewsConnector(api_key)
        news_items = await connector.fetch_news("Madrid", 1)
        
        if news_items:
            logger.info("perplexity_connection_test_success", items_count=len(news_items))
            print(f"✅ Successfully fetched {len(news_items)} test news item(s)")
            print(f"📰 First item: {news_items[0].get('titulo', 'N/A')}")
            return True
        else:
            logger.warn("perplexity_connection_test_no_results")
            return False
            
    except Exception as e:
        logger.error("perplexity_connection_test_error", error=str(e))
        return False


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Test Perplexity API connection")
    parser.add_argument("--test", action="store_true", default=True, help="Test API connection")
    
    args = parser.parse_args()
    
    print("Testing Perplexity API connection...")
    print(f"Using API key from environment: PERPLEXITY_API_KEY")
    
    success = await test_perplexity_connection()
    
    if success:
        print("✅ Perplexity API connection test successful")
        print("📰 The 'Medios Generalistas' source is ready to fetch news daily at 9:00 AM")
    else:
        print("❌ Perplexity API connection test failed")
        print("🔑 Check that PERPLEXITY_API_KEY environment variable is set correctly")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())