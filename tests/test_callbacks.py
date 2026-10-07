import pytest

from src.bot import callbacks as cb
from src.flib import ALL_FORMATS

MAX_BOOK_ID = "9" * 12


@pytest.mark.parametrize(
    "callback",
    [
        cb.ShowBook("123"),
        cb.ShowAnnotation("123"),
        cb.SwitchMode("chat", "123"),
        cb.SwitchMode("email", "123"),
        *(cb.GetBook(mode, MAX_BOOK_ID, fmt) for mode in cb.MODES for fmt in ALL_FORMATS),
        cb.ShowPage("0a1b2c3d", 0),
        cb.ShowPage("0a1b2c3d", 99_999),
        cb.Noop(),
    ],
)
def test_roundtrip_and_size_limit(callback: cb.Callback) -> None:
    data = cb.encode(callback)

    assert len(data.encode()) <= cb.MAX_CALLBACK_DATA_BYTES
    assert cb.decode(data) == callback


def test_encode_rejects_data_over_64_bytes() -> None:
    with pytest.raises(ValueError, match="64 bytes"):
        cb.encode(cb.ShowBook("1" * 80))


@pytest.mark.parametrize(
    "callback",
    [
        cb.ShowBook("12a"),
        cb.ShowBook(""),
        cb.ShowBook("../etc"),
        cb.GetBook("chat", "1", "exe"),
        cb.GetBook("ftp", "1", "fb2"),  # type: ignore[arg-type]
        cb.ShowPage("not hex", 1),
        cb.ShowPage("abcd", -1),
    ],
)
def test_encode_rejects_invalid_fields(callback: cb.Callback) -> None:
    with pytest.raises(cb.InvalidCallbackData):
        cb.encode(callback)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("find_book_by_id 123", cb.ShowBook("123")),
        ("show_annotation 123", cb.ShowAnnotation("123")),
        ("switch_mode email 123", cb.SwitchMode("email", "123")),
        ("switch_mode chat 123", cb.SwitchMode("chat", "123")),
        ("get_book chat 123 (fb2)", cb.GetBook("chat", "123", "fb2")),
        ("get_book email 123 (epub)", cb.GetBook("email", "123", "epub")),
        ("get_book chat 123 (скачать pdf)", cb.GetBook("chat", "123", "pdf")),
        ("get_book email 123 (скачать djvu)", cb.GetBook("email", "123", "djvu")),
        ("get_book chat 123 fb2", cb.GetBook("chat", "123", "fb2")),
    ],
)
def test_decode_legacy_buttons(data: str, expected: cb.Callback) -> None:
    assert cb.decode(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        None,
        "",
        "x",
        "b",
        "b:",
        "b:abc",
        "b:1:2",
        "g:c:1",
        "g:x:1:fb2",
        "g:c:1:exe",
        "m:c",
        "p:zz:1",
        "p:abcd:x",
        "p:abcd:-1",
        "n:1",
        "find_book_by_id",
        "find_book_by_id abc",
        "get_book chat 123",
        "get_book chat 123 (скачать rtf)",
        "get_book telegram 123 (fb2)",
        "switch_mode chat",
        "drop_table users",
        "b:" + "1" * 100,
    ],
)
def test_decode_rejects_garbage(data: str | None) -> None:
    with pytest.raises(cb.InvalidCallbackData):
        cb.decode(data)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("(fb2)", "fb2"), ("(скачать PDF)", "pdf"), (".epub", "epub"), ("(djvu)", "djvu")],
)
def test_normalize_format(raw: str, expected: str) -> None:
    assert cb.normalize_format(raw) == expected


@pytest.mark.parametrize(
    ("action", "data"),
    [
        (cb.ShowBook("7"), "r:b:7"),
        (cb.GetBook("email", "1234567", "djvu"), "r:g:e:1234567:djvu"),
        (cb.ShowPage("abcdef12", 3), "r:p:abcdef12:3"),
    ],
)
def test_retry_roundtrip(action: cb.Action, data: str) -> None:
    assert cb.encode(cb.Retry(action)) == data
    assert cb.decode(data) == cb.Retry(action)


@pytest.mark.parametrize("data", ["r:", "r:n", "r:r:b:7", "r:x:1"])
def test_retry_rejects_bad_action(data: str) -> None:
    with pytest.raises(cb.InvalidCallbackData):
        cb.decode(data)
