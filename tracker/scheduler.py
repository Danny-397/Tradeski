# tracker/scheduler.py
# Daily cron jobs, clean logging, start/stop control, and modular design.

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)


class SchedulerManager:
    """Manage background scheduled jobs using APScheduler."""

    def __init__(self):
        self.scheduler = BackgroundScheduler()

    def start(self):
        logger.info("Starting background scheduler")
        self.scheduler.start()

    def stop(self):
        logger.info("Stopping background scheduler")
        self.scheduler.shutdown()

    def add_interval_job(self, func, seconds: int, name: str):
        """Schedule a job to run every N seconds."""
        self.scheduler.add_job(
            func,
            IntervalTrigger(seconds=seconds),
            id=name,
            replace_existing=True,
        )
        logger.info("Scheduled interval job: %s every %ss", name, seconds)

    def add_daily_job(self, func, hour: int, minute: int, name: str):
        """Schedule a job to run daily at a specific hour/minute."""
        self.scheduler.add_job(
            func,
            CronTrigger(hour=hour, minute=minute),
            id=name,
            replace_existing=True,
        )
        logger.info("Scheduled daily job: %s at %02d:%02d", name, hour, minute)
