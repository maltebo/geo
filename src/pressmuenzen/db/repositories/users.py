"""User, visited and watch persistence."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pressmuenzen.db.geo import point_wkt
from pressmuenzen.db.models import User, Visited, Watch
from pressmuenzen.domain.models import Coordinate


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self,
        telegram_chat_id: int,
        telegram_user_id: int | None = None,
        display_name: str | None = None,
    ) -> User:
        user = (
            await self.session.execute(
                select(User).where(User.telegram_chat_id == telegram_chat_id)
            )
        ).scalar_one_or_none()
        if user is None:
            user = User(
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                display_name=display_name,
            )
            self.session.add(user)
            await self.session.flush()
        else:
            user.last_seen_at = func.now()
        return user

    async def set_home(self, telegram_chat_id: int, coord: Coordinate) -> User:
        user = await self.get_or_create(telegram_chat_id)
        user.home_geom = point_wkt(coord)
        await self.session.flush()
        return user

    async def set_muted(self, telegram_chat_id: int, muted: bool) -> None:
        user = await self.get_or_create(telegram_chat_id)
        user.muted = muted
        await self.session.flush()

    # --- visited -------------------------------------------------------------

    async def add_visited(self, telegram_chat_id: int, machine_id: int) -> bool:
        """Return True if newly added, False if it was already marked visited."""
        user = await self.get_or_create(telegram_chat_id)
        stmt = (
            insert(Visited)
            .values(user_id=user.id, machine_id=machine_id)
            .on_conflict_do_nothing(index_elements=["user_id", "machine_id"])
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        return result.rowcount > 0

    async def delete_visited(self, telegram_chat_id: int, machine_id: int) -> bool:
        """Return True if a row was removed, False if it was not marked visited."""
        user = await self.get_or_create(telegram_chat_id)
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                delete(Visited).where(Visited.user_id == user.id, Visited.machine_id == machine_id)
            ),
        )
        return result.rowcount > 0

    async def visited_machine_ids(self, telegram_chat_id: int) -> set[int]:
        user = await self.get_or_create(telegram_chat_id)
        rows = await self.session.execute(
            select(Visited.machine_id).where(Visited.user_id == user.id)
        )
        return set(rows.scalars().all())

    # --- watches -------------------------------------------------------------

    async def add_watch(self, telegram_chat_id: int, coord: Coordinate, radius_km: float) -> Watch:
        user = await self.get_or_create(telegram_chat_id)
        watch = Watch(user_id=user.id, center_geom=point_wkt(coord), radius_km=radius_km)
        self.session.add(watch)
        await self.session.flush()
        return watch

    async def list_watches(self, telegram_chat_id: int) -> list[Watch]:
        user = await self.get_or_create(telegram_chat_id)
        rows = await self.session.execute(
            select(Watch).where(Watch.user_id == user.id, Watch.active.is_(True))
        )
        return list(rows.scalars().all())

    async def deactivate_watch(self, telegram_chat_id: int, watch_id: int) -> bool:
        user = await self.get_or_create(telegram_chat_id)
        watch = await self.session.get(Watch, watch_id)
        if watch is None or watch.user_id != user.id:
            return False
        watch.active = False
        await self.session.flush()
        return True
