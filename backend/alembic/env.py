"""Alembic environment script.

Reads DATABASE_URL from `app.core.config.Settings` (i.e. from the
environment / .env file), same as the running app — no URL is duplicated
in alembic.ini. Uses an async engine since the app's DATABASE_URL is an
asyncpg URL; migrations run via `connection.run_sync(...)`.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Ensure `app` package is importable when alembic is run from backend/.
from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402  (imports every model for autogenerate)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_settings = get_settings()


def get_url() -> str:
    return _settings.database_url


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live DB connection (`alembic upgrade --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable: AsyncEngine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
