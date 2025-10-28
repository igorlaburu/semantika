"""Workflow management system with usage control and backward compatibility.

Handles workflow execution, usage tracking, and tier-based limits while maintaining
compatibility with existing endpoints.
"""

from typing import Dict, Any, Optional, Callable
from datetime import datetime
import asyncio
import traceback
import importlib

from .logger import get_logger
from .supabase_client import get_supabase_client

logger = get_logger("workflow_manager")


class WorkflowManager:
    """Manages workflow execution with usage control and safety."""
    
    def __init__(self):
        self.supabase = get_supabase_client()
        
    async def execute_workflow(
        self,
        workflow_code: str,
        company_id: str,
        client_id: Optional[str],
        tier: str,
        workflow_function: Callable,
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute a workflow with usage control and safety.
        
        Args:
            workflow_code: Workflow identifier (e.g., 'micro_edit')
            company_id: Company UUID
            client_id: Client UUID (optional for scheduled workflows)
            tier: Pricing tier (starter, pro, unlimited)
            workflow_function: The actual workflow function to execute
            *args, **kwargs: Arguments to pass to the workflow function
            
        Returns:
            Workflow execution result or error response
        """
        execution_start = datetime.utcnow()
        
        try:
            # 1. Check usage limits (skip for unlimited tier)
            if tier != 'unlimited':
                usage_check = await self._check_usage_limits(
                    company_id=company_id,
                    workflow_code=workflow_code,
                    tier=tier
                )
                
                if not usage_check.get('allowed', False):
                    logger.warn(
                        "workflow_usage_limit_exceeded",
                        workflow_code=workflow_code,
                        company_id=company_id,
                        tier=tier,
                        error=usage_check.get('error')
                    )
                    return {
                        "success": False,
                        "error": "usage_limit_exceeded",
                        "details": usage_check.get('error'),
                        "usage_info": usage_check
                    }
            
            # 2. Execute workflow safely
            logger.info(
                "workflow_execution_start",
                workflow_code=workflow_code,
                company_id=company_id,
                tier=tier
            )
            
            # Execute the actual workflow function
            result = await workflow_function(*args, **kwargs)
            
            # 3. Record usage (even for unlimited tier for analytics)
            try:
                await self._record_usage(
                    company_id=company_id,
                    workflow_code=workflow_code,
                    client_id=client_id
                )
            except Exception as usage_error:
                # Don't fail the workflow if usage recording fails
                logger.warn(
                    "usage_recording_failed",
                    workflow_code=workflow_code,
                    error=str(usage_error)
                )
            
            # 4. Record execution metrics
            execution_time_ms = (datetime.utcnow() - execution_start).total_seconds() * 1000
            
            logger.info(
                "workflow_execution_success",
                workflow_code=workflow_code,
                company_id=company_id,
                execution_time_ms=round(execution_time_ms, 2)
            )
            
            return {
                "success": True,
                "data": result,
                "execution_time_ms": round(execution_time_ms, 2),
                "workflow_code": workflow_code
            }
            
        except Exception as e:
            # 5. Handle errors safely
            execution_time_ms = (datetime.utcnow() - execution_start).total_seconds() * 1000
            error_trace = traceback.format_exc()
            
            logger.error(
                "workflow_execution_failed",
                workflow_code=workflow_code,
                company_id=company_id,
                error=str(e),
                execution_time_ms=round(execution_time_ms, 2),
                trace=error_trace[:500]  # Truncate long traces
            )
            
            return {
                "success": False,
                "error": "workflow_execution_failed",
                "details": str(e),
                "execution_time_ms": round(execution_time_ms, 2),
                "workflow_code": workflow_code
            }
    
    async def _check_usage_limits(
        self,
        company_id: str,
        workflow_code: str,
        tier: str
    ) -> Dict[str, Any]:
        """Check if company can execute workflow based on tier limits."""
        try:
            # Call the PostgreSQL function
            result = self.supabase.client.rpc(
                'check_workflow_usage_limit',
                {
                    'p_company_id': company_id,
                    'p_workflow_code': workflow_code,
                    'p_tier': tier
                }
            ).execute()
            
            if result.data:
                return result.data
            else:
                # Fallback: allow execution if function fails
                logger.warn(
                    "usage_check_failed_allowing",
                    workflow_code=workflow_code,
                    company_id=company_id
                )
                return {"allowed": True, "fallback": True}
                
        except Exception as e:
            logger.error(
                "usage_check_error",
                workflow_code=workflow_code,
                error=str(e)
            )
            # Fail-safe: allow execution if check fails
            return {"allowed": True, "fallback": True}
    
    async def _record_usage(
        self,
        company_id: str,
        workflow_code: str,
        client_id: Optional[str]
    ) -> bool:
        """Record workflow usage for analytics and billing."""
        try:
            # Call the PostgreSQL function
            result = self.supabase.client.rpc(
                'record_workflow_usage',
                {
                    'p_company_id': company_id,
                    'p_workflow_code': workflow_code,
                    'p_client_id': client_id
                }
            ).execute()
            
            return result.data if result.data is not None else True
            
        except Exception as e:
            logger.error(
                "usage_recording_error",
                workflow_code=workflow_code,
                error=str(e)
            )
            return False


# Global workflow manager instance
_workflow_manager: Optional[WorkflowManager] = None


def get_workflow_manager() -> WorkflowManager:
    """Get the global workflow manager instance."""
    global _workflow_manager
    
    if _workflow_manager is None:
        _workflow_manager = WorkflowManager()
    
    return _workflow_manager


def workflow_wrapper(workflow_code: str):
    """
    Decorator to wrap existing workflow functions with usage control.
    
    Usage:
        @workflow_wrapper("micro_edit")
        async def micro_edit_function(client, request):
            # Existing function logic
            pass
    """
    def decorator(func):
        async def wrapper(client: Dict[str, Any], *args, **kwargs):
            manager = get_workflow_manager()
            
            # Extract company info
            company_id = client.get("company_id")
            client_id = client.get("client_id")
            tier = client.get("metadata", {}).get("tier", "starter")
            
            # If no company_id, use demo for backward compatibility
            if not company_id:
                company_id = "00000000-0000-0000-0000-000000000001"  # Demo company
                tier = "unlimited"
                logger.info(
                    "using_demo_company_fallback",
                    workflow_code=workflow_code,
                    client_id=client_id
                )
            
            return await manager.execute_workflow(
                workflow_code=workflow_code,
                company_id=company_id,
                client_id=client_id,
                tier=tier,
                workflow_function=func,
                client,
                *args,
                **kwargs
            )
        
        return wrapper
    return decorator