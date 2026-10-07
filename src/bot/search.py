import asyncio
import secrets
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from src import flib
from src.custom_logging import get_logger
from src.flib import Book

logger = get_logger(__name__)

MAX_QUERY_LENGTH = 100
MAX_RESULTS = 200

# В user_data (persistence) хранится только сам запрос; найденные книги лежат
# в памяти процесса, а после рестарта или вытеснения поиск повторяется при листании.
SEARCHES_KEY = "searches"
MAX_SEARCHES_PER_USER = 5

CACHE_TTL = 30 * 60
CACHE_MAX_ENTRIES = 500


class SearchFailed(Exception):
    """Все источники поиска завершились ошибкой."""

    def __init__(self, errors: list[Exception]) -> None:
        super().__init__(f"all {len(errors)} search sources failed")
        self.errors = errors


@dataclass(frozen=True, slots=True)
class SearchQuery:
    title: str
    author: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "author": self.author}

    @classmethod
    def from_dict(cls, data: Any) -> "SearchQuery | None":
        if not isinstance(data, dict) or not isinstance(data.get("title"), str):
            return None

        return cls(title=data["title"], author=str(data.get("author") or ""))


@dataclass(frozen=True, slots=True)
class SearchResult:
    books: list[Book]
    partial: bool = False
    truncated: bool = False


def _clean(line: str) -> str:
    return " ".join(line.split())[:MAX_QUERY_LENGTH].rstrip()


def parse_query(text: str) -> SearchQuery | None:
    """Первая непустая строка — название (или автор), вторая — фамилия автора."""
    lines = [cleaned for line in text.splitlines() if (cleaned := _clean(line))]

    if not lines:
        return None

    return SearchQuery(title=lines[0], author=lines[1] if len(lines) > 1 else "")


def dedupe(books: Iterable[Book]) -> list[Book]:
    seen: set[str] = set()
    result: list[Book] = []

    for book in books:
        # нецифровой id не пройдёт в callback_data и говорит о сбое парсинга
        if book.id in seen or not (book.id.isascii() and book.id.isdigit()):
            continue

        seen.add(book.id)
        result.append(book)

    return result


async def _by_id(book_id: str) -> list[Book]:
    book = await flib.get_book_by_id(book_id)

    return [book] if book else []


def _sources(query: SearchQuery) -> list[Callable[[], Awaitable[list[Book]]]]:
    if query.author:
        return [lambda: flib.search_by_title_and_author(query.title, query.author)]

    sources: list[Callable[[], Awaitable[list[Book]]]] = []

    # точное совпадение по номеру книги — первым в выдаче
    if query.title.isascii() and query.title.isdigit():
        sources.append(lambda: _by_id(query.title))

    sources.append(lambda: flib.search_by_title(query.title))
    sources.append(lambda: flib.search_by_author(query.title))

    return sources


async def run_search(query: SearchQuery) -> SearchResult:
    """Источники опрашиваются параллельно и независимо: сбой одного не обнуляет остальные."""
    outcomes = await asyncio.gather(
        *(source() for source in _sources(query)),
        return_exceptions=True,
    )

    books: list[Book] = []
    errors: list[Exception] = []

    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning(
                "Search source failed",
                extra={"exception_type": type(outcome).__name__, "exception": repr(outcome)},
                exc_info=outcome,
            )
            errors.append(outcome)
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            books += outcome or []

    if errors and len(errors) == len(outcomes):
        raise SearchFailed(errors)

    books = dedupe(books)

    return SearchResult(
        books=books[:MAX_RESULTS],
        partial=bool(errors),
        truncated=len(books) > MAX_RESULTS,
    )


class SearchCache:
    def __init__(
        self,
        ttl: float = CACHE_TTL,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[tuple[int, str], tuple[float, SearchResult]] = OrderedDict()

    def put(self, user_id: int, search_id: str, result: SearchResult) -> None:
        key = (user_id, search_id)
        self._items[key] = (self._clock() + self._ttl, result)
        self._items.move_to_end(key)

        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)

    def get(self, user_id: int, search_id: str) -> SearchResult | None:
        key = (user_id, search_id)
        item = self._items.get(key)

        if item is None:
            return None

        expires_at, result = item

        if expires_at <= self._clock():
            del self._items[key]
            return None

        self._items.move_to_end(key)

        return result


cache = SearchCache()


def remember_query(user_data: dict[Any, Any], query: SearchQuery) -> str:
    """Запоминает запрос пользователя и возвращает id выдачи для кнопок листания."""
    searches = user_data.get(SEARCHES_KEY)

    if not isinstance(searches, dict):
        searches = user_data[SEARCHES_KEY] = {}

    search_id = secrets.token_hex(4)
    searches[search_id] = query.to_dict()

    while len(searches) > MAX_SEARCHES_PER_USER:
        del searches[next(iter(searches))]

    return search_id


def recall_query(user_data: dict[Any, Any], search_id: str) -> SearchQuery | None:
    searches = user_data.get(SEARCHES_KEY)

    if not isinstance(searches, dict):
        return None

    return SearchQuery.from_dict(searches.get(search_id))
