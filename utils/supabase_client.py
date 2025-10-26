"""Supabase client for semantika.

Handles all interactions with Supabase database for configuration management.
"""

from typing import Optional, Dict, Any, List
from supabase import create_client, Client
import secrets

from .config import settings
from .logger import get_logger

logger = get_logger("supabase_client")


class SupabaseClient:
    """Supabase client wrapper for semantika configuration."""

    def __init__(self):
        """Initialize Supabase client."""
        try:
            self.client: Client = create_client(
                settings.supabase_url,
                settings.supabase_key
            )
            logger.info("supabase_connected", url=settings.supabase_url)
        except Exception as e:
            logger.error("supabase_connection_failed", error=str(e))
            raise

    # ============================================
    # CLIENTS
    # ============================================

    async def get_client_by_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Get client information by API key.

        Args:
            api_key: Client API key

        Returns:
            Client data or None if not found
        """
        try:
            response = self.client.table("clients").select("*").eq("api_key", api_key).eq("is_active", True).execute()

            if response.data and len(response.data) > 0:
                logger.debug("client_found", api_key_prefix=api_key[:10])
                return response.data[0]
            else:
                logger.warn("client_not_found", api_key_prefix=api_key[:10])
                return None

        except Exception as e:
            logger.error("get_client_error", error=str(e))
            return None

    async def get_client_by_id(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get client by ID."""
        try:
            response = self.client.table("clients").select("*").eq("client_id", client_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("get_client_by_id_error", error=str(e), client_id=client_id)
            return None

    async def create_client(self, client_name: str, email: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new client with generated API key.

        Args:
            client_name: Name of the client
            email: Optional email address

        Returns:
            Created client data including API key
        """
        # Generate API key
        api_key = f"sk-{secrets.token_hex(32)}"

        try:
            client_data = {
                "client_name": client_name,
                "api_key": api_key,
                "is_active": True
            }

            if email:
                client_data["email"] = email

            response = self.client.table("clients").insert(client_data).execute()

            if response.data and len(response.data) > 0:
                created_client = response.data[0]
                logger.info(
                    "client_created",
                    client_id=created_client["client_id"],
                    client_name=client_name
                )
                return created_client
            else:
                raise Exception("Failed to create client")

        except Exception as e:
            logger.error("create_client_error", error=str(e), client_name=client_name)
            raise

    async def list_clients(self) -> List[Dict[str, Any]]:
        """List all clients."""
        try:
            response = self.client.table("clients").select("client_id, client_name, email, is_active, created_at").execute()
            return response.data or []
        except Exception as e:
            logger.error("list_clients_error", error=str(e))
            return []

    # ============================================
    # TASKS
    # ============================================

    async def get_tasks_by_client(self, client_id: str, is_active: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Get all tasks for a client."""
        try:
            query = self.client.table("tasks").select("*").eq("client_id", client_id)

            if is_active is not None:
                query = query.eq("is_active", is_active)

            response = query.execute()
            return response.data or []

        except Exception as e:
            logger.error("get_tasks_error", error=str(e), client_id=client_id)
            return []

    async def get_all_active_tasks(self) -> List[Dict[str, Any]]:
        """Get all active tasks for scheduling."""
        try:
            response = self.client.table("tasks").select("*").eq("is_active", True).execute()
            return response.data or []
        except Exception as e:
            logger.error("get_all_tasks_error", error=str(e))
            return []

    async def create_task(
        self,
        client_id: str,
        source_type: str,
        target: str,
        frequency_min: int,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new task."""
        try:
            task_data = {
                "client_id": client_id,
                "source_type": source_type,
                "target": target,
                "frequency_min": frequency_min,
                "is_active": True,
                "config": config or {}
            }

            response = self.client.table("tasks").insert(task_data).execute()

            if response.data and len(response.data) > 0:
                created_task = response.data[0]
                logger.info(
                    "task_created",
                    task_id=created_task["task_id"],
                    client_id=client_id,
                    source_type=source_type
                )
                return created_task
            else:
                raise Exception("Failed to create task")

        except Exception as e:
            logger.error("create_task_error", error=str(e), client_id=client_id)
            raise

    async def get_task_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task by ID."""
        try:
            response = self.client.table("tasks").select("*").eq("task_id", task_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("get_task_by_id_error", error=str(e), task_id=task_id)
            return None

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task (soft delete - sets is_active to False)."""
        try:
            response = self.client.table("tasks").update({"is_active": False}).eq("task_id", task_id).execute()

            if response.data and len(response.data) > 0:
                logger.info("task_deleted", task_id=task_id)
                return True
            else:
                raise Exception("Failed to delete task")

        except Exception as e:
            logger.error("delete_task_error", error=str(e), task_id=task_id)
            raise

    async def update_task_last_run(self, task_id: str, last_run_timestamp: str) -> bool:
        """Update task's last_run timestamp."""
        try:
            response = self.client.table("tasks").update({"last_run": last_run_timestamp}).eq("task_id", task_id).execute()

            if response.data and len(response.data) > 0:
                logger.debug("task_last_run_updated", task_id=task_id, last_run=last_run_timestamp)
                return True
            else:
                logger.warn("task_last_run_update_failed", task_id=task_id)
                return False

        except Exception as e:
            logger.error("update_task_last_run_error", error=str(e), task_id=task_id)
            return False

    # ============================================
    # API CREDENTIALS
    # ============================================

    async def get_credentials(self, client_id: str, service_name: str) -> Optional[Dict[str, Any]]:
        """Get API credentials for a service."""
        try:
            response = self.client.table("api_credentials").select("credentials").eq("client_id", client_id).eq("service_name", service_name).execute()

            if response.data and len(response.data) > 0:
                return response.data[0]["credentials"]
            return None

        except Exception as e:
            logger.error("get_credentials_error", error=str(e), client_id=client_id, service=service_name)
            return None


# Global Supabase client instance
_supabase_client: Optional[SupabaseClient] = None


def get_supabase_client() -> SupabaseClient:
    """Get or create Supabase client singleton."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client
