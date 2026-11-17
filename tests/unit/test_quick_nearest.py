"""Unit tests for the bare-location shortcut (nearest machines without /suche)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import ConversationHandler, MessageHandler

from pressmuenzen.bot import texts
from pressmuenzen.bot.handlers import search
from pressmuenzen.domain.models import Coordinate, GpsSource, MachineHit


def _make_update(lat: float = 53.55, lon: float = 9.99) -> MagicMock:
    update = MagicMock()
    update.message.location.latitude = lat
    update.message.location.longitude = lon
    update.message.reply_text = AsyncMock()
    update.message.reply_html = AsyncMock()
    return update


def _make_context(user_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    return ctx


@asynccontextmanager
async def _fake_session_scope():
    yield MagicMock()


def _patch_service(hits: list[MachineHit]) -> tuple[MagicMock, AsyncMock, AsyncMock]:
    service = MagicMock()
    service.nearest = AsyncMock(return_value=hits)
    service.within_radius = AsyncMock(return_value=hits)
    return service, service.nearest, service.within_radius


@pytest.mark.asyncio
async def test_quick_nearest_lists_ten_nearest() -> None:
    hits = [
        MachineHit(
            id=1,
            name="Dom",
            url="https://example.com",
            description="",
            category="",
            entry_date_text=None,
            is_limited=False,
            gps_source=next(iter(GpsSource)),
            coordinate=Coordinate(lat=53.5, lon=9.9),
            distance_km=1.2,
        )
    ]
    service, nearest, within = _patch_service(hits)
    update = _make_update()
    # Stale /suche state must not leak into the shortcut.
    context = _make_context({"mode": "radius", "value": 50.0})

    with (
        patch.object(search, "session_scope", _fake_session_scope),
        patch.object(search, "SearchService", return_value=service),
        patch.object(search, "hosted_map_url", return_value="https://x/map/t") as map_url,
    ):
        await search.quick_nearest(update, context)

    nearest.assert_awaited_once_with(Coordinate(lat=53.55, lon=9.99), search.QUICK_NEAREST_COUNT)
    within.assert_not_awaited()
    map_url.assert_called_once_with(Coordinate(lat=53.55, lon=9.99), "nearest", 10.0)
    update.message.reply_text.assert_awaited_once_with(
        texts.MAP_READY.format(url="https://x/map/t")
    )
    assert "Dom" in update.message.reply_html.await_args.args[0]


@pytest.mark.asyncio
async def test_quick_nearest_no_hits() -> None:
    service, _, _ = _patch_service([])
    update = _make_update()

    with (
        patch.object(search, "session_scope", _fake_session_scope),
        patch.object(search, "SearchService", return_value=service),
    ):
        await search.quick_nearest(update, _make_context())

    update.message.reply_text.assert_awaited_once_with(texts.NO_MACHINE_FOUND)
    update.message.reply_html.assert_not_awaited()


@pytest.mark.asyncio
async def test_suche_pin_still_uses_conversation_state() -> None:
    service, nearest, within = _patch_service([])
    update = _make_update()
    context = _make_context({"mode": "radius", "value": 7.5})

    with (
        patch.object(search, "session_scope", _fake_session_scope),
        patch.object(search, "SearchService", return_value=service),
    ):
        result = await search.on_location_pin(update, context)

    assert result == ConversationHandler.END
    within.assert_awaited_once_with(Coordinate(lat=53.55, lon=9.99), 7.5)
    nearest.assert_not_awaited()


def test_shortcut_registered_after_conversations() -> None:
    """A pin awaited by /suche, /heimat or /melden must reach the conversation first."""
    from pressmuenzen.bot import app as bot_app

    settings = MagicMock()
    settings.telegram_token = "123:abc"
    with patch.object(bot_app, "get_settings", return_value=settings):
        application = bot_app.build_application()

    handlers = application.handlers[0]
    shortcut_idx = next(
        i
        for i, h in enumerate(handlers)
        if isinstance(h, MessageHandler) and h.callback is search.quick_nearest
    )
    last_conv_idx = max(i for i, h in enumerate(handlers) if isinstance(h, ConversationHandler))
    assert shortcut_idx > last_conv_idx
