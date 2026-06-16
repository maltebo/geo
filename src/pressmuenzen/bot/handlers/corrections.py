"""Crowdsourced corrections: /melden conversation."""

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

REPORT_WAIT = 0

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
    async with session_scope() as session:
        user = await UserRepository(session).get_or_create(chat_id)
        await CorrectionRepository(session).create(
            machine_id=machine_id,
            user_id=user.id,
            type_=type_,
            comment=comment,
            proposed=proposed,
        )
    user_data.pop("report_machine_id", None)
    await message.reply_text(texts.REPORT_THANKS)
