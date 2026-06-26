"""/details, /alle_zeigen and /start handlers."""

from __future__ import annotations

from html import escape

from telegram import Update
from telegram.ext import ContextTypes

from pressmuenzen.bot import texts
from pressmuenzen.bot.handlers.common import (
    TEXT_SEARCH_LIMIT,
    find_result_html,
    hosted_map_url,
    require_args,
    require_chat_id,
    require_message,
)
from pressmuenzen.bot.handlers.corrections import handle_deeplink_correction, parse_fix_payload
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import Coordinate


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = require_args(context)
    if args and parse_fix_payload(args[0]) is not None:
        await handle_deeplink_correction(update, context)
        return
    await require_message(update).reply_text(texts.START)


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help users find their chat id (for ADMIN_CHAT_IDS configuration)."""
    await require_message(update).reply_text(f"chat_id: {require_chat_id(update)}")


async def show_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Centre the "all machines" map on a neutral point; the page fits bounds itself.
    url = hosted_map_url(Coordinate(lat=51.0, lon=10.0), "all", 0)
    await require_message(update).reply_text(texts.MAP_ALL_READY.format(url=url))


async def find(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text name search over the catalogue (incl. machines missing from the map).

    A diagnostic/lookup tool: given a term it returns matching ids and flags any
    result that is removed or has no coordinate, which is why it would not appear
    on the map or in /suche.
    """
    message = require_message(update)
    query = " ".join(require_args(context)).strip()
    if len(query) < 2:
        await message.reply_text(texts.FIND_USAGE)
        return

    async with session_scope() as session:
        matches = await MachineRepository(session).search_by_name(query, TEXT_SEARCH_LIMIT)

    if not matches:
        await message.reply_text(texts.FIND_NONE.format(query=query))
        return
    await message.reply_html(find_result_html(query, matches))


async def details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = require_message(update)
    args = require_args(context)
    if len(args) != 1 or not args[0].isdigit():
        await message.reply_text(texts.DETAILS_USAGE)
        return
    machine_id = int(args[0])

    async with session_scope() as session:
        hit = await MachineRepository(session).get_hit(machine_id)
        machine = await MachineRepository(session).get(machine_id)

    if machine is None:
        await message.reply_text(texts.DETAILS_NOT_FOUND.format(id=machine_id))
        return

    # HTML mode with escaped values: forum text (name/description) is arbitrary
    # and would break Telegram's fragile Markdown parser. Labels are bold; values
    # are html.escape()d so a stray *, _, [ or & can never corrupt the message.
    def row(label: str, value: object) -> str:
        return f"<b>{label}:</b> {escape(str(value))}"

    lines = [row("ID", machine_id), row("Name", machine.name)]
    lines.append(row("Kategorie", hit.category if hit else ""))
    lines.append(row("Link", machine.source_url))
    if machine.entry_date_text:
        lines.append(row("Eingetragen am", machine.entry_date_text))
    lines.append(row("Koordinatenquelle", machine.gps_source))
    if hit is not None:
        lines.append(row("Google Maps", hit.coordinate.maps_link))
    if machine.is_limited:
        lines.append("<b>Hinweis:</b> möglicherweise nur zeitlich begrenzt verfügbar!")
    if machine.description:
        lines.append(row("Beschreibung", machine.description))

    await message.reply_html("\n".join(lines))
