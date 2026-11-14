"""Alembic environment. Uses the direct (non-pooled) DATABASE_URL from .env,
or MENGED_MIGRATION_URL when set (used to autogenerate against SQLite)."""

import asyncio
import os

from alembic import context

from app.config import get_settings
from app.db import make_engine
from app.models import Base

target_metadata = Base.metadata


def _url_and_raw() -> tuple[str, str]:
    override = os.environ.get("MENGED_MIGRATION_URL")
    if override:
        return override, override
    s = get_settings()
    return s.migration_database_url, s.database_url


def run_migrations_offline() -> None:
    url, _ = _url_and_raw()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, raw = _url_and_raw()
    engine = make_engine(url, raw_url=raw)
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
