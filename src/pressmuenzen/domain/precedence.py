"""Coordinate-source precedence resolution -- the data-quality core.

A machine accumulates one or more coordinate candidates over its lifetime
(forum GPS, name geocodes, approved corrections). This pure function picks the
authoritative one in fixed order:

    corrected -> forum_gps -> full_name_geocode -> partial_name_geocode -> none

It is the ONLY place that decides a machine's chosen coordinate and its
``gps_source``. Keeping it pure and unit-tested means precedence is recomputed
(never overwritten) whenever a candidate is added by the scraper, the geocoder,
or an approved correction.
"""

from __future__ import annotations

from pressmuenzen.domain.models import CandidateInput, Coordinate, GpsSource


def resolve(candidates: list[CandidateInput]) -> tuple[Coordinate | None, GpsSource]:
    """Return the highest-precedence coordinate and its source.

    With no usable candidate, returns ``(None, GpsSource.NONE)``.
    """
    best: CandidateInput | None = None
    for candidate in candidates:
        if candidate.source is GpsSource.NONE:
            continue
        if best is None or candidate.source.precedence < best.source.precedence:
            best = candidate

    if best is None:
        return None, GpsSource.NONE
    return best.coordinate, best.source
