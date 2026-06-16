"""Shared helpers for bot handlers."""

from __future__ import annotations

from html import escape

from pressmuenzen.config import get_settings
from pressmuenzen.domain.models import Coordinate, MachineHit
from pressmuenzen.services.maps import make_map_token


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
