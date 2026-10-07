"""Async SQLAlchemy engine/session factory + FastAPI dependency.

DATABASE_URL is read from `app.core.config.Settings` — never hardcoded. PostgreSQL (asyncpg) is the
supported production/dev database; SQLite (aiosqlite) works for tests via `configure_database`.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

engine: AsyncEngine
AsyncSessionLocal: async_sessionmaker[AsyncSession]


def configure_database(url: str | None = None) -> None:
    """(Re)build the global engine + session factory. Called once at import and by tests."""
    global engine, AsyncSessionLocal
    url = url or get_settings().database_url
    kwargs: dict = {"echo": False}
    if not url.startswith("sqlite"):
        kwargs["pool_pre_ping"] = True
    engine = create_async_engine(url, **kwargs)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return AsyncSessionLocal


configure_database()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: commits on clean exit, rolls back on exception, always closes."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
