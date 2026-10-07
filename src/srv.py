from telegram import Update

from src.bot.app import build_application
from src.custom_logging import setup_logging


def main() -> None:
    setup_logging()

    app = build_application()
    app.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])


if __name__ == "__main__":
    main()
