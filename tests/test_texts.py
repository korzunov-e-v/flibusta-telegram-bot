from src.bot import texts
from src.flib import Book


def test_escape() -> None:
    assert texts.escape("<b>Tom & Jerry</b>") == "&lt;b&gt;Tom &amp; Jerry&lt;/b&gt;"


def test_truncate() -> None:
    assert texts.truncate("короткий", 20) == "короткий"
    assert texts.truncate("a" * 10, 10) == "a" * 10
    assert texts.truncate("a" * 11, 10) == "a" * 9 + "…"
    assert texts.truncate("слово   и ещё", 6) == "слово…"


def test_book_caption_escapes_site_data() -> None:
    book = Book(
        id="1",
        title="C++ <для> чайников & co",
        author="Иванов <script>",
        link="https://flibusta.is/b/1",
        size="1 Мб & <2>",
    )

    caption = texts.book_caption(book, with_cover=True)

    assert "<b>C++ &lt;для&gt; чайников &amp; co</b>" in caption
    assert "Иванов &lt;script&gt;" in caption
    assert "1 Мб &amp; &lt;2&gt;" in caption
    assert "https://flibusta.is/b/1" in caption
    assert texts.NO_COVER not in caption
    assert texts.book_caption(book, with_cover=False).startswith(texts.NO_COVER)


def test_book_caption_fits_photo_caption_limit() -> None:
    book = Book(
        id="1",
        title="&" * 5000,
        author="<" * 5000,
        link="https://flibusta.is/b/1",
        size=">" * 500,
    )

    caption = texts.book_caption(book, with_cover=True)
    # Telegram считает длину после разбора разметки
    parsed = caption.replace("<b>", "").replace("</b>", "")
    parsed = parsed.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    assert len(parsed) <= 1024


def test_book_caption_skips_empty_fields() -> None:
    assert texts.book_caption(Book(id="1", title="Т"), with_cover=True) == "📖 <b>Т</b>"


def test_annotation_truncated_before_escaping() -> None:
    book = Book(id="1", title="<T>", annotation="&" * 10_000)

    text = texts.annotation_text(book)
    body = text.split("\n\n", maxsplit=1)[1]

    assert text.startswith("📖 <b>&lt;T&gt;</b>\n\n")
    # ни одной разрезанной сущности: только целые &amp; и многоточие
    assert body.replace("&amp;", "") == "…"
    assert body.count("&amp;") + len("📖 <T>\n\n…") <= 4096


def test_book_button_text() -> None:
    assert texts.book_button_text(Book(id="1", title="1984", author="Оруэлл")) == "1984 — Оруэлл"
    assert texts.book_button_text(Book(id="1", title="  1984\n\t ")) == "1984"
    assert texts.book_button_text(Book(id="77")) == "77"
    assert len(texts.book_button_text(Book(id="1", title="a" * 500, author="b"))) == 60


def test_search_results_text() -> None:
    assert texts.search_results_text(total=3, page=0, pages=1) == "Найдено книг: 3. Выберите книгу:"

    text = texts.search_results_text(total=250, page=1, pages=20, partial=True, truncated_to=200)

    assert "Страница 2 из 20" in text
    assert "первые 200" in text
    assert texts.SEARCH_PARTIAL in text


def test_too_large_text() -> None:
    chat = texts.too_large_text(50, 60 * 1024 * 1024, by_email=False)
    email = texts.too_large_text(25, None, by_email=True)

    assert "60.0 МБ" in chat and "в чат" in chat and "50 МБ" in chat
    assert "по почте" in email and "25 МБ" in email and "размер файла" not in email
