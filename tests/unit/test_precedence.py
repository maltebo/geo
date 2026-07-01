"""Unit tests for coordinate-source precedence resolution."""

from __future__ import annotations

from pressmuenzen.domain.models import CandidateInput, Coordinate, GpsSource
from pressmuenzen.domain.precedence import resolve

C = Coordinate(lat=50.0, lon=8.0)
C2 = Coordinate(lat=51.0, lon=9.0)


def _cand(source: GpsSource, coord: Coordinate = C) -> CandidateInput:
    return CandidateInput(source=source, coordinate=coord)


def test_empty_resolves_to_none() -> None:
    coord, source = resolve([])
    assert coord is None
    assert source is GpsSource.NONE


def test_corrected_wins_over_everything() -> None:
    coord, source = resolve(
        [
            _cand(GpsSource.PARTIAL_NAME_GEOCODE),
            _cand(GpsSource.FORUM_GPS),
            _cand(GpsSource.CORRECTED, C2),
            _cand(GpsSource.FULL_NAME_GEOCODE),
        ]
    )
    assert source is GpsSource.CORRECTED
    assert coord == C2


def test_forum_gps_beats_name_geocodes() -> None:
    _, source = resolve([_cand(GpsSource.FULL_NAME_GEOCODE), _cand(GpsSource.FORUM_GPS)])
    assert source is GpsSource.FORUM_GPS


def test_full_name_beats_partial_name() -> None:
    _, source = resolve([_cand(GpsSource.PARTIAL_NAME_GEOCODE), _cand(GpsSource.FULL_NAME_GEOCODE)])
    assert source is GpsSource.FULL_NAME_GEOCODE


def test_none_candidates_are_ignored() -> None:
    coord, source = resolve([_cand(GpsSource.NONE), _cand(GpsSource.FORUM_GPS)])
    assert source is GpsSource.FORUM_GPS
    assert coord == C


def test_ai_address_beats_full_name_geocode() -> None:
    _, source = resolve(
        [_cand(GpsSource.FULL_NAME_GEOCODE), _cand(GpsSource.AI_ADDRESS_GEOCODE, C2)]
    )
    assert source is GpsSource.AI_ADDRESS_GEOCODE


def test_forum_gps_beats_ai_address() -> None:
    _, source = resolve([_cand(GpsSource.AI_ADDRESS_GEOCODE), _cand(GpsSource.FORUM_GPS, C2)])
    assert source is GpsSource.FORUM_GPS


def test_ai_address_low_beats_partial_name() -> None:
    _, source = resolve(
        [_cand(GpsSource.PARTIAL_NAME_GEOCODE), _cand(GpsSource.AI_ADDRESS_GEOCODE_LOW, C2)]
    )
    assert source is GpsSource.AI_ADDRESS_GEOCODE_LOW


def test_full_name_beats_ai_address_low() -> None:
    _, source = resolve(
        [_cand(GpsSource.AI_ADDRESS_GEOCODE_LOW), _cand(GpsSource.FULL_NAME_GEOCODE, C2)]
    )
    assert source is GpsSource.FULL_NAME_GEOCODE


def test_precedence_order_is_the_documented_contract() -> None:
    order = [
        GpsSource.CORRECTED,
        GpsSource.FORUM_GPS,
        GpsSource.AI_ADDRESS_GEOCODE,
        GpsSource.FULL_NAME_GEOCODE,
        GpsSource.AI_ADDRESS_GEOCODE_LOW,
        GpsSource.PARTIAL_NAME_GEOCODE,
    ]
    precedences = [s.precedence for s in order]
    assert precedences == sorted(precedences)
    assert len(set(precedences)) == len(precedences)
