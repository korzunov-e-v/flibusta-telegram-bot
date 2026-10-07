from collections.abc import Iterable, Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import callbacks as cb
from src.bot.texts import book_button_text
from src.flib import ALL_FORMATS, Book

PAGE_SIZE = 10
FORMATS_PER_ROW = 3


def _button(text: str, callback: cb.Callback) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cb.encode(callback))


def _chunks[T](items: Sequence[T], size: int) -> list[list[T]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def page_count(total: int, page_size: int = PAGE_SIZE) -> int:
    return max((total + page_size - 1) // page_size, 1)


def clamp_page(page: int, total: int, page_size: int = PAGE_SIZE) -> int:
    return min(max(page, 0), page_count(total, page_size) - 1)


def book_keyboard(
    book_id: str,
    formats: Iterable[str],
    mode: cb.Mode = "chat",
) -> InlineKeyboardMarkup:
    if mode == "chat":
        icon = "⬇️"
        switch_text = "Отправить на почту 📩"
        other_mode: cb.Mode = "email"
    else:
        icon = "📩"
        switch_text = "Прислать в чат ⬇️"
        other_mode = "chat"

    available = set(formats)
    format_buttons = [
        _button(f"{icon} .{book_format}", cb.GetBook(mode, book_id, book_format))
        for book_format in ALL_FORMATS
        if book_format in available
    ]

    rows = [[_button("📝 Читать аннотацию", cb.ShowAnnotation(book_id))]]
    rows += _chunks(format_buttons, FORMATS_PER_ROW)

    if format_buttons:
        rows.append([_button(switch_text, cb.SwitchMode(other_mode, book_id))])

    return InlineKeyboardMarkup(rows)


def retry_keyboard(action: cb.Action) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_button("🔄 Повторить", cb.Retry(action))]])


def formats_from_keyboard(markup: InlineKeyboardMarkup | None) -> list[str]:
    """Форматы книги по кнопкам уже отправленной карточки — чтобы при
    переключении режима не ходить на сайт. Понимает и старые кнопки."""
    if markup is None:
        return []

    formats: list[str] = []

    for row in markup.inline_keyboard:
        for button in row:
            if not isinstance(button.callback_data, str):
                continue

            try:
                callback = cb.decode(button.callback_data)
            except cb.InvalidCallbackData:
                continue

            if isinstance(callback, cb.GetBook) and callback.book_format not in formats:
                formats.append(callback.book_format)

    return formats


def search_keyboard(
    books: Sequence[Book],
    search_id: str,
    page: int,
    page_size: int = PAGE_SIZE,
) -> InlineKeyboardMarkup:
    pages = page_count(len(books), page_size)
    page = clamp_page(page, len(books), page_size)
    start = page * page_size

    rows = [
        [_button(book_button_text(book), cb.ShowBook(book.id))]
        for book in books[start : start + page_size]
    ]

    if pages > 1:
        noop = _button(" ", cb.Noop())
        rows.append(
            [
                _button("◀️", cb.ShowPage(search_id, page - 1)) if page > 0 else noop,
                _button(f"{page + 1}/{pages}", cb.Noop()),
                _button("▶️", cb.ShowPage(search_id, page + 1)) if page < pages - 1 else noop,
            ]
        )

    return InlineKeyboardMarkup(rows)
