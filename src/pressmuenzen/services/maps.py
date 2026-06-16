"""Map delivery: GeoJSON building, marker styling, and signed hosted-map tokens.

Replaces the legacy "write a random HTML file, send it as a document, delete it"
flow. The bot now sends a link to GET /map/{token}; the web layer renders the
Leaflet page. Markers are coloured by gps_source so coordinate confidence is
visible (corrected=green, forum_gps=blue, name-geocoded=lighter).
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from hashlib import sha256
from typing import Any

from pressmuenzen.config import get_settings
from pressmuenzen.domain.models import Coordinate, GpsSource, MachineHit

# Marker colour by coordinate source -- confidence made visible.
SOURCE_COLOR: dict[GpsSource, str] = {
    GpsSource.CORRECTED: "green",
    GpsSource.FORUM_GPS: "blue",
    GpsSource.FULL_NAME_GEOCODE: "lightblue",
    GpsSource.PARTIAL_NAME_GEOCODE: "gray",
    GpsSource.NONE: "lightgray",
}

_TOKEN_TTL_SECONDS = 60 * 60 * 24  # 24h hosted-map link lifetime


def machines_to_geojson(hits: list[MachineHit], origin: Coordinate | None = None) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection for the given machines (+ optional origin)."""
    features: list[dict[str, Any]] = []
    for hit in hits:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [hit.coordinate.lon, hit.coordinate.lat],
                },
                "properties": {
                    "id": hit.id,
                    "name": hit.name,
                    "category": hit.category,
                    "url": hit.url,
                    "maps_link": hit.coordinate.maps_link,
                    "gps_source": str(hit.gps_source),
                    "color": SOURCE_COLOR.get(hit.gps_source, "blue"),
                    "is_limited": hit.is_limited,
                    "description": (hit.description or "")[:280],
                    "distance_km": (
                        round(hit.distance_km, 1) if hit.distance_km is not None else None
                    ),
                },
            }
        )
    collection: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if origin is not None:
        collection["origin"] = {"lat": origin.lat, "lon": origin.lon}
    return collection


# --- signed hosted-map tokens ------------------------------------------------
#
# A token encodes the search query (origin + mode + value) so GET /map/{token}
# re-runs the search server-side. HMAC-signed and time-limited; a leaked/expired
# token cannot be forged or replayed past its TTL.


def _secret() -> bytes:
    return get_settings().map_token_secret.encode("utf-8")


def make_map_token(origin: Coordinate, mode: str, value: float, *, now: float | None = None) -> str:
    payload = {
        "lat": round(origin.lat, 6),
        "lon": round(origin.lon, 6),
        "mode": mode,  # "radius" | "nearest" | "all"
        "value": value,
        "exp": int((now or time.time()) + _TOKEN_TTL_SECONDS),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=")
    sig = base64.urlsafe_b64encode(_sign(body)).rstrip(b"=")
    return f"{body.decode()}.{sig.decode()}"


def parse_map_token(token: str, *, now: float | None = None) -> dict[str, Any] | None:
    try:
        body_str, sig_str = token.split(".", 1)
    except ValueError:
        return None
    body = body_str.encode("utf-8")
    expected = base64.urlsafe_b64encode(_sign(body)).rstrip(b"=").decode()
    if not hmac.compare_digest(expected, sig_str):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body_str + "=" * (-len(body_str) % 4)))
    except ValueError:  # covers json.JSONDecodeError and bad base64
        return None
    if payload.get("exp", 0) < (now or time.time()):
        return None
    return payload


def _sign(body: bytes) -> bytes:
    return hmac.new(_secret(), body, sha256).digest()
