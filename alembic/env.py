"""Alembic environment. Runs migrations against the async engine.

The DB URL comes from application settings (env), not alembic.ini, so there is
one source of truth. geoalchemy2 is imported so geometry types resolve.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

import geoalchemy2  # noqa: F401  (registers geometry types for autogenerate)
from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from pressmuenzen.config import get_settings
from pressmuenzen.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def _include_object(obj: object, name: str | None, type_: str, *args: object) -> bool:
    # geoalchemy2 manages spatial indexes; let Alembic ignore them to avoid churn.
    is_spatial_index = (
        type_ == "index" and name is not None and name.startswith("idx_") and "geom" in name
    )
    return not is_spatial_index


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
