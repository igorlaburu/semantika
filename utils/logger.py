"""JSON structured logging for semantika.

All services log to stdout in JSON format for easy parsing and monitoring.
"""

import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional


def log(
    level: str,
    service: str,
    action: str,
    **kwargs: Any
) -> None:
    """
    Log a structured JSON message to stdout.

    Args:
        level: Log level (DEBUG, INFO, WARN, ERROR)
        service: Service name (api, scheduler, core_ingest, etc.)
        action: Action being performed (ingest_start, document_added, etc.)
        **kwargs: Additional context fields

    Example:
        log("INFO", "core_ingest", "document_added",
            client_id="uuid-A", qdrant_id="uuid-1", source="web")
    """
    log_entry = {
        "level": level.upper(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": service,
        "action": action,
        **kwargs
    }

    # Print to stdout as JSON
    print(json.dumps(log_entry), file=sys.stdout, flush=True)


class Logger:
    """Logger class with service context."""

    def __init__(self, service: str):
        """
        Initialize logger for a specific service.

        Args:
            service: Name of the service (api, scheduler, etc.)
        """
        self.service = service

    def debug(self, action: str, **kwargs: Any) -> None:
        """Log DEBUG level message."""
        log("DEBUG", self.service, action, **kwargs)

    def info(self, action: str, **kwargs: Any) -> None:
        """Log INFO level message."""
        log("INFO", self.service, action, **kwargs)

    def warn(self, action: str, **kwargs: Any) -> None:
        """Log WARN level message."""
        log("WARN", self.service, action, **kwargs)

    def error(self, action: str, error: Optional[str] = None, **kwargs: Any) -> None:
        """Log ERROR level message."""
        if error:
            kwargs["error"] = error
        log("ERROR", self.service, action, **kwargs)


def get_logger(service: str) -> Logger:
    """
    Get a logger instance for a service.

    Args:
        service: Name of the service

    Returns:
        Logger instance

    Example:
        logger = get_logger("api")
        logger.info("request_received", method="GET", path="/health")
    """
    return Logger(service)
