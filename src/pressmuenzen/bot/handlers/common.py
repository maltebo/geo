"""Shared helpers for bot handlers."""

from __future__ import annotations

from html import escape
from typing import Any

from telegram import Message, Update
from telegram.ext import ContextTypes

from pressmuenzen.bot import texts
from pressmuenzen.config import get_settings
from pressmuenzen.domain.models import Coordinate, MachineHit, MachineStatus, MachineTextMatch
from pressmuenzen.services.maps import make_diff_map_token, make_map_token

# Max rows a /finden text search returns. Shared so the repo query and the
# "result truncated" hint in the formatter can never drift apart.
TEXT_SEARCH_LIMIT = 25


def require_message(update: Update) -> Message:
    """Narrow ``update.message`` to non-None.

    PTB types the triggering message Optional, but our command/message handlers
    are only ever registered for updates that carry one. Fail loudly if that
    invariant is ever violated rather than silencing the type with an ignore.
    """
    message = update.message
    assert message is not None, "handler invoked without a message"
    return message


def require_chat_id(update: Update) -> int:
    chat = update.effective_chat
    assert chat is not None, "handler invoked without an effective chat"
    return chat.id


def require_args(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    """Command arguments, or an empty list when PTB supplies none."""
    return context.args or []


def require_user_data(context: ContextTypes.DEFAULT_TYPE) -> dict[Any, Any]:
    """The per-user conversation state dict, narrowed to non-None."""
    data = context.user_data
    assert data is not None, "conversation handler invoked without user_data"
    return data


def hosted_map_url(origin: Coordinate, mode: str, value: float) -> str:
    token = make_map_token(origin, mode, value)
    return f"{get_settings().public_base_url_clean}/map/{token}"


def correction_diff_map_url(old: Coordinate | None, new: Coordinate, name: str) -> str:
    token = make_diff_map_token(old, new, name)
    return f"{get_settings().public_base_url_clean}/map/{token}"


def result_list_html(hits: list[MachineHit], origin_label: str | None = None) -> str:
    """Render the search result list as HTML (bold ids, escaped names).

    HTML + escaping avoids Telegram's fragile Markdown parser choking on a stray
    *, _, [ or & in a forum-sourced machine name.
    """
    lines: list[str] = []
    if origin_label:
        lines.append(f"<b>Eingegebener Standort:</b> {escape(origin_label)}")
    for hit in hits[:15]:
        line = f"<b>{hit.id}</b>: {escape(hit.name)}"
        if hit.distance_km is not None:
            line += f" ({round(hit.distance_km, 1)} km)"
        lines.append(line)
    if len(hits) > 15:
        lines.append("... (nur die ersten 15 Einträge werden angezeigt)")
    return "\n".join(lines)


def find_result_html(query: str, matches: list[MachineTextMatch]) -> str:
    """Render /finden results as HTML, flagging rows that are missing from the map.

    Names are forum-sourced and arbitrary, so everything is ``html.escape``d. Each
    line shows the id (for /details, /besucht, /melden) and, when a machine is not
    visible on the map, *why*: removed vs no coordinates.
    """
    lines = [texts.FIND_HEADER.format(query=escape(query), count=len(matches))]
    for m in matches:
        if m.status is MachineStatus.GONE:
            flag = texts.FIND_FLAG_GONE
        elif not m.on_map:
            flag = texts.FIND_FLAG_NO_COORDS
        else:
            flag = ""
        lines.append(f"<b>{m.id}</b>: {escape(m.name)}{flag}")
    if len(matches) >= TEXT_SEARCH_LIMIT:
        lines.append(texts.FIND_TRUNCATED.format(limit=TEXT_SEARCH_LIMIT))
    return "\n".join(lines)
