from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from telegram import CallbackQuery, Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest

from src import flib
from src.bot import callbacks as cb
from src.bot import search, texts, throttle, verification
from src.bot.delivery import deliver_book
from src.bot.errors import guard
from src.bot.helpers import Context, get_user_data, safe_answer, safe_delete, status_message
from src.bot.keyboards import book_keyboard, formats_from_keyboard
from src.bot.messages import nothing_found_text, render_results, send_results
from src.bot.search import recall_query, run_search
from src.custom_logging import get_logger
from src.database import crud

logger = get_logger(__name__)


async def button(update: Update, context: Context) -> None:
    query = update.callback_query
    user = update.effective_user
    chat = update.effective_chat

    if query is None:
        return

    try:
        callback = cb.decode(query.data)
    except cb.InvalidCallbackData:
        logger.info("Stale or invalid callback data", extra={"data": query.data})
        callback = None

    if callback is None or user is None or chat is None:
        await safe_answer(query, texts.STALE_BUTTON, alert=True)
        return

    if isinstance(callback, cb.Noop):
        await safe_answer(query)
        return

    is_retry = isinstance(callback, cb.Retry)
    action = callback.action if isinstance(callback, cb.Retry) else callback
    # переключение режима правит саму карточку, повторять его из сообщения об ошибке нечем
    retry = None if isinstance(action, cb.SwitchMode) else action

    async with guard(update, context, retry=retry):
        throttled = False

        try:
            match action:
                case cb.ShowBook(book_id):
                    await show_book(query, context, chat.id, user.id, book_id)
                case cb.ShowAnnotation(book_id):
                    await show_annotation(query, context, chat.id, user.id, book_id)
                case cb.SwitchMode(mode, book_id):
                    await switch_mode(query, mode, book_id)
                case cb.GetBook():
                    await get_book(query, context, chat.id, user.id, action)
                case cb.ShowPage(search_id, page) if is_retry:
                    await retry_search(query, context, chat.id, user.id, search_id, page)
                case cb.ShowPage(search_id, page):
                    await show_page(query, context, user.id, search_id, page)
        except throttle.Throttled:
            throttled = True
            raise
        finally:
            # сообщение об ошибке с кнопкой «Повторить» своё отработало: при новом сбое
            # придёт новое. Если повтор отклонён троттлингом, кнопка остаётся.
            if is_retry and not throttled and isinstance(query.message, Message):
                await safe_delete(query.message)


@contextmanager
def ignore_not_modified() -> Iterator[None]:
    try:
        yield
    except BadRequest as e:
        # повторное нажатие той же кнопки
        if "not modified" not in e.message.lower():
            raise


async def show_book(
    query: CallbackQuery,
    context: Context,
    chat_id: int,
    user_id: int,
    book_id: str,
) -> None:
    bot = context.bot

    with throttle.light.slot(user_id):
        await safe_answer(query)

        logger.info(
            "find the book",
            extra={"command": "find_book_by_id", "user_id": user_id, "book_id": book_id},
        )

        async with status_message(bot, chat_id, texts.LOADING):
            book = await flib.get_book_by_id(book_id)

            if book is None:
                await bot.send_message(chat_id=chat_id, text=texts.BOOK_NOT_FOUND)
                return

            markup = book_keyboard(book.id, book.formats)

            try:
                cover = await flib.download_cover(book)
            except httpx.HTTPError:
                cover = None

            if cover:
                try:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=cover,
                        caption=texts.book_caption(book, with_cover=True),
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML,
                    )
                    return
                except BadRequest:
                    # Telegram не принял картинку (формат, размеры) — отправим карточку без неё
                    logger.warning(
                        "Failed to send cover", extra={"book_id": book_id}, exc_info=True
                    )

            await bot.send_message(
                chat_id=chat_id,
                text=texts.book_caption(book, with_cover=False),
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )


async def show_annotation(
    query: CallbackQuery,
    context: Context,
    chat_id: int,
    user_id: int,
    book_id: str,
) -> None:
    bot = context.bot

    with throttle.light.slot(user_id):
        await safe_answer(query)

        async with status_message(bot, chat_id, texts.LOADING_ANNOTATION):
            book = await flib.get_book_by_id(book_id)

        if book is None:
            await bot.send_message(chat_id=chat_id, text=texts.BOOK_NOT_FOUND)
        elif not book.annotation.strip():
            await bot.send_message(chat_id=chat_id, text=texts.NO_ANNOTATION)
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=texts.annotation_text(book),
                parse_mode=ParseMode.HTML,
            )


async def switch_mode(query: CallbackQuery, mode: cb.Mode, book_id: str) -> None:
    await safe_answer(query)

    # форматы берём из кнопок самой карточки, без запроса к сайту
    markup = query.message.reply_markup if isinstance(query.message, Message) else None
    formats = formats_from_keyboard(markup)

    if not formats:
        book = await flib.get_book_by_id(book_id)
        formats = list(book.formats) if book else []

    with ignore_not_modified():
        await query.edit_message_reply_markup(reply_markup=book_keyboard(book_id, formats, mode))


async def get_book(
    query: CallbackQuery,
    context: Context,
    chat_id: int,
    user_id: int,
    callback: cb.GetBook,
) -> None:
    if callback.mode == "email" and not await crud.get_email(user_id):
        await safe_answer(query)

        verification.await_email(
            get_user_data(context),
            book_id=callback.book_id,
            book_format=callback.book_format,
        )
        await context.bot.send_message(chat_id=chat_id, text=texts.EMAIL_ASK)
        return

    with throttle.heavy.slot(user_id):
        await safe_answer(query)

        await deliver_book(
            context,
            chat_id=chat_id,
            user_id=user_id,
            mode=callback.mode,
            book_id=callback.book_id,
            book_format=callback.book_format,
        )


async def retry_search(
    query: CallbackQuery,
    context: Context,
    chat_id: int,
    user_id: int,
    search_id: str,
    page: int,
) -> None:
    search_query = recall_query(get_user_data(context), search_id)

    if search_query is None:
        await safe_answer(query, texts.STALE_SEARCH, alert=True)
        return

    await safe_answer(query)
    await send_results(
        context,
        chat_id=chat_id,
        user_id=user_id,
        query=search_query,
        search_id=search_id,
        page=page,
    )


async def show_page(
    query: CallbackQuery,
    context: Context,
    user_id: int,
    search_id: str,
    page: int,
) -> None:
    search_query = recall_query(get_user_data(context), search_id)

    if search_query is None:
        await safe_answer(query, texts.STALE_SEARCH, alert=True)
        return

    result = search.cache.get(user_id, search_id)

    if result is None:
        # выдача вытеснена из памяти или бот перезапускался — повторяем поиск
        with throttle.heavy.slot(user_id):
            await safe_answer(query)
            result = await run_search(search_query)
            search.cache.put(user_id, search_id, result)
    else:
        await safe_answer(query)

    if not result.books:
        with ignore_not_modified():
            await query.edit_message_text(nothing_found_text(search_query, result))
        return

    text, markup = render_results(result, search_id, page)

    with ignore_not_modified():
        await query.edit_message_text(text, reply_markup=markup)
