from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import callbacks as cb
from src.bot.keyboards import (
    PAGE_SIZE,
    book_keyboard,
    clamp_page,
    formats_from_keyboard,
    page_count,
    search_keyboard,
)
from src.bot.texts import MAX_BUTTON_TEXT_LENGTH
from src.flib import Book


def _buttons(markup: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    return [button for row in markup.inline_keyboard for button in row]


def _callbacks(markup: InlineKeyboardMarkup) -> list[cb.Callback]:
    return [cb.decode(str(button.callback_data)) for button in _buttons(markup)]


def _books(count: int) -> list[Book]:
    return [Book(id=str(i), title=f"Книга {i}", author="Автор") for i in range(1, count + 1)]


def test_book_keyboard_chat_mode() -> None:
    markup = book_keyboard("7", {"pdf": "u", "fb2": "u", "epub": "u", "mobi": "u"})

    assert _callbacks(markup) == [
        cb.ShowAnnotation("7"),
        cb.GetBook("chat", "7", "fb2"),
        cb.GetBook("chat", "7", "epub"),
        cb.GetBook("chat", "7", "mobi"),
        cb.GetBook("chat", "7", "pdf"),
        cb.SwitchMode("email", "7"),
    ]
    assert [b.text for b in _buttons(markup)][1] == "⬇️ .fb2"
    assert max(len(row) for row in markup.inline_keyboard) <= 3


def test_book_keyboard_email_mode_and_unknown_formats() -> None:
    markup = book_keyboard("7", ["fb2", "rtf"], mode="email")

    assert _callbacks(markup) == [
        cb.ShowAnnotation("7"),
        cb.GetBook("email", "7", "fb2"),
        cb.SwitchMode("chat", "7"),
    ]
    assert [b.text for b in _buttons(markup)][1] == "📩 .fb2"


def test_book_keyboard_without_formats_has_no_switcher() -> None:
    assert _callbacks(book_keyboard("7", [])) == [cb.ShowAnnotation("7")]


def test_formats_from_keyboard_roundtrip() -> None:
    markup = book_keyboard("7", ["epub", "fb2", "djvu"], mode="email")

    assert formats_from_keyboard(markup) == ["fb2", "epub", "djvu"]
    assert formats_from_keyboard(None) == []


def test_formats_from_legacy_keyboard() -> None:
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝", callback_data="show_annotation 7")],
            [
                InlineKeyboardButton(".(fb2)", callback_data="get_book chat 7 (fb2)"),
                InlineKeyboardButton(
                    ".(скачать pdf)", callback_data="get_book chat 7 (скачать pdf)"
                ),
                InlineKeyboardButton("?", callback_data="мусор"),
                InlineKeyboardButton("url", url="https://example.com"),
            ],
            [InlineKeyboardButton("📩", callback_data="switch_mode email 7")],
        ]
    )

    assert formats_from_keyboard(markup) == ["fb2", "pdf"]


def test_page_math() -> None:
    assert page_count(0) == 1
    assert page_count(PAGE_SIZE) == 1
    assert page_count(PAGE_SIZE + 1) == 2
    assert clamp_page(-5, 25) == 0
    assert clamp_page(99, 25) == 2
    assert clamp_page(1, 25) == 1


def test_search_keyboard_single_page_has_no_navigation() -> None:
    markup = search_keyboard(_books(3), "abcd", 0)

    assert _callbacks(markup) == [cb.ShowBook("1"), cb.ShowBook("2"), cb.ShowBook("3")]


def test_search_keyboard_pages() -> None:
    books = _books(25)

    first = search_keyboard(books, "abcd", 0)
    assert len(first.inline_keyboard) == PAGE_SIZE + 1
    assert _callbacks(first)[:PAGE_SIZE] == [cb.ShowBook(str(i)) for i in range(1, 11)]
    assert _callbacks(first)[PAGE_SIZE:] == [cb.Noop(), cb.Noop(), cb.ShowPage("abcd", 1)]
    assert [b.text for b in first.inline_keyboard[-1]][1:] == ["1/3", "▶️"]

    middle = search_keyboard(books, "abcd", 1)
    assert _callbacks(middle)[PAGE_SIZE:] == [
        cb.ShowPage("abcd", 0),
        cb.Noop(),
        cb.ShowPage("abcd", 2),
    ]

    last = search_keyboard(books, "abcd", 2)
    assert _callbacks(last) == [
        *(cb.ShowBook(str(i)) for i in range(21, 26)),
        cb.ShowPage("abcd", 1),
        cb.Noop(),
        cb.Noop(),
    ]

    # страница за пределами выдачи (книг стало меньше после повторного поиска)
    assert _callbacks(search_keyboard(books, "abcd", 50)) == _callbacks(last)


def test_search_keyboard_truncates_long_titles() -> None:
    markup = search_keyboard([Book(id="1", title="Очень " * 100, author="Автор")], "abcd", 0)
    text = _buttons(markup)[0].text

    assert len(text) <= MAX_BUTTON_TEXT_LENGTH
    assert text.endswith("…")
