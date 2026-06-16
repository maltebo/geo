"""Unit tests for the /finden result formatter (pure, no DB/Telegram needed)."""

from __future__ import annotations

from pressmuenzen.bot import texts
from pressmuenzen.bot.handlers.common import TEXT_SEARCH_LIMIT, find_result_html
from pressmuenzen.domain.models import MachineStatus, MachineTextMatch


def _match(mid: int, name: str, status: MachineStatus, on_map: bool) -> MachineTextMatch:
    return MachineTextMatch(id=mid, name=name, status=status, on_map=on_map)


def test_header_counts_and_lists_ids() -> None:
    matches = [
        _match(1001, "Hamburg Dom", MachineStatus.ACTIVE, True),
        _match(1002, "Hamburg Hafen", MachineStatus.ACTIVE, True),
    ]
    html = find_result_html("Hamburg", matches)
    assert html.startswith("Treffer für „Hamburg“ (2):")
    assert "<b>1001</b>: Hamburg Dom" in html
    assert "<b>1002</b>: Hamburg Hafen" in html
    # No flags for machines that are on the map.
    assert texts.FIND_FLAG_GONE not in html
    assert texts.FIND_FLAG_NO_COORDS not in html


def test_flags_removed_and_missing_coordinates() -> None:
    matches = [
        _match(2001, "Weg hier", MachineStatus.GONE, False),
        _match(2002, "Ohne Koordinaten", MachineStatus.ACTIVE, False),
    ]
    html = find_result_html("x", matches)
    assert f"<b>2001</b>: Weg hier{texts.FIND_FLAG_GONE}" in html
    assert f"<b>2002</b>: Ohne Koordinaten{texts.FIND_FLAG_NO_COORDS}" in html


def test_escapes_html_in_names_and_query() -> None:
    matches = [_match(3001, "A & B <Test>", MachineStatus.ACTIVE, True)]
    html = find_result_html("<q>", matches)
    assert "A &amp; B &lt;Test&gt;" in html
    assert "&lt;q&gt;" in html
    assert "<Test>" not in html


def test_truncation_hint_only_when_limit_hit() -> None:
    few = [_match(i, f"M{i}", MachineStatus.ACTIVE, True) for i in range(3)]
    assert "verfeinern" not in find_result_html("m", few)

    full = [_match(i, f"M{i}", MachineStatus.ACTIVE, True) for i in range(TEXT_SEARCH_LIMIT)]
    assert texts.FIND_TRUNCATED.format(limit=TEXT_SEARCH_LIMIT) in find_result_html("m", full)
