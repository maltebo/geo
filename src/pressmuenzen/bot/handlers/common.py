"""Shared helpers for bot handlers."""

from __future__ import annotations

from html import escape
from typing import Any

from telegram import Message, Update
from telegram.ext import ContextTypes

from pressmuenzen.config import get_settings
from pressmuenzen.domain.models import Coordinate, MachineHit
from pressmuenzen.services.maps import make_map_token


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
