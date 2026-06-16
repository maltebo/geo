"""Search service: radius and nearest-N queries over PostGIS.

Thin orchestration over MachineRepository. The spatial work happens in SQL
(ST_DWithin / KNN <->); this layer exists so the bot and web share one code path
and so the legacy module-level-cached-database bug cannot reappear (every call
runs a fresh query in a fresh session).
"""

from __future__ import annotations

from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import Coordinate, MachineHit


class SearchService:
    def __init__(self, repo: MachineRepository) -> None:
        self.repo = repo

    async def nearest(self, origin: Coordinate, n: int) -> list[MachineHit]:
        n = max(1, min(n, 200))
        return await self.repo.nearest_n(origin, n)

    async def within_radius(self, origin: Coordinate, radius_km: float) -> list[MachineHit]:
        radius_km = max(0.1, min(radius_km, 2000.0))
        return await self.repo.within_radius_km(origin, radius_km)

    async def all_machines(self) -> list[MachineHit]:
        return await self.repo.all_with_coords()
