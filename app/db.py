"""Async database engine and session factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings, needs_ssl

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def make_engine(url: str, raw_url: str = "", pgbouncer: bool = False) -> AsyncEngine:
    if url.startswith("sqlite"):
        return create_async_engine(url)
    connect_args: dict = {}
    if needs_ssl(raw_url or url):
        connect_args["ssl"] = "require"
    kwargs: dict = {"pool_pre_ping": True}
    if pgbouncer:
        # PgBouncer in transaction mode cannot keep prepared statements.
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        kwargs = {"poolclass": NullPool}
    return create_async_engine(url, connect_args=connect_args, **kwargs)


def init_engine(engine: AsyncEngine | None = None) -> AsyncEngine:
    """Create (or install) the global engine. Tests pass their own engine."""
    global _engine, _sessionmaker
    if engine is None:
        s = get_settings()
        engine = make_engine(
            s.app_database_url,
            raw_url=s.database_url_pooled or s.database_url,
            pgbouncer=s.uses_pgbouncer,
        )
    _engine = engine
    _sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A session that commits on success and rolls back on error."""
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        # Work that must only start once this transaction's rows are visible
        # to other sessions (e.g. background tasks that reference a new trip).
        for callback in session.info.pop("after_commit", []):
            callback()


def after_commit(session: AsyncSession, callback) -> None:
    """Run `callback()` after `session_scope` commits; dropped on rollback."""
    session.info.setdefault("after_commit", []).append(callback)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session
