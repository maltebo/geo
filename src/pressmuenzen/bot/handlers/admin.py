"""Admin moderation commands: /queue, /ok, /nope, /stale, /entfernen.

Admin rights are derived from the configured ADMIN_CHAT_IDS list (config), never
from a DB column. Adding an admin = editing one env value and restarting.
"""

from __future__ import annotations

from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

from pressmuenzen.bot import texts
from pressmuenzen.bot.handlers.common import require_args, require_chat_id, require_message
from pressmuenzen.config import get_settings
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.corrections import CorrectionRepository
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import MachineStatus
from pressmuenzen.services.corrections import CorrectionService
from pressmuenzen.services.notifications import notify_admins


def _is_admin(update: Update) -> bool:
    return get_settings().is_admin(require_chat_id(update))


async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = require_message(update)
    if not _is_admin(update):
        await message.reply_text(texts.ADMIN_ONLY)
        return
    async with session_scope() as session:
        pending = await CorrectionRepository(session).pending()
        machine_repo = MachineRepository(session)
        if not pending:
            await message.reply_text(texts.QUEUE_EMPTY)
            return
        lines = [texts.QUEUE_HEADER]
        for c in pending:
            machine = await machine_repo.get(c.machine_id)
            name = machine.name if machine else f"#{c.machine_id}"
            lines.append(f"#{c.id} [{c.type}] {name}: {c.comment or ''}")
        lines.append("\nAnnehmen: /ok <id>   Ablehnen: /nope <id>")
    await message.reply_text("\n".join(lines))


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = require_message(update)
    if not _is_admin(update):
        await message.reply_text(texts.ADMIN_ONLY)
        return
    args = require_args(context)
    if len(args) != 1 or not args[0].isdigit():
        await message.reply_text(texts.OK_USAGE)
        return
    correction_id = int(args[0])
    async with session_scope() as session:
        result = await CorrectionService(session).approve(correction_id, require_chat_id(update))
    await message.reply_text(
        texts.CORRECTION_APPROVED.format(id=correction_id)
        if result.applied
        else texts.CORRECTION_NOT_FOUND.format(id=correction_id)
    )
    # A removed location is a catalogue change every admin should see, even the
    # one who just approved it (there may be several). Sent after commit so the
    # alert never outruns the persisted status change.
    if result.deleted_machine_name is not None:
        await notify_admins(
            texts.NOTIFY_ADMIN_DELETED.format(
                id=result.deleted_machine_id, name=result.deleted_machine_name
            )
        )


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = require_message(update)
    if not _is_admin(update):
        await message.reply_text(texts.ADMIN_ONLY)
        return
    args = require_args(context)
    if len(args) != 1 or not args[0].isdigit():
        await message.reply_text(texts.NOPE_USAGE)
        return
    correction_id = int(args[0])
    async with session_scope() as session:
        ok = await CorrectionService(session).reject(correction_id, require_chat_id(update))
    await message.reply_text(
        texts.CORRECTION_REJECTED.format(id=correction_id)
        if ok
        else texts.CORRECTION_NOT_FOUND.format(id=correction_id)
    )


async def stale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List active locations the scraper has not re-seen for a while, for review.

    Read-only: this only surfaces candidates. Removing one is the admin's explicit
    /entfernen decision, never automatic, because forum threads outlive the machine.
    """
    message = require_message(update)
    if not _is_admin(update):
        await message.reply_text(texts.ADMIN_ONLY)
        return
    threshold = get_settings().stale_after_days
    now = datetime.now(UTC)
    async with session_scope() as session:
        machines = await MachineRepository(session).stale(threshold)
        if not machines:
            await message.reply_text(texts.STALE_NONE)
            return
        lines = [texts.STALE_HEADER.format(days=threshold)]
        lines += [
            texts.STALE_ITEM.format(id=m.id, name=m.name, days=(now - m.last_seen_at).days)
            for m in machines
        ]
        lines.append(texts.STALE_FOOTER)
    await message.reply_text("\n".join(lines))


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Soft-delete a location (status -> GONE). Used to act on /stale findings."""
    message = require_message(update)
    if not _is_admin(update):
        await message.reply_text(texts.ADMIN_ONLY)
        return
    args = require_args(context)
    if len(args) != 1 or not args[0].isdigit():
        await message.reply_text(texts.REMOVE_USAGE)
        return
    machine_id = int(args[0])
    removed_name: str | None = None
    async with session_scope() as session:
        repo = MachineRepository(session)
        machine = await repo.get(machine_id)
        if machine is None:
            reply = texts.DETAILS_NOT_FOUND.format(id=machine_id)
        elif machine.status is MachineStatus.GONE:
            reply = texts.REMOVE_ALREADY_GONE.format(id=machine_id)
        else:
            await repo.mark_gone(machine_id)
            removed_name = machine.name
            reply = texts.REMOVE_DONE.format(id=machine_id, name=removed_name)
    await message.reply_text(reply)
    # Mirror the corrections-driven deletion: every admin learns about the removal.
    if removed_name is not None:
        await notify_admins(texts.NOTIFY_ADMIN_DELETED.format(id=machine_id, name=removed_name))
