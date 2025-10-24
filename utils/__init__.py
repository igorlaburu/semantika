"""Utilities module for semantika."""

from .logger import get_logger, log
from .config import settings
from .supabase_client import get_supabase_client, SupabaseClient
from .qdrant_client import get_qdrant_client, QdrantClient
from .openrouter_client import get_openrouter_client, OpenRouterClient

__all__ = [
    "get_logger",
    "log",
    "settings",
    "get_supabase_client",
    "SupabaseClient",
    "get_qdrant_client",
    "QdrantClient",
    "get_openrouter_client",
    "OpenRouterClient",
]
