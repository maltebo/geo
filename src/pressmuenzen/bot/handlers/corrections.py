"""Crowdsourced corrections: /melden conversation and map deep-link flow."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from pressmuenzen.bot import texts
from pressmuenzen.bot.handlers.common import (
    require_args,
    require_chat_id,
    require_message,
    require_user_data,
)
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.corrections import CorrectionRepository
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.db.repositories.users import UserRepository
from pressmuenzen.domain.models import Coordinate, CorrectionType
from pressmuenzen.services.notifications import notify_admins

REPORT_WAIT = 0


def parse_fix_payload(payload: str) -> tuple[int, float, float] | None:
    """Parse a map deep-link payload of the form fix_<id>_<lat6>_<lon6>.

    lat6/lon6 are lat/lon multiplied by 1e6 and rounded to integers. Negative
    values are encoded with an "n" prefix (e.g. n9876543 == -9.876543).
    Returns (machine_id, lat, lon) or None if the payload is malformed.
    """
    if not payload.startswith("fix_"):
        return None
    parts = payload[4:].split("_")
    if len(parts) != 3:
        return None
    machine_id_str, lat_str, lon_str = parts
    if not machine_id_str.isdigit():
        return None
    try:
        machine_id = int(machine_id_str)
        lat = _decode_coord(lat_str)
        lon = _decode_coord(lon_str)
    except (ValueError, IndexError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return machine_id, lat, lon


def _decode_coord(s: str) -> float:
    if s.startswith("n"):
        return -int(s[1:]) / 1_000_000
    return int(s) / 1_000_000


_KEYWORD_TO_TYPE = {
    "weg": CorrectionType.GONE,
    "umgezogen": CorrectionType.MOVED,
    "name": CorrectionType.NAME,
    "sonstiges": CorrectionType.OTHER,
}


async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = require_message(update)
    args = require_args(context)
    if len(args) != 1 or not args[0].isdigit():
        await message.reply_text(texts.REPORT_USAGE)
        return ConversationHandler.END
    machine_id = int(args[0])

    async with session_scope() as session:
        machine = await MachineRepository(session).get(machine_id)
    if machine is None:
        await message.reply_text(texts.DETAILS_NOT_FOUND.format(id=machine_id))
        return ConversationHandler.END

    require_user_data(context)["report_machine_id"] = machine_id
    await message.reply_text(texts.REPORT_START.format(name=machine.name))
    return REPORT_WAIT


async def report_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = require_message(update).location
    assert loc is not None, "location handler invoked without a location"
    await _store_correction(
        update,
        context,
        type_=CorrectionType.GPS,
        proposed=Coordinate(lat=loc.latitude, lon=loc.longitude),
        comment="Korrigierte Position per Pin",
    )
    return ConversationHandler.END


async def report_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = require_message(update).text or ""
    type_ = _KEYWORD_TO_TYPE.get(raw.strip().lower(), CorrectionType.OTHER)
    await _store_correction(update, context, type_=type_, proposed=None, comment=raw)
    return ConversationHandler.END


async def handle_deeplink_correction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store a GPS correction that arrived via a map deep-link (/start fix_...).

    The user picked a point on the Leaflet map and confirmed it; the coordinates
    are already baked into the start payload so no further conversation is needed.
    """
    message = require_message(update)
    args = require_args(context)
    parsed = parse_fix_payload(args[0]) if args else None
    if parsed is None:
        await message.reply_text(texts.REPORT_DEEPLINK_INVALID)
        return

    machine_id, lat, lon = parsed
    chat_id = require_chat_id(update)

    correction_id: int | None = None
    machine_name: str = str(machine_id)
    async with session_scope() as session:
        machine = await MachineRepository(session).get(machine_id)
        if machine is None:
            await message.reply_text(texts.DETAILS_NOT_FOUND.format(id=machine_id))
            return
        machine_name = machine.name
        user = await UserRepository(session).get_or_create(chat_id)
        correction = await CorrectionRepository(session).create(
            machine_id=machine_id,
            user_id=user.id,
            type_=CorrectionType.GPS,
            comment="Korrigierte Position per Karten-Klick",
            proposed=Coordinate(lat=lat, lon=lon),
        )
        correction_id = correction.id

    await message.reply_text(texts.REPORT_DEEPLINK_THANKS.format(name=machine_name))
    await notify_admins(
        texts.NOTIFY_ADMIN_NEW_CORRECTION.format(
            id=correction_id,
            type=CorrectionType.GPS.value,
            name=machine_name,
            comment="Korrigierte Position per Karten-Klick",
        )
    )


async def _store_correction(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    type_: CorrectionType,
    proposed: Coordinate | None,
    comment: str,
) -> None:
    message = require_message(update)
    user_data = require_user_data(context)
    machine_id = user_data.get("report_machine_id")
    if machine_id is None:
        await message.reply_text(texts.GENERIC_ERROR)
        return
    chat_id = require_chat_id(update)
    correction_id: int | None = None
    machine_name: str = str(machine_id)
    async with session_scope() as session:
        machine = await MachineRepository(session).get(machine_id)
        if machine is not None:
            machine_name = machine.name
        user = await UserRepository(session).get_or_create(chat_id)
        correction = await CorrectionRepository(session).create(
            machine_id=machine_id,
            user_id=user.id,
            type_=type_,
            comment=comment,
            proposed=proposed,
        )
        correction_id = correction.id
    user_data.pop("report_machine_id", None)
    await message.reply_text(texts.REPORT_THANKS)
    await notify_admins(
        texts.NOTIFY_ADMIN_NEW_CORRECTION.format(
            id=correction_id,
            type=type_.value,
            name=machine_name,
            comment=comment,
        )
    )
