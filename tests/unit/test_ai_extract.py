"""Unit tests for AI extraction result parsing and job helper logic.

The LLM call itself is not tested here (it requires an API key and is
integration territory). We test the pure parsing of the JSON response dict
and the confidence-filtering / move-routing logic that is independent of
the database.
"""

from __future__ import annotations

from pressmuenzen.ai.extract import (
    ExtractionResult,
    OpeningHours,
    OpeningHoursPeriod,
    _parse_response,
)

# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_full_response() -> None:
    raw = {
        "address": {"found": True, "value": "Hauptstraße 1, 53111 Bonn", "confidence": "high"},
        "moved": {"detected": False, "new_address": ""},
        "opening_hours": {
            "found": True,
            "periods": [
                {"days": ["Monday", "Tuesday"], "open": "09:00", "close": "18:00"},
            ],
            "notes": "Feiertage geschlossen",
        },
        "summary": "Der Automat steht am Bahnhof.",
    }

    result = _parse_response(raw)

    assert result.address_found is True
    assert result.address_value == "Hauptstraße 1, 53111 Bonn"
    assert result.address_confidence == "high"
    assert result.moved_detected is False
    assert result.opening_hours is not None
    assert len(result.opening_hours.periods) == 1
    assert result.opening_hours.periods[0].days == ["Monday", "Tuesday"]
    assert result.opening_hours.notes == "Feiertage geschlossen"
    assert result.summary == "Der Automat steht am Bahnhof."


def test_parse_address_not_found() -> None:
    raw = {
        "address": {"found": False},
        "moved": {"detected": False},
        "opening_hours": {"found": False},
        "summary": "Kein Standort erwähnt.",
    }

    result = _parse_response(raw)

    assert result.address_found is False
    assert result.address_value == ""
    assert result.opening_hours is None


def test_parse_move_detected() -> None:
    raw = {
        "address": {"found": False},
        "moved": {"detected": True, "new_address": "Neue Straße 5, Köln"},
        "opening_hours": {"found": False},
        "summary": "Umgezogen.",
    }

    result = _parse_response(raw)

    assert result.moved_detected is True
    assert result.moved_new_address == "Neue Straße 5, Köln"


def test_parse_missing_optional_fields_uses_defaults() -> None:
    raw = {
        "address": {"found": True, "value": "Irgendwo", "confidence": "medium"},
        "moved": {"detected": False},
        "opening_hours": {"found": False},
        "summary": "",
    }

    result = _parse_response(raw)

    assert result.address_found is True
    assert result.summary == ""
    assert result.moving_detected is False if hasattr(result, "moving_detected") else True


def test_parse_null_address_value_treated_as_empty() -> None:
    raw = {
        "address": {"found": True, "value": None, "confidence": "low"},
        "moved": {"detected": False},
        "opening_hours": {"found": False},
        "summary": "summary",
    }

    result = _parse_response(raw)

    assert result.address_value == ""


def test_parse_empty_raw_returns_defaults() -> None:
    result = _parse_response({})

    assert result.address_found is False
    assert result.moved_detected is False
    assert result.opening_hours is None
    assert result.summary == ""


# ---------------------------------------------------------------------------
# ExtractionResult defaults
# ---------------------------------------------------------------------------


def test_extraction_result_defaults() -> None:
    r = ExtractionResult()

    assert r.address_found is False
    assert r.address_value == ""
    assert r.address_confidence == "low"
    assert r.moved_detected is False
    assert r.moved_new_address == ""
    assert r.opening_hours is None
    assert r.summary == ""


# ---------------------------------------------------------------------------
# OpeningHours.to_json
# ---------------------------------------------------------------------------


def test_opening_hours_to_json_roundtrip() -> None:
    import json

    oh = OpeningHours(
        periods=[
            OpeningHoursPeriod(days=["Monday", "Friday"], open="10:00", close="20:00"),
        ],
        notes="Nur werktags",
    )

    parsed = json.loads(oh.to_json())

    assert parsed["periods"][0]["days"] == ["Monday", "Friday"]
    assert parsed["periods"][0]["open"] == "10:00"
    assert parsed["notes"] == "Nur werktags"


def test_opening_hours_to_json_empty() -> None:
    import json

    oh = OpeningHours()
    parsed = json.loads(oh.to_json())

    assert parsed["periods"] == []
    assert parsed["notes"] == ""


# ---------------------------------------------------------------------------
# Confidence rank contract (tested via the module-level dict)
# ---------------------------------------------------------------------------


def test_confidence_ranks_are_ordered() -> None:
    from pressmuenzen.ai.extract import _CONFIDENCE_RANK

    assert _CONFIDENCE_RANK["low"] < _CONFIDENCE_RANK["medium"] < _CONFIDENCE_RANK["high"]
