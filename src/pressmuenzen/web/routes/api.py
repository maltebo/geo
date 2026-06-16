"""GeoJSON markers API. Read-only, public, filterable."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import GpsSource
from pressmuenzen.services.maps import machines_to_geojson

router = APIRouter(prefix="/api")

# min_quality: drop candidates worse than the named source (by precedence).
_QUALITY_FLOOR: dict[str, int] = {
    "any": GpsSource.NONE.precedence,
    "name": GpsSource.PARTIAL_NAME_GEOCODE.precedence,
    "full_name": GpsSource.FULL_NAME_GEOCODE.precedence,
    "forum": GpsSource.FORUM_GPS.precedence,
    "corrected": GpsSource.CORRECTED.precedence,
}


@router.get("/machines")
async def machines(
    limited_only: bool = Query(default=False),
    category: str | None = Query(default=None),
    min_quality: str = Query(default="any"),
) -> dict[str, Any]:
    floor = _QUALITY_FLOOR.get(min_quality, GpsSource.NONE.precedence)
    async with session_scope() as session:
        hits = await MachineRepository(session).all_with_coords()

    filtered = [
        h
        for h in hits
        if h.gps_source.precedence <= floor
        and (not limited_only or h.is_limited)
        and (category is None or h.category == category)
    ]
    return machines_to_geojson(filtered)
