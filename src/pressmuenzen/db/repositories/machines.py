"""Machine + coordinate-candidate persistence and spatial queries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pressmuenzen.db.geo import distance_m, geography, lat_expr, lon_expr, point_wkt
from pressmuenzen.db.models import CoordinateCandidate, Machine, Region
from pressmuenzen.domain.models import (
    CandidateInput,
    Coordinate,
    GpsSource,
    MachineHit,
    MachineStatus,
    MachineTextMatch,
)
from pressmuenzen.domain.precedence import resolve


def _row_to_hit(row: Sequence[Any], distance_m_value: float | None = None) -> MachineHit:
    m, region_name, lat, lon = row
    return MachineHit(
        id=m.id,
        name=m.name,
        url=m.source_url,
        description=m.description,
        category=region_name or "",
        entry_date_text=m.entry_date_text,
        is_limited=m.is_limited,
        gps_source=m.gps_source,
        coordinate=Coordinate(lat=lat, lon=lon),
        distance_km=(distance_m_value / 1000.0) if distance_m_value is not None else None,
    )


class MachineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- reads ---------------------------------------------------------------

    async def get(self, machine_id: int) -> Machine | None:
        return await self.session.get(Machine, machine_id)

    async def get_by_url(self, source_url: str) -> Machine | None:
        # source_url is not unique (one legacy machine is listed under two
        # regions). Pick the lowest id deterministically so the scraper always
        # updates the same canonical row instead of choking on duplicates.
        return (
            (
                await self.session.execute(
                    select(Machine)
                    .where(Machine.source_url == source_url)
                    .order_by(Machine.id)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def next_id(self) -> int:
        """Allocate the next machine id, continuing the legacy loc_ID sequence."""
        max_id = (await self.session.execute(select(func.max(Machine.id)))).scalar()
        return (max_id or 999) + 1

    async def get_hit(self, machine_id: int) -> MachineHit | None:
        stmt = (
            select(Machine, Region.name, lat_expr(Machine.geom), lon_expr(Machine.geom))
            .outerjoin(Region, Machine.region_id == Region.id)
            .where(Machine.id == machine_id, Machine.geom.isnot(None))
        )
        row = (await self.session.execute(stmt)).first()
        return _row_to_hit(row) if row else None

    async def all_with_coords(self) -> list[MachineHit]:
        stmt = (
            select(Machine, Region.name, lat_expr(Machine.geom), lon_expr(Machine.geom))
            .outerjoin(Region, Machine.region_id == Region.id)
            .where(Machine.geom.isnot(None), Machine.status != MachineStatus.GONE)
        )
        rows = (await self.session.execute(stmt)).all()
        return [_row_to_hit(r) for r in rows]

    async def search_by_name(self, query: str, limit: int = 25) -> list[MachineTextMatch]:
        """Case-insensitive substring search over machine names (titles).

        Deliberately does NOT apply the map filters (geom present, not GONE): the
        point of this search is to find machines that are missing from the map, so
        coordinate-less and removed rows are exactly what must show up. ``%``/``_``
        in the user's term are treated literally, not as SQL wildcards.
        """
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        stmt = (
            select(Machine.id, Machine.name, Machine.status, Machine.geom.isnot(None))
            .where(Machine.name.ilike(like, escape="\\"))
            .order_by(Machine.name)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            MachineTextMatch(
                id=mid,
                name=name,
                status=status,
                on_map=has_geom and status != MachineStatus.GONE,
            )
            for mid, name, status, has_geom in rows
        ]

    async def nearest_n(self, origin: Coordinate, n: int) -> list[MachineHit]:
        """N nearest machines, ordered by distance, using the KNN (<->) operator."""
        dist = distance_m(Machine.geom, origin)
        stmt = (
            select(Machine, Region.name, lat_expr(Machine.geom), lon_expr(Machine.geom), dist)
            .outerjoin(Region, Machine.region_id == Region.id)
            .where(Machine.geom.isnot(None), Machine.status != MachineStatus.GONE)
            .order_by(Machine.geom.op("<->")(point_wkt(origin)))
            .limit(n)
        )
        rows = (await self.session.execute(stmt)).all()
        return [_row_to_hit(r[:4], r[4]) for r in rows]

    async def within_radius_km(self, origin: Coordinate, radius_km: float) -> list[MachineHit]:
        """All machines within ``radius_km``, ordered by distance (ST_DWithin)."""
        dist = distance_m(Machine.geom, origin)
        stmt = (
            select(Machine, Region.name, lat_expr(Machine.geom), lon_expr(Machine.geom), dist)
            .outerjoin(Region, Machine.region_id == Region.id)
            .where(
                Machine.geom.isnot(None),
                Machine.status != MachineStatus.GONE,
                func.ST_DWithin(
                    func.cast(Machine.geom, geography()),
                    func.cast(point_wkt(origin), geography()),
                    radius_km * 1000.0,
                ),
            )
            .order_by(dist)
        )
        rows = (await self.session.execute(stmt)).all()
        return [_row_to_hit(r[:4], r[4]) for r in rows]

    async def stale(self, threshold_days: int) -> list[Machine]:
        """Active machines the scraper has not re-seen for ``threshold_days`` days.

        Oldest first. A read-time view for admin review; it changes no state. A
        machine re-seen by a later scrape refreshes ``last_seen_at`` and drops off
        this list on its own, so there is nothing to undo.
        """
        cutoff = datetime.now(UTC) - timedelta(days=threshold_days)
        rows = await self.session.execute(
            select(Machine)
            .where(Machine.status == MachineStatus.ACTIVE, Machine.last_seen_at < cutoff)
            .order_by(Machine.last_seen_at)
        )
        return list(rows.scalars().all())

    # --- writes --------------------------------------------------------------

    async def mark_gone(self, machine_id: int) -> Machine | None:
        """Soft-delete a machine (status -> GONE). Returns it, or None if absent.

        Soft, never a row delete: keeps the legacy loc_ID stable and preserves
        users' visited history and corrections (all FK-CASCADE off machines.id).
        """
        machine = await self.session.get(Machine, machine_id)
        if machine is None:
            return None
        machine.status = MachineStatus.GONE
        await self.session.flush()
        return machine

    async def upsert_region(
        self, source_forum_url: str, name: str, is_limited_section: bool
    ) -> Region:
        region = (
            await self.session.execute(
                select(Region).where(Region.source_forum_url == source_forum_url)
            )
        ).scalar_one_or_none()
        if region is None:
            region = Region(
                source_forum_url=source_forum_url,
                name=name,
                is_limited_section=is_limited_section,
            )
            self.session.add(region)
            await self.session.flush()
        return region

    async def add_candidate(
        self, machine_id: int, source: GpsSource, coord: Coordinate, raw_text: str | None = None
    ) -> None:
        self.session.add(
            CoordinateCandidate(
                machine_id=machine_id,
                source=source,
                geom=point_wkt(coord),
                raw_text=raw_text,
            )
        )
        await self.session.flush()

    async def list_candidates(self, machine_id: int) -> list[CandidateInput]:
        stmt = select(
            CoordinateCandidate.source,
            lat_expr(CoordinateCandidate.geom),
            lon_expr(CoordinateCandidate.geom),
        ).where(CoordinateCandidate.machine_id == machine_id)
        rows = (await self.session.execute(stmt)).all()
        return [
            CandidateInput(source=source, coordinate=Coordinate(lat=lat, lon=lon))
            for source, lat, lon in rows
        ]

    async def recompute_geom(self, machine_id: int) -> None:
        """Recompute and persist the chosen geom/gps_source from all candidates.

        This is the only writer of ``machines.geom``/``machines.gps_source``.
        """
        candidates = await self.list_candidates(machine_id)
        coord, source = resolve(candidates)
        machine = await self.session.get(Machine, machine_id)
        if machine is None:
            return
        machine.gps_source = source
        machine.geom = point_wkt(coord) if coord is not None else None
        await self.session.flush()

    async def clear_candidates_of_source(self, machine_id: int, source: GpsSource) -> None:
        await self.session.execute(
            delete(CoordinateCandidate).where(
                CoordinateCandidate.machine_id == machine_id,
                CoordinateCandidate.source == source,
            )
        )
