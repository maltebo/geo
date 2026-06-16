"""Reply keyboards for the bot conversations."""

from __future__ import annotations

from telegram import ReplyKeyboardMarkup

RADIUS_LABEL = "Radius (km)"
COUNT_LABEL = "Anzahl Punkte"


def radius_or_count() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[RADIUS_LABEL, COUNT_LABEL]],
        one_time_keyboard=True,
        resize_keyboard=True,
        input_field_placeholder="Radius oder Automatenanzahl?",
    )
