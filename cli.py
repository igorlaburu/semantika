"""CLI tool for semantika administration.

Manage clients, tasks, and view system information.
"""

import asyncio
import sys
from typing import Optional
import argparse

from utils.supabase_client import get_supabase_client
from utils.qdrant_client import get_qdrant_client
from utils.logger import get_logger
import re
import json

logger = get_logger("cli")


async def add_client(name: str, email: Optional[str] = None):
    """Add a new client."""
    try:
        supabase = get_supabase_client()
        client = await supabase.create_client(name, email)

        print(f"\n✅ Client created successfully!")
        print(f"Client ID: {client['client_id']}")
        print(f"Name: {client['client_name']}")
        print(f"API Key: {client['api_key']}")
        print(f"\n⚠️  Save this API key - it won't be shown again!\n")

        logger.info("cli_client_created", client_id=client['client_id'])

    except Exception as e:
        print(f"\n❌ Error creating client: {str(e)}\n")
        logger.error("cli_create_client_error", error=str(e))
        sys.exit(1)


async def list_clients():
    """List all clients."""
    try:
        supabase = get_supabase_client()
        clients = await supabase.list_clients()

        if not clients:
            print("\nNo clients found.\n")
            return

        print(f"\n📋 {len(clients)} client(s) found:\n")
        print(f"{'ID':<38} {'Name':<30} {'Active':<8} {'Created'}")
        print("-" * 100)

        for client in clients:
            active = "✅" if client['is_active'] else "❌"
            created = client['created_at'][:10] if client.get('created_at') else 'N/A'
            print(f"{client['client_id']:<38} {client['client_name']:<30} {active:<8} {created}")

        print()

    except Exception as e:
        print(f"\n❌ Error listing clients: {str(e)}\n")
        logger.error("cli_list_clients_error", error=str(e))
        sys.exit(1)


async def add_task(
    client_id: str,
    source_type: str,
    target: str,
    frequency: int
):
    """Add a new task."""
    try:
        supabase = get_supabase_client()

        # Verify client exists
        client = await supabase.get_client_by_id(client_id)
        if not client:
            print(f"\n❌ Client not found: {client_id}\n")
            sys.exit(1)

        # Create task
        task = await supabase.create_task(
            client_id=client_id,
            source_type=source_type,
            target=target,
            frequency_min=frequency
        )

        print(f"\n✅ Task created successfully!")
        print(f"Task ID: {task['task_id']}")
        print(f"Client: {client['client_name']}")
        print(f"Type: {source_type}")
        print(f"Target: {target}")
        print(f"Frequency: Every {frequency} minutes\n")

        logger.info("cli_task_created", task_id=task['task_id'], client_id=client_id)

    except Exception as e:
        print(f"\n❌ Error creating task: {str(e)}\n")
        logger.error("cli_create_task_error", error=str(e))
        sys.exit(1)


async def list_tasks(client_id: Optional[str] = None):
    """List tasks."""
    try:
        supabase = get_supabase_client()

        if client_id:
            tasks = await supabase.get_tasks_by_client(client_id)
            client = await supabase.get_client_by_id(client_id)
            title = f"Tasks for {client['client_name']}" if client else f"Tasks for {client_id}"
        else:
            tasks = await supabase.get_all_active_tasks()
            title = "All active tasks"

        if not tasks:
            print(f"\n{title}: No tasks found.\n")
            return

        print(f"\n📋 {title} ({len(tasks)} task(s)):\n")
        print(f"{'ID':<38} {'Type':<15} {'Target':<40} {'Freq (min)':<12} {'Active'}")
        print("-" * 120)

        for task in tasks:
            active = "✅" if task['is_active'] else "❌"
            target = task['target'][:37] + "..." if len(task['target']) > 40 else task['target']
            print(f"{task['task_id']:<38} {task['source_type']:<15} {target:<40} {task['frequency_min']:<12} {active}")

        print()

    except Exception as e:
        print(f"\n❌ Error listing tasks: {str(e)}\n")
        logger.error("cli_list_tasks_error", error=str(e))
        sys.exit(1)


async def delete_task(task_id: str):
    """Delete a task."""
    try:
        supabase = get_supabase_client()

        # Verify task exists
        task = await supabase.get_task_by_id(task_id)
        if not task:
            print(f"\n❌ Task not found: {task_id}\n")
            sys.exit(1)

        # Delete task
        await supabase.delete_task(task_id)

        print(f"\n✅ Task deleted successfully!")
        print(f"Task ID: {task_id}")
        print(f"Type: {task['source_type']}")
        print(f"Target: {task['target']}\n")

        logger.info("cli_task_deleted", task_id=task_id)

    except Exception as e:
        print(f"\n❌ Error deleting task: {str(e)}\n")
        logger.error("cli_delete_task_error", error=str(e))
        sys.exit(1)


async def qdrant_info():
    """Show Qdrant collection information."""
    try:
        qdrant = get_qdrant_client()
        info = qdrant.get_collection_info()

        print(f"\n📊 Qdrant Collection Information:\n")
        print(f"Collection: {info.get('name', 'N/A')}")
        print(f"Status: {info.get('status', 'N/A')}")
        print(f"Vectors: {info.get('vectors_count') or 0:,}")
        print(f"Points: {info.get('points_count') or 0:,}")
        print()

    except Exception as e:
        print(f"\n❌ Error getting Qdrant info: {str(e)}\n")
        logger.error("cli_qdrant_info_error", error=str(e))
        sys.exit(1)


async def add_org(slug: str, name: str):
    """Add a new organization."""
    try:
        # Validate slug format
        if not re.match(r'^[a-zA-Z0-9\-\.]+$', slug):
            print(f"\n❌ Invalid slug format. Use only alphanumeric, hyphens, and dots.\n")
            sys.exit(1)

        if len(slug) < 3 or len(slug) > 100:
            print(f"\n❌ Slug must be 3-100 characters.\n")
            sys.exit(1)

        supabase = get_supabase_client()

        data = {
            "slug": slug,
            "name": name,
            "is_active": True,
            "channels": {},
            "settings": {"language": "es", "store_in_qdrant": False}
        }

        result = supabase.table("organizations").insert(data).execute()

        print(f"\n✅ Organization created successfully!")
        print(f"Slug: {slug}")
        print(f"Name: {name}")
        print(f"ID: {result.data[0]['id']}\n")

        logger.info("cli_org_created", slug=slug)

    except Exception as e:
        print(f"\n❌ Error creating organization: {str(e)}\n")
        logger.error("cli_create_org_error", error=str(e))
        sys.exit(1)


async def list_orgs():
    """List all organizations."""
    try:
        supabase = get_supabase_client()
        result = supabase.table("organizations").select("*").execute()

        if not result.data:
            print("\nNo organizations found.\n")
            return

        print(f"\n📋 {len(result.data)} organization(s) found:\n")
        print(f"{'Slug':<20} {'Name':<30} {'Active':<8} {'Channels'}")
        print("-" * 80)

        for org in result.data:
            email_channels = org.get("channels", {}).get("email", {}).get("addresses", [])
            email_str = ", ".join(email_channels) if email_channels else "None"
            active = "✓" if org["is_active"] else "✗"

            print(f"{org['slug']:<20} {org['name']:<30} {active:<8} {email_str}")

        print()

    except Exception as e:
        print(f"\n❌ Error listing organizations: {str(e)}\n")
        logger.error("cli_list_orgs_error", error=str(e))
        sys.exit(1)


async def add_org_channel(slug: str, emails: str):
    """Add email channel to organization."""
    try:
        supabase = get_supabase_client()

        # Get organization
        org_result = supabase.table("organizations").select("*").eq("slug", slug).single().execute()

        if not org_result.data:
            print(f"\n❌ Organization not found: {slug}\n")
            sys.exit(1)

        # Parse emails
        email_list = [e.strip() for e in emails.split(",")]

        # Update channels
        channels = org_result.data.get("channels", {})
        channels["email"] = {
            "addresses": email_list,
            "enabled": True
        }

        supabase.table("organizations").update({"channels": channels}).eq("slug", slug).execute()

        print(f"\n✅ Email channel added to {slug}!")
        print(f"Emails: {', '.join(email_list)}\n")

        logger.info("cli_org_channel_added", slug=slug, emails=email_list)

    except Exception as e:
        print(f"\n❌ Error adding channel: {str(e)}\n")
        logger.error("cli_add_channel_error", error=str(e))
        sys.exit(1)


async def add_user(email: str, org: str, name: Optional[str] = None, role: str = "member"):
    """Add user to organization."""
    try:
        supabase = get_supabase_client()

        # Get organization
        org_result = supabase.table("organizations").select("id").eq("slug", org).single().execute()

        if not org_result.data:
            print(f"\n❌ Organization not found: {org}\n")
            sys.exit(1)

        org_id = org_result.data["id"]

        data = {
            "email": email,
            "name": name,
            "organization_id": org_id,
            "role": role,
            "is_active": True
        }

        result = supabase.table("users").insert(data).execute()

        print(f"\n✅ User added successfully!")
        print(f"Email: {email}")
        print(f"Organization: {org}")
        print(f"Role: {role}\n")

        logger.info("cli_user_added", email=email, org=org)

    except Exception as e:
        print(f"\n❌ Error adding user: {str(e)}\n")
        logger.error("cli_add_user_error", error=str(e))
        sys.exit(1)


async def list_users(org: Optional[str] = None):
    """List users."""
    try:
        supabase = get_supabase_client()

        if org:
            # Get organization ID
            org_result = supabase.table("organizations").select("id").eq("slug", org).single().execute()
            if not org_result.data:
                print(f"\n❌ Organization not found: {org}\n")
                sys.exit(1)

            result = supabase.table("users").select("*").eq("organization_id", org_result.data["id"]).execute()
        else:
            result = supabase.table("users").select("*").execute()

        if not result.data:
            print("\nNo users found.\n")
            return

        print(f"\n📋 {len(result.data)} user(s) found:\n")
        print(f"{'Email':<35} {'Name':<25} {'Role':<10} {'Active'}")
        print("-" * 80)

        for user in result.data:
            name = user.get("name") or "N/A"
            active = "✓" if user["is_active"] else "✗"
            print(f"{user['email']:<35} {name:<25} {user['role']:<10} {active}")

        print()

    except Exception as e:
        print(f"\n❌ Error listing users: {str(e)}\n")
        logger.error("cli_list_users_error", error=str(e))
        sys.exit(1)


async def list_context_units(org: Optional[str] = None, limit: int = 20):
    """List context units."""
    try:
        supabase = get_supabase_client()

        query = supabase.table("context_units").select("*").order("created_at", desc=True).limit(limit)

        if org:
            # Get organization ID
            org_result = supabase.table("organizations").select("id").eq("slug", org).single().execute()
            if not org_result.data:
                print(f"\n❌ Organization not found: {org}\n")
                sys.exit(1)

            query = query.eq("organization_id", org_result.data["id"])

        result = query.execute()

        if not result.data:
            print("\nNo context units found.\n")
            return

        print(f"\n📋 {len(result.data)} context unit(s) found:\n")
        print(f"{'Title':<50} {'Source':<10} {'Status':<12} {'Statements'}")
        print("-" * 90)

        for cu in result.data:
            title = (cu.get("title") or "N/A")[:47] + "..." if len(cu.get("title") or "") > 50 else (cu.get("title") or "N/A")
            source = cu.get("source_type", "N/A")
            status = cu.get("status", "N/A")
            statements_count = len(cu.get("atomic_statements", []))

            print(f"{title:<50} {source:<10} {status:<12} {statements_count}")

        print()

    except Exception as e:
        print(f"\n❌ Error listing context units: {str(e)}\n")
        logger.error("cli_list_context_units_error", error=str(e))
        sys.exit(1)


async def get_usage(org: Optional[str] = None, days: int = 30):
    """Get LLM usage statistics."""
    try:
        from utils.usage_tracker import get_usage_tracker

        tracker = get_usage_tracker()

        # Get organization ID if slug provided
        organization_id = None
        if org:
            supabase = get_supabase_client()
            org_result = supabase.client.table("organizations").select("id, name").eq("slug", org).single().execute()
            if not org_result.data:
                print(f"\n❌ Organization not found: {org}\n")
                sys.exit(1)
            organization_id = org_result.data["id"]
            print(f"\n📊 LLM Usage for: {org_result.data['name']} (last {days} days)\n")
        else:
            print(f"\n📊 LLM Usage - All organizations (last {days} days)\n")

        summary = await tracker.get_usage_summary(organization_id, days)

        if not summary or summary.get("total_calls", 0) == 0:
            print("No usage data found.\n")
            return

        # Overall stats
        print(f"Total API calls: {summary['total_calls']:,}")
        print(f"Total tokens: {summary['total_tokens']:,}")
        print(f"Total cost: ${summary['total_cost_usd']:.2f}\n")

        # By operation
        if summary.get("by_operation"):
            print(f"{'Operation':<20} {'Calls':<10} {'Tokens':<15} {'Cost (USD)'}")
            print("-" * 60)
            for op, stats in summary["by_operation"].items():
                print(f"{op:<20} {stats['calls']:<10} {stats['tokens']:,<15} ${stats['cost']:.2f}")
            print()

    except Exception as e:
        print(f"\n❌ Error getting usage: {str(e)}\n")
        logger.error("cli_get_usage_error", error=str(e))
        sys.exit(1)


async def create_company(name: str, cif: str, tier: str = "starter"):
    """Create a new company with default setup (ADMIN ONLY).
    
    Creates:
    - Company record
    - Client record with API key
    - Default Manual source (source_id = company_id)
    - Default organization
    
    This is the recommended way for admins to onboard new companies.
    """
    try:
        import secrets
        import uuid
        from datetime import datetime
        
        supabase = get_supabase_client()
        
        # Validate tier
        valid_tiers = ["starter", "pro", "unlimited"]
        if tier not in valid_tiers:
            print(f"\n❌ Invalid tier. Must be one of: {', '.join(valid_tiers)}\n")
            sys.exit(1)
        
        # Normalize CIF
        cif_normalized = cif.upper().replace(" ", "")
        
        # Check if company exists
        existing = supabase.client.table("companies")\
            .select("id, company_name")\
            .eq("company_code", cif_normalized)\
            .maybe_single()\
            .execute()
        
        if existing.data:
            print(f"\n❌ Company with CIF {cif_normalized} already exists: {existing.data['company_name']}\n")
            sys.exit(1)
        
        print(f"\n🏢 Creating company: {name}")
        print(f"   CIF: {cif_normalized}")
        print(f"   Tier: {tier}\n")
        
        # 1. Create company
        company_data = {
            "company_code": cif_normalized,
            "company_name": name,
            "tier": tier,
            "is_active": True
        }
        
        company_result = supabase.client.table("companies").insert(company_data).execute()
        
        if not company_result or not company_result.data:
            error_msg = str(company_result) if company_result else "No response from Supabase"
            print(f"\n❌ Failed to create company")
            print(f"Debug: {error_msg}\n")
            sys.exit(1)
        
        company = company_result.data[0]
        company_id = company["id"]
        
        print(f"✅ Company created: {company_id}")
        
        # 2. Create client with API key
        api_key = f"sk-{secrets.token_hex(32)}"
        client_data = {
            "company_id": company_id,
            "client_name": f"{name} (Default)",
            "api_key": api_key,
            "is_active": True
        }
        
        client_result = supabase.client.table("clients").insert(client_data).execute()
        
        if not client_result.data:
            print(f"\n❌ Failed to create client\n")
            sys.exit(1)
        
        client = client_result.data[0]
        client_id = client["client_id"]
        
        print(f"✅ Client created: {client_id}")
        print(f"✅ API Key: {api_key}")
        
        # 3. Create Manual source (source_id = company_id)
        manual_source = {
            "id": company_id,  # KEY: source.id = company.id
            "company_id": company_id,
            "source_type": "manual",
            "source_name": "Manual",
            "is_active": True,
            "config": {"description": "Contenido manual (API/Frontend/Email)"},
            "schedule_config": {}
        }
        
        source_result = supabase.client.table("sources").insert(manual_source).execute()
        
        if not source_result.data:
            print(f"\n⚠️  Warning: Failed to create Manual source\n")
        else:
            print(f"✅ Manual source created: {company_id}")
        
        # 4. Create default organization
        org_slug = cif_normalized.lower()
        org_data = {
            "company_id": company_id,
            "slug": org_slug,
            "name": name,
            "is_active": True,
            "settings": {"language": "es"}
        }
        
        org_result = supabase.client.table("organizations").insert(org_data).execute()
        
        if not org_result.data:
            print(f"\n⚠️  Warning: Failed to create organization\n")
        else:
            org = org_result.data[0]
            print(f"✅ Organization created: {org_slug} ({org['id']})")
        
        # Summary
        print(f"\n{'='*60}")
        print(f"🎉 Company Onboarding Complete!")
        print(f"{'='*60}")
        print(f"\n📋 Company Details:")
        print(f"   ID: {company_id}")
        print(f"   Name: {name}")
        print(f"   CIF: {cif_normalized}")
        print(f"   Tier: {tier}")
        print(f"\n🔑 API Credentials:")
        print(f"   Client ID: {client_id}")
        print(f"   API Key: {api_key}")
        print(f"   ⚠️  SAVE THIS KEY - won't be shown again!")
        print(f"\n🏗️  Default Resources:")
        print(f"   Manual Source ID: {company_id}")
        print(f"   Organization Slug: {org_slug}")
        print(f"\n📝 Next Steps:")
        print(f"   1. Create auth users: python cli.py create-auth-user --email user@example.com --company-id {company_id}")
        print(f"   2. Add sources: Use Supabase UI or API")
        print(f"   3. Share API key with client\n")
        
        logger.info("cli_company_created",
            company_id=company_id,
            company_name=name,
            client_id=client_id
        )
        
    except Exception as e:
        print(f"\n❌ Error creating company: {str(e)}\n")
        logger.error("cli_create_company_error", error=str(e))
        sys.exit(1)


async def create_auth_user(email: str, password: str, company_id: str, name: Optional[str] = None):
    """Create user in Supabase Auth and link to company (ADMIN ONLY).
    
    Creates a user account that can log in to the frontend.
    Links user to company via user_metadata.
    """
    try:
        from utils.supabase_auth import get_supabase_admin_client
        
        supabase = get_supabase_client()
        
        # Verify company exists
        company_result = supabase.client.table("companies")\
            .select("*")\
            .eq("id", company_id)\
            .maybe_single()\
            .execute()
        
        if not company_result.data:
            print(f"\n❌ Company not found: {company_id}\n")
            sys.exit(1)
        
        company = company_result.data
        
        print(f"\n👤 Creating auth user for: {company['company_name']}")
        print(f"   Email: {email}")
        print(f"   Password: {'*' * len(password)}\n")
        
        # Create user in Supabase Auth
        admin_client = get_supabase_admin_client()
        
        auth_response = admin_client.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,  # Auto-confirm email
            "user_metadata": {
                "company_id": company_id,
                "name": name or email.split("@")[0],
                "email": email
            }
        })
        
        if not auth_response.user:
            print(f"\n❌ Failed to create auth user\n")
            sys.exit(1)
        
        user_id = auth_response.user.id
        
        print(f"✅ Auth user created: {user_id}")
        print(f"\n{'='*60}")
        print(f"🎉 User Created Successfully!")
        print(f"{'='*60}")
        print(f"\n📋 User Details:")
        print(f"   User ID: {user_id}")
        print(f"   Email: {email}")
        print(f"   Password: {password}")
        print(f"   Company: {company['company_name']} ({company_id})")
        print(f"\n📝 Login Credentials (share with user):")
        print(f"   Email: {email}")
        print(f"   Password: {password}")
        print(f"   URL: https://press.ekimen.ai\n")
        
        logger.info("cli_auth_user_created",
            user_id=user_id,
            email=email,
            company_id=company_id
        )
        
    except Exception as e:
        print(f"\n❌ Error creating auth user: {str(e)}\n")
        logger.error("cli_create_auth_user_error", error=str(e))
        sys.exit(1)


async def pool_discover():
    """Run Pool discovery flow (GNews + origin hunting)."""
    try:
        from workflows.discovery_flow import execute_discovery_job
        
        print("\n🔍 Starting Pool discovery flow...\n")
        
        result = await execute_discovery_job()
        
        if result.get("success"):
            print(f"✅ Discovery completed!")
            print(f"   Articles found: {result.get('articles_found', 0)}")
            print(f"   Domains analyzed: {result.get('domains_analyzed', 0)}")
            print(f"   Sources discovered: {result.get('sources_discovered', 0)}\n")
            
            logger.info("cli_pool_discover_completed", result=result)
        else:
            print(f"❌ Discovery failed: {result.get('error')}\n")
            logger.error("cli_pool_discover_error", error=result.get('error'))
            sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ Error running discovery: {str(e)}\n")
        logger.error("cli_pool_discover_exception", error=str(e))
        sys.exit(1)


async def pool_ingest():
    """Run Pool ingestion flow (scrape active sources)."""
    try:
        from workflows.ingestion_flow import execute_ingestion_job
        
        print("\n📥 Starting Pool ingestion flow...\n")
        
        result = await execute_ingestion_job()
        
        if result.get("success"):
            print(f"✅ Ingestion completed!")
            print(f"   Sources processed: {result.get('sources_processed', 0)}")
            print(f"   Items ingested: {result.get('items_ingested', 0)}\n")
            
            logger.info("cli_pool_ingest_completed", result=result)
        else:
            print(f"❌ Ingestion failed: {result.get('error')}\n")
            logger.error("cli_pool_ingest_error", error=result.get('error'))
            sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ Error running ingestion: {str(e)}\n")
        logger.error("cli_pool_ingest_exception", error=str(e))
        sys.exit(1)


async def pool_stats():
    """Show Pool statistics."""
    try:
        from utils.pool_client import get_pool_client
        
        supabase = get_supabase_client()
        pool = get_pool_client()
        
        print(f"\n📊 Pool Statistics:\n")
        
        # Qdrant stats
        qdrant_stats = pool.get_stats()
        print(f"Qdrant Collection: {qdrant_stats.get('collection_name', 'N/A')}")
        print(f"Total context units: {qdrant_stats.get('total_context_units', 0):,}\n")
        
        # Discovered sources stats
        sources_result = supabase.client.table("discovered_sources")\
            .select("status", count="exact")\
            .execute()
        
        total_sources = sources_result.count or 0
        
        # By status
        trial = supabase.client.table("discovered_sources")\
            .select("source_id", count="exact")\
            .eq("status", "trial")\
            .execute()
        
        active = supabase.client.table("discovered_sources")\
            .select("source_id", count="exact")\
            .eq("status", "active")\
            .execute()
        
        inactive = supabase.client.table("discovered_sources")\
            .select("source_id", count="exact")\
            .eq("status", "inactive")\
            .execute()
        
        print(f"Discovered Sources:")
        print(f"   Total: {total_sources}")
        print(f"   Trial: {trial.count or 0}")
        print(f"   Active: {active.count or 0}")
        print(f"   Inactive: {inactive.count or 0}\n")
        
        logger.info("cli_pool_stats_viewed")
    
    except Exception as e:
        print(f"\n❌ Error getting Pool stats: {str(e)}\n")
        logger.error("cli_pool_stats_error", error=str(e))
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="semantika CLI - Manage clients and tasks"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # add-client
    add_client_parser = subparsers.add_parser("add-client", help="Create a new client")
    add_client_parser.add_argument("--name", required=True, help="Client name")
    add_client_parser.add_argument("--email", help="Client email (optional)")

    # list-clients
    subparsers.add_parser("list-clients", help="List all clients")

    # add-task
    add_task_parser = subparsers.add_parser("add-task", help="Create a new task")
    add_task_parser.add_argument("--client-id", required=True, help="Client UUID")
    add_task_parser.add_argument(
        "--type",
        required=True,
        choices=["web_llm", "twitter", "api_efe", "api_reuters", "api_wordpress", "manual"],
        help="Source type"
    )
    add_task_parser.add_argument("--target", required=True, help="URL, query, or endpoint")
    add_task_parser.add_argument("--freq", type=int, required=True, help="Frequency in minutes")

    # list-tasks
    list_tasks_parser = subparsers.add_parser("list-tasks", help="List tasks")
    list_tasks_parser.add_argument("--client-id", help="Filter by client ID (optional)")

    # delete-task
    delete_task_parser = subparsers.add_parser("delete-task", help="Delete a task")
    delete_task_parser.add_argument("--task-id", required=True, help="Task UUID to delete")

    # qdrant-info
    subparsers.add_parser("qdrant-info", help="Show Qdrant collection information")

    # add-org
    add_org_parser = subparsers.add_parser("add-org", help="Create a new organization")
    add_org_parser.add_argument("--slug", required=True, help="Organization slug (alphanumeric, -, .)")
    add_org_parser.add_argument("--name", required=True, help="Organization name")

    # list-orgs
    subparsers.add_parser("list-orgs", help="List all organizations")

    # add-org-channel
    add_channel_parser = subparsers.add_parser("add-org-channel", help="Add email channel to organization")
    add_channel_parser.add_argument("--slug", required=True, help="Organization slug")
    add_channel_parser.add_argument("--emails", required=True, help="Comma-separated email addresses")

    # add-user
    add_user_parser = subparsers.add_parser("add-user", help="Add user to organization")
    add_user_parser.add_argument("--email", required=True, help="User email")
    add_user_parser.add_argument("--name", help="User name (optional)")
    add_user_parser.add_argument("--org", required=True, help="Organization slug")
    add_user_parser.add_argument("--role", default="member", choices=["admin", "editor", "member"], help="User role")

    # list-users
    list_users_parser = subparsers.add_parser("list-users", help="List users")
    list_users_parser.add_argument("--org", help="Filter by organization slug (optional)")

    # list-context-units
    list_cu_parser = subparsers.add_parser("list-context-units", help="List context units")
    list_cu_parser.add_argument("--org", help="Filter by organization slug (optional)")
    list_cu_parser.add_argument("--limit", type=int, default=20, help="Number of results")

    # usage
    usage_parser = subparsers.add_parser("usage", help="Show LLM usage statistics")
    usage_parser.add_argument("--org", help="Filter by organization slug (optional)")
    usage_parser.add_argument("--days", type=int, default=30, help="Number of days to look back (default: 30)")

    # create-company (ADMIN ONBOARDING)
    create_company_parser = subparsers.add_parser("create-company", help="Create new company with full setup (ADMIN)")
    create_company_parser.add_argument("--name", required=True, help="Company name")
    create_company_parser.add_argument("--cif", required=True, help="Company tax ID (CIF)")
    create_company_parser.add_argument("--tier", default="starter", choices=["starter", "pro", "unlimited"], help="Company tier")

    # create-auth-user (ADMIN ONBOARDING)
    create_user_parser = subparsers.add_parser("create-auth-user", help="Create auth user for company (ADMIN)")
    create_user_parser.add_argument("--email", required=True, help="User email")
    create_user_parser.add_argument("--password", required=True, help="User password")
    create_user_parser.add_argument("--company-id", required=True, help="Company UUID")
    create_user_parser.add_argument("--name", help="User display name (optional)")

    # POOL COMMANDS
    subparsers.add_parser("pool-discover", help="Run Pool discovery flow (GNews + origin hunting)")
    subparsers.add_parser("pool-ingest", help="Run Pool ingestion flow (scrape active sources)")
    subparsers.add_parser("pool-stats", help="Show Pool statistics")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Execute command
    if args.command == "add-client":
        asyncio.run(add_client(args.name, args.email))
    elif args.command == "list-clients":
        asyncio.run(list_clients())
    elif args.command == "add-task":
        asyncio.run(add_task(args.client_id, args.type, args.target, args.freq))
    elif args.command == "list-tasks":
        asyncio.run(list_tasks(args.client_id if hasattr(args, 'client_id') else None))
    elif args.command == "delete-task":
        asyncio.run(delete_task(args.task_id))
    elif args.command == "qdrant-info":
        asyncio.run(qdrant_info())
    elif args.command == "add-org":
        asyncio.run(add_org(args.slug, args.name))
    elif args.command == "list-orgs":
        asyncio.run(list_orgs())
    elif args.command == "add-org-channel":
        asyncio.run(add_org_channel(args.slug, args.emails))
    elif args.command == "add-user":
        asyncio.run(add_user(args.email, args.org, args.name if hasattr(args, 'name') else None, args.role))
    elif args.command == "list-users":
        asyncio.run(list_users(args.org if hasattr(args, 'org') else None))
    elif args.command == "list-context-units":
        asyncio.run(list_context_units(args.org if hasattr(args, 'org') else None, args.limit))
    elif args.command == "usage":
        asyncio.run(get_usage(args.org if hasattr(args, 'org') else None, args.days))
    elif args.command == "create-company":
        asyncio.run(create_company(args.name, args.cif, args.tier))
    elif args.command == "create-auth-user":
        asyncio.run(create_auth_user(args.email, args.password, args.company_id, args.name if hasattr(args, 'name') else None))
    elif args.command == "pool-discover":
        asyncio.run(pool_discover())
    elif args.command == "pool-ingest":
        asyncio.run(pool_ingest())
    elif args.command == "pool-stats":
        asyncio.run(pool_stats())


if __name__ == "__main__":
    main()
