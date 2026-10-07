from telegram import InlineKeyboardMarkup, Update

from src.bot import callbacks as cb
from src.bot import search, texts, throttle, verification
from src.bot.email_flow import handle_code_input, handle_email_input
from src.bot.errors import guard
from src.bot.helpers import Context, get_user_data, status_message
from src.bot.keyboards import clamp_page, page_count, search_keyboard
from src.bot.search import (
    MAX_RESULTS,
    SearchQuery,
    SearchResult,
    parse_query,
    remember_query,
    run_search,
)
from src.custom_logging import get_logger

logger = get_logger(__name__)


def render_results(
    result: SearchResult,
    search_id: str,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    total = len(result.books)
    page = clamp_page(page, total)

    text = texts.search_results_text(
        total=total,
        page=page,
        pages=page_count(total),
        partial=result.partial,
        truncated_to=MAX_RESULTS if result.truncated else None,
    )

    return text, search_keyboard(result.books, search_id, page)


def nothing_found_text(query: SearchQuery, result: SearchResult) -> str:
    text = texts.NOTHING_FOUND_PARTIAL if result.partial else texts.NOTHING_FOUND

    if len(query.author.split()) > 1:
        text += "\n\n" + texts.AUTHOR_HINT

    return text


async def handle_text(update: Update, context: Context) -> None:
    message = update.effective_message

    if message is None or update.effective_user is None:
        return

    text = (message.text or "").strip()

    async with guard(update, context):
        user_data = get_user_data(context)
        flow = verification.load(user_data)

        if flow is not None:
            if flow.stage == verification.STAGE_CODE and verification.looks_like_code(text):
                await handle_code_input(update, context, text)
                return

            if flow.expired():
                verification.clear(user_data)
            elif flow.stage == verification.STAGE_EMAIL:
                await handle_email_input(update, context, flow, text)
                return

        await search_books(update, context, text)


async def search_books(update: Update, context: Context, text: str) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return

    query = parse_query(text)

    if query is None:
        await message.reply_text(texts.EMPTY_QUERY)
        return

    logger.info(
        "find the book",
        extra={
            "command": "find_the_book",
            "user_id": user.id,
            "book_name": query.title,
            "author": query.author or None,
        },
    )

    # запрос запоминаем до поиска: по его id работает кнопка «Повторить» после сбоя
    search_id = remember_query(get_user_data(context), query)

    async with guard(update, context, retry=cb.ShowPage(search_id, 0)):
        await send_results(
            context,
            chat_id=message.chat_id,
            user_id=user.id,
            query=query,
            search_id=search_id,
        )


async def send_results(
    context: Context,
    *,
    chat_id: int,
    user_id: int,
    query: SearchQuery,
    search_id: str,
    page: int = 0,
) -> None:
    """Ищет (или берёт выдачу из кеша) и отправляет страницу результатов новым сообщением."""
    bot = context.bot

    with throttle.heavy.slot(user_id):
        result = search.cache.get(user_id, search_id)

        if result is None:
            async with status_message(bot, chat_id, texts.SEARCHING):
                result = await run_search(query)

            search.cache.put(user_id, search_id, result)

        if not result.books:
            await bot.send_message(chat_id=chat_id, text=nothing_found_text(query, result))
            return

        text, markup = render_results(result, search_id, page)
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
