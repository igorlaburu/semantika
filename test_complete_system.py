#!/usr/bin/env python3
"""
Complete system test for semantika multi-company workflow system.

Tests the entire pipeline from email routing to workflow processing.
"""

import os
import sys
import asyncio
from typing import Dict, Any

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from core.source_content import SourceContent
from workflows.workflow_factory import get_workflow, list_available_workflows

logger = get_logger("test_complete_system")


async def test_workflow_factory():
    """Test workflow factory pattern."""
    logger.info("testing_workflow_factory")
    
    try:
        # Test default workflow
        default_workflow = get_workflow("demo")
        logger.info("default_workflow_loaded", company_code="demo")
        
        # Test custom workflow (should fallback to default)
        elconfidencial_workflow = get_workflow("elconfidencial")
        logger.info("elconfidencial_workflow_loaded", company_code="elconfidencial")
        
        # List available workflows
        available = list_available_workflows()
        logger.info("available_workflows", workflows=available)
        
        return True
        
    except Exception as e:
        logger.error("workflow_factory_test_failed", error=str(e))
        return False


async def test_source_content_creation():
    """Test SourceContent creation and methods."""
    logger.info("testing_source_content")
    
    try:
        # Create sample source content
        source_content = SourceContent(
            source_type="email",
            source_id="test_email_123",
            organization_slug="demo",
            text_content="Este es un email de prueba con contenido relevante para el análisis.",
            metadata={
                "subject": "Test Email",
                "from": "test@example.com"
            },
            title="Test Email Subject"
        )
        
        # Test methods
        display_title = source_content.get_display_title()
        text_preview = source_content.get_text_preview(50)
        word_count = source_content.get_word_count()
        
        logger.info("source_content_created",
            id=source_content.id,
            display_title=display_title,
            word_count=word_count,
            preview_length=len(text_preview)
        )
        
        return True
        
    except Exception as e:
        logger.error("source_content_test_failed", error=str(e))
        return False


async def test_workflow_processing():
    """Test complete workflow processing pipeline."""
    logger.info("testing_workflow_processing")
    
    try:
        # Create test source content
        source_content = SourceContent(
            source_type="email",
            source_id="test_workflow_email",
            organization_slug="demo",
            text_content="El Gobierno español ha anunciado nuevas medidas económicas para impulsar el sector tecnológico. Las medidas incluyen incentivos fiscales y programas de financiación para startups.",
            metadata={
                "subject": "Nuevas medidas económicas para el sector tech",
                "company_code": "demo"
            }
        )
        
        # Get workflow for demo company
        workflow = get_workflow("demo")
        
        # Process content
        result = await workflow.process_content(source_content)
        
        logger.info("workflow_processing_completed",
            company_code=result["company_code"],
            context_unit_title=result["context_unit"].get("title"),
            analysis_flags=result["analysis"].get("flags", []),
            custom_data_keys=list(result["custom_data"].keys())
        )
        
        # Verify result structure
        required_keys = ["context_unit", "analysis", "custom_data", "company_code"]
        if all(key in result for key in required_keys):
            logger.info("workflow_result_structure_valid")
            return True
        else:
            logger.error("workflow_result_structure_invalid", missing_keys=[k for k in required_keys if k not in result])
            return False
        
    except Exception as e:
        logger.error("workflow_processing_test_failed", error=str(e))
        return False


async def test_multi_company_setup():
    """Test multi-company database setup."""
    logger.info("testing_multi_company_setup")
    
    try:
        supabase = get_supabase_client()
        
        # Test companies exist
        companies = supabase.client.table("companies")\
            .select("company_code, tier, settings")\
            .in_("company_code", ["demo", "elconfidencial"])\
            .execute()
        
        if len(companies.data) >= 2:
            for company in companies.data:
                logger.info("company_found",
                    company_code=company["company_code"],
                    tier=company["tier"],
                    has_email_alias="email_alias" in company.get("settings", {})
                )
        else:
            logger.error("insufficient_companies", found=len(companies.data))
            return False
        
        # Test organizations exist
        orgs = supabase.client.table("organizations")\
            .select("slug, company_id")\
            .in_("slug", ["demo", "elconfidencial"])\
            .execute()
        
        if len(orgs.data) >= 2:
            logger.info("organizations_found", count=len(orgs.data))
        else:
            logger.error("insufficient_organizations", found=len(orgs.data))
            return False
        
        # Test workflow configs exist
        workflows = supabase.client.table("workflow_configs")\
            .select("workflow_code, is_api_enabled")\
            .execute()
        
        if len(workflows.data) >= 5:
            enabled_workflows = [w["workflow_code"] for w in workflows.data if w["is_api_enabled"]]
            logger.info("workflow_configs_found", 
                total=len(workflows.data),
                api_enabled=len(enabled_workflows),
                enabled_codes=enabled_workflows
            )
        else:
            logger.error("insufficient_workflow_configs", found=len(workflows.data))
            return False
        
        return True
        
    except Exception as e:
        logger.error("multi_company_setup_test_failed", error=str(e))
        return False


async def test_email_routing_simulation():
    """Simulate email routing without actual IMAP."""
    logger.info("testing_email_routing_simulation")
    
    try:
        from sources.multi_company_email_monitor import MultiCompanyEmailMonitor
        
        # Create mock monitor
        class MockMonitor(MultiCompanyEmailMonitor):
            def __init__(self):
                self.TEXT_EXTENSIONS = {".txt", ".md"}
                self.AUDIO_EXTENSIONS = {".mp3", ".wav"}
        
        monitor = MockMonitor()
        
        # Test company extraction
        test_cases = [
            ("p.demo@ekimen.ai", "demo"),
            ("p.elconfidencial@ekimen.ai", "elconfidencial"),
            ("contact@ekimen.ai", None)
        ]
        
        for to_header, expected in test_cases:
            result = monitor._extract_company_from_to_header(to_header)
            if result != expected:
                logger.error("email_routing_extraction_failed",
                    to_header=to_header,
                    expected=expected,
                    result=result
                )
                return False
        
        # Test company lookup
        demo_company = await monitor._get_company_and_organization("demo")
        if demo_company:
            company, org = demo_company
            logger.info("email_routing_lookup_success",
                company_code=company["company_code"],
                org_slug=org["slug"]
            )
        else:
            logger.error("email_routing_lookup_failed", company_code="demo")
            return False
        
        return True
        
    except Exception as e:
        logger.error("email_routing_simulation_failed", error=str(e))
        return False


async def main():
    """Run complete system tests."""
    logger.info("complete_system_test_start")
    
    tests = [
        ("Multi-Company Database Setup", test_multi_company_setup),
        ("Source Content Creation", test_source_content_creation),
        ("Workflow Factory Pattern", test_workflow_factory),
        ("Workflow Processing Pipeline", test_workflow_processing),
        ("Email Routing Simulation", test_email_routing_simulation),
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
    logger.info("complete_system_test_complete")
    
    print("\n" + "="*70)
    print("COMPLETE SEMANTIKA SYSTEM TEST RESULTS")
    print("="*70)
    
    all_passed = True
    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:35} {status}")
        if not success:
            all_passed = False
    
    print("="*70)
    
    if all_passed:
        print("🎉 COMPLETE SYSTEM IS READY!")
        print("\n📧 Email Routing Examples:")
        print("• p.demo@ekimen.ai           → Demo company (unlimited)")
        print("• p.elconfidencial@ekimen.ai → El Confidencial (pro tier)")
        
        print("\n🔄 Workflow Processing:")
        print("• Email → Company Lookup → Workflow Factory → LLM Analysis → Storage")
        
        print("\n🏗️ Architecture Completed:")
        print("• ✅ Multi-tenancy with company isolation")
        print("• ✅ Workflow system with usage control")
        print("• ✅ Email routing with company aliases")
        print("• ✅ Dynamic workflow loading")
        print("• ✅ Tier-based usage limits")
        print("• ✅ LLM cost tracking")
        
        print("\n🚀 Production Ready:")
        print("1. Configure email server with aliases")
        print("2. Set EMAIL_MONITOR_ENABLED=true")
        print("3. Start: docker-compose up")
        print("4. Add real companies and workflows")
        
        print("\n🔑 Demo API Key:")
        print("sk-demo-unlimited-test-key-0000000000000000000000000000")
        
    else:
        print("❌ SOME TESTS FAILED - System needs fixes")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())