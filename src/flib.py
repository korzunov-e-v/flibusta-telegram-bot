import asyncio
import io
import random
import re
import time
import urllib.parse
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from email.message import Message

import httpx
from bs4 import BeautifulSoup, Tag

from src.custom_logging import get_logger
from src.settings import settings

logger = get_logger(__name__)

ALL_FORMATS = ("fb2", "epub", "mobi", "pdf", "djvu")
NO_AUTHOR = "[автор не указан]"

# Сайт нестабилен: примерно каждый пятый запрос зависает или отдаёт 502, при том что
# обычный ответ приходит за 1–2 секунды. Поэтому ждём недолго и повторяем быстро.
HTTP_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
# Файлы и обложки отдаёт другой хост, первый байт может идти дольше
HTTP_DOWNLOAD_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
HTTP_RETRIES = 4
HTTP_RETRY_DELAY = 0.5
HTTP_MAX_CONNECTIONS = 20
HTTP_MAX_KEEPALIVE = 10
HTTP_USER_AGENT = "Mozilla/5.0 (compatible; flibusta-telegram-bot/0.1)"

# В выдаче поиска по автору бывает до 50 человек, страница каждого — отдельный запрос
AUTHOR_SEARCH_LIMIT = 5
AUTHOR_SEARCH_CONCURRENCY = 3

BOOK_CACHE_TTL = 600.0
BOOK_CACHE_SIZE = 256

# Лимит Telegram на фото
COVER_MAX_SIZE = 10 * 1024 * 1024

_BOOK_HREF = re.compile(r"^/b/(\d+)/?$")
_AUTHOR_HREF = re.compile(r"^/a/(\d+)/?$")
# «(fb2)», «(скачать pdf)»
_FORMAT_LABEL = re.compile(r"\(\s*(?:скачать\s+)?(\w+)\s*\)")
_FORMAT_ALIASES = {"djv": "djvu"}
_AUTHOR_BOOK_COUNT = re.compile(r"\((\d+)\s+книг")
_BOOK_ID_SCRIPT = re.compile(r"bookId\s*=\s*(\d+)")

_client: httpx.AsyncClient | None = None


@dataclass(slots=True)
class Book:
    id: str
    title: str = ""
    author: str = ""
    link: str = ""
    formats: dict[str, str] = field(default_factory=dict)
    cover: str | None = None
    size: str = ""
    annotation: str = ""

    def __str__(self) -> str:
        return f"{self.title} - {self.author} ({self.id})"


@dataclass(slots=True)
class DownloadedFile:
    content: bytes
    filename: str


class BookTooLargeError(Exception):
    def __init__(self, size: int | None = None) -> None:
        super().__init__(f"file is too large: {size if size is not None else 'unknown'} bytes")
        self.size = size


class _BookCache:
    def __init__(self, ttl: float, max_size: int) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._items: dict[str, tuple[float, Book]] = {}

    def get(self, book_id: str) -> Book | None:
        item = self._items.get(book_id)

        if item is None:
            return None

        expires_at, book = item

        if expires_at <= time.monotonic():
            del self._items[book_id]
            return None

        return _copy_book(book)

    def put(self, book: Book) -> None:
        now = time.monotonic()
        self._items.pop(book.id, None)

        if len(self._items) >= self._max_size:
            self._items = {k: v for k, v in self._items.items() if v[0] > now}

        # dict хранит порядок вставки, первый ключ — самый старый
        while len(self._items) >= self._max_size:
            del self._items[next(iter(self._items))]

        self._items[book.id] = (now + self._ttl, _copy_book(book))

    def clear(self) -> None:
        self._items.clear()


def _copy_book(book: Book) -> Book:
    return replace(book, formats=dict(book.formats))


_book_cache = _BookCache(BOOK_CACHE_TTL, BOOK_CACHE_SIZE)


def _create_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": HTTP_USER_AGENT},
        limits=httpx.Limits(
            max_connections=HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=HTTP_MAX_KEEPALIVE,
        ),
        transport=transport,
    )


def get_client() -> httpx.AsyncClient:
    """Общий клиент: переиспользует TCP-соединения между запросами."""
    global _client

    if _client is None or _client.is_closed:
        _client = _create_client()

    return _client


async def close_client() -> None:
    global _client

    if _client is not None and not _client.is_closed:
        await _client.aclose()

    _client = None


def _site() -> str:
    return settings.flibusta_url.rstrip("/")


def _absolute(href: str) -> str:
    return urllib.parse.urljoin(_site() + "/", href)


def _is_retryable(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


async def _send(url: str, *, stream: bool = False) -> httpx.Response:
    """GET с ретраями. При stream=True ответ закрывает вызывающий."""
    client = get_client()
    timeout = HTTP_DOWNLOAD_TIMEOUT if stream else HTTP_TIMEOUT
    attempt = 0

    while True:
        attempt += 1
        last_attempt = attempt >= HTTP_RETRIES

        try:
            request = client.build_request("GET", url, timeout=timeout)
            response = await client.send(request, stream=stream)

        # Таймауты, обрывы соединения и протухшие keep-alive соединения
        except httpx.TransportError:
            if last_attempt:
                raise
        else:
            if response.is_success:
                return response

            await response.aclose()

            if last_attempt or not _is_retryable(response.status_code):
                response.raise_for_status()

                # raise_for_status не бросает на 1xx/3xx, а тело уже закрыто
                raise httpx.HTTPStatusError(
                    f"Unexpected status {response.status_code} for {url}",
                    request=response.request,
                    response=response,
                )

        delay = HTTP_RETRY_DELAY * 2 ** (attempt - 1)
        await asyncio.sleep(delay * random.uniform(0.5, 1.5))


async def _read_limited(response: httpx.Response, max_size: int) -> bytes:
    declared = response.headers.get("content-length", "")

    if declared.isdigit() and int(declared) > max_size:
        raise BookTooLargeError(int(declared))

    chunks: list[bytes] = []
    total = 0

    # Content-Length может отсутствовать или врать, поэтому считаем и по факту
    async for chunk in response.aiter_bytes():
        total += len(chunk)

        if total > max_size:
            raise BookTooLargeError()

        chunks.append(chunk)

    return b"".join(chunks)


async def _scrape[T](url: str, parse: Callable[[BeautifulSoup], T]) -> T:
    response = await _send(url)
    html = response.text

    # Страницы авторов весят сотни килобайт, их разбор заметно блокирует event loop
    return await asyncio.to_thread(lambda: parse(BeautifulSoup(html, "html.parser")))


def _href(tag: Tag) -> str:
    value = tag.get("href")

    return value if isinstance(value, str) else ""


def _book_id(link: Tag) -> str | None:
    match = _BOOK_HREF.match(_href(link))

    return match.group(1) if match else None


def _is_author_link(link: Tag) -> bool:
    return _AUTHOR_HREF.match(_href(link)) is not None


def _join_authors(links: Iterable[Tag]) -> str:
    return ", ".join(link.text.strip() for link in links) or NO_AUTHOR


def _make_book(book_id: str, title: str, author: str) -> Book:
    return Book(
        id=book_id,
        title=title.strip(),
        author=author,
        link=f"{_site()}/b/{book_id}/",
    )


def _unique(books: Iterable[Book]) -> list[Book]:
    result: dict[str, Book] = {}

    for book in books:
        result.setdefault(book.id, book)

    return list(result.values())


def normalize_format(label: str) -> str | None:
    """«(fb2)» → «fb2», «(скачать pdf)» → «pdf»; None для неподдерживаемых форматов."""
    match = _FORMAT_LABEL.search(label)

    if match is None:
        return None

    book_format = match.group(1).lower()
    book_format = _FORMAT_ALIASES.get(book_format, book_format)

    return book_format if book_format in ALL_FORMATS else None


def _parse_title_search(soup: BeautifulSoup) -> list[Book]:
    books = []

    for li in soup.select("div#main li"):
        links = li.select("a[href]")
        book_id = _book_id(links[0]) if links else None

        if book_id is None:
            continue

        authors = [link for link in links[1:] if _is_author_link(link)]
        books.append(_make_book(book_id, links[0].text, _join_authors(authors)))

    return _unique(books)


def _parse_author_search(soup: BeautifulSoup) -> list[str]:
    found: list[tuple[int, str]] = []

    for li in soup.select("div#main li"):
        link = li.select_one("a[href]")
        match = _AUTHOR_HREF.match(_href(link)) if link else None

        if match is None:
            continue

        count = _AUTHOR_BOOK_COUNT.search(li.text)
        found.append((int(count.group(1)) if count else 0, match.group(1)))

    # Сайт сортирует по имени, поэтому самого известного однофамильца
    # среди первых может не быть: берём авторов с наибольшим числом книг
    found.sort(key=lambda item: item[0], reverse=True)

    return list(dict.fromkeys(author_id for _, author_id in found))[:AUTHOR_SEARCH_LIMIT]


def _parse_author_page(soup: BeautifulSoup) -> list[Book]:
    title = soup.select_one("div#main h1.title")
    form = soup.select_one('div#main form[method="POST" i]')

    if title is None or form is None:
        return []

    author = title.text.strip()
    books = []

    # Перед каждой книгой стоит svg с оценкой
    for element in form.select("svg, h3"):
        if element.name == "h3":
            # Дальше идут переводы — книги других авторов
            if element.text.strip() == "Переводы":
                break

            continue

        link = element.find_next_sibling("a")
        book_id = _book_id(link) if isinstance(link, Tag) else None

        if link is None or book_id is None:
            continue

        books.append(_make_book(book_id, link.text, author))

    return _unique(books)


def _parse_book_list(soup: BeautifulSoup) -> list[Book]:
    books = []

    for div in soup.select('form[name="bk"] div'):
        links = div.select("a[href]")
        book_link = next((link for link in links if _book_id(link)), None)
        book_id = _book_id(book_link) if book_link else None

        if book_link is None or book_id is None:
            continue

        # Авторы перечислены после размера, до него в скобках идут переводчики
        size = div.select_one("span[style=size]")
        after_size = size.find_next_siblings("a") if size else links
        authors = [link for link in after_size if isinstance(link, Tag) and _is_author_link(link)]

        if not authors:
            authors = [link for link in links if _is_author_link(link)]

        books.append(_make_book(book_id, book_link.text, _join_authors(authors)))

    return _unique(books)


def _is_book_page(main: Tag, book_id: str) -> bool:
    # На несуществующий id сайт отвечает 200 и страницей поиска «Книги по названию <id>»
    for script in main.select("script"):
        match = _BOOK_ID_SCRIPT.search(script.text)

        if match:
            return match.group(1) == book_id

    return main.select_one(f'a[href^="/b/{book_id}/"]') is not None


def _parse_annotation(main: Tag, title: Tag) -> str:
    header = main.find("h2", string=re.compile("Аннотация", re.IGNORECASE))

    if header is None:
        first_p = title.find_next_sibling("p")

        return first_p.text.strip() if first_p else ""

    paragraphs = []

    for sibling in header.next_siblings:
        if not isinstance(sibling, Tag):
            continue

        if sibling.name == "h2":
            break

        if sibling.name == "p" and sibling.text.strip():
            paragraphs.append(sibling.text.strip())

    return "\n\n".join(paragraphs)


def _parse_book(soup: BeautifulSoup, book_id: str) -> Book | None:
    main = soup.select_one("div#main")
    title = main.select_one("h1.title") if main else None

    if main is None or title is None or not _is_book_page(main, book_id):
        return None

    authors = []

    # Ссылки на авторов идут сразу за заголовком, до блока с жанрами
    for sibling in title.next_siblings:
        if not isinstance(sibling, Tag):
            continue

        if sibling.name == "div":
            break

        if sibling.name == "a" and _is_author_link(sibling):
            authors.append(sibling)

    book = _make_book(book_id, title.text, _join_authors(authors))
    book.annotation = _parse_annotation(main, title)

    size = main.select_one("span[style=size]")

    if size:
        book.size = size.text.strip()

    cover = main.select_one('img[alt="Cover image"]')
    cover_src = cover.get("src") if cover else None

    if isinstance(cover_src, str) and cover_src:
        book.cover = _absolute(cover_src)

    for link in main.select(f'a[href^="/b/{book_id}/"]'):
        book_format = normalize_format(link.text)

        if book_format:
            book.formats.setdefault(book_format, _absolute(_href(link)))

    return book


async def search_by_title(text: str) -> list[Book]:
    query = urllib.parse.quote(text)

    return await _scrape(f"{_site()}/booksearch?ask={query}&chb=on", _parse_title_search)


async def search_by_author(text: str) -> list[Book]:
    query = urllib.parse.quote(text)
    author_ids = await _scrape(f"{_site()}/booksearch?ask={query}&cha=on", _parse_author_search)

    semaphore = asyncio.Semaphore(AUTHOR_SEARCH_CONCURRENCY)

    async def load(author_id: str) -> list[Book] | httpx.HTTPError:
        async with semaphore:
            try:
                return await _scrape(f"{_site()}/a/{author_id}", _parse_author_page)
            except httpx.HTTPError as error:
                logger.warning(
                    "Failed to load author page",
                    extra={"author_id": author_id, "error": repr(error)},
                )
                return error

    pages = await asyncio.gather(*(load(author_id) for author_id in author_ids))
    loaded = [page for page in pages if isinstance(page, list)]
    errors = [page for page in pages if not isinstance(page, list)]

    # Одна упавшая страница не мешает остальным, но если упали все — это сбой сайта
    if errors and not loaded:
        raise errors[0]

    return _unique(book for page in loaded for book in page)


async def search_by_title_and_author(title: str, author: str) -> list[Book]:
    title_q = urllib.parse.quote(title)
    author_q = urllib.parse.quote(author)
    url = f"{_site()}/makebooklist?ab=ab1&t={title_q}&ln={author_q}&sort=sd2"

    return await _scrape(url, _parse_book_list)


async def get_book_by_id(book_id: str) -> Book | None:
    # id попадает в URL, а приходит в том числе из callback_data
    if not (book_id.isascii() and book_id.isdigit()):
        return None

    cached = _book_cache.get(book_id)

    if cached is not None:
        return cached

    try:
        book = await _scrape(f"{_site()}/b/{book_id}", lambda soup: _parse_book(soup, book_id))
    except httpx.HTTPStatusError as error:
        if error.response.status_code == httpx.codes.NOT_FOUND:
            return None

        raise

    if book is not None:
        _book_cache.put(book)

    return book


async def download_cover(book: Book) -> bytes | None:
    if not book.cover:
        return None

    try:
        response = await _send(book.cover, stream=True)

        try:
            return await _read_limited(response, COVER_MAX_SIZE)
        finally:
            await response.aclose()

    except (httpx.HTTPError, BookTooLargeError) as error:
        logger.warning(
            "Failed to download cover",
            extra={"book_id": book.id, "url": book.cover, "error": repr(error)},
        )
        return None


def _filename(response: httpx.Response) -> str | None:
    content_disposition = response.headers.get("content-disposition")

    if not content_disposition:
        return None

    message = Message()
    message["content-disposition"] = content_disposition

    filename = message.get_filename()

    return filename or None


def _unpack_fb2(file: DownloadedFile, max_size: int) -> DownloadedFile:
    """Сайт отдаёт fb2 в zip-архиве; если распаковать нельзя, архив уходит как есть."""
    if not file.filename.endswith(".fb2.zip"):
        return file

    try:
        with zipfile.ZipFile(io.BytesIO(file.content)) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]

            if len(members) != 1 or members[0].file_size > max_size:
                return file

            with archive.open(members[0]) as source:
                # Размер в заголовке архива может не совпадать с реальным
                content = source.read(max_size + 1)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError):
        return file

    if len(content) > max_size:
        return file

    return DownloadedFile(content=content, filename=file.filename.removesuffix(".zip"))


async def download_book(
    book: Book,
    book_format: str,
    *,
    max_size: int,
) -> DownloadedFile | None:
    url = book.formats.get(book_format)
    log_extra = {"book_id": book.id, "format": book_format, "url": url}

    if url is None:
        logger.warning("Book has no such format", extra=log_extra)
        return None

    try:
        response = await _send(url, stream=True)

        try:
            filename = _filename(response)

            # Вместо файла сайт может отдать HTML-страницу (книга удалена, нужен вход и т.п.)
            if filename is None:
                logger.warning(
                    "Download response is not a file",
                    extra={
                        **log_extra,
                        "final_url": str(response.url),
                        "content_type": response.headers.get("content-type"),
                    },
                )
                return None

            content = await _read_limited(response, max_size)
        finally:
            await response.aclose()

    except httpx.HTTPError as error:
        logger.warning("Failed to download book", extra={**log_extra, "error": repr(error)})
        return None
    except BookTooLargeError as error:
        logger.warning("Book is too large", extra={**log_extra, "size": error.size})
        raise

    file = DownloadedFile(content=content, filename=filename)

    return await asyncio.to_thread(_unpack_fb2, file, max_size)
