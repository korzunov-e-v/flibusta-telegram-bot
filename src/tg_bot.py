import asyncio
import os
import smtplib
from email.message import EmailMessage

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import CallbackContext
from pydantic import ValidationError

from src import flib
from src.custom_logging import get_logger
from src.database.crud import get_email, set_email
from src.settings import settings
from src.schemas import EmailData


logger = get_logger(__name__)

def send_email(
    file_content,
    filename,
    to_email,
):
    msg = EmailMessage()

    msg["Subject"] = f"Книга: {filename}"
    msg["From"] = settings.smtp_user
    msg["To"] = to_email

    msg.set_content(
        "Приятного чтения! Файл с книгой прикреплен к этому письму."
    )

    msg.add_attachment(
        file_content,
        maintype="application",
        subtype="octet-stream",
        filename=filename,
    )

    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
    ) as server:
        server.starttls()

        server.login(
            settings.smtp_user,
            settings.smtp_pass.get_secret_value(),
        )

        server.send_message(msg)


def build_book_keyboard(
    book_id,
    formats,
    mode="chat",
):
    annotation_row = [
        InlineKeyboardButton(
            "📝 Читать аннотацию",
            callback_data=f"show_annotation {book_id}",
        )
    ]

    if mode == "chat":
        icon = "⬇️"
        switch_text = "Отправить на почту 📩"
        switch_mode_val = "email"
    else:
        icon = "📩"
        switch_text = "Прислать в чат ⬇️"
        switch_mode_val = "chat"

    formats_row = []

    for book_format in formats:
        text = f"{icon} .{book_format}"

        callback_data = (
            f"get_book {mode} {book_id} {book_format}"
        )

        formats_row.append(
            InlineKeyboardButton(
                text,
                callback_data=callback_data,
            )
        )

    switcher_row = [
        InlineKeyboardButton(
            switch_text,
            callback_data=(
                f"switch_mode "
                f"{switch_mode_val} "
                f"{book_id}"
            ),
        )
    ]

    return InlineKeyboardMarkup(
        [
            annotation_row,
            formats_row,
            switcher_row,
        ]
    )


async def start_callback(
    update: Update,
    _: CallbackContext,
):
    await update.message.reply_text(
        "Введите название книги (без автора) "
        "ИЛИ добавьте фамилию автора на новой строке.\n\n"
        "Пример:\n"
        "1984\n"
        "Оруэлл\n\n"
        "Также вы можете задать почту для отправки "
        "книг командой /email"
    )


async def help_command(
    update: Update,
    _: CallbackContext,
) -> None:
    await update.message.reply_text(
        "Нажмите /start чтобы начать"
    )


async def email_command(
    update: Update,
    context: CallbackContext,
) -> None:
    args = context.args

    if not args:
        current = await get_email(
            update.effective_user.id
        )

        if current:
            await update.message.reply_text(
                f"Ваш текущий email: {current}\n"
                "Чтобы изменить его, напишите: "
                "/email ваш@адрес.com"
            )
        else:
            await update.message.reply_text(
                "У вас не задан email. "
                "Напишите: /email ваш@адрес.com"
            )

        return

    new_email = args[0]

    try:
        email_data = EmailData(email=new_email)
    except ValidationError:
        await update.message.reply_text(
            "❌ Неверный формат email."
        )
        return

    await set_email(
        update.effective_user.id,
        str(email_data.email),
    )

    await update.message.reply_text(
        f"✅ Email успешно изменён на {email_data.email}"
    )


async def handle_text(
    update: Update,
    context: CallbackContext,
) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    pending_request = context.user_data.get(
        "pending_email_request"
    )

    if pending_request:
        try:
            email_data = EmailData(email=text)
        except ValidationError:
            await update.message.reply_text(
                "❌ Неверный формат email.\n"
                "Попробуйте ещё раз:"
            )
            return

        await set_email(
            user_id,
            str(email_data.email),
        )

        context.user_data.pop(
            "pending_email_request",
            None,
        )

        await update.message.reply_text(
            "✅ Email успешно сохранён!\n"
            "Если захотите заменить его в будущем, "
            "воспользуйтесь командой /email."
        )

        mes = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Продолжаю отправку книги...",
        )

        await download_and_send(
            "email",
            pending_request["book_id"],
            pending_request["format"],
            update,
            context,
            mes,
        )

        return

    await find_the_book(
        update,
        context,
    )

async def find_the_book(
    update: Update,
    context: CallbackContext,
) -> None:
    lines = update.message.text.split("\n")

    if len(lines) == 2:
        log_author = lines[1]
    else:
        log_author = None

    logger.info(
        msg="find the book",
        extra={
            "command": "find_the_book",
            "user_id": update.effective_user.id,
            "book_name": lines[0],
            "author": log_author,
        },
    )

    search_string = update.message.text

    mes = await update.message.reply_text(
        "Подождите, идёт поиск..."
    )

    err_author = False

    try:
        libr = []

        if "\n" in search_string:
            title, author = search_string.split(
                "\n",
                maxsplit=1,
            )

            if len(author.split(" ")) > 1:
                err_author = True

            scr_lib = await flib.scrape_books_mbl(
                title,
                author,
            )

            if scr_lib:
                libr += scr_lib

        else:
            libr_t = await flib.scrape_books_by_title(
                search_string
            )

            libr_a = await flib.scrape_books_by_author(
                search_string
            )

            if libr_t:
                libr += libr_t

            if libr_a:
                libr += [
                    book
                    for nested_list in libr_a
                    for book in nested_list
                ]

        if search_string.isdigit():
            book_by_id = await flib.get_book_by_id(
                search_string
            )

            if book_by_id:
                libr.append(book_by_id)

    except httpx.HTTPError as e:
        await context.bot.delete_message(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
        )

        await update.message.reply_text(
            "Произошла ошибка на сервере."
        )

        logger.error(
            "Flibusta request failed",
            extra={
                "exception_type": type(e).__name__,
                "exception": repr(e),
                "url": str(e.request.url) if e.request else None,
            },
        )

        return

    if not libr:
        await context.bot.delete_message(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
        )

        await update.message.reply_text(
            "К сожалению, ничего не найдено =("
        )

        if err_author:
            await update.message.reply_text(
                "Вероятно вместо фамилии автора "
                "на второй строке было указано что-то ещё"
            )

    else:
        kbs = []
        kb = []

        for i in range(len(libr)):
            book = libr[i]

            text = f"{book.title} - {book.author}"

            kb.append(
                [
                    InlineKeyboardButton(
                        text,
                        callback_data=(
                            "find_book_by_id "
                            + book.id
                        ),
                    )
                ]
            )

            if len(kb) == 49:
                kbs.append(kb.copy())
                kb = []

        if kb:
            kbs.append(kb)

        await context.bot.delete_message(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
        )

        for keyboard in kbs:
            await update.message.reply_text(
                "Выберите книгу:",
                reply_markup=InlineKeyboardMarkup(
                    keyboard
                ),
            )


async def button(
    update: Update,
    context: CallbackContext,
) -> None:
    query = update.callback_query

    await query.answer()

    command, arg = query.data.split(
        " ",
        maxsplit=1,
    )

    if command == "find_book_by_id":
        await find_book_by_id(
            book_id=arg,
            update=update,
            context=context,
        )

    elif command == "switch_mode":
        new_mode, book_id = arg.split(" ")

        book = await flib.get_book_by_id(
            book_id
        )

        if book:
            await query.edit_message_reply_markup(
                reply_markup=build_book_keyboard(
                    book.id,
                    book.formats,
                    mode=new_mode,
                )
            )

    elif command == "get_book":
        await process_book_request(
            arg,
            update,
            context,
        )

    elif command == "show_annotation":
        await show_annotation(
            arg,
            update,
            context,
        )


async def find_book_by_id(
    book_id,
    update: Update,
    context: CallbackContext,
):
    logger.info(
        msg="find the book",
        extra={
            "command": "find_book_by_id",
            "user_id": update.effective_user.id,
        },
    )

    mes = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Подождите, идёт загрузка...",
    )

    book = await flib.get_book_by_id(
        book_id
    )

    if not book:
        await context.bot.delete_message(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
        )

        await update.message.reply_text(
            "Книга не найдена."
        )

        return

    safe_title = (
        book.title
        .replace("<", "<")
        .replace(">", ">")
    )

    safe_author = (
        book.author
        .replace("<", "<")
        .replace(">", ">")
    )

    capt = (
        "📖 {title}\n"
        "🗣 {author}\n"
        "⚖️ {size}\n"
        "🌐 Страница книги {url}"
    ).format(
        author=safe_author,
        title=safe_title,
        url=book.link,
        size=book.size,
    )

    reply_markup = build_book_keyboard(
        book.id,
        book.formats,
        mode="chat",
    )

    if book.cover:
        await flib.download_book_cover(book)

        c_full_path = os.path.join(
            os.getcwd(),
            "books",
            book_id,
            "cover.jpg",
        )

        with open(
            c_full_path,
            "rb",
        ) as cover:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=cover,
                caption=capt,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="[обложки нет]\n\n" + capt,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    await context.bot.delete_message(
        chat_id=mes.chat_id,
        message_id=mes.message_id,
    )


async def show_annotation(
    book_id,
    update: Update,
    context: CallbackContext,
):
    mes = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Загружаю аннотацию...",
    )

    book = await flib.get_book_by_id(
        book_id
    )

    if not book:
        await context.bot.edit_message_text(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
            text="Книга не найдена.",
        )
        return

    annotation = getattr(
        book,
        "annotation",
        "",
    ).strip()

    if not annotation:
        await context.bot.edit_message_text(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
            text=(
                "К сожалению, для этой книги "
                "нет аннотации на сайте."
            ),
        )
        return

    safe_title = (
        book.title
        .replace("<", "<")
        .replace(">", ">")
    )

    safe_annotation = (
        annotation
        .replace("<", "<")
        .replace(">", ">")
    )

    text = (
        f"📖 {safe_title}\n\n"
        f"{safe_annotation}"
    )

    if len(text) > 4000:
        text = text[:4000] + "..."

    await context.bot.edit_message_text(
        chat_id=mes.chat_id,
        message_id=mes.message_id,
        text=text,
        parse_mode="HTML",
    )


async def process_book_request(
    arg: str,
    update: Update,
    context: CallbackContext,
):
    mode, book_id, book_format = arg.split(" ")

    user_id = update.effective_user.id

    if mode == "email":
        email = await get_email(user_id)

        if not email:
            context.user_data["pending_email_request"] = {
                "book_id": book_id,
                "format": book_format,
            }

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    "У вас не задан E-mail.\n"
                    "Пожалуйста, отправьте адрес "
                    "вашей электронной почты "
                    "ответным сообщением:"
                ),
            )

            return

    mes = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Подождите, идёт скачивание...",
    )

    await download_and_send(
        mode,
        book_id,
        book_format,
        update,
        context,
        mes,
    )


async def download_and_send(
    mode,
    book_id,
    book_format,
    update: Update,
    context: CallbackContext,
    mes,
):
    book = await flib.get_book_by_id(
        book_id
    )

    if not book:
        await context.bot.delete_message(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Книга не найдена.",
        )

        return

    result = await flib.download_book(
        book,
        book_format,
    )

    if not result:
        await context.bot.delete_message(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "Произошла ошибка "
                "при скачивании файла."
            ),
        )

        return

    b_content, b_filename = result

    if mode == "chat":
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=b_content,
            filename=b_filename,
        )

        await context.bot.delete_message(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
        )

    elif mode == "email":
        email = await get_email(
            update.effective_user.id
        )

        await context.bot.edit_message_text(
            chat_id=mes.chat_id,
            message_id=mes.message_id,
            text=f"Отправляю книгу на {email}...",
        )

        try:
            await asyncio.to_thread(
                send_email,
                b_content,
                b_filename,
                email,
            )

            await context.bot.delete_message(
                chat_id=mes.chat_id,
                message_id=mes.message_id,
            )

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    f"✅ Книга {b_filename} "
                    f"успешно отправлена на {email}!\n\n"
                    "Не забудьте проверить папку «Спам», "
                    "если письма долго нет во входящих."
                ),
                parse_mode="HTML",
            )

        except Exception as e:
            logger.error(
                f"Email send error: {e}"
            )

            await context.bot.edit_message_text(
                chat_id=mes.chat_id,
                message_id=mes.message_id,
                text=(
                    "❌ Ошибка отправки. "
                    "Попробуйте ещё раз позже."
                ),
            )
