from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
)
from telegram.ext.filters import TEXT

from src.settings import settings
from src.tg_bot import (
    button,
    email_command,
    handle_text,
    help_command,
    start_callback,
)
from src.custom_logging import get_logger

logger = get_logger(__name__)


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    error = context.error

    logger.error(
        "Unhandled telegram error",
        extra={
            "exception_type": type(error).__name__,
            "exception": repr(error),
        },
        exc_info=(
            type(error),
            error,
            error.__traceback__,
        ),
    )


def main():
    app = (
        ApplicationBuilder()
        .token(settings.token.get_secret_value())
        .build()
    )

    app.add_error_handler(error_handler)

    app.add_handler(
        CommandHandler(
            "start",
            start_callback,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "email",
            email_command,
        )
    )

    app.add_handler(
        CallbackQueryHandler(button)
    )

    app.add_handler(
        MessageHandler(
            TEXT,
            handle_text,
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
