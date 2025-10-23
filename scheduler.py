"""APScheduler daemon for periodic task execution.

Reads tasks from Supabase and executes them on schedule.
Also runs daily TTL cleanup job.
"""

import time
from utils.logger import get_logger

# Initialize logger
logger = get_logger("scheduler")


def main():
    """Main scheduler loop (placeholder for Phase 5)."""
    logger.info("scheduler_starting")

    try:
        # Keep scheduler alive
        while True:
            logger.debug("scheduler_heartbeat")
            time.sleep(60)  # Sleep for 1 minute

    except KeyboardInterrupt:
        logger.info("scheduler_stopping", reason="keyboard_interrupt")
    except Exception as e:
        logger.error("scheduler_error", error=str(e))
        raise


if __name__ == "__main__":
    main()
