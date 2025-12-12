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

    async def get_tasks_by_client(self, client_id: str, company_id: str, is_active: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Get all tasks for a client within a company."""
        try:
            query = self.client.table("tasks").select("*").eq("client_id", client_id).eq("company_id", company_id)

            if is_active is not None:
                query = query.eq("is_active", is_active)

            response = query.execute()
            return response.data or []

        except Exception as e:
            logger.error("get_tasks_error", error=str(e), client_id=client_id, company_id=company_id)
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
        company_id: str,
        source_type: str,
        target: str,
        frequency_min: int,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new task."""
        try:
            task_data = {
                "client_id": client_id,
                "company_id": company_id,
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
                    company_id=company_id,
                    source_type=source_type
                )
                return created_task
            else:
                raise Exception("Failed to create task")

        except Exception as e:
            logger.error("create_task_error", error=str(e), client_id=client_id, company_id=company_id)
            raise

    async def get_task_by_id(self, task_id: str, company_id: str) -> Optional[Dict[str, Any]]:
        """Get task by ID within a company."""
        try:
            response = self.client.table("tasks").select("*").eq("task_id", task_id).eq("company_id", company_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("get_task_by_id_error", error=str(e), task_id=task_id, company_id=company_id)
            return None

    async def delete_task(self, task_id: str, company_id: str) -> bool:
        """Delete a task (soft delete - sets is_active to False) within a company."""
        try:
            response = self.client.table("tasks").update({"is_active": False}).eq("task_id", task_id).eq("company_id", company_id).execute()

            if response.data and len(response.data) > 0:
                logger.info("task_deleted", task_id=task_id, company_id=company_id)
                return True
            else:
                raise Exception("Failed to delete task")

        except Exception as e:
            logger.error("delete_task_error", error=str(e), task_id=task_id, company_id=company_id)
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
    # EXECUTIONS
    # ============================================

    async def log_execution(
        self,
        client_id: str,
        source_name: str,
        source_type: str,
        items_count: int = 0,
        status_code: Optional[int] = None,
        status: str = "success",
        details: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict] = None,
        duration_ms: Optional[int] = None,
        task_id: Optional[str] = None,
        workflow_code: Optional[str] = None,
        company_id: Optional[str] = None
    ) -> str:
        """Log an execution to the executions table."""
        try:
            execution_data = {
                "client_id": client_id,
                "company_id": company_id,
                "source_name": source_name,
                "source_type": source_type,
                "items_count": items_count,
                "status_code": status_code,
                "status": status,
                "details": details,
                "error_message": error_message,
                "metadata": metadata or {},
                "duration_ms": duration_ms,
                "task_id": task_id,
                "workflow_code": workflow_code
            }
            
            result = self.client.table("executions").insert(execution_data).execute()
            
            if result.data and len(result.data) > 0:
                execution_id = result.data[0]["execution_id"]
                logger.debug("execution_logged", 
                    execution_id=execution_id,
                    source_name=source_name,
                    source_type=source_type,
                    status=status
                )
                return execution_id
            else:
                logger.error("log_execution_failed", data=execution_data)
                return None
            
        except Exception as e:
            logger.error("log_execution_error", error=str(e))
            raise

    # ============================================
    # PRESS SOURCES
    # ============================================

    async def get_sources_by_client(self, client_id: str, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all sources for a client, optionally filtered by type."""
        try:
            query = self.client.table("sources")\
                .select("*")\
                .eq("client_id", client_id)\
                .eq("is_active", True)
            
            if source_type:
                query = query.eq("source_type", source_type)
            
            response = query.execute()
            return response.data or []
            
        except Exception as e:
            logger.error("get_sources_by_client_error", error=str(e))
            return []

    async def get_email_routing_for_address(self, email_address: str) -> Optional[Dict[str, Any]]:
        """Find which source handles a specific email address."""
        try:
            # First try exact match
            exact_match = self.client.table("email_routing")\
                .select("*, sources!inner(*)")\
                .eq("email_pattern", email_address)\
                .eq("pattern_type", "exact")\
                .eq("sources.is_active", True)\
                .order("priority", desc=True)\
                .limit(1)\
                .execute()
            
            if exact_match.data:
                return exact_match.data[0]
            
            # Try pattern matching (prefix, domain, etc.)
            # This could be enhanced with more sophisticated pattern matching
            domain = email_address.split('@')[1] if '@' in email_address else ""
            
            domain_match = self.client.table("email_routing")\
                .select("*, sources!inner(*)")\
                .eq("email_pattern", f"@{domain}")\
                .eq("pattern_type", "domain")\
                .eq("sources.is_active", True)\
                .order("priority", desc=True)\
                .limit(1)\
                .execute()
            
            if domain_match.data:
                return domain_match.data[0]
            
            return None
            
        except Exception as e:
            logger.error("get_email_routing_error", email=email_address, error=str(e))
            return None

    async def get_scheduled_sources(self) -> List[Dict[str, Any]]:
        """Get all sources that need scheduled execution."""
        try:
            response = self.client.table("sources")\
                .select("*")\
                .eq("is_active", True)\
                .in_("source_type", ["scraping", "api", "system"])\
                .not_.is_("schedule_config", "null")\
                .execute()
            
            return response.data or []
            
        except Exception as e:
            logger.error("get_scheduled_sources_error", error=str(e))
            return []

    async def update_source_execution_stats(
        self, 
        source_id: str, 
        success: bool, 
        items_processed: int = 0
    ) -> bool:
        """Update execution statistics for a source."""
        try:
            # Use SQL functions for incrementing
            if success:
                response = self.client.rpc('increment_source_stats', {
                    'source_id': source_id,
                    'success': True,
                    'items_processed': items_processed
                }).execute()
            else:
                response = self.client.rpc('increment_source_stats', {
                    'source_id': source_id,
                    'success': False,
                    'items_processed': 0
                }).execute()
            
            return len(response.data) > 0
            
        except Exception as e:
            logger.error("update_source_execution_stats_error", source_id=source_id, error=str(e))
            return False

    # ============================================
    # COMPANIES
    # ============================================

    async def get_company_by_email_alias(self, email_alias: str) -> Optional[Dict[str, Any]]:
        """Get company by email alias in settings."""
        try:
            response = self.client.table("companies")\
                .select("*")\
                .contains("settings", {"email_alias": email_alias})\
                .eq("is_active", True)\
                .execute()

            if response.data and len(response.data) > 0:
                logger.debug("company_found_by_email", email_alias=email_alias, company_id=response.data[0]["id"])
                return response.data[0]
            else:
                logger.warn("company_not_found_by_email", email_alias=email_alias)
                return None

        except Exception as e:
            logger.error("get_company_by_email_error", error=str(e), email_alias=email_alias)
            return None

    async def get_company_by_id(self, company_id: str) -> Optional[Dict[str, Any]]:
        """Get company by ID."""
        try:
            response = self.client.table("companies").select("*").eq("id", company_id).eq("is_active", True).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("get_company_by_id_error", error=str(e), company_id=company_id)
            return None

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

    # ============================================
    # PRESS CONTEXT UNITS
    # ============================================

    async def create_context_unit(
        self,
        context_unit_id: str,
        company_id: str,
        organization_id: str,
        source_type: str,
        source_id: str,
        source_metadata: Dict[str, Any],
        title: str,
        summary: str,
        tags: List[str],
        atomic_statements: List[Dict[str, Any]],
        raw_text: str = ""
    ) -> Dict[str, Any]:
        """Create a context unit."""
        try:
            data = {
                "id": context_unit_id,
                "company_id": company_id,
                "organization_id": organization_id,
                "source_type": source_type,
                "source_id": source_id,
                "source_metadata": source_metadata,
                "title": title,
                "summary": summary,
                "tags": tags,
                "atomic_statements": atomic_statements,
                "raw_text": raw_text,
                "status": "completed"
            }

            response = self.client.table("press_context_units").insert(data).execute()

            if response.data and len(response.data) > 0:
                created_unit = response.data[0]
                logger.info(
                    "context_unit_created",
                    context_unit_id=context_unit_id,
                    company_id=company_id
                )
                return created_unit
            else:
                raise Exception("Failed to create context unit")

        except Exception as e:
            logger.error("create_context_unit_error", error=str(e), context_unit_id=context_unit_id)
            raise

    async def get_context_units_by_company(
        self,
        company_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get context units for a company."""
        try:
            response = self.client.table("press_context_units")\
                .select("*")\
                .eq("company_id", company_id)\
                .order("processed_at", desc=True)\
                .limit(limit)\
                .offset(offset)\
                .execute()

            return response.data or []

        except Exception as e:
            logger.error("get_context_units_error", error=str(e), company_id=company_id)
            return []

    # ============================================
    # PRESS STYLES
    # ============================================

    async def create_style(
        self,
        company_id: str,
        style_name: str,
        style_guide_markdown: str,
        created_by_client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a style guide."""
        try:
            data = {
                "company_id": company_id,
                "style_name": style_name,
                "style_guide_markdown": style_guide_markdown,
                "is_active": True
            }

            if created_by_client_id:
                data["created_by_client_id"] = created_by_client_id

            response = self.client.table("press_styles").insert(data).execute()

            if response.data and len(response.data) > 0:
                created_style = response.data[0]
                logger.info(
                    "style_created",
                    style_id=created_style["id"],
                    style_name=style_name,
                    company_id=company_id
                )
                return created_style
            else:
                raise Exception("Failed to create style")

        except Exception as e:
            logger.error("create_style_error", error=str(e), style_name=style_name)
            raise

    async def get_styles_by_company(self, company_id: str) -> List[Dict[str, Any]]:
        """Get all active styles for a company."""
        try:
            response = self.client.table("press_styles")\
                .select("*")\
                .eq("company_id", company_id)\
                .eq("is_active", True)\
                .order("created_at", desc=True)\
                .execute()

            return response.data or []

        except Exception as e:
            logger.error("get_styles_error", error=str(e), company_id=company_id)
            return []

    async def get_style_by_id(self, style_id: str, company_id: str) -> Optional[Dict[str, Any]]:
        """Get style by ID and company."""
        try:
            response = self.client.table("press_styles")\
                .select("*")\
                .eq("id", style_id)\
                .eq("company_id", company_id)\
                .eq("is_active", True)\
                .single()\
                .execute()

            return response.data

        except Exception as e:
            logger.error("get_style_by_id_error", error=str(e), style_id=style_id)
            return None


# Global Supabase client instance
_supabase_client: Optional[SupabaseClient] = None


def get_supabase_client() -> SupabaseClient:
    """Get or create Supabase client singleton."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client
