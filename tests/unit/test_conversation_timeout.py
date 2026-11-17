"""Unit tests for the conversation timeout wiring and its handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ConversationHandler

from pressmuenzen.bot import app as bot_app
from pressmuenzen.bot import texts
from pressmuenzen.bot.handlers.common import on_conversation_timeout


def _build() -> bot_app._Application:
    settings = MagicMock()
    settings.telegram_token = "123:abc"
    with patch.object(bot_app, "get_settings", return_value=settings):
        return bot_app.build_application()


def test_every_conversation_has_timeout() -> None:
    application = _build()
    conversations = [h for h in application.handlers[0] if isinstance(h, ConversationHandler)]

    assert len(conversations) == 4
    for conv in conversations:
        assert conv.conversation_timeout == bot_app.CONVERSATION_TIMEOUT
        assert ConversationHandler.TIMEOUT in conv.states


def test_job_queue_available() -> None:
    # Without a JobQueue PTB only warns and the timeout never fires.
    assert _build().job_queue is not None


@pytest.mark.asyncio
async def test_timeout_clears_state_and_notifies() -> None:
    update = MagicMock(spec=Update)
    update.effective_chat.id = 42
    context = MagicMock()
    context.user_data = {"mode": "radius", "value": 5.0}
    context.bot.send_message = AsyncMock()

    await on_conversation_timeout(update, context)

    assert context.user_data == {}
    context.bot.send_message.assert_awaited_once()
    args, kwargs = context.bot.send_message.await_args
    assert args == (42, texts.CONVERSATION_TIMEOUT)
    assert isinstance(kwargs["reply_markup"], ReplyKeyboardRemove)
