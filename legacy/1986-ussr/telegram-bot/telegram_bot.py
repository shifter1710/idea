from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import load_settings
from app.database import connect, initialize_database, seed_placeholder_events
from app.repository import AthleticsRepository
from app.scoring import ScoringService


LOGGER = logging.getLogger(__name__)
SELECTED_EVENT_KEY = "selected_event_id"


def _build_service() -> ScoringService:
    settings = load_settings()
    connection = connect(settings.database_path)
    initialize_database(connection)
    seed_placeholder_events(connection)
    repository = AthleticsRepository(connection)
    return ScoringService(repository)


def _build_events_keyboard(service: ScoringService) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(event.name, callback_data=f"event:{event.id}")]
        for event in service.list_events()
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service: ScoringService = context.application.bot_data["service"]
    context.user_data.pop(SELECTED_EVENT_KEY, None)
    await update.effective_message.reply_text(
        "Выберите дистанцию:",
        reply_markup=_build_events_keyboard(service),
    )


async def choose_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    _, raw_event_id = query.data.split(":", 1)
    event_id = int(raw_event_id)

    service: ScoringService = context.application.bot_data["service"]
    event = service.repository.get_event(event_id)
    if event is None:
        await query.edit_message_text("Дисциплина не найдена. Нажмите /start и попробуйте снова.")
        return

    context.user_data[SELECTED_EVENT_KEY] = event_id
    await query.edit_message_text(
        f"Дисциплина: {event.name}\n"
        "Теперь отправьте результат числом.\n"
        "Примеры: `10.43`, `52.1`, `245.7`",
        parse_mode="Markdown",
    )


async def handle_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    event_id = context.user_data.get(SELECTED_EVENT_KEY)
    if event_id is None:
        await update.message.reply_text("Сначала выберите дистанцию через /start.")
        return

    raw_result = update.message.text
    service: ScoringService = context.application.bot_data["service"]

    try:
        event, result_key, points = service.calculate_points(event_id, raw_result)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    except LookupError as exc:
        await update.message.reply_text(
            f"{exc}\n"
            f"Дисциплина: {service.repository.get_event(event_id).name}\n"
            f"Результат: {raw_result.strip()}"
        )
        return

    context.user_data.pop(SELECTED_EVENT_KEY, None)
    await update.message.reply_text(
        f"Дисциплина: {event.name}\n"
        f"Результат: {result_key}\n"
        f"Очки: {points}\n\n"
        "Для нового расчета нажмите /start."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Команды:\n"
        "/start - выбрать дисциплину\n"
        "/help - показать справку"
    )


def run() -> None:
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        level=logging.INFO,
    )

    settings = load_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан. Создайте файл .env на основе .env.example.")

    service = _build_service()
    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["service"] = service

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(choose_event, pattern=r"^event:\d+$"))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_result)
    )

    LOGGER.info("Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
