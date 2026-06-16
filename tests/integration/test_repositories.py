"""Integration tests: spatial search + precedence recompute against PostGIS."""

from __future__ import annotations

import pytest

from pressmuenzen.db.models import Machine
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.db.repositories.users import UserRepository
from pressmuenzen.domain.models import Coordinate, GpsSource

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
