import os

from dotenv import dotenv_values
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler
from telegram.ext.filters import TEXT

from src.tg_bot import start_callback, button, help_command, find_the_book


def main():
    if os.path.exists(".env"):
        settings = dotenv_values(".env")
    else:
        exit(404)

    app = ApplicationBuilder().token(settings["TOKEN"]).build()
    app.add_handler(CommandHandler("start", start_callback))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(TEXT, find_the_book))

    app.run_polling()


if __name__ == "__main__":
    main()
