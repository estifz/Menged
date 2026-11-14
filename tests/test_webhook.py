"""The webhook secret Telegram receives must be in its allowed alphabet, and the
webhook route must accept exactly that value."""

import re

from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.main import app

TELEGRAM_ALLOWED = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def test_any_secret_becomes_telegram_safe():
    # Render's generateValue output can contain + / = which Telegram rejects.
    for raw in ("change-me", "aB3+/x9==", "Zm9vYmFy/+==", "with spaces & symbols!"):
        token = Settings(webhook_secret=raw).telegram_secret_token
        assert TELEGRAM_ALLOWED.match(token), raw
    assert Settings(webhook_secret="a").telegram_secret_token != Settings(webhook_secret="b").telegram_secret_token


def test_weak_webhook_secrets_are_refused():
    assert not Settings(webhook_secret="change-me").webhook_secret_is_strong
    assert not Settings(webhook_secret="short").webhook_secret_is_strong
    assert Settings(webhook_secret="Zm9vYmFyYmF6cXV4+/==").webhook_secret_is_strong


async def test_webhook_route_checks_derived_secret(db, channel):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/telegram/webhook", json={})).status_code == 403
        raw = {"X-Telegram-Bot-Api-Secret-Token": get_settings().webhook_secret}
        assert (await c.post("/telegram/webhook", json={}, headers=raw)).status_code == 403
        good = {"X-Telegram-Bot-Api-Secret-Token": get_settings().telegram_secret_token}
        # Correct secret passes the check; 503 because the bot is disabled in tests.
        assert (await c.post("/telegram/webhook", json={}, headers=good)).status_code == 503
