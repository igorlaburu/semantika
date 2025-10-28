#!/usr/bin/env python3
"""
Test script to verify the workflow system is working correctly.
"""

import asyncio
import os
import sys
import json
from typing import Dict, Any

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.workflow_manager import get_workflow_manager

logger = get_logger("test_workflow")

async def test_demo_user():
    """Test that demo user exists and has correct configuration."""
    logger.info("testing_demo_user")
    
    try:
        supabase = get_supabase_client()
        
        # Test API key lookup
        client = await supabase.get_client_by_api_key("sk-demo-unlimited-test-key-0000000000000000000000000000")
        
        if not client:
            logger.error("demo_user_not_found")
            return False
        
        logger.info("demo_user_found", 
            client_id=client["client_id"],
            company_id=client.get("company_id"),
            organization_id=client.get("organization_id")
        )
        
        # Test company tier lookup
        if client.get("company_id"):
            company_result = supabase.client.table("companies").select("tier, company_code").eq("id", client["company_id"]).single().execute()
            if company_result.data:
                logger.info("company_tier_verified", 
                    tier=company_result.data["tier"],
                    company_code=company_result.data["company_code"]
                )
            else:
                logger.warn("company_not_found", company_id=client["company_id"])
        
        return True
        
    except Exception as e:
        logger.error("demo_user_test_failed", error=str(e))
        return False

async def test_workflow_configs():
    """Test that workflow configurations are loaded."""
    logger.info("testing_workflow_configs")
    
    try:
        supabase = get_supabase_client()
        
        configs = supabase.client.table("workflow_configs").select("workflow_code, workflow_name, is_api_enabled").execute()
        
        if not configs.data:
            logger.error("no_workflow_configs_found")
            return False
        
        logger.info("workflow_configs_found", count=len(configs.data))
        
        for config in configs.data:
            logger.info("workflow_config", 
                code=config["workflow_code"],
                name=config["workflow_name"],
                api_enabled=config["is_api_enabled"]
            )
        
        return True
        
    except Exception as e:
        logger.error("workflow_configs_test_failed", error=str(e))
        return False

async def test_usage_check():
    """Test usage limit checking function."""
    logger.info("testing_usage_check")
    
    try:
        supabase = get_supabase_client()
        
        # Test unlimited tier (should always allow)
        result = supabase.client.rpc(
            'check_workflow_usage_limit',
            {
                'p_company_id': '00000000-0000-0000-0000-000000000001',
                'p_workflow_code': 'micro_edit',
                'p_tier': 'unlimited'
            }
        ).execute()
        
        if result.data and result.data.get('allowed'):
            logger.info("usage_check_unlimited_success", result=result.data)
        else:
            logger.error("usage_check_unlimited_failed", result=result.data)
            return False
        
        # Test starter tier (should also allow initially)
        result2 = supabase.client.rpc(
            'check_workflow_usage_limit',
            {
                'p_company_id': '00000000-0000-0000-0000-000000000001',
                'p_workflow_code': 'micro_edit',
                'p_tier': 'starter'
            }
        ).execute()
        
        if result2.data:
            logger.info("usage_check_starter_success", result=result2.data)
        else:
            logger.error("usage_check_starter_failed", result=result2.data)
            return False
        
        return True
        
    except Exception as e:
        logger.error("usage_check_test_failed", error=str(e))
        return False

async def test_workflow_execution():
    """Test basic workflow execution without actual LLM call."""
    logger.info("testing_workflow_execution")
    
    try:
        # Simulate client data
        client = {
            "client_id": "00000000-0000-0000-0000-000000000001",
            "company_id": "00000000-0000-0000-0000-000000000001",
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "client_name": "Demo User"
        }
        
        # Simple test function that doesn't call LLM
        async def test_workflow_function(client, text):
            return {
                "original_text": text,
                "edited_text": f"PROCESSED: {text}",
                "word_count_change": 2
            }
        
        manager = get_workflow_manager()
        
        result = await manager.execute_workflow(
            workflow_code="micro_edit",
            company_id=client["company_id"],
            client_id=client["client_id"],
            tier="unlimited",
            workflow_function=test_workflow_function,
            client,
            "Test text"
        )
        
        if result.get("success"):
            logger.info("workflow_execution_success", result=result)
        else:
            logger.error("workflow_execution_failed", result=result)
            return False
        
        return True
        
    except Exception as e:
        logger.error("workflow_execution_test_failed", error=str(e))
        return False

async def main():
    """Run all tests."""
    logger.info("workflow_system_test_start")
    
    tests = [
        ("Demo User", test_demo_user),
        ("Workflow Configs", test_workflow_configs),
        ("Usage Check", test_usage_check),
        ("Workflow Execution", test_workflow_execution)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        logger.info("running_test", test=test_name)
        try:
            success = await test_func()
            results[test_name] = success
            logger.info("test_completed", test=test_name, success=success)
        except Exception as e:
            results[test_name] = False
            logger.error("test_exception", test=test_name, error=str(e))
    
    # Summary
    logger.info("workflow_system_test_complete")
    
    print("\n" + "="*50)
    print("WORKFLOW SYSTEM TEST RESULTS")
    print("="*50)
    
    all_passed = True
    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:20} {status}")
        if not success:
            all_passed = False
    
    print("="*50)
    
    if all_passed:
        print("🎉 ALL TESTS PASSED - Workflow system is ready!")
        print("\nDemo API Key:")
        print("sk-demo-unlimited-test-key-0000000000000000000000000000")
        print("\nTest with curl:")
        print("curl -H 'X-API-Key: sk-demo-unlimited-test-key-0000000000000000000000000000' \\")
        print("     http://localhost:8000/me")
    else:
        print("❌ SOME TESTS FAILED - Check logs above")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())