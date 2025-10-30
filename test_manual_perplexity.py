#!/usr/bin/env python3
"""
Test manual execution of Perplexity task
"""

import asyncio
import json
from utils.supabase_client import get_supabase_client
from sources.perplexity_news_connector import execute_perplexity_news_task

async def test_manual_execution():
    print("🔍 Obteniendo fuente de Perplexity...")
    
    supabase = get_supabase_client()
    result = supabase.client.table('sources').select('*').eq('source_name', 'Medios Generalistas').execute()
    
    if not result.data:
        print("❌ No se encontró la fuente 'Medios Generalistas'")
        return
        
    source = result.data[0]
    print(f"✅ Fuente encontrada: {source['source_name']}")
    print(f"📋 Config: {json.dumps(source['config'], indent=2)}")
    
    print("\n🚀 Ejecutando task de Perplexity...")
    result = await execute_perplexity_news_task(source)
    
    print(f"\n📊 Resultado:")
    print(json.dumps(result, indent=2))
    
    if result.get('success'):
        print(f"\n✅ ÉXITO: {result.get('items_processed', 0)} noticias procesadas")
    else:
        print(f"\n❌ ERROR: {result.get('error', 'Error desconocido')}")

if __name__ == "__main__":
    asyncio.run(test_manual_execution())