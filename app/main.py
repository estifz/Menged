"""Menged backend entry point: `uvicorn app.main:app`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters import base as channels
from app.adapters.api.routes import AppChannel
from app.adapters.api.routes import router as api_router
from app.config import get_settings
from app.db import get_engine, init_engine
from app.demo.data import load_demo
from app.services import nominatim
from app.services.http import close_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("menged")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    init_engine()
    channels.register("app", AppChannel())

    demo = load_demo()
    if demo:
        nominatim.seed_streets(demo.streets)

    scheduler = None
    if s.enable_scheduler:
        from app.engine.scheduler import create_scheduler

        scheduler = create_scheduler()
        scheduler.start()

    bot_started = False
    if s.enable_bot:
        from app.adapters.telegram.bot import start_bot

        await start_bot()
        bot_started = True

    log.info("Menged backend started")
    try:
        yield
    finally:
        if bot_started:
            from app.adapters.telegram.bot import stop_bot

            await stop_bot()
        if scheduler:
            scheduler.shutdown(wait=False)
        await close_client()
        await get_engine().dispose()


app = FastAPI(title="Menged backend", version="1.0", lifespan=lifespan)
app.include_router(api_router)

if get_settings().enable_bot:
    from app.adapters.telegram.bot import webhook_router

    app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
