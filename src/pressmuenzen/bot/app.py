"""python-telegram-bot Application wiring (long polling)."""

from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from pressmuenzen.bot.handlers import admin, corrections, details, search, visited, watches
from pressmuenzen.config import get_settings
from pressmuenzen.logging import configure_logging, get_logger

log = get_logger("bot")


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("unhandled bot error", exc_info=context.error)


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN is not set")

    app = ApplicationBuilder().token(settings.telegram_token).build()

    # Simple commands.
    app.add_handler(CommandHandler("start", details.start))
    app.add_handler(CommandHandler("whoami", details.whoami))
    app.add_handler(CommandHandler("alle_zeigen", details.show_all))
    app.add_handler(CommandHandler("details", details.details))
    app.add_handler(CommandHandler("besucht", visited.mark_visited))
    app.add_handler(CommandHandler("nicht_besucht", visited.unmark_visited))

    # Watches / notifications.
    app.add_handler(CommandHandler("beobachten", watches.add_watch))
    app.add_handler(CommandHandler("beobachtungen", watches.list_watches))
    app.add_handler(CommandHandler("beobachtung_loeschen", watches.remove_watch))
    app.add_handler(CommandHandler("stumm", watches.toggle_mute))

    # Admin moderation.
    app.add_handler(CommandHandler("queue", admin.queue))
    app.add_handler(CommandHandler("ok", admin.approve))
    app.add_handler(CommandHandler("nope", admin.reject))

    # /suche conversation.
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("suche", search.start)],
            states={
                search.CHOOSE_MODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, search.choose_mode)
                ],
                search.ENTER_VALUE: [MessageHandler(filters.Regex(r"^\d"), search.enter_value)],
                search.ENTER_LOCATION: [
                    MessageHandler(filters.LOCATION, search.on_location_pin),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, search.on_location_text),
                ],
            },
            fallbacks=[CommandHandler("cancel", search.cancel)],
        )
    )

    # /heimat conversation.
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("heimat", watches.home_start)],
            states={
                watches.HOME_WAIT: [
                    MessageHandler(filters.LOCATION, watches.home_set_from_pin),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, watches.home_set_from_text),
                ],
            },
            fallbacks=[CommandHandler("cancel", search.cancel)],
        )
    )

    # /melden conversation.
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("melden", corrections.report_start)],
            states={
                corrections.REPORT_WAIT: [
                    MessageHandler(filters.LOCATION, corrections.report_pin),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, corrections.report_text),
                ],
            },
            fallbacks=[CommandHandler("cancel", search.cancel)],
        )
    )

    app.add_error_handler(_on_error)
    return app


def run_bot() -> None:
    configure_logging()
    app = build_application()
    log.info("bot starting (long polling)")
    # bootstrap_retries=-1: keep retrying the initial Telegram handshake on
    # transient network errors instead of dying on the first blip (the default
    # of 0 aborts immediately). A genuinely bad token still fails fast (401).
    app.run_polling(allowed_updates=Update.ALL_TYPES, bootstrap_retries=-1)
