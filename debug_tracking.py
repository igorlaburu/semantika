#!/usr/bin/env python3
"""
Debug script para diagnosticar por qué no se registra el tracking de LLM.
"""

import asyncio
import json
from utils.openrouter_client import get_openrouter_client
from utils.usage_tracker import get_usage_tracker
from utils.logger import get_logger

logger = get_logger("debug_tracking")

async def test_tracking():
    """Test the LLM tracking system."""
    print("🔍 Iniciando diagnóstico del sistema de tracking de LLM...")
    
    try:
        # 1. Test conexión con OpenRouter
        print("\n1️⃣ Testeando conexión con OpenRouter...")
        client = get_openrouter_client()
        
        # 2. Test simple sin tracking
        print("\n2️⃣ Llamada LLM sin tracking...")
        response = await client.llm_sonnet.ainvoke([
            ("human", "Di 'hola' en una palabra")
        ])
        
        print(f"   Respuesta: {response.content}")
        print(f"   Tipo: {type(response)}")
        print(f"   Atributos: {dir(response)}")
        
        if hasattr(response, 'response_metadata'):
            print(f"   response_metadata: {response.response_metadata}")
        else:
            print("   ❌ No tiene response_metadata")
            
        if hasattr(response, 'usage_metadata'):
            print(f"   usage_metadata: {response.usage_metadata}")
        else:
            print("   ❌ No tiene usage_metadata")
            
        # 3. Test con tracking
        print("\n3️⃣ Llamada LLM CON tracking...")
        
        tracking_config = {
            'tracking': {
                'organization_id': 'test-org-123',
                'operation': 'debug_test',
                'client_id': None,
                'context_unit_id': 'test-cu-456'
            }
        }
        
        response2 = await client.llm_sonnet.ainvoke([
            ("human", "Di 'adiós' en una palabra")
        ], config=tracking_config)
        
        print(f"   Respuesta: {response2.content}")
        
        if hasattr(response2, 'response_metadata'):
            print(f"   response_metadata: {response2.response_metadata}")
            
            # Verificar si hay token_usage
            usage = response2.response_metadata.get('token_usage', {})
            print(f"   token_usage: {usage}")
            
            if usage and usage.get('total_tokens', 0) > 0:
                print("   ✅ Token usage encontrado!")
            else:
                print("   ❌ Token usage NO encontrado o es 0")
                
        # 4. Test directo del tracker
        print("\n4️⃣ Test directo del UsageTracker...")
        tracker = get_usage_tracker()
        
        await tracker.track(
            model="anthropic/claude-3.5-sonnet",
            operation="debug_manual_test",
            input_tokens=100,
            output_tokens=50,
            organization_id="test-org-123",
            context_unit_id="test-cu-456"
        )
        
        print("   ✅ Tracker manual ejecutado")
        
        # 5. Verificar si se guardó en BD
        print("\n5️⃣ Verificando registros en BD...")
        from utils.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        result = supabase.client.table("llm_usage") \
            .select("*") \
            .eq("organization_id", "test-org-123") \
            .order("timestamp", desc=True) \
            .limit(5) \
            .execute()
            
        if result.data:
            print(f"   ✅ Encontrados {len(result.data)} registros de test:")
            for record in result.data:
                print(f"      - {record['operation']}: {record['total_tokens']} tokens, ${record['total_cost_usd']}")
        else:
            print("   ❌ No se encontraron registros en BD")
            
        print("\n🏁 Diagnóstico completado!")
        
    except Exception as e:
        logger.error("debug_tracking_error", error=str(e))
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_tracking())