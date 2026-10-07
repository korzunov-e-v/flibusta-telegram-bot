import httpx
import pytest

from src import flib
from src.bot import search
from src.bot.search import SearchCache, SearchFailed, SearchQuery, SearchResult, parse_query
from src.flib import Book


def _book(book_id: str, title: str = "T") -> Book:
    return Book(id=book_id, title=title, author="A")


def _returns(*books: Book):
    async def source(*_: str) -> list[Book]:
        return list(books)

    return source


def _raises(error: Exception):
    async def source(*_: str) -> list[Book]:
        raise error

    return source


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1984", SearchQuery("1984")),
        ("  1984  \n  Оруэлл ", SearchQuery("1984", "Оруэлл")),
        ("1984\n\n\nОруэлл\nлишнее", SearchQuery("1984", "Оруэлл")),
        ("война   и\tмир", SearchQuery("война и мир")),
        ("\n  \nтолько вторая", SearchQuery("только вторая")),
        ("", None),
        (" \n\t\n ", None),
    ],
)
def test_parse_query(text: str, expected: SearchQuery | None) -> None:
    assert parse_query(text) == expected


def test_parse_query_truncates_long_lines() -> None:
    query = parse_query("a" * 5000 + "\n" + "b" * 5000)

    assert query == SearchQuery("a" * search.MAX_QUERY_LENGTH, "b" * search.MAX_QUERY_LENGTH)


def test_dedupe_keeps_first_and_drops_bad_ids() -> None:
    books = [_book("1", "first"), _book("2"), _book("1", "second"), _book("abc"), _book("")]

    assert [(b.id, b.title) for b in search.dedupe(books)] == [("1", "first"), ("2", "T")]


async def test_run_search_merges_title_and_author(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flib, "search_by_title", _returns(_book("1"), _book("2")))
    monkeypatch.setattr(flib, "search_by_author", _returns(_book("2"), _book("3")))

    result = await search.run_search(SearchQuery("запрос"))

    assert [b.id for b in result.books] == ["1", "2", "3"]
    assert not result.partial and not result.truncated


async def test_run_search_survives_one_failed_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flib, "search_by_title", _returns(_book("1")))
    monkeypatch.setattr(flib, "search_by_author", _raises(httpx.ConnectError("boom")))

    result = await search.run_search(SearchQuery("запрос"))

    assert [b.id for b in result.books] == ["1"]
    assert result.partial


async def test_run_search_parser_bug_is_a_failed_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flib, "search_by_title", _raises(AttributeError("layout changed")))
    monkeypatch.setattr(flib, "search_by_author", _returns())

    result = await search.run_search(SearchQuery("запрос"))

    assert result.books == [] and result.partial


async def test_run_search_all_sources_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flib, "search_by_title", _raises(httpx.ConnectError("a")))
    monkeypatch.setattr(flib, "search_by_author", _raises(httpx.ReadTimeout("b")))

    with pytest.raises(SearchFailed) as exc_info:
        await search.run_search(SearchQuery("запрос"))

    assert len(exc_info.value.errors) == 2


async def test_run_search_numeric_query_puts_exact_id_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def by_id(book_id: str) -> Book | None:
        return _book(book_id, "by id")

    monkeypatch.setattr(flib, "get_book_by_id", by_id)
    monkeypatch.setattr(flib, "search_by_title", _returns(_book("7"), _book("1984", "by title")))
    monkeypatch.setattr(flib, "search_by_author", _returns())

    result = await search.run_search(SearchQuery("1984"))

    assert [(b.id, b.title) for b in result.books] == [("1984", "by id"), ("7", "T")]


async def test_run_search_with_author_uses_combined_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def combined(title: str, author: str) -> list[Book]:
        calls.append((title, author))
        return [_book("5")]

    monkeypatch.setattr(flib, "search_by_title_and_author", combined)
    monkeypatch.setattr(flib, "search_by_title", _raises(AssertionError("must not be called")))
    monkeypatch.setattr(flib, "search_by_author", _raises(AssertionError("must not be called")))

    result = await search.run_search(SearchQuery("1984", "Оруэлл"))

    assert calls == [("1984", "Оруэлл")]
    assert [b.id for b in result.books] == ["5"]


async def test_run_search_caps_results(monkeypatch: pytest.MonkeyPatch) -> None:
    many = [_book(str(i)) for i in range(1, search.MAX_RESULTS + 50)]
    monkeypatch.setattr(flib, "search_by_title", _returns(*many))
    monkeypatch.setattr(flib, "search_by_author", _returns())

    result = await search.run_search(SearchQuery("запрос"))

    assert len(result.books) == search.MAX_RESULTS
    assert result.truncated


def test_search_cache_ttl_and_eviction() -> None:
    now = [0.0]
    cache = SearchCache(ttl=10, max_entries=2, clock=lambda: now[0])
    result = SearchResult(books=[_book("1")])

    cache.put(1, "a", result)
    assert cache.get(1, "a") is result
    assert cache.get(2, "a") is None  # чужая выдача недоступна

    now[0] = 10
    assert cache.get(1, "a") is None

    cache.put(1, "a", result)
    cache.put(1, "b", result)
    cache.get(1, "a")
    cache.put(1, "c", result)

    assert cache.get(1, "b") is None  # вытеснена как давно не использованная
    assert cache.get(1, "a") is result and cache.get(1, "c") is result


def test_remember_and_recall_query() -> None:
    user_data: dict[str, object] = {}

    ids = [search.remember_query(user_data, SearchQuery(f"q{i}", "a")) for i in range(7)]

    assert len(set(ids)) == 7
    assert len(user_data[search.SEARCHES_KEY]) == search.MAX_SEARCHES_PER_USER  # type: ignore[arg-type]
    assert search.recall_query(user_data, ids[0]) is None
    assert search.recall_query(user_data, ids[-1]) == SearchQuery("q6", "a")
    assert search.recall_query(user_data, "ffff") is None
    assert search.recall_query({}, ids[-1]) is None
    assert search.recall_query({search.SEARCHES_KEY: {"x": "мусор"}}, "x") is None
