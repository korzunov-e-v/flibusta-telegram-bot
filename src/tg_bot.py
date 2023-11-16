import logging
from urllib.error import HTTPError

import flib
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler
from telegram.ext import CallbackQueryHandler, CallbackContext

from telegram.ext import MessageHandler, Filters

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    encoding="utf-8",
    level=logging.INFO,
)

logger_search = logging.getLogger("search_history")
handler = logging.FileHandler(filename="search_log.log", encoding="utf-8")
handler.setLevel(logging.INFO)
handler.setFormatter(formatter)
logger_search.addHandler(handler)


def start_callback(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Введите название книги (без автора) ИЛИ добавьте фамилию автора на "
        "новой строке. \n\nПример:\n\n1984\nОруэлл"
    )


def find_the_book(update: Update, context: CallbackContext) -> None:
    log_command = "find_the_book".ljust(20)
    log_user_id = update.effective_user.id
    log_user_name = update.effective_user.name
    log_user_full_name = update.effective_user.full_name
    log_search_string = update.message.text.replace("\n", " - ")
    logger_search.info(
        f"{log_command}  {log_user_id} {log_user_name} "
        f"({log_user_full_name}) - {log_search_string}"
    )

    search_string = update.message.text
    mes = update.message.reply_text("Подождите, идёт поиск...")

    try:
        if "\n" in search_string:
            title, author = search_string.split("\n", maxsplit=1)
            libr = flib.scrape_books_mbl(title, author)
        else:
            libr = flib.scrape_books(search_string)
    except (AttributeError, HTTPError) as e:
        context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)
        update.message.reply_text("Произошла ошибка на сервере.")
        logger_search.error("Access error")
        return

    if libr is None:
        context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)
        update.message.reply_text("К сожалению, ничего не найдено =(")
    else:
        kb = []
        for i in range(len(libr)):
            book = libr[i]
            text = f"{book.title} - {book.author}"
            callback_data = "find_book_by_id " + book.id
            kb.append([InlineKeyboardButton(text, callback_data=callback_data)])

        reply_markup = InlineKeyboardMarkup(kb)

        update.message.reply_text("Выберите книгу:", reply_markup=reply_markup)
        context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)


def button(update: Update, context: CallbackContext) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query

    # CallbackQueries need to be answered, even if no notification to the user
    # is needed
    # Some clients may have trouble otherwise.
    # See https://core.telegram.org/bots/api#callbackquery
    query.answer()

    command, arg = query.data.split(" ", maxsplit=1)
    if command == "find_book_by_id":
        find_book_by_id(book_id=arg, update=update, context=context)
    if command == "get_book_by_format":
        get_book_by_format(data=arg, update=update, context=context)


def find_book_by_id(book_id, update: Update, context: CallbackContext):

    log_command = "find_book_by_id".ljust(20)
    log_user_id = update.effective_user.id
    log_user_name = update.effective_user.name
    log_user_full_name = update.effective_user.full_name
    log_search_string = book_id
    logger_search.info(
        f"{log_command}  {log_user_id} {log_user_name} "
        f"({log_user_full_name}) - {log_search_string}"
    )

    mes = context.bot.send_message(
        chat_id=update.effective_chat.id, text="Подождите, идёт загрузка..."
    )
    book = flib.get_book_by_id(book_id)
    capt = "\U0001F4D6 {title}\n\U0001F5E3 {author}".format(
        author=book.author, title=book.title
    )

    kb = []
    for b_format in book.formats:
        text = b_format
        callback_data = f"get_book_by_format {book.id}+{b_format}"
        kb.append([InlineKeyboardButton(text, callback_data=callback_data)])
    reply_markup = InlineKeyboardMarkup(kb)

    if book.cover:
        flib.download_book_cover(book)
        c_full_path = os.path.join(os.getcwd(), "books", book_id, "cover.jpg")
        cover = open(os.path.join(c_full_path), "rb")
        context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=cover,
            caption=capt,
            reply_markup=reply_markup,
        )
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="[обложки нет]\n\n" + capt,
            reply_markup=reply_markup,
        )
    context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)


def get_book_by_format(data: str, update: Update, context: CallbackContext):

    log_command = "get_book_by_format".ljust(20)
    log_user_id = update.effective_user.id
    log_user_name = update.effective_user.name
    log_user_full_name = update.effective_user.full_name
    logger_search.info(
        f"{log_command}  {log_user_id} {log_user_name} "
        f"({log_user_full_name}) - {data}"
    )

    mes = context.bot.send_message(
        chat_id=update.effective_chat.id, text="Подождите, идёт скачивание..."
    )

    book_id, book_format = data.split("+")
    book = flib.get_book_by_id(book_id)

    b_full_path = flib.download_book(book, book_format)

    if b_full_path:
        file = open(os.path.join(b_full_path), "rb")
        context.bot.send_document(
            chat_id=update.effective_chat.id, document=file)
        context.bot.deleteMessage(
            chat_id=mes.chat_id, message_id=mes.message_id)
    else:
        logger_search.info(
            f"{log_command}  {log_user_id} {log_user_name} "
            f"({log_user_full_name}) - {data} - download error"
        )
        context.bot.deleteMessage(
            chat_id=mes.chat_id, message_id=mes.message_id)
        mes = context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Произошла ошибка на сервере."
        )


def help_command(update: Update, context: CallbackContext) -> None:
    """Displays info on how to use the bot."""
    update.message.reply_text("Нажмите /start чтобы начать")


def get_updater(token: str) -> Updater:
    updater = Updater(token)
    updater.dispatcher.add_handler(CommandHandler("start", start_callback))
    updater.dispatcher.add_handler(CallbackQueryHandler(button))
    updater.dispatcher.add_handler(CommandHandler("help", help_command))
    updater.dispatcher.add_handler(MessageHandler(Filters.text, find_the_book))
    return updater
