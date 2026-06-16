"""Watch matching + Telegram dispatch for newly added machines.

After a scrape, find watches whose centre is within radius_km of a newly added
machine (ST_DWithin), send one message per (user, machine), and record it in
notifications_sent for idempotency.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pressmuenzen.bot import texts
from pressmuenzen.config import get_settings
from pressmuenzen.db.geo import distance_m, lat_expr, lon_expr
from pressmuenzen.db.models import Machine, NotificationSent, User, Watch
from pressmuenzen.domain.models import Coordinate
from pressmuenzen.logging import get_logger

log = get_logger("notifications")

KIND_NEW_MACHINE = "new_machine"


async def _machine_coord(
    session: AsyncSession, machine_id: int
) -> tuple[str, str, Coordinate] | None:
    row = (
        await session.execute(
            select(
                Machine.name, Machine.source_url, lat_expr(Machine.geom), lon_expr(Machine.geom)
            ).where(Machine.id == machine_id, Machine.geom.isnot(None))
        )
    ).first()
    if row is None or row[2] is None:
        return None
    return row[0], row[1], Coordinate(lat=row[2], lon=row[3])


async def _matches_for_machine(
    session: AsyncSession, coord: Coordinate
) -> list[tuple[int, int, float]]:
    """Return (user_id, chat_id, distance_km) for watches that cover ``coord``."""
    dist = distance_m(Watch.center_geom, coord)
    stmt = (
        select(User.id, User.telegram_chat_id, dist)
        .join(User, Watch.user_id == User.id)
        .where(
            Watch.active.is_(True),
            User.muted.is_(False),
            dist <= Watch.radius_km * 1000.0,
        )
    )
    rows = (await session.execute(stmt)).all()
    # One alert per user even if several of their watches match.
    best: dict[int, tuple[int, float]] = {}
    for uid, chat_id, d in rows:
        if uid not in best or d < best[uid][1]:
            best[uid] = (chat_id, d / 1000.0)
    return [(uid, chat_id, km) for uid, (chat_id, km) in best.items()]


async def _record_once(session: AsyncSession, user_id: int, machine_id: int) -> bool:
    """Insert a notifications_sent row; return False if it already existed."""
    stmt = (
        insert(NotificationSent)
        .values(user_id=user_id, machine_id=machine_id, kind=KIND_NEW_MACHINE)
        .on_conflict_do_nothing(constraint="uq_notification_idem")
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    return result.rowcount > 0


async def notify_new_machines(machine_ids: list[int]) -> int:
    """Dispatch notifications for the given new machines. Returns messages sent."""
    settings = get_settings()
    if not settings.telegram_token:
        log.warning("no telegram token; skipping notifications", count=len(machine_ids))
        return 0

    from telegram import Bot

    from pressmuenzen.db.engine import session_scope

    sent = 0
    bot = Bot(settings.telegram_token)
    async with bot:
        for machine_id in machine_ids:
            async with session_scope() as session:
                info = await _machine_coord(session, machine_id)
                if info is None:
                    continue
                name, url, coord = info
                matches = await _matches_for_machine(session, coord)
                for user_id, chat_id, distance_km in matches:
                    if not await _record_once(session, user_id, machine_id):
                        continue
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=texts.NOTIFY_NEW_MACHINE.format(
                                distance=round(distance_km, 1), name=name, url=url
                            ),
                        )
                        sent += 1
                    except Exception as exc:  # noqa: BLE001
                        log.warning("notify send failed", chat_id=chat_id, error=str(exc))
    log.info("notifications dispatched", sent=sent, machines=len(machine_ids))
    return sent
