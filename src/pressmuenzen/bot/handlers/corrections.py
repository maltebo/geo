"""Crowdsourced corrections: /melden conversation."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from pressmuenzen.bot import texts
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
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text(texts.REPORT_USAGE)
        return ConversationHandler.END
    machine_id = int(context.args[0])

    async with session_scope() as session:
        machine = await MachineRepository(session).get(machine_id)
    if machine is None:
        await update.message.reply_text(texts.DETAILS_NOT_FOUND.format(id=machine_id))
        return ConversationHandler.END

    context.user_data["report_machine_id"] = machine_id
    await update.message.reply_text(texts.REPORT_START.format(name=machine.name))
    return REPORT_WAIT


async def report_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    await _store_correction(
        update,
        context,
        type_=CorrectionType.GPS,
        proposed=Coordinate(lat=loc.latitude, lon=loc.longitude),
        comment="Korrigierte Position per Pin",
    )
    return ConversationHandler.END


async def report_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    type_ = _KEYWORD_TO_TYPE.get(text, CorrectionType.OTHER)
    await _store_correction(
        update, context, type_=type_, proposed=None, comment=update.message.text
    )
    return ConversationHandler.END


async def _store_correction(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    type_: CorrectionType,
    proposed: Coordinate | None,
    comment: str,
) -> None:
    machine_id = context.user_data.get("report_machine_id")
    if machine_id is None:
        await update.message.reply_text(texts.GENERIC_ERROR)
        return
    chat_id = update.effective_chat.id
    async with session_scope() as session:
        user = await UserRepository(session).get_or_create(chat_id)
        await CorrectionRepository(session).create(
            machine_id=machine_id,
            user_id=user.id,
            type_=type_,
            comment=comment,
            proposed=proposed,
        )
    context.user_data.pop("report_machine_id", None)
    await update.message.reply_text(texts.REPORT_THANKS)
