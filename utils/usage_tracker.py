"""LLM Usage Tracker.

Tracks token usage and costs for all LLM operations.
"""

import uuid
from typing import Optional, Dict, Any
from datetime import datetime

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client

logger = get_logger("usage_tracker")

# OpenRouter pricing (per 1M tokens)
# Source: https://openrouter.ai/models
PRICING = {
    "anthropic/claude-3.5-sonnet": {
        "input": 3.00,   # $3 per 1M input tokens
        "output": 15.00  # $15 per 1M output tokens
    },
    "openai/gpt-4o-mini": {
        "input": 0.15,   # $0.15 per 1M input tokens
        "output": 0.60   # $0.60 per 1M output tokens
    },
    "openai/gpt-4o": {
        "input": 5.00,
        "output": 15.00
    }
}


class UsageTracker:
    """Track LLM token usage and costs."""

    def __init__(self):
        """Initialize usage tracker."""
        self.supabase = get_supabase_client()

    async def track(
        self,
        model: str,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        organization_id: str,
        client_id: Optional[str] = None,
        context_unit_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Track LLM usage in database.

        Args:
            model: Full model name (e.g., "anthropic/claude-3.5-sonnet")
            operation: Operation type (e.g., "context_unit", "article", "style")
            input_tokens: Prompt tokens
            output_tokens: Completion tokens
            organization_id: Organization UUID (required)
            client_id: Client UUID (optional, for API calls)
            context_unit_id: Context unit UUID (optional)
            metadata: Additional metadata (optional)

        Returns:
            Usage record UUID
        """
        try:
            # Calculate costs
            pricing = PRICING.get(model, {"input": 0, "output": 0})
            input_cost = (input_tokens / 1_000_000) * pricing["input"]
            output_cost = (output_tokens / 1_000_000) * pricing["output"]
            total_cost = input_cost + output_cost

            # Create usage record (let Postgres generate the UUID)
            data = {
                "organization_id": organization_id,
                "context_unit_id": context_unit_id,
                "timestamp": datetime.utcnow().isoformat(),
                "model": model,
                "operation": operation,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "input_cost_usd": round(input_cost, 6),
                "output_cost_usd": round(output_cost, 6),
                "total_cost_usd": round(total_cost, 6),
                "metadata": metadata or {}
            }
            
            # Add client_id (now column exists, can be null for email sources)
            data["client_id"] = client_id

            # Insert into database
            result = self.supabase.client.table("llm_usage").insert(data).execute()

            logger.info(
                "usage_tracked",
                operation=operation,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(total_cost, 6)
            )

            return result.data[0]["id"] if result.data else ""

        except Exception as e:
            logger.error("usage_tracking_error", error=str(e))
            return ""

    async def get_usage_summary(
        self,
        organization_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get usage summary for organization or all.

        Args:
            organization_id: Filter by organization (None for all)
            days: Number of days to look back

        Returns:
            Dict with usage statistics
        """
        try:
            from datetime import timedelta

            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

            query = self.supabase.client.table("llm_usage") \
                .select("*") \
                .gte("timestamp", cutoff)

            if organization_id:
                query = query.eq("organization_id", organization_id)

            result = query.execute()

            # Calculate aggregates
            total_tokens = sum(r["total_tokens"] for r in result.data)
            total_cost = sum(r["total_cost_usd"] for r in result.data)
            total_calls = len(result.data)

            # Group by operation
            by_operation = {}
            for record in result.data:
                op = record["operation"]
                if op not in by_operation:
                    by_operation[op] = {"calls": 0, "tokens": 0, "cost": 0}
                by_operation[op]["calls"] += 1
                by_operation[op]["tokens"] += record["total_tokens"]
                by_operation[op]["cost"] += record["total_cost_usd"]

            return {
                "period_days": days,
                "total_calls": total_calls,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 2),
                "by_operation": by_operation
            }

        except Exception as e:
            logger.error("usage_summary_error", error=str(e))
            return {}


# Global instance
_usage_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    """Get or create usage tracker singleton."""
    global _usage_tracker
    if _usage_tracker is None:
        _usage_tracker = UsageTracker()
    return _usage_tracker
