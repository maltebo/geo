"""Shared pytest fixtures.

Integration tests need a live PostGIS. They run against ``TEST_DATABASE_URL``
(a CI service container or a local docker postgis). When that env var is unset,
integration tests are skipped so the unit suite still runs anywhere.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest


def _test_db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = _test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping integration tests")
    return url


@pytest.fixture
async def db_session(test_database_url: str) -> AsyncIterator[object]:
    # Imported lazily so unit-only runs do not require SQLAlchemy/asyncpg.
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from pressmuenzen.db.models import Base

    engine = create_async_engine(test_database_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
