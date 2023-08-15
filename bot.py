import os
import io

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
    ApplicationBuilder
)

import logging

import data.telegram_constants as c
import private.private_constants as pc

import show_map

import functions as f

import handle_userdata as user_data

# Actions that can be taken
START = "start"
SUCHE = "suche"
DETAILS = "details"
GET_ALL = "get_all"


def join(link):
    return os.path.join(pc.ABS_PATH, link)


# Enable logging

os.makedirs(join("private"), exist_ok=True)
logging.basicConfig(
    filename=join("private/geobot.log"), encoding="utf-8",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

NUM_POINTS_RADIUS, STANDORT, REPLY, CALCULATE_REPLY = range(4)


async def start(update: Update, context):
    logger.info("ENTERED START")

    await context.bot.send_message(chat_id=update.effective_chat.id, text=c.START_TEXT)

    user_data.add_action(update.effective_chat.id, START, True)


async def start_suche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("ENTERED START SUCHE")

    reply_keyboard = [["Radius (km)", "Anzahl Punkte"]]
    await update.message.reply_text(
        c.SUCHE_START_TEXT,
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Radius oder Automatenanzahl?"
        ),

    )

    return NUM_POINTS_RADIUS


async def get_points_or_radius(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("ENTERED GET POINTS OR RADIUS")

    ReplyKeyboardRemove()

    choice = update.message.text

    if choice == "Radius (km)":
        context.user_data["choice"] = 0
        await update.message.reply_text(c.ENTER_INT_TEXT_RADIUS)
    elif choice == "Anzahl Punkte":
        context.user_data["choice"] = 1
        await update.message.reply_text(c.ENTER_INT_TEXT_ANZAHL)
    else:
        await update.message.reply_text(
            f"{choice} war keine gültige Option. Bitte starte erneut und verwende die bereitgestellte Inline-Tastatur.")
        user_data.add_action(update.effective_chat.id, SUCHE, False)
        return ConversationHandler.END

    return STANDORT


async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("ENTERED LOCATION")

    try:
        if context.user_data["choice"] == 0:
            radius = float(update.message.text)
            context.user_data["number"] = radius
        elif context.user_data["choice"] == 1:
            number = int(update.message.text)
            context.user_data["number"] = number

    except:
        import traceback
        traceback.print_exc()
        await update.message.reply_text("Da ist etwas schiefgegangen ...")
        user_data.add_action(update.effective_chat.id, SUCHE, False)
        return ConversationHandler.END

    await update.message.reply_text(c.STANDORT_TEXT)

    return REPLY


async def calculate_reply_location_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("ENTERED REAL LOCATION")

    lat, lon = update.message.location.latitude, update.message.location.longitude

    try:
        loc = f.gc.geocode([lat, lon])
    except:
        import traceback
        traceback.print_exc()
        await update.message.reply_text(f"Da ist leider ein Fehler aufgetreten, der Ort konnte nicht gefunden werden.")
        user_data.add_action(update.effective_chat.id, SUCHE, False)
        return ConversationHandler.END

    context.user_data["location"] = loc
    await calculate_reply(update, context)

    return ConversationHandler.END
    # return calculate_reply(update, context, None)


async def calculate_reply_string_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("ENTERED STRING DATA")

    await update.message.reply_text("Okay, ich versuche, ob ich diese Adresse kenne!")

    loc_text = update.message.text

    loc = f.gc.geocode(loc_text)
    if not loc:
        await update.message.reply_text(
            f"Da ist leider ein Fehler aufgetreten. Dieser Ort ({loc_text}) wird nicht gefunden!")
        user_data.add_action(update.effective_chat.id, SUCHE, False)
        return ConversationHandler.END

    context.user_data["location"] = loc

    await calculate_reply(update, context)

    return ConversationHandler.END


async def calculate_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("ENTERED REPLY")

    if context.user_data["choice"] == 1:
        closest = f.find_closest_n_points(context.user_data["location"].point, context.user_data["number"])
    else:
        closest = f.find_closest_radius(context.user_data["location"].point, context.user_data["number"])

    if len(closest) < 1:
        await update.message.reply_text("Leider wurde kein Automat gefunden.")
        user_data.add_action(update.effective_chat.id, SUCHE, False)
        return ConversationHandler.END

    link, result_string = show_map.create_map(context.user_data["location"], closest)

    with open(link, 'rb') as fp:
        html_doc = fp.read()

    # Send the HTML document as a file and the result string as a message to the user
    await update.message.reply_document(document=io.BytesIO(html_doc),
                                        filename='overview.html')
    await update.message.reply_markdown(text=result_string)

    os.remove(link)

    user_data.add_action(update.effective_chat.id, SUCHE, True)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("ENTERED CANCEL")

    """Display the gathered info and end the conversation."""
    user_data = context.user_data

    await update.message.reply_text(
        f"Bye!",
        reply_markup=ReplyKeyboardRemove(),
    )
    user_data.clear()
    user_data.add_action(update.effective_chat.id, SUCHE, False)
    return ConversationHandler.END


async def show_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("ENTERED SHOW ALL")
    link, _ = show_map.create_map_all_locations()

    with open(link, 'rb') as fp:
        html_doc = fp.read()

    # Send the HTML document as a file and the result string as a message to the user
    await update.message.reply_document(document=io.BytesIO(html_doc),
                                        filename='overview.html')
    await update.message.reply_markdown(text="Hier ist die Karte mit allen Standorten!")

    os.remove(link)

    user_data.add_action(update.effective_chat.id, GET_ALL, True)

    return ConversationHandler.END


async def details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text(f"Da ist leider ein Fehler aufgetreten. "
                                        f"Bitte benutze diese Funktion folgendermaßen:\n/details <id>\n"
                                        f"Also zum Beispiel '/details 1894'")
        user_data.add_action(update.effective_chat.id, DETAILS, False)
        return

    try:
        s = f.create_info_md(context.args[0])
        if not s:
            await update.message.reply_text(f"Die ID {context.args[0]} scheint nicht gefunden zu werden ...")
            user_data.add_action(update.effective_chat.id, DETAILS, False)
            return

        user_data.add_action(update.effective_chat.id, DETAILS, True)
        await update.message.reply_markdown(s)

    except:
        import traceback
        traceback.print_exc()
        await update.message.reply_text(f"Da ist leider ein Fehler aufgetreten. "
                                        f"Bitte benutze diese Funktion folgendermaßen:\n/details <id>\n")
        user_data.add_action(update.effective_chat.id, DETAILS, False)
        return


if __name__ == '__main__':
    application = ApplicationBuilder().token(pc.TOKEN).build()

    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    full_map_handler = CommandHandler('alle_zeigen', show_all)
    application.add_handler(full_map_handler)

    details_handler = CommandHandler('details', details)
    application.add_handler(details_handler)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('suche', start_suche)],
        states={
            NUM_POINTS_RADIUS: [
                MessageHandler(
                    filters.Regex("^(Radius \(km\)|Anzahl Punkte)$"), get_points_or_radius
                )
            ],
            STANDORT: [
                MessageHandler(
                    filters.Regex("^\d+"), get_location
                )
            ],
            REPLY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, calculate_reply_string_data
                ),
                MessageHandler(
                    filters.LOCATION, calculate_reply_location_data
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(conv_handler)

    application.run_polling()
