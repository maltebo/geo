"""The /suche conversation: choose radius or N nearest, then a location."""

from __future__ import annotations

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from pressmuenzen.bot import keyboards, texts
from pressmuenzen.bot.handlers.common import hosted_map_url, result_list_html
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import Coordinate
from pressmuenzen.logging import get_logger
from pressmuenzen.scraper.geocoding import Geocoder
from pressmuenzen.services.search import SearchService

log = get_logger("bot.search")

CHOOSE_MODE, ENTER_VALUE, ENTER_LOCATION = range(3)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(texts.SUCHE_START, reply_markup=keyboards.radius_or_count())
    return CHOOSE_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    if choice == keyboards.RADIUS_LABEL:
        context.user_data["mode"] = "radius"
        await update.message.reply_text(texts.ENTER_RADIUS, reply_markup=ReplyKeyboardRemove())
    elif choice == keyboards.COUNT_LABEL:
        context.user_data["mode"] = "nearest"
        await update.message.reply_text(texts.ENTER_COUNT, reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(texts.INVALID_OPTION, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    return ENTER_VALUE


async def enter_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if context.user_data["mode"] == "radius":
            context.user_data["value"] = float(update.message.text.replace(",", "."))
        else:
            context.user_data["value"] = int(update.message.text)
    except (ValueError, KeyError):
        await update.message.reply_text(texts.GENERIC_ERROR)
        return ConversationHandler.END
    await update.message.reply_text(texts.ENTER_LOCATION)
    return ENTER_LOCATION


async def on_location_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    origin = Coordinate(lat=loc.latitude, lon=loc.longitude)
    await _reply_with_results(update, context, origin, origin_label=None)
    return ConversationHandler.END


async def on_location_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.message.text
    await update.message.reply_text(texts.TRYING_ADDRESS)
    async with session_scope() as session:
        coord = await Geocoder(session).geocode(query)
    if coord is None:
        await update.message.reply_text(texts.ADDRESS_NOT_FOUND.format(query=query))
        return ConversationHandler.END
    await _reply_with_results(update, context, coord, origin_label=query)
    return ConversationHandler.END


async def _reply_with_results(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    origin: Coordinate,
    origin_label: str | None,
) -> None:
    mode = context.user_data.get("mode", "nearest")
    value = context.user_data.get("value", 5)

    async with session_scope() as session:
        service = SearchService(MachineRepository(session))
        if mode == "radius":
            hits = await service.within_radius(origin, float(value))
        else:
            hits = await service.nearest(origin, int(value))

    if not hits:
        await update.message.reply_text(texts.NO_MACHINE_FOUND)
        return

    url = hosted_map_url(origin, mode, float(value))
    await update.message.reply_text(texts.MAP_READY.format(url=url))
    await update.message.reply_html(result_list_html(hits, origin_label))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(texts.BYE, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
