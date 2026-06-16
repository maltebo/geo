"""Helpers for converting between domain Coordinates and PostGIS geometry SQL."""

from __future__ import annotations

from sqlalchemy import ColumnElement, func

from pressmuenzen.domain.models import Coordinate


def point_wkt(coord: Coordinate) -> ColumnElement[str]:
    """A SQL expression producing a SRID-4326 POINT from a Coordinate.

    PostGIS expects (lon, lat) order for ST_MakePoint.
    """
    return func.ST_SetSRID(func.ST_MakePoint(coord.lon, coord.lat), 4326)


def lon_expr(geom: ColumnElement[str]) -> ColumnElement[float]:
    return func.ST_X(geom)


def lat_expr(geom: ColumnElement[str]) -> ColumnElement[float]:
    return func.ST_Y(geom)


def distance_m(geom: ColumnElement[str], coord: Coordinate) -> ColumnElement[float]:
    """Great-circle distance in metres between a geometry column and a point.

    Casts both to ``geography`` so the result is in metres on the spheroid.
    """
    return func.ST_Distance(func.cast(geom, geography()), func.cast(point_wkt(coord), geography()))


def geography():  # type: ignore[no-untyped-def]
    """Lazily-constructed geoalchemy2 Geography type for casting in queries."""
    from geoalchemy2 import Geography

    return Geography()
