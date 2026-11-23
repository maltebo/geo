"""Integration tests: AI extraction candidate selection and per-machine processing."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pressmuenzen.ai import job
from pressmuenzen.ai.extract import ExtractionResult
from pressmuenzen.db.models import Machine
from pressmuenzen.domain.models import GpsSource, MachineStatus

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 23, 3, 0, tzinfo=UTC)
RECHECK = timedelta(days=7)


def _machine(mid: int, *, source: GpsSource, analyzed: datetime | None = None) -> Machine:
    return Machine(
        id=mid,
        source_url=f"u{mid}",
        name=f"M{mid}",
        gps_source=source.value,
        last_ai_analyzed_at=analyzed,
    )


async def _pick(
    session: AsyncSession, limit: int, exclude: frozenset[int] = frozenset()
) -> list[int]:
    machines = await job.pick_machines(
        session, limit, exclude=exclude, now=NOW, recheck_after=RECHECK
    )
    return [m.id for m in machines]


async def test_recently_checked_machines_are_not_picked(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add_all(
        [
            _machine(1, source=GpsSource.NONE, analyzed=NOW - timedelta(days=1)),
            _machine(2, source=GpsSource.NONE, analyzed=NOW - timedelta(days=8)),
            _machine(3, source=GpsSource.FULL_NAME_GEOCODE),
        ]
    )
    await db_session.flush()

    assert await _pick(db_session, 10) == [2, 3]


async def test_pick_orders_by_uncertainty_then_age(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add_all(
        [
            _machine(1, source=GpsSource.FORUM_GPS),
            _machine(2, source=GpsSource.NONE, analyzed=NOW - timedelta(days=30)),
            _machine(3, source=GpsSource.NONE),
            _machine(4, source=GpsSource.PARTIAL_NAME_GEOCODE),
        ]
    )
    await db_session.flush()

    assert await _pick(db_session, 10) == [3, 2, 4, 1]


async def test_pick_honours_limit_and_exclusions(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add_all([_machine(i, source=GpsSource.NONE) for i in (1, 2, 3)])
    await db_session.flush()

    assert await _pick(db_session, 1, exclude=frozenset({1})) == [2]


async def test_pick_skips_inactive_machines(db_session) -> None:  # type: ignore[no-untyped-def]
    inactive = _machine(1, source=GpsSource.NONE)
    inactive.status = MachineStatus.GONE
    db_session.add_all([inactive, _machine(2, source=GpsSource.NONE)])
    await db_session.flush()

    assert await _pick(db_session, 10) == [2]


# ---------------------------------------------------------------------------
# process_machine
# ---------------------------------------------------------------------------


@pytest.fixture
def bound_session_scope(db_session, monkeypatch):  # type: ignore[no-untyped-def]
    maker = async_sessionmaker(db_session.bind, expire_on_commit=False)

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session
            await session.commit()

    monkeypatch.setattr(job, "session_scope", scope)
    return maker


def _fetcher(text: str, count: int = 1):  # type: ignore[no-untyped-def]
    async def fetch(url: str) -> tuple[str, int]:
        return text, count

    return fetch


async def _no_llm(text: str) -> ExtractionResult:
    raise AssertionError("LLM must not be called")


async def _reload(maker, mid: int) -> Machine:  # type: ignore[no-untyped-def]
    async with maker() as session:
        m = await session.get(Machine, mid)
        assert m is not None
        return m


async def test_unchanged_thread_skips_llm_and_starts_cooldown(
    db_session, bound_session_scope
) -> None:  # type: ignore[no-untyped-def]
    text = "[a]\nsome post"
    m = _machine(1, source=GpsSource.NONE, analyzed=NOW - timedelta(days=30))
    m.thread_content_hash = hashlib.sha256(text.encode()).hexdigest()
    db_session.add(m)
    await db_session.commit()

    outcome = await job.process_machine(m, fetch_thread=_fetcher(text), extract=_no_llm, now=NOW)

    assert outcome.llm_called is False
    assert (await _reload(bound_session_scope, 1)).last_ai_analyzed_at == NOW


async def test_empty_thread_fails_without_llm_and_starts_cooldown(
    db_session, bound_session_scope
) -> None:  # type: ignore[no-untyped-def]
    m = _machine(1, source=GpsSource.NONE)
    db_session.add(m)
    await db_session.commit()

    with pytest.raises(job.EmptyThreadError):
        await job.process_machine(m, fetch_thread=_fetcher("", 0), extract=_no_llm, now=NOW)

    stored = await _reload(bound_session_scope, 1)
    assert stored.last_ai_analyzed_at == NOW
    assert stored.thread_content_hash == hashlib.sha256(b"").hexdigest()


async def test_changed_thread_calls_llm_and_stores_hash(db_session, bound_session_scope) -> None:  # type: ignore[no-untyped-def]
    m = _machine(1, source=GpsSource.NONE)
    db_session.add(m)
    await db_session.commit()
    calls: list[str] = []

    async def extract(text: str) -> ExtractionResult:
        calls.append(text)
        return ExtractionResult(summary="Steht am Bahnhof.")

    outcome = await job.process_machine(
        m, fetch_thread=_fetcher("[a]\nnew post", 1), extract=extract, now=NOW
    )

    assert outcome.llm_called is True
    assert calls == ["[a]\nnew post"]
    stored = await _reload(bound_session_scope, 1)
    assert stored.last_ai_analyzed_at == NOW
    assert stored.ai_summary == "Steht am Bahnhof."
    assert stored.thread_content_hash == hashlib.sha256(b"[a]\nnew post").hexdigest()
