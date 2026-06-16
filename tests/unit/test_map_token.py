"""Signed hosted-map token round-trip and tamper/expiry checks."""

from __future__ import annotations

from pressmuenzen.domain.models import Coordinate
from pressmuenzen.services.maps import make_map_token, parse_map_token

ORIGIN = Coordinate(lat=50.5, lon=8.5)


def test_roundtrip() -> None:
    token = make_map_token(ORIGIN, "radius", 10.0, now=1000.0)
    payload = parse_map_token(token, now=1000.0)
    assert payload is not None
    assert payload["mode"] == "radius"
    assert payload["value"] == 10.0
    assert payload["lat"] == 50.5


def test_expired_token_rejected() -> None:
    token = make_map_token(ORIGIN, "radius", 10.0, now=1000.0)
    # Far in the future, past the 24h TTL.
    assert parse_map_token(token, now=1000.0 + 60 * 60 * 25) is None


def test_tampered_token_rejected() -> None:
    token = make_map_token(ORIGIN, "radius", 10.0, now=1000.0)
    body, _sig = token.split(".", 1)
    forged = body + ".AAAAAAAA"
    assert parse_map_token(forged, now=1000.0) is None


def test_garbage_token_rejected() -> None:
    assert parse_map_token("not-a-token", now=1000.0) is None
