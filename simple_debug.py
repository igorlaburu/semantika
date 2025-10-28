#!/usr/bin/env python3
"""
Debug simple para verificar formato de respuesta de OpenRouter.
"""

import os
import asyncio
import httpx
import json

async def test_openrouter_response():
    """Test directo a OpenRouter para ver formato de respuesta."""
    
    # API key from .env
    api_key = "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"
        
    if not api_key:
        print("❌ No se encontró OPENROUTER_API_KEY en .env")
        return
        
    print("🔍 Testeando respuesta directa de OpenRouter...")
    
    # Test request directo
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "anthropic/claude-3.5-sonnet",
                "messages": [
                    {"role": "user", "content": "Di 'test' en una palabra"}
                ],
                "temperature": 0.0
            }
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("\n📋 Respuesta completa:")
            print(json.dumps(data, indent=2))
            
            # Verificar si hay usage
            if 'usage' in data:
                print(f"\n✅ Usage encontrado: {data['usage']}")
            else:
                print("\n❌ No hay campo 'usage' en la respuesta")
                
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(test_openrouter_response())