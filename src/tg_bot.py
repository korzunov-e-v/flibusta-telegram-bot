import os
import re
import smtplib
from email.message import EmailMessage
from urllib.error import HTTPError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

from src import flib
from src.custom_logging import get_logger
from src.database.crud import get_email, set_email
from src.settings import settings

logger = get_logger(__name__)


# --- SMTP ОТПРАВКА ---
def send_email(file_content, filename, to_email):
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


pending_email_requests = {}

# --- ИНТЕРФЕЙС И КНОПКИ ---
def build_book_keyboard(book_id, formats, mode="chat"):
    # Ряд 1: Кнопка аннотации
    annotation_row = [InlineKeyboardButton("📝 Читать аннотацию", callback_data=f"show_annotation {book_id}")]
    
    if mode == "chat":
        icon = "⬇️"
        switch_text = "Отправить на почту 📩"
        switch_mode_val = "email"
    else:
        icon = "📩"
        switch_text = "Прислать в чат ⬇️"
        switch_mode_val = "chat"

    # Ряд 2: Кнопки форматов в одну линию
    formats_row = []
    for b_format in formats:
        text = f"{icon} .{b_format}"
        callback_data = f"get_book {mode} {book_id} {b_format}"
        formats_row.append(InlineKeyboardButton(text, callback_data=callback_data))

    # Ряд 3: Кнопка переключения режима
    switcher_row = [InlineKeyboardButton(switch_text, callback_data=f"switch_mode {switch_mode_val} {book_id}")]

    return InlineKeyboardMarkup([annotation_row, formats_row, switcher_row])

# --- БАЗОВЫЕ КОМАНДЫ ---
async def start_callback(update: Update, _: CallbackContext):
    await update.message.reply_text(
        "Введите название книги (без автора) ИЛИ добавьте фамилию автора на новой строке. \n\n"
        "Пример:\n"
        "1984\n"
        "Оруэлл\n\n"
        "Также вы можете задать почту для отправки книг командой /email"
    )

async def help_command(update: Update, _: CallbackContext) -> None:
    await update.message.reply_text("Нажмите /start чтобы начать")

async def email_command(update: Update, context: CallbackContext) -> None:
    args = context.args
    if not args:
        current = await get_email(update.effective_user.id)
        if current:
            await update.message.reply_text(f"Ваш текущий email: {current}\nЧтобы изменить его, напишите: /email ваш@адрес.com")
        else:
            await update.message.reply_text("У вас не задан email. Напишите: /email ваш@адрес.com")
        return
        
    new_email = args[0]
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        await set_email(update.effective_user.id, new_email)
        await update.message.reply_text(f"✅ Email успешно изменён на {new_email}")
    else:
        await update.message.reply_text("❌ Неверный формат email.")

# --- ОБРАБОТЧИК ТЕКСТА ---
async def handle_text(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in pending_email_requests:
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text):
            await set_email(user_id, text)
            req = pending_email_requests.pop(user_id)
            await update.message.reply_text("✅ Email успешно сохранён!\nЕсли захотите заменить его в будущем, воспользуйтесь командой /email.")
            mes = await context.bot.send_message(chat_id=update.effective_chat.id, text="Продолжаю отправку книги...")
            await download_and_send("email", req["book_id"], req["format"], update, context, mes)
            return
        else:
            del pending_email_requests[user_id]

    await find_the_book(update, context)

# --- ЛОГИКА ПОИСКА И ОТПРАВКИ ---
async def find_the_book(update: Update, context: CallbackContext) -> None:
    if len(update.message.text.split('\n')) == 2:
        log_author = update.message.text.split('\n')[1]
    else:
        log_author = None
    logger.info(msg="find the book", extra={"command": "find_the_book", "user_id": update.effective_user.id, "book_name": update.message.text.split('\n')[0], "author": log_author})
    search_string = update.message.text
    mes = await update.message.reply_text("Подождите, идёт поиск...")
    err_author = False
    
    try:
        libr = []
        if "\n" in search_string:
            title, author = search_string.split("\n", maxsplit=1)
            if len(author.split(" ")) > 1:
                err_author = True
            scr_lib = flib.scrape_books_mbl(title, author)
            if scr_lib:
                libr += scr_lib
        else:
            libr_t = flib.scrape_books_by_title(search_string)
            libr_a = flib.scrape_books_by_author(search_string)
            if libr_t:
                libr += libr_t
            if libr_a:
                libr += [book for nested_list in libr_a for book in nested_list]
        if search_string.isdigit():
            book_by_id = flib.get_book_by_id(search_string)
            if book_by_id:
                libr.append(book_by_id)

    except (AttributeError, HTTPError) as e:
        await context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)
        await update.message.reply_text("Произошла ошибка на сервере.")
        logger.error(f"Access error {e}", extra={"exc": e})
        return

    if not libr:
        await context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)
        await update.message.reply_text("К сожалению, ничего не найдено =(")
        if err_author:
            await update.message.reply_text("Вероятно вместо фамилии автора на второй строке было указано что-то ещё")
    else:
        kbs, kb = [], []
        for i in range(len(libr)):
            book = libr[i]
            text = f"{book.title} - {book.author}"
            kb.append([InlineKeyboardButton(text, callback_data="find_book_by_id " + book.id)])
            if len(kb) == 49:
                kbs.append(kb.copy())
                kb = []
        if kb:
            kbs.append(kb)

        await context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)
        for kb in kbs:
            await update.message.reply_text("Выберите книгу:", reply_markup=InlineKeyboardMarkup(kb))

async def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    command, arg = query.data.split(" ", maxsplit=1)
    
    if command == "find_book_by_id":
        await find_book_by_id(book_id=arg, update=update, context=context)
    elif command == "switch_mode":
        new_mode, book_id = arg.split(" ")
        book = flib.get_book_by_id(book_id)
        await query.edit_message_reply_markup(reply_markup=build_book_keyboard(book.id, book.formats, mode=new_mode))
    elif command == "get_book":
        await process_book_request(arg, update, context)
    elif command == "show_annotation":
        await show_annotation(arg, update, context)

async def find_book_by_id(book_id, update: Update, context: CallbackContext):
    logger.info(msg="find the book", extra={"command": "find_book_by_id", "user_id": update.effective_user.id})
    mes = await context.bot.send_message(chat_id=update.effective_chat.id, text="Подождите, идёт загрузка...")
    book = flib.get_book_by_id(book_id)
    
    # Экранируем спецсимволы
    safe_title = book.title.replace('<', '<').replace('>', '>')
    safe_author = book.author.replace('<', '<').replace('>', '>')
    
    # Красивая карточка БЕЗ аннотации (она теперь по кнопке)
    capt = "📖 {title}\n🗣 {author}\n⚖️ {size}\n🌐 Страница книги {url}".format(
        author=safe_author, title=safe_title, url=book.link, size=book.size
    )

    reply_markup = build_book_keyboard(book.id, book.formats, mode="chat")

    if book.cover:
        flib.download_book_cover(book)
        c_full_path = os.path.join(os.getcwd(), "books", book_id, "cover.jpg")
        with open(os.path.join(c_full_path), "rb") as cover:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=cover, caption=capt, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="[обложки нет]\n\n" + capt, reply_markup=reply_markup, parse_mode='HTML')
    await context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)

async def show_annotation(book_id, update: Update, context: CallbackContext):
    mes = await context.bot.send_message(chat_id=update.effective_chat.id, text="Загружаю аннотацию...")
    book = flib.get_book_by_id(book_id)
    
    annotation = getattr(book, 'annotation', '').strip()
    
    if not annotation:
        await context.bot.edit_message_text(chat_id=mes.chat_id, message_id=mes.message_id, text="К сожалению, для этой книги нет аннотации на сайте.")
        return

    safe_title = book.title.replace('<', '<').replace('>', '>')
    safe_annotation = annotation.replace('<', '<').replace('>', '>')
    
    text = f"📖 {safe_title}\n\n{safe_annotation}"
    
    # Телеграм поддерживает до 4096 символов в одном сообщении, на всякий случай обрезаем, если вдруг текст огромный
    if len(text) > 4000:
        text = text[:4000] + "..."
        
    await context.bot.edit_message_text(chat_id=mes.chat_id, message_id=mes.message_id, text=text, parse_mode='HTML')

async def process_book_request(arg: str, update: Update, context: CallbackContext):
    mode, book_id, book_format = arg.split(" ")
    user_id = update.effective_user.id
    
    if mode == "email":
        email = await get_email(user_id)
        if not email:
            pending_email_requests[user_id] = {"book_id": book_id, "format": book_format}
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text="У вас не задан E-mail.\nПожалуйста, отправьте адрес вашей электронной почты ответным сообщением:"
            )
            return

    mes = await context.bot.send_message(chat_id=update.effective_chat.id, text="Подождите, идёт скачивание...")
    await download_and_send(mode, book_id, book_format, update, context, mes)

async def download_and_send(mode, book_id, book_format, update: Update, context: CallbackContext, mes):
    book = flib.get_book_by_id(book_id)
    b_content, b_filename = flib.download_book(book, book_format)

    if not b_filename:
        await context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Произошла ошибка при скачивании файла.")
        return

    if mode == "chat":
        await context.bot.send_document(chat_id=update.effective_chat.id, document=b_content, filename=b_filename)
        await context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)
    elif mode == "email":
        email = await get_email(update.effective_user.id)
        await context.bot.edit_message_text(chat_id=mes.chat_id, message_id=mes.message_id, text=f"Отправляю книгу на {email}...")
        try:
            send_email(b_content, b_filename, email)
            await context.bot.deleteMessage(chat_id=mes.chat_id, message_id=mes.message_id)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ Книга {b_filename} успешно отправлена на {email}!\n\nНе забудьте проверить папку «Спам», если письма долго нет во входящих.", parse_mode='HTML')
        except Exception as e:
            logger.error(f"Email send error: {e}")
            await context.bot.edit_message_text(chat_id=mes.chat_id, message_id=mes.message_id, text=f"❌ Ошибка отправки: {e}")
