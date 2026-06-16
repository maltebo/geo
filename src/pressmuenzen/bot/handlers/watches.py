"""Notifications & watches: /heimat, /beobachten, /beobachtungen, /stumm."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from pressmuenzen.bot import texts
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.users import UserRepository
from pressmuenzen.domain.models import Coordinate
from pressmuenzen.scraper.geocoding import Geocoder

DEFAULT_WATCH_RADIUS_KM = 25.0

HOME_WAIT = 0


async def home_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(texts.HOME_ASK)
    return HOME_WAIT


async def home_set_from_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    await _set_home(update, Coordinate(lat=loc.latitude, lon=loc.longitude))
    return ConversationHandler.END


async def home_set_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    async with session_scope() as session:
        coord = await Geocoder(session).geocode(update.message.text)
    if coord is None:
        await update.message.reply_text(texts.ADDRESS_NOT_FOUND.format(query=update.message.text))
        return ConversationHandler.END
    await _set_home(update, coord)
    return ConversationHandler.END


async def _set_home(update: Update, coord: Coordinate) -> None:
    chat_id = update.effective_chat.id
    async with session_scope() as session:
        repo = UserRepository(session)
        await repo.set_home(chat_id, coord)
        # A home location auto-creates a default watch (idempotent enough for hobby use).
        existing = await repo.list_watches(chat_id)
        if not existing:
            await repo.add_watch(chat_id, coord, DEFAULT_WATCH_RADIUS_KM)
    await update.message.reply_text(texts.HOME_SET.format(radius=DEFAULT_WATCH_RADIUS_KM))


async def add_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text(texts.WATCH_USAGE)
        return
    try:
        radius = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text(texts.WATCH_USAGE)
        return

    chat_id = update.effective_chat.id
    async with session_scope() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(chat_id)
        if user.home_geom is None:
            await update.message.reply_text(texts.WATCH_NEED_HOME)
            return
        # Read the home coordinate back to re-use as the watch centre.
        home = await _home_coord(session, chat_id)
        if home is None:
            await update.message.reply_text(texts.WATCH_NEED_HOME)
            return
        await repo.add_watch(chat_id, home, radius)
    await update.message.reply_text(texts.WATCH_ADDED.format(radius=radius))


async def list_watches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with session_scope() as session:
        watches = await UserRepository(session).list_watches(chat_id)
    if not watches:
        await update.message.reply_text(texts.WATCH_NONE)
        return
    lines = [texts.WATCH_LIST_HEADER]
    lines.extend(f"#{w.id}: Umkreis {w.radius_km} km" for w in watches)
    lines.append("\nEntfernen mit /beobachtung_loeschen <id>")
    await update.message.reply_text("\n".join(lines))


async def remove_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Bitte: /beobachtung_loeschen <id>")
        return
    watch_id = int(context.args[0])
    async with session_scope() as session:
        ok = await UserRepository(session).deactivate_watch(update.effective_chat.id, watch_id)
    if ok:
        await update.message.reply_text(texts.WATCH_REMOVED.format(id=watch_id))
    else:
        await update.message.reply_text(texts.WATCH_NONE)


async def toggle_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with session_scope() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(chat_id)
        new_state = not user.muted
        await repo.set_muted(chat_id, new_state)
    await update.message.reply_text(texts.MUTED if new_state else texts.UNMUTED)


async def _home_coord(session, chat_id: int) -> Coordinate | None:  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from pressmuenzen.db.geo import lat_expr, lon_expr
    from pressmuenzen.db.models import User

    row = (
        await session.execute(
            select(lat_expr(User.home_geom), lon_expr(User.home_geom)).where(
                User.telegram_chat_id == chat_id
            )
        )
    ).first()
    if row is None or row[0] is None:
        return None
    return Coordinate(lat=row[0], lon=row[1])
