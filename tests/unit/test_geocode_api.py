"""Unit tests for the /api/geocode endpoint helper."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from pressmuenzen.domain.models import Coordinate
from pressmuenzen.web.routes.api import _resolve_address


async def test_resolve_address_found() -> None:
    mock = AsyncMock()
    mock.geocode.return_value = Coordinate(lat=52.52, lon=13.40)
    coord = await _resolve_address(mock, "Berlin")
    assert coord.lat == 52.52
    assert coord.lon == 13.40
    mock.geocode.assert_awaited_once_with("Berlin")


async def test_resolve_address_not_found() -> None:
    mock = AsyncMock()
    mock.geocode.return_value = None
    with pytest.raises(HTTPException) as exc_info:
        await _resolve_address(mock, "xyzabc123notreal")
    assert exc_info.value.status_code == 404


async def test_resolve_address_strips_whitespace() -> None:
    mock = AsyncMock()
    mock.geocode.return_value = Coordinate(lat=48.13, lon=11.57)
    coord = await _resolve_address(mock, "  München  ")
    assert coord.lat == 48.13
    # Geocoder receives the query as-is; stripping is done inside Geocoder.geocode
    mock.geocode.assert_awaited_once_with("  München  ")
