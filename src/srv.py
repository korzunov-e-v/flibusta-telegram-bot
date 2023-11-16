import os

from dotenv import dotenv_values

from src.tg_bot import get_updater


def main() -> None:
    """Run the bot."""
    if os.path.exists(".env"):
        settings = dotenv_values(".env")
    else:
        exit(404)

    # Create the Updater and pass it your bot`s token.
    updater = get_updater(settings["TOKEN"])

    # Start the Bot
    updater.start_polling()

    # Run the bot until the user presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT
    updater.idle()


if __name__ == "__main__":
    main()
