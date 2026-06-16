"""Health endpoint for uptime checks and the deploy health gate."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from pressmuenzen.db.engine import session_scope

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception:  # noqa: BLE001
        return {"status": "degraded", "db": "error"}
