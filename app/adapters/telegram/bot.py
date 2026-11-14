"""Bot setup: polling for local development, webhook in production."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request

from app.adapters import base as channels
from app.adapters.telegram.channel import TelegramChannel
from app.adapters.telegram.handlers import router as handlers_router
from app.adapters.telegram.handlers import setup_commands
from app.config import get_settings

log = logging.getLogger(__name__)

bot: Bot | None = None
dp: Dispatcher | None = None
_polling_task: asyncio.Task | None = None

webhook_router = APIRouter()
WEBHOOK_PATH = "/telegram/webhook"


async def start_bot() -> None:
    global bot, dp, _polling_task
    s = get_settings()
    if not s.telegram_bot_token:
        log.warning("TELEGRAM_BOT_TOKEN not set; bot disabled")
        return
    bot = Bot(s.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers_router)
    channels.register("telegram", TelegramChannel(bot))

    try:
        await setup_commands(bot)
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)

    # Telegram may be unreachable for a while (network hiccup, DNS block).
    # Never fail start-up because of it: keep retrying in the background.
    if s.telegram_mode == "webhook":
        _polling_task = asyncio.create_task(_set_webhook_forever())
    else:
        _polling_task = asyncio.create_task(_poll_forever())


async def _set_webhook_forever() -> None:
    s = get_settings()
    url = s.webhook_base_url.rstrip("/") + WEBHOOK_PATH
    while True:
        try:
            assert bot is not None and dp is not None
            await bot.set_webhook(url, secret_token=s.webhook_secret, allowed_updates=dp.resolve_used_update_types())
            log.info("webhook set to %s", url)
            return
        except Exception as e:
            log.warning("Telegram not reachable (%s); retrying webhook setup in 15 s", e)
            await asyncio.sleep(15)


async def _poll_forever() -> None:
    delay = 5
    while True:
        try:
            assert bot is not None and dp is not None
            await bot.delete_webhook(drop_pending_updates=False)
            log.info("bot polling started")
            await dp.start_polling(bot, handle_signals=False, allowed_updates=dp.resolve_used_update_types())
            return  # polling stopped normally
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Telegram not reachable (%s); retrying in %d s", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


async def stop_bot() -> None:
    global _polling_task
    if dp is not None and _polling_task is not None:
        try:
            await dp.stop_polling()
        except RuntimeError:
            pass
        _polling_task.cancel()
        _polling_task = None
    if bot is not None:
        await bot.session.close()


@webhook_router.post(WEBHOOK_PATH, include_in_schema=False)
async def telegram_webhook(
    request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)
) -> dict:
    if x_telegram_bot_api_secret_token != get_settings().webhook_secret:
        raise HTTPException(status_code=403)
    if bot is None or dp is None:
        raise HTTPException(status_code=503)
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}
