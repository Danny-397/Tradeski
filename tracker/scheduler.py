# daily cron jobs
# clean logging. Start/stop contorl and modular design 


from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self):
        self.scheduler = BackgroundScheduler()

    def start(self):
        logger.info("Starting background scheduler")
        self.scheduler.start()

    def stop(self):
        logger.info("Stopping background scheduler")
        self.scheduler.shutdown()

    def add_interval_job(self, func, seconds: int, name: str):
        self.scheduler.add_job(
            func,
            IntervalTrigger(seconds=seconds),
            id=name,
            replace_existing=True
        )
        logger.info(f"Scheduled interval job: {name} every {seconds}s")

    def add_daily_job(self, func, hour: int, minute: int, name: str):
        self.scheduler.add_job(
            func,
            CronTrigger(hour=hour, minute=minute),
            id=name,
            replace_existing=True
        )
        logger.info(f"Scheduled daily job: {name} at {hour}:{minute:02d}")

