"""Nominatim geocoding client: async, rate-limited, and DB-cached.

Respects the Nominatim usage policy: max 1 request/second, a real identifying
User-Agent (with contact) from settings, and a persistent cache so we never
re-hit the API for a query we have already resolved. Used by the scraper (name
geocoding) and by the bot (resolving a user-typed address).
"""

from __future__ import annotations

import httpx
from aiolimiter import AsyncLimiter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from pressmuenzen.config import get_settings
from pressmuenzen.db.geo import lat_expr, lon_expr, point_wkt
from pressmuenzen.db.models import GeocodeCache
from pressmuenzen.domain.models import Coordinate
from pressmuenzen.logging import get_logger

log = get_logger("geocoding")

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Process-wide 1 req/s limiter, shared across all callers in this process.
_limiter = AsyncLimiter(max_rate=1, time_period=1.0)


class Geocoder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._ua = get_settings().nominatim_user_agent

    async def geocode(self, query: str) -> Coordinate | None:
        query = query.strip()
        if not query:
            return None

        cached = await self._from_cache(query)
        if cached is not None:
            return cached.coordinate

        coord = await self._fetch(query)
        await self._store(query, coord)
        return coord

    async def reverse_to_coordinate(self, lat: float, lon: float) -> Coordinate:
        """A location pin is already a coordinate; no API call needed."""
        return Coordinate(lat=lat, lon=lon)

    # --- internals -----------------------------------------------------------

    async def _from_cache(self, query: str) -> _CacheHit | None:
        row = (
            await self.session.execute(
                select(
                    GeocodeCache.id,
                    lat_expr(GeocodeCache.geom),
                    lon_expr(GeocodeCache.geom),
                ).where(GeocodeCache.query == query)
            )
        ).first()
        if row is None:
            return None
        _id, lat, lon = row
        coord = Coordinate(lat=lat, lon=lon) if lat is not None else None
        return _CacheHit(coordinate=coord)

    async def _store(self, query: str, coord: Coordinate | None) -> None:
        entry = GeocodeCache(
            query=query,
            geom=point_wkt(coord) if coord is not None else None,
            provider="nominatim",
        )
        self.session.add(entry)
        await self.session.flush()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def _fetch(self, query: str) -> Coordinate | None:
        async with (
            _limiter,
            httpx.AsyncClient(timeout=10.0, headers={"User-Agent": self._ua}) as client,
        ):
            resp = await client.get(
                _NOMINATIM_URL,
                params={"q": query, "format": "jsonv2", "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()
        if not data:
            log.info("geocode miss", query=query)
            return None
        return Coordinate(lat=float(data[0]["lat"]), lon=float(data[0]["lon"]))


class _CacheHit:
    __slots__ = ("coordinate",)

    def __init__(self, coordinate: Coordinate | None) -> None:
        self.coordinate = coordinate
