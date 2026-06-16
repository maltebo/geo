"""Admin moderation panel (corrections queue).

Authorisation is handled at the edge by Caddy HTTP basic auth on the admin
domain (see Caddyfile). This keeps the app simple for hobby ops; a Telegram-login
check is the documented upgrade path.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.corrections import CorrectionRepository
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.services.corrections import CorrectionService
from pressmuenzen.web.app import templates

router = APIRouter(prefix="/admin")

# reviewed_by 0 marks a web-panel action (vs a Telegram chat id).
_WEB_REVIEWER = 0


@router.get("", response_class=HTMLResponse)
async def queue(request: Request) -> HTMLResponse:
    async with session_scope() as session:
        pending = await CorrectionRepository(session).pending()
        machine_repo = MachineRepository(session)
        rows = []
        for c in pending:
            machine = await machine_repo.get(c.machine_id)
            rows.append(
                {
                    "id": c.id,
                    "machine_id": c.machine_id,
                    "machine_name": machine.name if machine else f"#{c.machine_id}",
                    "type": str(c.type),
                    "comment": c.comment or "",
                    "created_at": c.created_at.isoformat(),
                }
            )
    return templates.TemplateResponse(
        request, "admin.html", {"title": "Moderation", "corrections": rows}
    )


@router.post("/corrections/{correction_id}/approve")
async def approve(correction_id: int) -> RedirectResponse:
    async with session_scope() as session:
        await CorrectionService(session).approve(correction_id, _WEB_REVIEWER)
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/corrections/{correction_id}/reject")
async def reject(correction_id: int) -> RedirectResponse:
    async with session_scope() as session:
        await CorrectionService(session).reject(correction_id, _WEB_REVIEWER)
    return RedirectResponse(url="/admin", status_code=303)
