"""Regression corpus for the GPS parser.

The corpus is 618 real (gps_text -> lat/lon) pairs extracted from the production
database. It is a CONTRACT: any change to the parser must keep every entry
parsing to the same coordinate. See domain/gps_parser.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pressmuenzen.domain.gps_parser import LatLon, parse_gps_text

_CORPUS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "gps_strings.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("entry", _CORPUS, ids=lambda e: str(e["loc_id"]))
def test_corpus_entry_parses_to_expected_coordinate(entry: dict) -> None:
    result = parse_gps_text(entry["gps_text"])
    assert result is not None, f"parser returned None for {entry['gps_text']!r}"
    assert result.lat == pytest.approx(entry["lat"], abs=1e-9)
    assert result.lon == pytest.approx(entry["lon"], abs=1e-9)


def test_corpus_is_not_empty() -> None:
    # Guards against a silently truncated / missing fixture file.
    assert len(_CORPUS) >= 600


@pytest.mark.parametrize(
    "garbage",
    ["", "kein gps", "abc", "1234567"],  # too short / unparseable
)
def test_unparseable_returns_none(garbage: str) -> None:
    assert parse_gps_text(garbage) is None


def test_rejects_out_of_range() -> None:
    # 200 degrees latitude is physically impossible -> None.
    assert parse_gps_text("200.0, 8.0") is None


def test_returns_latlon_type() -> None:
    result = parse_gps_text("N 47.899813888888886 E 8.152569444444444")
    assert isinstance(result, LatLon)
