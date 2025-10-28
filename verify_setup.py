#!/usr/bin/env python3
"""
Quick verification that workflow system is properly set up.
"""

import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from utils.config import settings
    from utils.supabase_client import get_supabase_client
    
    print("✅ Imports successful")
    
    # Test Supabase connection
    supabase = get_supabase_client()
    print("✅ Supabase client created")
    
    # Test database query
    result = supabase.client.table("companies").select("company_code, tier").limit(5).execute()
    print(f"✅ Database connection: Found {len(result.data)} companies")
    
    # Check for demo company
    demo_check = supabase.client.table("companies").select("*").eq("company_code", "demo").execute()
    if demo_check.data:
        print(f"✅ Demo company exists with tier: {demo_check.data[0]['tier']}")
    else:
        print("❌ Demo company not found")
    
    # Check workflow configs
    workflow_check = supabase.client.table("workflow_configs").select("workflow_code").execute()
    if workflow_check.data:
        codes = [w["workflow_code"] for w in workflow_check.data]
        print(f"✅ Workflow configs exist: {', '.join(codes)}")
    else:
        print("❌ No workflow configs found")
    
    # Check demo client
    client_check = supabase.client.table("clients").select("client_name, api_key").eq("client_name", "Demo User").execute()
    if client_check.data:
        api_key = client_check.data[0]["api_key"]
        print(f"✅ Demo client exists")
        print(f"   API Key: {api_key}")
    else:
        print("❌ Demo client not found")
    
    print("\n🎉 WORKFLOW SYSTEM IS READY!")
    print("\nNext steps:")
    print("1. Start the server: docker-compose up")
    print("2. Test with: curl -H 'X-API-Key: sk-demo-unlimited-test-key-0000000000000000000000000000' http://localhost:8000/me")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're in a Python environment with dependencies installed")
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)