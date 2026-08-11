from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
)
from telegram.ext.filters import TEXT

from settings import settings
from src.tg_bot import (
    button,
    email_command,
    handle_text,
    help_command,
    start_callback,
)


def main():
    app = (
        ApplicationBuilder()
        .token(settings.token.get_secret_value())
        .build()
    )

    app.add_handler(
        CommandHandler("start", start_callback)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    app.add_handler(
        CommandHandler("email", email_command)
    )

    app.add_handler(
        CallbackQueryHandler(button)
    )

    app.add_handler(
        MessageHandler(TEXT, handle_text)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
