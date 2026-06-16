"""Corrections (moderation queue) and scrape-run persistence."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pressmuenzen.db.geo import point_wkt
from pressmuenzen.db.models import Correction, ScrapeRun
from pressmuenzen.domain.models import (
    Coordinate,
    CorrectionStatus,
    CorrectionType,
)


class CorrectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        machine_id: int,
        user_id: int | None,
        type_: CorrectionType,
        comment: str | None = None,
        proposed: Coordinate | None = None,
    ) -> Correction:
        correction = Correction(
            machine_id=machine_id,
            user_id=user_id,
            type=type_,
            comment=comment,
            proposed_geom=point_wkt(proposed) if proposed is not None else None,
        )
        self.session.add(correction)
        await self.session.flush()
        return correction

    async def get(self, correction_id: int) -> Correction | None:
        return await self.session.get(Correction, correction_id)

    async def pending(self) -> list[Correction]:
        rows = await self.session.execute(
            select(Correction)
            .where(Correction.status == CorrectionStatus.PENDING)
            .order_by(Correction.created_at)
        )
        return list(rows.scalars().all())

    async def set_status(
        self, correction_id: int, status: CorrectionStatus, reviewer_chat_id: int
    ) -> Correction | None:
        correction = await self.session.get(Correction, correction_id)
        if correction is None:
            return None
        correction.status = status
        correction.reviewed_at = func.now()
        correction.reviewed_by = reviewer_chat_id
        await self.session.flush()
        return correction


class ScrapeRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(self, mode: str) -> ScrapeRun:
        run = ScrapeRun(mode=mode, status="running")
        self.session.add(run)
        await self.session.flush()
        return run

    async def trailing_parse_rate(self, limit: int = 5) -> float | None:
        """Average parse-success-rate over the last successful runs (for the canary)."""
        rows = await self.session.execute(
            select(ScrapeRun.parse_success_rate)
            .where(ScrapeRun.parse_success_rate.isnot(None), ScrapeRun.status == "ok")
            .order_by(ScrapeRun.started_at.desc())
            .limit(limit)
        )
        rates = [r for r in rows.scalars().all() if r is not None]
        return sum(rates) / len(rates) if rates else None
