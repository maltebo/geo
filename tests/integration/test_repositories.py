"""Integration tests: spatial search + precedence recompute against PostGIS."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pressmuenzen.db.models import Machine
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.db.repositories.users import UserRepository
from pressmuenzen.domain.models import Coordinate, GpsSource, MachineStatus

pytestmark = pytest.mark.integration

KOELN = Coordinate(lat=50.9413, lon=6.9583)
BONN = Coordinate(lat=50.7374, lon=7.0982)  # ~27 km from Köln
BERLIN = Coordinate(lat=52.52, lon=13.405)  # far away


async def _make_machine(session, repo: MachineRepository, mid: int, url: str) -> None:  # type: ignore[no-untyped-def]
    session.add(Machine(id=mid, source_url=url, name=f"M{mid}"))
    await session.flush()


async def test_recompute_geom_uses_precedence(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = MachineRepository(db_session)
    await _make_machine(db_session, repo, 1000, "u1000")

    await repo.add_candidate(1000, GpsSource.PARTIAL_NAME_GEOCODE, BERLIN)
    await repo.add_candidate(1000, GpsSource.FORUM_GPS, KOELN)
    await repo.recompute_geom(1000)

    hit = await repo.get_hit(1000)
    assert hit is not None
    assert hit.gps_source is GpsSource.FORUM_GPS
    assert hit.coordinate.lat == pytest.approx(KOELN.lat, abs=1e-6)


async def test_within_radius_and_nearest(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = MachineRepository(db_session)
    await _make_machine(db_session, repo, 1000, "u1000")
    await _make_machine(db_session, repo, 1001, "u1001")
    await repo.add_candidate(1000, GpsSource.FORUM_GPS, BONN)
    await repo.add_candidate(1001, GpsSource.FORUM_GPS, BERLIN)
    await repo.recompute_geom(1000)
    await repo.recompute_geom(1001)

    within = await repo.within_radius_km(KOELN, 50)
    assert {h.id for h in within} == {1000}  # Bonn in, Berlin out

    nearest = await repo.nearest_n(KOELN, 2)
    assert nearest[0].id == 1000  # Bonn is closer than Berlin


async def test_visited_roundtrip(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = MachineRepository(db_session)
    await _make_machine(db_session, repo, 1000, "u1000")
    users = UserRepository(db_session)

    assert await users.add_visited(42, 1000) is True
    assert await users.add_visited(42, 1000) is False  # idempotent
    assert 1000 in await users.visited_machine_ids(42)
    assert await users.delete_visited(42, 1000) is True


async def test_stale_lists_only_old_active_and_mark_gone(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = MachineRepository(db_session)
    old = datetime.now(UTC) - timedelta(days=90)
    db_session.add(Machine(id=2000, source_url="u2000", name="Old", last_seen_at=old))
    db_session.add(Machine(id=2001, source_url="u2001", name="Fresh"))  # last_seen defaults to now
    await db_session.flush()

    assert [m.id for m in await repo.stale(60)] == [2000]

    gone = await repo.mark_gone(2000)
    assert gone is not None
    assert gone.status is MachineStatus.GONE
    # A GONE machine drops off the stale list (stale only considers ACTIVE).
    assert await repo.stale(60) == []
    assert await repo.mark_gone(99999) is None


async def test_search_by_name_finds_offmap_and_flags_them(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = MachineRepository(db_session)
    db_session.add(Machine(id=3000, source_url="u3000", name="Hamburger Dom"))
    db_session.add(Machine(id=3001, source_url="u3001", name="Hamburger Hafen"))  # no coords
    db_session.add(Machine(id=3002, source_url="u3002", name="Bremen Markt"))
    await db_session.flush()
    # 3000 gets a coordinate and is on the map; 3001 stays coordinate-less.
    await repo.add_candidate(3000, GpsSource.FORUM_GPS, KOELN)
    await repo.recompute_geom(3000)
    await repo.mark_gone(3002)  # matches a different term, used below

    matches = await repo.search_by_name("hamburger")  # case-insensitive
    by_id = {m.id: m for m in matches}
    assert set(by_id) == {3000, 3001}
    assert by_id[3000].on_map is True
    assert by_id[3001].on_map is False  # surfaced precisely because it is missing
    assert by_id[3001].status is MachineStatus.ACTIVE

    # A removed machine is still found (so an admin can see it was removed).
    gone_matches = await repo.search_by_name("bremen")
    assert [(m.id, m.status, m.on_map) for m in gone_matches] == [(3002, MachineStatus.GONE, False)]

    # %/_ are treated literally, not as SQL wildcards.
    assert await repo.search_by_name("%") == []


async def test_search_by_name_respects_limit(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = MachineRepository(db_session)
    for i in range(5):
        db_session.add(Machine(id=4000 + i, source_url=f"u400{i}", name=f"Kiosk {i}"))
    await db_session.flush()
    assert len(await repo.search_by_name("kiosk", limit=3)) == 3


async def test_ungeocoded_excludes_geocoded_and_gone(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = MachineRepository(db_session)
    # Active, no coords -> should appear
    db_session.add(Machine(id=5000, source_url="u5000", name="No Coord"))
    db_session.add(Machine(id=5001, source_url="u5001", name="Also No Coord"))
    await db_session.flush()
    # Active, with coords -> must not appear
    await repo.add_candidate(5000, GpsSource.FORUM_GPS, KOELN)
    await repo.recompute_geom(5000)
    # Gone, no coords -> must not appear
    db_session.add(Machine(id=5002, source_url="u5002", name="Gone No Coord"))
    await db_session.flush()
    await repo.mark_gone(5002)

    results = await repo.ungeocoded(10)
    ids = {m.id for m in results}

    assert 5001 in ids  # active + no geom
    assert 5000 not in ids  # has geom
    assert 5002 not in ids  # gone


async def test_ungeocoded_respects_limit(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = MachineRepository(db_session)
    for i in range(5):
        db_session.add(Machine(id=6000 + i, source_url=f"u600{i}", name=f"U{i}"))
    await db_session.flush()

    results = await repo.ungeocoded(3)
    assert len(results) == 3
