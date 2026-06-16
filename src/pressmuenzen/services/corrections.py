"""Corrections moderation state machine.

Approving a GPS correction inserts a top-precedence CORRECTED coordinate
candidate and recomputes the machine's geom; precedence does the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pressmuenzen.db.geo import lat_expr, lon_expr
from pressmuenzen.db.models import Correction
from pressmuenzen.db.repositories.corrections import CorrectionRepository
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import (
    Coordinate,
    CorrectionStatus,
    CorrectionType,
    GpsSource,
    MachineStatus,
)
from pressmuenzen.logging import get_logger

log = get_logger("corrections")


@dataclass
class ApprovalResult:
    """Outcome of approving a correction.

    ``deleted_machine_*`` are populated only when the approval removed a location
    (an accepted GONE report), so the caller can alert the admins after commit.
    """

    applied: bool
    deleted_machine_id: int | None = None
    deleted_machine_name: str | None = None


class CorrectionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.corrections = CorrectionRepository(session)
        self.machines = MachineRepository(session)

    async def approve(self, correction_id: int, reviewer_chat_id: int) -> ApprovalResult:
        correction = await self.corrections.get(correction_id)
        if correction is None or correction.status is not CorrectionStatus.PENDING:
            return ApprovalResult(applied=False)

        deleted_id: int | None = None
        deleted_name: str | None = None

        if correction.type is CorrectionType.GPS and correction.proposed_geom is not None:
            coord = await self._proposed_coord(correction_id)
            if coord is not None:
                # A correction supersedes any prior correction.
                await self.machines.clear_candidates_of_source(
                    correction.machine_id, GpsSource.CORRECTED
                )
                await self.machines.add_candidate(
                    correction.machine_id,
                    GpsSource.CORRECTED,
                    coord,
                    raw_text="user correction",
                )
                await self.machines.recompute_geom(correction.machine_id)
        elif correction.type is CorrectionType.GONE:
            machine = await self.machines.get(correction.machine_id)
            if machine is not None:
                machine.status = MachineStatus.GONE
                await self.session.flush()
                deleted_id = machine.id
                deleted_name = machine.name

        await self.corrections.set_status(
            correction_id, CorrectionStatus.APPROVED, reviewer_chat_id
        )
        log.info("correction approved", correction_id=correction_id, type=correction.type)
        return ApprovalResult(
            applied=True,
            deleted_machine_id=deleted_id,
            deleted_machine_name=deleted_name,
        )

    async def reject(self, correction_id: int, reviewer_chat_id: int) -> bool:
        correction = await self.corrections.get(correction_id)
        if correction is None or correction.status is not CorrectionStatus.PENDING:
            return False
        await self.corrections.set_status(
            correction_id, CorrectionStatus.REJECTED, reviewer_chat_id
        )
        return True

    async def _proposed_coord(self, correction_id: int) -> Coordinate | None:
        row = (
            await self.session.execute(
                select(
                    lat_expr(Correction.proposed_geom), lon_expr(Correction.proposed_geom)
                ).where(Correction.id == correction_id)
            )
        ).first()
        if row is None or row[0] is None:
            return None
        return Coordinate(lat=row[0], lon=row[1])
