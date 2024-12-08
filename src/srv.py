import os

from dotenv import dotenv_values

from src.tg_bot import get_updater


def main():
    if os.path.exists(".env"):
        settings = dotenv_values(".env")
    else:
        exit(404)

    updater = get_updater(settings["TOKEN"])
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
