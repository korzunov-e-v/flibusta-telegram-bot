from datetime import timedelta

from telegram.error import TelegramError

from src import flib, mailer
from src.bot import callbacks as cb
from src.bot import texts
from src.bot.helpers import Context, Status, status_message
from src.bot.keyboards import retry_keyboard
from src.custom_logging import get_logger
from src.database import crud
from src.settings import settings

logger = get_logger(__name__)

DAY = timedelta(days=1)


async def email_limit_reached(user_id: int) -> bool:
    sent = await crud.count_sent_emails(user_id, crud.KIND_BOOK, DAY)

    return sent >= settings.email_daily_limit


async def deliver_book(
    context: Context,
    *,
    chat_id: int,
    user_id: int,
    mode: cb.Mode,
    book_id: str,
    book_format: str,
) -> None:
    """Скачивает книгу и отправляет её в чат или на подтверждённый адрес пользователя."""
    bot = context.bot
    by_email = mode == "email"
    email: str | None = None

    logger.info(
        "get book",
        extra={"user_id": user_id, "book_id": book_id, "format": book_format, "mode": mode},
    )

    async with status_message(bot, chat_id, texts.DOWNLOADING) as status:
        if by_email:
            email = await crud.get_email(user_id)

            if not email:
                await bot.send_message(chat_id=chat_id, text=texts.EMAIL_NOT_SET)
                return

            if await email_limit_reached(user_id):
                await bot.send_message(
                    chat_id=chat_id,
                    text=texts.EMAIL_DAILY_LIMIT.format(limit=settings.email_daily_limit),
                )
                return

        book = await flib.get_book_by_id(book_id)

        if book is None:
            await bot.send_message(chat_id=chat_id, text=texts.BOOK_NOT_FOUND)
            return

        if book_format not in book.formats:
            await bot.send_message(chat_id=chat_id, text=texts.FORMAT_UNAVAILABLE)
            return

        limit_mb = settings.max_email_file_mb if by_email else settings.max_chat_file_mb
        max_size = settings.max_email_file_size if by_email else settings.max_chat_file_size

        try:
            file = await flib.download_book(book, book_format, max_size=max_size)
        except flib.BookTooLargeError as e:
            await bot.send_message(
                chat_id=chat_id,
                text=texts.too_large_text(limit_mb, e.size, by_email=by_email),
            )
            return

        if file is None:
            await bot.send_message(
                chat_id=chat_id,
                text=texts.DOWNLOAD_FAILED,
                reply_markup=retry_keyboard(cb.GetBook(mode, book_id, book_format)),
            )
            return

        if email is not None:
            await _send_to_email(context, status, chat_id, user_id, email, file)
        else:
            await _send_to_chat(context, chat_id, user_id, file)


async def _send_to_chat(
    context: Context,
    chat_id: int,
    user_id: int,
    file: flib.DownloadedFile,
) -> None:
    try:
        await context.bot.send_document(
            chat_id=chat_id,
            document=file.content,
            filename=file.filename,
        )
    except TelegramError:
        logger.exception(
            "Failed to send document",
            extra={"user_id": user_id, "size": len(file.content)},
        )
        await context.bot.send_message(chat_id=chat_id, text=texts.SEND_FAILED)


async def _send_to_email(
    context: Context,
    status: Status,
    chat_id: int,
    user_id: int,
    email: str,
    file: flib.DownloadedFile,
) -> None:
    bot = context.bot
    log_extra = {"user_id": user_id, "email": mailer.mask_email(email), "size": len(file.content)}

    await status.edit(texts.EMAIL_SENDING.format(email=email))

    try:
        await mailer.send_book(file.content, file.filename, email)
    except mailer.MailTooLargeError:
        logger.warning("Mail server rejected message size", extra=log_extra)
        await bot.send_message(chat_id=chat_id, text=texts.EMAIL_REJECTED_SIZE)
        return
    except Exception:
        logger.exception("Email send error", extra=log_extra)
        await bot.send_message(chat_id=chat_id, text=texts.EMAIL_SEND_FAILED)
        return

    await crud.log_sent_email(user_id, crud.KIND_BOOK)
    logger.info("Book sent by email", extra=log_extra)

    await bot.send_message(
        chat_id=chat_id,
        text=texts.EMAIL_SENT.format(filename=file.filename, email=email),
    )
