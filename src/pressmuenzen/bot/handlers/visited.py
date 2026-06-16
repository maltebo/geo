"""/besucht and /nicht_besucht handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from pressmuenzen.bot import texts
from pressmuenzen.bot.handlers.common import require_args, require_chat_id, require_message
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.db.repositories.users import UserRepository


async def mark_visited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = require_message(update)
    args = require_args(context)
    if len(args) != 1 or not args[0].isdigit():
        await message.reply_text(texts.VISITED_USAGE)
        return
    machine_id = int(args[0])
    chat_id = require_chat_id(update)

    async with session_scope() as session:
        machine = await MachineRepository(session).get(machine_id)
        if machine is None:
            await message.reply_text(texts.DETAILS_NOT_FOUND.format(id=machine_id))
            return
        added = await UserRepository(session).add_visited(chat_id, machine_id)

    if added:
        await message.reply_text(texts.VISITED_ADDED.format(name=machine.name))
    else:
        await message.reply_text(texts.VISITED_ALREADY.format(name=machine.name))


async def unmark_visited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = require_message(update)
    args = require_args(context)
    if len(args) != 1 or not args[0].isdigit():
        await message.reply_text(texts.NOT_VISITED_USAGE)
        return
    machine_id = int(args[0])
    chat_id = require_chat_id(update)

    async with session_scope() as session:
        machine = await MachineRepository(session).get(machine_id)
        if machine is None:
            await message.reply_text(texts.DETAILS_NOT_FOUND.format(id=machine_id))
            return
        removed = await UserRepository(session).delete_visited(chat_id, machine_id)

    if removed:
        await message.reply_text(texts.NOT_VISITED_REMOVED.format(name=machine.name))
    else:
        await message.reply_text(texts.NOT_VISITED_ABSENT.format(name=machine.name))
