import os
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler
from telegram.ext.filters import TEXT

from src.tg_bot import start_callback, button, help_command, handle_text, email_command

def main():
    load_dotenv(".env")

    app = ApplicationBuilder().token(os.getenv("TOKEN")).build()
    
    app.add_handler(CommandHandler("start", start_callback))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(TEXT, handle_text))

    app.run_polling()

if __name__ == "__main__":
    main()
