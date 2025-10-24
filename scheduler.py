"""APScheduler daemon for periodic task execution.

Runs:
- File monitor (watches directory for new files)
- Email monitor (watches inbox for new emails)
- Task scheduler (executes scheduled scraping tasks - FASE 5)
- TTL cleanup (daily cleanup of old data - FASE 5)
"""

import asyncio
from typing import Optional

from utils.logger import get_logger
from utils.config import settings
from sources.file_monitor import FileMonitor
from sources.email_monitor import EmailMonitor

logger = get_logger("scheduler")


async def run_file_monitor():
    """Run file monitor in background."""
    try:
        if not settings.file_monitor_enabled:
            logger.info("file_monitor_disabled")
            return

        logger.info("starting_file_monitor")

        monitor = FileMonitor(
            watch_dir=settings.file_monitor_watch_dir,
            processed_dir=settings.file_monitor_processed_dir,
            check_interval=settings.file_monitor_interval
        )

        await monitor.start()

    except Exception as e:
        logger.error("file_monitor_error", error=str(e))


async def run_email_monitor():
    """Run email monitor in background."""
    try:
        if not settings.email_monitor_enabled:
            logger.info("email_monitor_disabled")
            return

        logger.info("starting_email_monitor")

        monitor = EmailMonitor(
            imap_server=settings.email_imap_server,
            imap_port=settings.email_imap_port,
            email_address=settings.email_address,
            password=settings.email_password,
            check_interval=settings.email_monitor_interval
        )

        await monitor.start()

    except Exception as e:
        logger.error("email_monitor_error", error=str(e))


async def main():
    """Main scheduler entry point."""
    logger.info("scheduler_starting")

    try:
        # Create tasks for monitors
        tasks = []

        if settings.file_monitor_enabled:
            tasks.append(asyncio.create_task(run_file_monitor()))

        if settings.email_monitor_enabled:
            tasks.append(asyncio.create_task(run_email_monitor()))

        if not tasks:
            logger.warn("no_monitors_enabled", message="Enable at least one monitor in .env")
            # Keep alive anyway
            while True:
                logger.debug("scheduler_heartbeat")
                await asyncio.sleep(60)
        else:
            # Run all monitors concurrently
            await asyncio.gather(*tasks)

    except KeyboardInterrupt:
        logger.info("scheduler_stopping", reason="keyboard_interrupt")
    except Exception as e:
        logger.error("scheduler_error", error=str(e))
        raise


if __name__ == "__main__":
    asyncio.run(main())
