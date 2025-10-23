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


async def qdrant_info():
    """Show Qdrant collection information."""
    try:
        qdrant = get_qdrant_client()
        info = qdrant.get_collection_info()

        print(f"\n📊 Qdrant Collection Information:\n")
        print(f"Collection: {info.get('name', 'N/A')}")
        print(f"Status: {info.get('status', 'N/A')}")
        print(f"Vectors: {info.get('vectors_count', 0):,}")
        print(f"Points: {info.get('points_count', 0):,}")
        print()

    except Exception as e:
        print(f"\n❌ Error getting Qdrant info: {str(e)}\n")
        logger.error("cli_qdrant_info_error", error=str(e))
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

    # qdrant-info
    subparsers.add_parser("qdrant-info", help="Show Qdrant collection information")

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
    elif args.command == "qdrant-info":
        asyncio.run(qdrant_info())


if __name__ == "__main__":
    main()
