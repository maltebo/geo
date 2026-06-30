"""Unit tests for the admin geocodieren conversation handler.

The Telegram Update/context objects are mocked at the boundary so the
handler logic (state transitions, user_data management, admin guard) is
tested without a live bot or database.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import ConversationHandler

from pressmuenzen.bot.handlers.admin_geocode import (
    GEOCODE_ADDRESS,
    GEOCODE_CONFIRM,
    GEOCODE_PICK,
    geocode_address,
    geocode_confirm,
    geocode_pick,
    geocode_start,
)
from pressmuenzen.domain.models import Coordinate, GpsSource, MachineStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_update(text: str = "", chat_id: int = 1) -> MagicMock:
    """Build a minimal mock Update that our handlers can navigate."""
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.location = None
    return update


def _make_context(user_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.args = []
    return ctx


def _make_machine(
    machine_id: int = 1,
    name: str = "Test",
    source_url: str = "http://example.com",
    description: str = "Beschreibung",
    geom: object = None,
) -> MagicMock:
    m = MagicMock()
    m.id = machine_id
    m.name = name
    m.source_url = source_url
    m.description = description
    m.geom = geom
    m.status = MachineStatus.ACTIVE
    return m


@asynccontextmanager
async def _fake_session_scope():
    yield MagicMock()


# ---------------------------------------------------------------------------
# geocode_start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_non_admin_returns_end() -> None:
    update = _make_update(chat_id=9999)
    context = _make_context()

    with patch("pressmuenzen.bot.handlers.admin_geocode._is_admin", return_value=False):
        result = await geocode_start(update, context)

    assert result == ConversationHandler.END
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_admin_no_machines_returns_end() -> None:
    update = _make_update(chat_id=1)
    context = _make_context()

    mock_repo = AsyncMock()
    mock_repo.ungeocoded.return_value = []

    with (
        patch("pressmuenzen.bot.handlers.admin_geocode._is_admin", return_value=True),
        patch("pressmuenzen.bot.handlers.admin_geocode.session_scope", _fake_session_scope),
        patch(
            "pressmuenzen.bot.handlers.admin_geocode.MachineRepository",
            return_value=mock_repo,
        ),
    ):
        result = await geocode_start(update, context)

    assert result == ConversationHandler.END


@pytest.mark.asyncio
async def test_start_admin_with_machines_returns_pick() -> None:
    update = _make_update(chat_id=1)
    context = _make_context()

    mock_repo = AsyncMock()
    mock_repo.ungeocoded.return_value = [_make_machine(42, "Kiosk Bonn")]

    with (
        patch("pressmuenzen.bot.handlers.admin_geocode._is_admin", return_value=True),
        patch("pressmuenzen.bot.handlers.admin_geocode.session_scope", _fake_session_scope),
        patch(
            "pressmuenzen.bot.handlers.admin_geocode.MachineRepository",
            return_value=mock_repo,
        ),
    ):
        result = await geocode_start(update, context)

    assert result == GEOCODE_PICK
    # Message should mention the machine
    sent_text = update.message.reply_text.call_args[0][0]
    assert "42" in sent_text
    assert "Kiosk Bonn" in sent_text


# ---------------------------------------------------------------------------
# geocode_pick
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_non_digit_stays_in_pick() -> None:
    update = _make_update(text="not-a-number")
    context = _make_context()

    result = await geocode_pick(update, context)

    assert result == GEOCODE_PICK
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_pick_unknown_id_stays_in_pick() -> None:
    update = _make_update(text="9999")
    context = _make_context()

    mock_repo = AsyncMock()
    mock_repo.get.return_value = None  # machine not found

    with (
        patch("pressmuenzen.bot.handlers.admin_geocode.session_scope", _fake_session_scope),
        patch(
            "pressmuenzen.bot.handlers.admin_geocode.MachineRepository",
            return_value=mock_repo,
        ),
    ):
        result = await geocode_pick(update, context)

    assert result == GEOCODE_PICK


@pytest.mark.asyncio
async def test_pick_machine_already_geocoded_stays_in_pick() -> None:
    update = _make_update(text="42")
    context = _make_context()

    mock_repo = AsyncMock()
    mock_repo.get.return_value = _make_machine(42, geom="POINT(8 50)")  # already has geom

    with (
        patch("pressmuenzen.bot.handlers.admin_geocode.session_scope", _fake_session_scope),
        patch(
            "pressmuenzen.bot.handlers.admin_geocode.MachineRepository",
            return_value=mock_repo,
        ),
    ):
        result = await geocode_pick(update, context)

    assert result == GEOCODE_PICK


@pytest.mark.asyncio
async def test_pick_valid_stores_id_and_returns_address() -> None:
    update = _make_update(text="42")
    context = _make_context()

    machine = _make_machine(42, name="Münzautomat Bonn", geom=None)
    mock_repo = AsyncMock()
    mock_repo.get.return_value = machine

    with (
        patch("pressmuenzen.bot.handlers.admin_geocode.session_scope", _fake_session_scope),
        patch(
            "pressmuenzen.bot.handlers.admin_geocode.MachineRepository",
            return_value=mock_repo,
        ),
    ):
        result = await geocode_pick(update, context)

    assert result == GEOCODE_ADDRESS
    assert context.user_data["geocode_machine_id"] == 42
    # The reply should include the machine name and URL
    sent_text = update.message.reply_text.call_args[0][0]
    assert "Münzautomat Bonn" in sent_text


# ---------------------------------------------------------------------------
# geocode_address
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_address_geocode_miss_stays_in_address() -> None:
    update = _make_update(text="Nonexistent Place XYZ")
    context = _make_context({"geocode_machine_id": 42})

    mock_geocoder = AsyncMock()
    mock_geocoder.geocode.return_value = None

    with (
        patch("pressmuenzen.bot.handlers.admin_geocode.session_scope", _fake_session_scope),
        patch(
            "pressmuenzen.bot.handlers.admin_geocode.Geocoder",
            return_value=mock_geocoder,
        ),
    ):
        result = await geocode_address(update, context)

    assert result == GEOCODE_ADDRESS
    assert "geocode_coord" not in context.user_data


@pytest.mark.asyncio
async def test_address_geocode_hit_stores_coord_and_returns_confirm() -> None:
    update = _make_update(text="Bonn Hauptbahnhof")
    context = _make_context({"geocode_machine_id": 42})

    coord = Coordinate(lat=50.7374, lon=7.0982)
    mock_geocoder = AsyncMock()
    mock_geocoder.geocode.return_value = coord

    with (
        patch("pressmuenzen.bot.handlers.admin_geocode.session_scope", _fake_session_scope),
        patch(
            "pressmuenzen.bot.handlers.admin_geocode.Geocoder",
            return_value=mock_geocoder,
        ),
    ):
        result = await geocode_address(update, context)

    assert result == GEOCODE_CONFIRM
    assert context.user_data["geocode_coord"] == (50.7374, 7.0982)
    sent_text = update.message.reply_text.call_args[0][0]
    assert "maps.google.com" in sent_text


# ---------------------------------------------------------------------------
# geocode_confirm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_nein_clears_state_and_returns_end() -> None:
    update = _make_update(text="nein")
    context = _make_context({"geocode_machine_id": 42, "geocode_coord": (50.0, 7.0)})

    result = await geocode_confirm(update, context)

    assert result == ConversationHandler.END
    assert "geocode_machine_id" not in context.user_data
    assert "geocode_coord" not in context.user_data


@pytest.mark.asyncio
async def test_confirm_ja_applies_coord_and_returns_end() -> None:
    update = _make_update(text="ja")
    context = _make_context({"geocode_machine_id": 42, "geocode_coord": (50.7374, 7.0982)})

    machine = _make_machine(42, name="Kiosk Bonn")
    mock_repo = AsyncMock()
    mock_repo.get.return_value = machine

    with (
        patch("pressmuenzen.bot.handlers.admin_geocode.session_scope", _fake_session_scope),
        patch(
            "pressmuenzen.bot.handlers.admin_geocode.MachineRepository",
            return_value=mock_repo,
        ),
    ):
        result = await geocode_confirm(update, context)

    assert result == ConversationHandler.END
    mock_repo.clear_candidates_of_source.assert_awaited_once_with(42, GpsSource.CORRECTED)
    mock_repo.add_candidate.assert_awaited_once_with(
        42, GpsSource.CORRECTED, Coordinate(lat=50.7374, lon=7.0982)
    )
    mock_repo.recompute_geom.assert_awaited_once_with(42)
    assert "geocode_machine_id" not in context.user_data
    assert "geocode_coord" not in context.user_data


@pytest.mark.asyncio
async def test_confirm_missing_state_returns_end_with_error() -> None:
    update = _make_update(text="ja")
    context = _make_context({})  # user_data lost somehow

    result = await geocode_confirm(update, context)

    assert result == ConversationHandler.END
    update.message.reply_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# State constant contract
# ---------------------------------------------------------------------------


def test_state_constants_are_distinct_integers() -> None:
    assert isinstance(GEOCODE_PICK, int)
    assert isinstance(GEOCODE_ADDRESS, int)
    assert isinstance(GEOCODE_CONFIRM, int)
    assert len({GEOCODE_PICK, GEOCODE_ADDRESS, GEOCODE_CONFIRM}) == 3
