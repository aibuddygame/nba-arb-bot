"""
Scheduler module for NBA Arbitrage Bot.

This module handles timezone-aware scheduling of scan operations.
It uses APScheduler with explicit timezone handling to ensure
consistent behavior regardless of the local machine's timezone.

Key features:
- Timezone-aware scheduling (does NOT rely on local machine timezone)
- Configurable start time and interval from config.yaml
- Proper handling of DST transitions
- Logging of next scheduled run times

Usage:
    from nba_arb_bot.scheduler import start_scheduler

    # Blocking - runs until interrupted
    start_scheduler()

    # Or get the scheduler instance for more control
    from nba_arb_bot.scheduler import create_scheduler
    scheduler = create_scheduler()
    scheduler.start()
"""

from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from nba_arb_bot.config import Config, load_config

# Module logger
logger = logging.getLogger(__name__)


def run_scan() -> None:
    """
    Run the scheduled scan job.

    This function is called by the scheduler at each interval.
    It scrapes NBA odds, generates an analysis report, and exports it to a file.
    """
    # Get timezone-aware current time for logging
    config = load_config()
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)

    logger.info(f"[SCAN] Running scan at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    try:
        # Import here to avoid circular imports
        from nba_arb_bot.report import export_report
        
        # Generate and export the report
        filepath = export_report()
        logger.info(f"[SCAN] Scan complete. Report saved to: {filepath}")
        
    except Exception as e:
        logger.error(f"[SCAN] Scan failed: {e}")
        raise


def setup_logging(config: Config) -> None:
    """
    Configure logging based on config settings.

    Args:
        config: Configuration object with logging settings
    """
    log_level = getattr(logging, config.logging.level, logging.INFO)

    # Create formatter with timezone-aware timestamps
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if config.logging.file_enabled:
        from pathlib import Path

        log_path = Path(config.logging.file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_next_run_time(scheduler: BlockingScheduler, config: Config) -> str:
    """
    Get a formatted string of the next scheduled run time.

    Args:
        scheduler: The APScheduler instance
        config: Configuration object for timezone

    Returns:
        Formatted string with next run time in configured timezone
    """
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    
    # Calculate next run time based on config
    start_hour, start_minute = map(int, config.scan_start_time.split(":"))
    
    # Find the next scheduled hour
    if config.scan_interval == 1:
        # Every hour at start_minute
        next_run = now.replace(minute=start_minute, second=0, microsecond=0)
        if now.minute >= start_minute:
            next_run = next_run + timedelta(hours=1)
    else:
        # Specific hours based on interval
        run_hours = [h for h in range(24) if (h - start_hour) % config.scan_interval == 0]
        
        # Find next run hour
        next_hour = None
        for h in run_hours:
            if h > now.hour or (h == now.hour and now.minute < start_minute):
                next_hour = h
                break
        
        if next_hour is None:
            # Next run is tomorrow at first scheduled hour
            next_run = now.replace(hour=run_hours[0], minute=start_minute, second=0, microsecond=0)
            next_run = next_run + timedelta(days=1)
        else:
            next_run = now.replace(hour=next_hour, minute=start_minute, second=0, microsecond=0)

    return next_run.strftime("%Y-%m-%d %H:%M:%S %Z")


def log_next_run(scheduler: BlockingScheduler, config: Config) -> None:
    """
    Log when the next scan will occur.

    Args:
        scheduler: The APScheduler instance
        config: Configuration object
    """
    next_run = get_next_run_time(scheduler, config)
    logger.info(f"[SCHEDULER] Next scan scheduled for: {next_run}")


def create_scheduler(config: Config | None = None) -> BlockingScheduler:
    """
    Create and configure the scheduler without starting it.

    This allows for more control over the scheduler lifecycle,
    useful for testing or custom integrations.

    Args:
        config: Optional configuration object. If not provided,
                loads from default config file.

    Returns:
        Configured BlockingScheduler instance (not started)

    Example:
        >>> scheduler = create_scheduler()
        >>> scheduler.start()  # Blocks until interrupted
    """
    if config is None:
        config = load_config()

    # Parse start time
    start_hour, start_minute = map(int, config.scan_start_time.split(":"))

    # Get timezone object
    tz = ZoneInfo(config.timezone)

    # Create scheduler with explicit timezone
    # job_defaults prevent jobs from piling up if one takes too long
    scheduler = BlockingScheduler(
        timezone=tz,
        job_defaults={
            "coalesce": True,  # Combine missed runs into one
            "max_instances": 1,  # Only one instance of each job at a time
            "misfire_grace_time": 60 * 30,  # 30 minutes grace for missed jobs
        },
    )

    # Build cron trigger for hourly runs starting at configured time
    # This creates runs at: 00:00, 01:00, 02:00, ... (if interval=1)
    # Or: 00:00, 04:00, 08:00, ... (if interval=4)
    #
    # The cron expression handles intervals by specifying which hours to run:
    # - interval=1: every hour (0-23)
    # - interval=2: every 2 hours starting from start_hour
    # - interval=4: every 4 hours starting from start_hour
    if config.scan_interval == 1:
        # Every hour at the configured minute
        trigger = CronTrigger(
            minute=start_minute,
            timezone=tz,
        )
    else:
        # Calculate which hours to run based on interval
        # Starting from start_hour, run every scan_interval hours
        run_hours = list(range(start_hour, 24, config.scan_interval))
        if start_hour > 0:
            # Also include hours before start_hour that fit the pattern
            # e.g., if start=2, interval=4: hours are 2,6,10,14,18,22
            run_hours = [h for h in range(24) if (h - start_hour) % config.scan_interval == 0]

        trigger = CronTrigger(
            hour=",".join(map(str, run_hours)),
            minute=start_minute,
            timezone=tz,
        )

    # Add the scan job
    scheduler.add_job(
        run_scan,
        trigger=trigger,
        id="arbitrage_scan",
        name="NBA Arbitrage Scan",
        replace_existing=True,
    )

    return scheduler


def start_scheduler(config: Config | None = None) -> None:
    """
    Start the scheduler and block until interrupted.

    This is the main entry point for running the scheduler.
    It sets up logging, creates the scheduler, and handles
    graceful shutdown on SIGINT/SIGTERM.

    Args:
        config: Optional configuration object. If not provided,
                loads from default config file.

    Example:
        >>> from nba_arb_bot.scheduler import start_scheduler
        >>> start_scheduler()  # Blocks until Ctrl+C
    """
    if config is None:
        config = load_config()

    # Set up logging
    setup_logging(config)

    # Get timezone for display
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)

    logger.info("=" * 60)
    logger.info("NBA Arbitrage Bot - Scheduler Starting")
    logger.info("=" * 60)
    logger.info(f"[CONFIG] Timezone:       {config.timezone}")
    logger.info(f"[CONFIG] Current time:   {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info(f"[CONFIG] Scan start:     {config.scan_start_time}")
    logger.info(f"[CONFIG] Scan interval:  Every {config.scan_interval} hour(s)")
    logger.info(f"[CONFIG] Dry run:        {config.is_dry_run}")
    logger.info("=" * 60)

    # Create scheduler
    scheduler = create_scheduler(config)

    # Log next run time
    log_next_run(scheduler, config)

    # Set up graceful shutdown handlers
    def shutdown(signum: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(signum).name
        logger.info(f"[SCHEDULER] Received {sig_name}, shutting down...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start the scheduler (blocking)
    logger.info("[SCHEDULER] Scheduler started. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[SCHEDULER] Scheduler stopped.")


# Allow running this module directly
if __name__ == "__main__":
    start_scheduler()
