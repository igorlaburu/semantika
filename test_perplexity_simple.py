#!/usr/bin/env python3
"""
Simple test for Perplexity API connection.
"""

import os
import asyncio
import aiohttp
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_perplexity_api():
    """Test Perplexity API with simple request."""
    
    api_key = os.getenv('PERPLEXITY_API_KEY')
    if not api_key:
        print("❌ PERPLEXITY_API_KEY not found in environment")
        print("Please add your Perplexity API key to the .env file:")
        print("PERPLEXITY_API_KEY=pplx-your-key-here")
        return False
    
    print(f"🔑 Using API key: {api_key[:10]}...")
    
    url = "https://api.perplexity.ai/chat/completions"
    
    payload = {
        "model": "sonar",
        "messages": [
            {"role": "user", "content": "2 noticias de Madrid. Responde SOLO este JSON: {\"news\": [{\"titulo\": \"...\", \"texto\": \"...\", \"fuente\": \"URL\", \"fecha\": \"YYYY-MM-DD\"}]}"}
        ],
        "temperature": 0.1,
        "max_tokens": 1000
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                
                print(f"📡 Response status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    print("✅ Perplexity API connection successful!")
                    print(f"📰 Response preview: {content[:200]}...")
                    
                    try:
                        # Try to parse as JSON
                        if content.strip().startswith('```json'):
                            content = content.strip()[7:]
                        if content.strip().endswith('```'):
                            content = content.strip()[:-3]
                        
                        parsed = json.loads(content.strip())
                        if "news" in parsed:
                            print(f"🎯 Found {len(parsed['news'])} news items")
                            return True
                    except json.JSONDecodeError:
                        print("⚠️  Response is not valid JSON, but API connection works")
                        return True
                        
                else:
                    error_text = await response.text()
                    print(f"❌ API Error {response.status}: {error_text}")
                    return False
                    
    except Exception as e:
        print(f"❌ Connection error: {str(e)}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_perplexity_api())
    exit(0 if success else 1)