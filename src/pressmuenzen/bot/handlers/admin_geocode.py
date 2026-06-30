"""Admin-only conversation for manually geocoding machines with no coordinates.

/geocodieren shows a random sample of ungeocoded active machines; the admin
picks one by ID, types an address, sees the geocoded result, and confirms.
The coordinate is applied directly as GpsSource.CORRECTED (no correction queue).
"""

from __future__ import annotations

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from pressmuenzen.bot import texts
from pressmuenzen.bot.handlers.admin import _is_admin
from pressmuenzen.bot.handlers.common import require_message, require_user_data
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import Coordinate, GpsSource
from pressmuenzen.scraper.geocoding import Geocoder

GEOCODE_PICK = 0
GEOCODE_ADDRESS = 1
GEOCODE_CONFIRM = 2

_SAMPLE_SIZE = 10
_CONFIRM_KEYBOARD = ReplyKeyboardMarkup(
    [["ja", "nein"]], one_time_keyboard=True, resize_keyboard=True
)


async def geocode_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = require_message(update)
    if not _is_admin(update):
        await message.reply_text(texts.ADMIN_ONLY)
        return ConversationHandler.END

    async with session_scope() as session:
        machines = await MachineRepository(session).ungeocoded(_SAMPLE_SIZE)

    if not machines:
        await message.reply_text(texts.GEOCODE_NONE)
        return ConversationHandler.END

    lines = [texts.GEOCODE_LIST_HEADER]
    for m in machines:
        lines.append(texts.GEOCODE_LIST_ITEM.format(id=m.id, name=m.name, url=m.source_url))
    lines.append(texts.GEOCODE_LIST_FOOTER)
    await message.reply_text("\n".join(lines))
    return GEOCODE_PICK


async def geocode_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = require_message(update)
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.reply_text(texts.GEOCODE_INVALID_ID)
        return GEOCODE_PICK

    machine_id = int(raw)
    async with session_scope() as session:
        machine = await MachineRepository(session).get(machine_id)

    if machine is None or machine.geom is not None:
        await message.reply_text(texts.GEOCODE_INVALID_ID)
        return GEOCODE_PICK

    require_user_data(context)["geocode_machine_id"] = machine_id
    description = (machine.description or "").strip() or "(keine Beschreibung)"
    await message.reply_text(
        texts.GEOCODE_DETAILS.format(
            name=machine.name,
            url=machine.source_url,
            description=description,
        )
    )
    return GEOCODE_ADDRESS


async def geocode_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = require_message(update)
    query = (message.text or "").strip()
    if not query:
        return GEOCODE_ADDRESS

    await message.reply_text(texts.GEOCODE_TRYING)
    async with session_scope() as session:
        coord = await Geocoder(session).geocode(query)

    if coord is None:
        await message.reply_text(texts.GEOCODE_NOT_FOUND)
        return GEOCODE_ADDRESS

    require_user_data(context)["geocode_coord"] = (coord.lat, coord.lon)
    await message.reply_text(
        texts.GEOCODE_RESULT.format(maps_link=coord.maps_link),
        reply_markup=_CONFIRM_KEYBOARD,
    )
    return GEOCODE_CONFIRM


async def geocode_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = require_message(update)
    answer = (message.text or "").strip().lower()
    user_data = require_user_data(context)

    if answer != "ja":
        user_data.pop("geocode_machine_id", None)
        user_data.pop("geocode_coord", None)
        await message.reply_text(texts.GEOCODE_ABORTED, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    machine_id: int | None = user_data.pop("geocode_machine_id", None)
    raw_coord: tuple[float, float] | None = user_data.pop("geocode_coord", None)
    if machine_id is None or raw_coord is None:
        await message.reply_text(texts.GENERIC_ERROR, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    coord = Coordinate(lat=raw_coord[0], lon=raw_coord[1])
    machine_name: str = str(machine_id)
    async with session_scope() as session:
        repo = MachineRepository(session)
        machine = await repo.get(machine_id)
        if machine is not None:
            machine_name = machine.name
        await repo.clear_candidates_of_source(machine_id, GpsSource.CORRECTED)
        await repo.add_candidate(machine_id, GpsSource.CORRECTED, coord)
        await repo.recompute_geom(machine_id)

    await message.reply_text(
        texts.GEOCODE_APPLIED.format(name=machine_name),
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END
