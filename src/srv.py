import os

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler
from telegram.ext.filters import TEXT

from src.tg_bot import start_callback, button, help_command, find_the_book


def main():
    load_dotenv(".env")

    app = ApplicationBuilder().token(os.getenv("TOKEN")).build()
    app.add_handler(CommandHandler("start", start_callback))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(TEXT, find_the_book))

    app.run_polling()


if __name__ == "__main__":
    main()
