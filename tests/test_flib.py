import io
import zipfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from src import flib
from src.settings import settings

BASE = "https://flibusta.test"
STATIC = "https://static.flibusta.test"
FIXTURES = Path(__file__).parent / "fixtures"
MEGABYTE = 1024 * 1024

Handler = Callable[[httpx.Request], httpx.Response]

real_site = flib._site


def page(name: str) -> Handler:
    html = (FIXTURES / name).read_text(encoding="utf-8")

    return lambda request: httpx.Response(200, html=html)


def status(code: int) -> Handler:
    return lambda request: httpx.Response(code)


def network_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


class FakeSite:
    """Отвечает по пути запроса; несколько ответов отдаются по очереди, последний повторяется."""

    def __init__(self) -> None:
        self.routes: dict[str, list[Handler]] = {}
        self.requests: list[httpx.Request] = []

    def add(self, path: str, *handlers: Handler) -> None:
        self.routes[path] = list(handlers)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handlers = self.routes.get(request.url.path)

        if not handlers:
            return httpx.Response(404)

        handler = handlers.pop(0) if len(handlers) > 1 else handlers[0]

        return handler(request)


@pytest.fixture
async def site(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeSite]:
    fake = FakeSite()
    monkeypatch.setattr(flib, "_client", flib._create_client(httpx.MockTransport(fake)))
    monkeypatch.setattr(flib, "_site", lambda: BASE)
    monkeypatch.setattr(flib, "HTTP_RETRY_DELAY", 0.0)
    monkeypatch.setattr(flib, "_book_cache", flib._BookCache(600.0, 16))

    yield fake

    await flib.close_client()


def book_with(**formats: str) -> flib.Book:
    return flib.Book(id="857081", formats=formats)


def file_response(
    filename: str | None,
    content: bytes,
    *,
    content_length: bool = True,
) -> Handler:
    headers = {"content-type": "application/zip"}

    if filename:
        headers["content-disposition"] = f'attachment; filename="{filename}"'

    def handler(request: httpx.Request) -> httpx.Response:
        if content_length:
            return httpx.Response(200, headers=headers, content=content)

        async def chunks() -> AsyncIterator[bytes]:
            for start in range(0, len(content), 1024):
                yield content[start : start + 1024]

        return httpx.Response(200, headers=headers, content=chunks())

    return handler


# --- форматы ---


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("(fb2)", "fb2"),
        ("(epub)", "epub"),
        ("(mobi)", "mobi"),
        ("(скачать pdf)", "pdf"),
        ("(скачать djvu)", "djvu"),
        ("(скачать DJVU)", "djvu"),
        ("(скачать djv)", "djvu"),
        ("(скачать doc)", None),
        ("(читать)", None),
        ("(следить)", None),
        ("fb2 info", None),
        ("", None),
    ],
)
def test_normalize_format(label: str, expected: str | None) -> None:
    assert flib.normalize_format(label) == expected


# --- поиск по названию ---


async def test_search_by_title(site: FakeSite) -> None:
    site.add("/booksearch", page("search_title.html"))

    books = await flib.search_by_title("мастер и маргарита")

    assert len(books) == 42
    assert len({book.id for book in books}) == 42
    assert all(book.id.isdigit() and book.link == f"{BASE}/b/{book.id}/" for book in books)

    first = books[0]
    assert first.id == "368728"
    # Подсветка совпадений (<b>) в название не попадает
    assert first.title == "«Мастер и Маргарита» в иллюстрациях [только иллюстрации, компиляция]"
    assert first.author == "Андрей Петрович Карапетян (иллюстратор)"

    by_id = {book.id: book for book in books}
    assert by_id["605352"].author == (
        "Михаил Афанасьевич Булгаков, Виктор Васильевич Прокофьев (иллюстратор)"
    )

    request = site.requests[0]
    assert request.url.params["ask"] == "мастер и маргарита"
    assert request.url.params["chb"] == "on"
    assert request.headers["user-agent"] == flib.HTTP_USER_AGENT


async def test_search_by_title_nothing_found(site: FakeSite) -> None:
    site.add("/booksearch", page("search_title_empty.html"))

    assert await flib.search_by_title("qwzxqwzxqwzx") == []


async def test_search_raises_http_error_after_retries(site: FakeSite) -> None:
    site.add("/booksearch", status(503))

    with pytest.raises(httpx.HTTPError):
        await flib.search_by_title("книга")

    assert len(site.requests) == flib.HTTP_RETRIES


# --- поиск по автору ---

# В search_author.html 50 однофамильцев; это пятеро с наибольшим числом книг
TOP_AUTHORS = ["17584", "77715", "167022", "126237", "135372"]


async def test_search_by_author(site: FakeSite) -> None:
    site.add("/booksearch", page("search_author.html"))
    site.add("/a/17584", page("author_17584.html"))
    # Страницы других Булгаковых (в жизни у них другие id); одна из страниц недоступна
    site.add("/a/77715", page("author_46322.html"))
    site.add("/a/135372", page("author_197233.html"))
    site.add("/a/126237", status(503))

    books = await flib.search_by_author("булгаков")

    assert site.requests[0].url.params["ask"] == "булгаков"
    assert site.requests[0].url.params["cha"] == "on"
    assert sorted(set(site.paths()[1:])) == sorted(f"/a/{author_id}" for author_id in TOP_AUTHORS)

    ids = [book.id for book in books]
    assert len(ids) == len(set(ids)) == 47

    by_id = {book.id: book for book in books}
    assert by_id["514779"].title == "Белая гвардия"
    assert by_id["514779"].author == "Михаил Афанасьевич Булгаков"
    assert by_id["514779"].link == f"{BASE}/b/514779/"

    assert by_id["9398"].author == "Александр Григорьевич Булгаков"
    # Переводы — чужие книги, в выдачу не идут
    assert "752508" not in by_id


async def test_search_by_author_picks_most_prolific(site: FakeSite) -> None:
    html = (FIXTURES / "search_author.html").read_text(encoding="utf-8")

    author_ids = flib._parse_author_search(flib.BeautifulSoup(html, "html.parser"))

    assert author_ids == TOP_AUTHORS


async def test_search_by_author_translations_only(site: FakeSite) -> None:
    html = (FIXTURES / "author_197233.html").read_text(encoding="utf-8")

    assert flib._parse_author_page(flib.BeautifulSoup(html, "html.parser")) == []


async def test_search_by_author_nothing_found(site: FakeSite) -> None:
    site.add("/booksearch", page("search_title_empty.html"))

    assert await flib.search_by_author("qwzxqwzxqwzx") == []
    assert len(site.requests) == 1


async def test_search_by_author_raises_when_all_pages_failed(site: FakeSite) -> None:
    site.add("/booksearch", page("search_author.html"))

    for author_id in TOP_AUTHORS:
        site.add(f"/a/{author_id}", network_error)

    with pytest.raises(httpx.HTTPError):
        await flib.search_by_author("булгаков")


# --- поиск по названию и автору ---


async def test_search_by_title_and_author(site: FakeSite) -> None:
    site.add("/makebooklist", page("booklist.html"))

    books = await flib.search_by_title_and_author("мастер", "булгаков")

    params = site.requests[0].url.params
    assert (params["t"], params["ln"]) == ("мастер", "булгаков")

    assert len(books) == 24
    assert len({book.id for book in books}) == 24

    first = books[0]
    assert first.id == "857081"
    assert first.title == "Мастер и Маргарита"
    assert first.author == "Михаил Афанасьевич Булгаков"
    assert first.link == f"{BASE}/b/857081/"

    by_id = {book.id: book for book in books}
    assert by_id["605352"].author == (
        "Михаил Афанасьевич Булгаков, Виктор Васильевич Прокофьев (иллюстратор)"
    )


async def test_search_by_title_and_author_skips_translators(site: FakeSite) -> None:
    site.add("/makebooklist", page("booklist_pdf_djvu.html"))

    books = {book.id: book for book in await flib.search_by_title_and_author("анализ", "")}

    assert len(books) == 43
    # «(пер. Евгений Владимирович Поникаров)» стоит перед размером и автором не считается
    assert books["622660"].author == "Стивен Строгац"
    assert books["750933"].author == (
        "Слав Николаевич Олехник, И. А. Виноградова, В. А. Садовничий"
    )


async def test_search_by_title_and_author_nothing_found(site: FakeSite) -> None:
    site.add("/makebooklist", page("booklist_empty.html"))

    assert await flib.search_by_title_and_author("qwzx", "qwzx") == []


# --- карточка книги ---


async def test_get_book_by_id(site: FakeSite) -> None:
    site.add("/b/857081", page("book_857081.html"))

    book = await flib.get_book_by_id("857081")

    assert book is not None
    assert book.id == "857081"
    assert book.title == "Мастер и Маргарита (fb2)"
    assert book.author == "Михаил Афанасьевич Булгаков"
    assert book.link == f"{BASE}/b/857081/"
    assert book.size == "7117K, 391 с."
    assert book.cover == f"{BASE}/i/81/857081/cover.jpg"
    assert book.formats == {
        "fb2": f"{BASE}/b/857081/fb2",
        "epub": f"{BASE}/b/857081/epub",
        "mobi": f"{BASE}/b/857081/mobi",
    }
    assert book.annotation.startswith("Иллюстрированное издание со статьей")
    assert book.annotation.endswith("гениального произведения Михаила Булгакова.")
    assert "<" not in book.annotation


@pytest.mark.parametrize(
    ("book_id", "fixture", "book_format", "size"),
    [
        ("783815", "book_783815_pdf.html", "pdf", "18105K"),
        ("818680", "book_818680_djvu.html", "djvu", "3620K, 271 с."),
    ],
)
async def test_get_book_by_id_pdf_and_djvu(
    site: FakeSite,
    book_id: str,
    fixture: str,
    book_format: str,
    size: str,
) -> None:
    site.add(f"/b/{book_id}", page(fixture))

    book = await flib.get_book_by_id(book_id)

    assert book is not None
    assert book.formats == {book_format: f"{BASE}/b/{book_id}/download"}
    assert set(book.formats) <= set(flib.ALL_FORMATS)
    assert book.size == size
    assert book.cover is None
    # «Аннотация отсутствует»
    assert book.annotation == ""


async def test_get_book_by_id_several_authors(site: FakeSite) -> None:
    site.add("/b/605352", page("book_605352_two_authors.html"))

    book = await flib.get_book_by_id("605352")

    assert book is not None
    assert book.author == "Михаил Афанасьевич Булгаков, Виктор Васильевич Прокофьев"
    assert book.cover == f"{BASE}/ib/83/489283/bulgakov_obl-200x317.jpg"
    assert list(book.formats) == ["pdf"]


async def test_get_book_by_id_replaced_book(site: FakeSite) -> None:
    site.add("/b/1", page("book_1_deleted.html"))

    book = await flib.get_book_by_id("1")

    assert book is not None
    # Между заголовком и автором стоит ссылка на исправленную версию
    assert book.author == "Андрей Аарх"
    assert book.title == "Аида (старая версия файла) (fb2)"


async def test_get_book_by_id_unknown_book(site: FakeSite) -> None:
    # Сайт отвечает 200 и страницей поиска «Книги по названию 999999999»
    site.add("/b/999999999", page("book_not_found.html"))

    assert await flib.get_book_by_id("999999999") is None


async def test_get_book_by_id_404(site: FakeSite) -> None:
    assert await flib.get_book_by_id("123") is None
    assert site.paths() == ["/b/123"]


@pytest.mark.parametrize("book_id", ["", "abc", "12a", "1/../2", "-1", "1 2", "١٢٣"])
async def test_get_book_by_id_rejects_non_numeric_id(site: FakeSite, book_id: str) -> None:
    assert await flib.get_book_by_id(book_id) is None
    assert site.requests == []


async def test_get_book_by_id_raises_http_error(site: FakeSite) -> None:
    site.add("/b/857081", status(500))

    with pytest.raises(httpx.HTTPError):
        await flib.get_book_by_id("857081")

    assert len(site.requests) == flib.HTTP_RETRIES


# --- ретраи ---


@pytest.mark.parametrize("failure", [status(429), status(502), status(503), network_error])
async def test_retries_transient_failures(site: FakeSite, failure: Handler) -> None:
    site.add("/b/857081", failure, failure, page("book_857081.html"))

    book = await flib.get_book_by_id("857081")

    assert book is not None
    assert len(site.requests) == 3


async def test_gives_up_after_retries_on_network_error(site: FakeSite) -> None:
    site.add("/b/857081", network_error)

    with pytest.raises(httpx.TransportError):
        await flib.get_book_by_id("857081")

    assert len(site.requests) == flib.HTTP_RETRIES


async def test_does_not_retry_client_errors(site: FakeSite) -> None:
    site.add("/booksearch", status(403))

    with pytest.raises(httpx.HTTPStatusError):
        await flib.search_by_title("книга")

    assert len(site.requests) == 1


# --- кеш ---


async def test_book_is_cached(site: FakeSite) -> None:
    site.add("/b/857081", page("book_857081.html"))

    first = await flib.get_book_by_id("857081")
    assert first is not None
    first.formats.clear()
    first.title = "испорчено"

    second = await flib.get_book_by_id("857081")

    assert len(site.requests) == 1
    assert second is not None
    assert second.title == "Мастер и Маргарита (fb2)"
    assert set(second.formats) == {"fb2", "epub", "mobi"}


async def test_cache_expires(site: FakeSite, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flib, "_book_cache", flib._BookCache(0.0, 16))
    site.add("/b/857081", page("book_857081.html"))

    await flib.get_book_by_id("857081")
    await flib.get_book_by_id("857081")

    assert len(site.requests) == 2


async def test_missing_book_is_not_cached(site: FakeSite) -> None:
    site.add("/b/857081", page("book_not_found.html"), page("book_857081.html"))

    assert await flib.get_book_by_id("857081") is None
    assert await flib.get_book_by_id("857081") is not None


def test_cache_is_bounded() -> None:
    cache = flib._BookCache(600.0, 2)

    for book_id in ("1", "2", "3"):
        cache.put(flib.Book(id=book_id))

    assert cache.get("1") is None
    assert cache.get("2") is not None
    assert cache.get("3") is not None


# --- скачивание ---


async def test_download_book(site: FakeSite) -> None:
    content = b"PK" + b"x" * 5000
    site.add(
        "/b/857081/fb2",
        lambda request: httpx.Response(302, headers={"location": f"{STATIC}/b.fb2/book.fb2.zip"}),
    )
    site.add("/b.fb2/book.fb2.zip", file_response("Bulgakov_Master.857081.fb2.zip", content))

    result = await flib.download_book(
        book_with(fb2=f"{BASE}/b/857081/fb2"),
        "fb2",
        max_size=MEGABYTE,
    )

    # Не архив — отдаём как есть, имя не подменяем
    assert result == flib.DownloadedFile(content=content, filename="Bulgakov_Master.857081.fb2.zip")
    assert site.requests[-1].url.host == "static.flibusta.test"
    assert site.requests[-1].headers["user-agent"] == flib.HTTP_USER_AGENT


def zipped(name: str, data: bytes) -> bytes:
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, data)

    return buffer.getvalue()


async def test_download_book_unpacks_fb2(site: FakeSite) -> None:
    fb2 = b"<FictionBook>" + b"x" * 5000 + b"</FictionBook>"
    site.add("/b/857081/fb2", file_response("book.857081.fb2.zip", zipped("book.fb2", fb2)))

    result = await flib.download_book(
        book_with(fb2=f"{BASE}/b/857081/fb2"),
        "fb2",
        max_size=MEGABYTE,
    )

    assert result == flib.DownloadedFile(content=fb2, filename="book.857081.fb2")


async def test_download_book_keeps_archive_if_unpacked_is_too_large(site: FakeSite) -> None:
    archive = zipped("book.fb2", b"x" * 50_000)
    site.add("/b/857081/fb2", file_response("book.fb2.zip", archive))

    result = await flib.download_book(
        book_with(fb2=f"{BASE}/b/857081/fb2"),
        "fb2",
        max_size=10_000,
    )

    assert result == flib.DownloadedFile(content=archive, filename="book.fb2.zip")


async def test_download_book_keeps_other_extensions(site: FakeSite) -> None:
    site.add("/b/818680/download", file_response("Opoycev.818680.djvu", b"djvu"))

    result = await flib.download_book(
        book_with(djvu=f"{BASE}/b/818680/download"),
        "djvu",
        max_size=4,
    )

    assert result == flib.DownloadedFile(content=b"djvu", filename="Opoycev.818680.djvu")


async def test_download_book_missing_format(site: FakeSite) -> None:
    result = await flib.download_book(
        book_with(fb2=f"{BASE}/b/857081/fb2"),
        "pdf",
        max_size=MEGABYTE,
    )

    assert result is None
    assert site.requests == []


async def test_download_book_not_a_file(site: FakeSite) -> None:
    site.add("/b/857081/fb2", page("book_857081.html"))

    result = await flib.download_book(
        book_with(fb2=f"{BASE}/b/857081/fb2"),
        "fb2",
        max_size=MEGABYTE,
    )

    assert result is None


@pytest.mark.parametrize("failure", [status(404), status(503), network_error])
async def test_download_book_http_failure(site: FakeSite, failure: Handler) -> None:
    site.add("/b/857081/fb2", failure)

    result = await flib.download_book(
        book_with(fb2=f"{BASE}/b/857081/fb2"),
        "fb2",
        max_size=MEGABYTE,
    )

    assert result is None


async def test_download_book_retries(site: FakeSite) -> None:
    site.add("/b/857081/fb2", status(503), file_response("book.epub", b"data"))

    result = await flib.download_book(
        book_with(fb2=f"{BASE}/b/857081/fb2"),
        "fb2",
        max_size=MEGABYTE,
    )

    assert result == flib.DownloadedFile(content=b"data", filename="book.epub")


async def test_download_book_too_large_by_content_length(site: FakeSite) -> None:
    site.add("/b/857081/fb2", file_response("book.fb2.zip", b"x" * 2001))

    with pytest.raises(flib.BookTooLargeError) as error:
        await flib.download_book(book_with(fb2=f"{BASE}/b/857081/fb2"), "fb2", max_size=2000)

    assert error.value.size == 2001


async def test_download_book_too_large_without_content_length(site: FakeSite) -> None:
    site.add(
        "/b/857081/fb2",
        file_response("book.fb2.zip", b"x" * 10_000, content_length=False),
    )

    with pytest.raises(flib.BookTooLargeError) as error:
        await flib.download_book(book_with(fb2=f"{BASE}/b/857081/fb2"), "fb2", max_size=2000)

    assert error.value.size is None


async def test_download_book_without_content_length(site: FakeSite) -> None:
    content = b"x" * 10_000
    site.add("/b/857081/fb2", file_response("book.epub", content, content_length=False))

    result = await flib.download_book(
        book_with(fb2=f"{BASE}/b/857081/fb2"),
        "fb2",
        max_size=10_000,
    )

    assert result == flib.DownloadedFile(content=content, filename="book.epub")


# --- обложка ---


async def test_download_cover(site: FakeSite) -> None:
    jpeg = b"\xff\xd8\xff" + b"0" * 100
    site.add(
        "/i/81/857081/cover.jpg", status(502), lambda request: httpx.Response(200, content=jpeg)
    )

    book = flib.Book(id="857081", cover=f"{BASE}/i/81/857081/cover.jpg")

    assert await flib.download_cover(book) == jpeg
    assert len(site.requests) == 2


async def test_download_cover_without_cover(site: FakeSite) -> None:
    assert await flib.download_cover(flib.Book(id="1")) is None
    assert site.requests == []


@pytest.mark.parametrize("failure", [status(404), network_error])
async def test_download_cover_failure(site: FakeSite, failure: Handler) -> None:
    site.add("/cover.jpg", failure)

    assert await flib.download_cover(flib.Book(id="1", cover=f"{BASE}/cover.jpg")) is None


async def test_download_cover_too_large(site: FakeSite, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flib, "COVER_MAX_SIZE", 10)
    site.add("/cover.jpg", lambda request: httpx.Response(200, content=b"0" * 11))

    assert await flib.download_cover(flib.Book(id="1", cover=f"{BASE}/cover.jpg")) is None


# --- настройки и клиент ---


def test_site_url_is_read_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "flibusta_url", "https://mirror.test/")

    assert real_site() == "https://mirror.test"


async def test_close_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flib, "_client", None)

    client = flib.get_client()
    assert flib.get_client() is client
    assert client.headers["user-agent"] == flib.HTTP_USER_AGENT

    await flib.close_client()

    assert client.is_closed
    assert flib.get_client() is not client

    await flib.close_client()
