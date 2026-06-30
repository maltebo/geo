"""Pure domain types, free of any persistence or framework concerns."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class GpsSource(enum.StrEnum):
    """Where a coordinate came from, in descending order of trust.

    The numeric ``precedence`` (lower = more trusted) is the contract used by
    :mod:`pressmuenzen.domain.precedence`. Preserving these exact tiers keeps the
    legacy precedence behaviour (``corrected > forum_gps > ai_address > full_name > partial_name``).
    """

    CORRECTED = "corrected"
    FORUM_GPS = "forum_gps"
    AI_ADDRESS_GEOCODE = "ai_address_geocode"
    FULL_NAME_GEOCODE = "full_name_geocode"
    PARTIAL_NAME_GEOCODE = "partial_name_geocode"
    NONE = "none"

    @property
    def precedence(self) -> int:
        return _PRECEDENCE[self]


_PRECEDENCE: dict[GpsSource, int] = {
    GpsSource.CORRECTED: 0,
    GpsSource.FORUM_GPS: 1,
    GpsSource.AI_ADDRESS_GEOCODE: 2,
    GpsSource.FULL_NAME_GEOCODE: 3,
    GpsSource.PARTIAL_NAME_GEOCODE: 4,
    GpsSource.NONE: 99,
}


class MachineStatus(enum.StrEnum):
    ACTIVE = "active"
    GONE = "gone"
    UNKNOWN = "unknown"


class CorrectionType(enum.StrEnum):
    GPS = "gps"
    GONE = "gone"
    MOVED = "moved"
    NAME = "name"
    OTHER = "other"


class CorrectionStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Coordinate:
    """A WGS84 point. ``lat``/``lon`` in decimal degrees."""

    lat: float
    lon: float

    @property
    def maps_link(self) -> str:
        return f"https://maps.google.com/?q={self.lat},{self.lon}"


@dataclass(frozen=True, slots=True)
class CandidateInput:
    """A coordinate candidate considered during precedence resolution."""

    source: GpsSource
    coordinate: Coordinate


@dataclass(frozen=True, slots=True)
class MachineTextMatch:
    """A machine found by a free-text name search, for diagnostics/lookup.

    Unlike :class:`MachineHit` this is intentionally coordinate-agnostic: it
    surfaces machines that are *missing* from the map (no coordinate, or removed)
    so an admin can tell why something is not visible. ``on_map`` mirrors exactly
    the map/spatial filter (has a coordinate and not removed).
    """

    id: int
    name: str
    status: MachineStatus
    on_map: bool


@dataclass(frozen=True, slots=True)
class MachineHit:
    """A machine returned from a query, with its resolved coordinate.

    A pure read-model DTO (no persistence concerns) so it can be shared by the
    repository, the search service, the maps service and the web layer without
    dragging SQLAlchemy into otherwise-pure modules.
    """

    id: int
    name: str
    url: str
    description: str
    category: str
    entry_date_text: str | None
    is_limited: bool
    gps_source: GpsSource
    coordinate: Coordinate
    distance_km: float | None = None
