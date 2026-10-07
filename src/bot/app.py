from pathlib import Path

from telegram import BotCommand
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PersistenceInput,
    PicklePersistence,
    filters,
)

from src import flib
from src.bot import texts
from src.bot.buttons import button
from src.bot.commands import (
    cancel_command,
    email_command,
    help_command,
    start_command,
    unknown_command,
)
from src.bot.errors import error_handler
from src.bot.messages import handle_text
from src.custom_logging import get_logger
from src.database.session import engine
from src.settings import settings

logger = get_logger(__name__)

PERSISTENCE_FILE = "bot_state.pickle"
PERSISTENCE_UPDATE_INTERVAL = 30

# только новые сообщения: правки (edited_message) и посты каналов не обрабатываем
NEW_MESSAGE = filters.UpdateType.MESSAGE


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [BotCommand(command, description) for command, description in texts.COMMANDS]
    )


async def post_shutdown(_: Application) -> None:
    await flib.close_client()
    await engine.dispose()


def build_persistence() -> PicklePersistence | None:
    data_dir = Path(settings.data_dir)

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        # проверяем запись заранее: иначе ошибка всплывёт только при первом сбросе на диск
        probe = data_dir / ".write_test"
        probe.touch()
        probe.unlink()
    except OSError:
        logger.exception(
            "Data directory is not writable, running without persistence",
            extra={"data_dir": str(data_dir)},
        )
        return None

    return PicklePersistence(
        filepath=data_dir / PERSISTENCE_FILE,
        store_data=PersistenceInput(
            bot_data=False,
            chat_data=False,
            user_data=True,
            callback_data=False,
        ),
        update_interval=PERSISTENCE_UPDATE_INTERVAL,
    )


def build_application() -> Application:
    builder = (
        ApplicationBuilder()
        .token(settings.token.get_secret_value())
        .concurrent_updates(True)
        .rate_limiter(AIORateLimiter(max_retries=2))
        .media_write_timeout(120)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
    )

    persistence = build_persistence()

    if persistence is not None:
        builder = builder.persistence(persistence)

    app = builder.build()

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start_command, filters=NEW_MESSAGE))
    app.add_handler(CommandHandler("help", help_command, filters=NEW_MESSAGE))
    app.add_handler(CommandHandler("email", email_command, filters=NEW_MESSAGE))
    app.add_handler(CommandHandler("cancel", cancel_command, filters=NEW_MESSAGE))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(NEW_MESSAGE & filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(NEW_MESSAGE & filters.TEXT & ~filters.COMMAND, handle_text))

    return app
