"""Background jobs in the same process (APScheduler): the 30-second trip timer
and the hourly privacy purge."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db import session_scope
from app.engine import trips as engine

log = logging.getLogger(__name__)


async def tick_job() -> None:
    try:
        async with session_scope() as session:
            await engine.tick(session)
    except Exception:
        log.exception("tick failed")


async def purge_job() -> None:
    try:
        async with session_scope() as session:
            n = await engine.purge_old_points(session)
        if n:
            log.info("purged %d old location points", n)
    except Exception:
        log.exception("purge failed")


def create_scheduler() -> AsyncIOScheduler:
    s = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(tick_job, "interval", seconds=s.tick_seconds, max_instances=1, coalesce=True, id="tick")
    scheduler.add_job(purge_job, "interval", hours=1, max_instances=1, coalesce=True, id="purge")
    return scheduler
