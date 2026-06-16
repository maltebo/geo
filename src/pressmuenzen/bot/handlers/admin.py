"""Admin moderation commands: /queue, /ok, /nope.

Admin rights are derived from the configured ADMIN_CHAT_IDS list (config), never
from a DB column. Adding an admin = editing one env value and restarting.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from pressmuenzen.bot import texts
from pressmuenzen.config import get_settings
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.corrections import CorrectionRepository
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.services.corrections import CorrectionService


def _is_admin(update: Update) -> bool:
    return get_settings().is_admin(update.effective_chat.id)


async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text(texts.ADMIN_ONLY)
        return
    async with session_scope() as session:
        pending = await CorrectionRepository(session).pending()
        machine_repo = MachineRepository(session)
        if not pending:
            await update.message.reply_text(texts.QUEUE_EMPTY)
            return
        lines = [texts.QUEUE_HEADER]
        for c in pending:
            machine = await machine_repo.get(c.machine_id)
            name = machine.name if machine else f"#{c.machine_id}"
            lines.append(f"#{c.id} [{c.type}] {name}: {c.comment or ''}")
        lines.append("\nAnnehmen: /ok <id>   Ablehnen: /nope <id>")
    await update.message.reply_text("\n".join(lines))


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text(texts.ADMIN_ONLY)
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text(texts.OK_USAGE)
        return
    correction_id = int(context.args[0])
    async with session_scope() as session:
        ok = await CorrectionService(session).approve(correction_id, update.effective_chat.id)
    await update.message.reply_text(
        texts.CORRECTION_APPROVED.format(id=correction_id)
        if ok
        else texts.CORRECTION_NOT_FOUND.format(id=correction_id)
    )


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text(texts.ADMIN_ONLY)
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text(texts.NOPE_USAGE)
        return
    correction_id = int(context.args[0])
    async with session_scope() as session:
        ok = await CorrectionService(session).reject(correction_id, update.effective_chat.id)
    await update.message.reply_text(
        texts.CORRECTION_REJECTED.format(id=correction_id)
        if ok
        else texts.CORRECTION_NOT_FOUND.format(id=correction_id)
    )
