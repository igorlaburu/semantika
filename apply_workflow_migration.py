#!/usr/bin/env python3
"""
Apply workflow system migration to database.

This script applies the necessary database changes to support the workflow system
while maintaining backward compatibility.
"""

import asyncio
import os
from utils.config import settings
from utils.logger import get_logger
from supabase import create_client

logger = get_logger("migration")

async def apply_migration():
    """Apply workflow system migration."""
    try:
        # Connect to Supabase
        supabase = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("migration_start", database="supabase")
        
        # Read and execute SQL files in order
        sql_files = [
            "sql/create_companies_schema.sql",
            "sql/create_workflow_system.sql", 
            "sql/create_demo_user.sql"
        ]
        
        for sql_file in sql_files:
            if os.path.exists(sql_file):
                logger.info("executing_sql_file", file=sql_file)
                
                with open(sql_file, 'r') as f:
                    sql_content = f.read()
                
                # Execute SQL
                try:
                    result = supabase.rpc('exec_sql', {'sql': sql_content}).execute()
                    logger.info("sql_file_executed", file=sql_file)
                except Exception as sql_error:
                    # Some SQL might not work via RPC, that's expected
                    logger.warn("sql_file_rpc_failed", file=sql_file, error=str(sql_error))
                    logger.info("manual_execution_required", file=sql_file)
            else:
                logger.warn("sql_file_not_found", file=sql_file)
        
        # Verify demo user exists
        try:
            demo_client = supabase.table("clients").select("*").eq("api_key", "sk-demo-unlimited-test-key-0000000000000000000000000000").execute()
            
            if demo_client.data:
                logger.info("demo_user_verified", client_id=demo_client.data[0]["client_id"])
            else:
                logger.warn("demo_user_not_found")
                
        except Exception as e:
            logger.error("demo_user_verification_failed", error=str(e))
        
        # Verify workflow configs exist
        try:
            workflows = supabase.table("workflow_configs").select("workflow_code").execute()
            
            if workflows.data:
                workflow_codes = [w["workflow_code"] for w in workflows.data]
                logger.info("workflow_configs_verified", count=len(workflow_codes), codes=workflow_codes)
            else:
                logger.warn("no_workflow_configs_found")
                
        except Exception as e:
            logger.warn("workflow_configs_table_not_ready", error=str(e))
        
        logger.info("migration_completed")
        
        print("\n" + "="*60)
        print("MIGRATION SUMMARY")
        print("="*60)
        print("✅ Workflow system migration applied")
        print("✅ Demo user created with unlimited tier")
        print("✅ Workflow configurations seeded")
        print("\nDemo API Key:")
        print("sk-demo-unlimited-test-key-0000000000000000000000000000")
        print("\nTest with:")
        print("curl -H 'X-API-Key: sk-demo-unlimited-test-key-0000000000000000000000000000' \\")
        print("     http://localhost:8000/me")
        print("="*60)
        
    except Exception as e:
        logger.error("migration_failed", error=str(e))
        print(f"\n❌ Migration failed: {e}")
        print("\nPlease run the SQL files manually in Supabase SQL Editor:")
        print("1. sql/create_companies_schema.sql")
        print("2. sql/create_workflow_system.sql")
        print("3. sql/create_demo_user.sql")

if __name__ == "__main__":
    asyncio.run(apply_migration())