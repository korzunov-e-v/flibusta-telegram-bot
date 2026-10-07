"""Протокол callback_data инлайн-кнопок: всё кодирование и разбор — только здесь.

Текущий формат — поля через двоеточие: ``b:<id>``, ``a:<id>``, ``m:<c|e>:<id>``,
``g:<c|e>:<id>:<format>``, ``p:<search_id>:<page>``, ``n``, а также ``r:<действие>`` —
повтор действия после сбоя.
Кнопки, выпущенные до его появления (``get_book chat 123 (fb2)`` и т.п.), тоже разбираются.
"""

import re
from dataclasses import dataclass
from typing import Literal, get_args

from src.flib import ALL_FORMATS

MAX_CALLBACK_DATA_BYTES = 64

Mode = Literal["chat", "email"]
MODES: tuple[Mode, ...] = get_args(Mode)

_MODE_TO_CODE: dict[Mode, str] = {"chat": "c", "email": "e"}
_CODE_TO_MODE: dict[str, Mode] = {code: mode for mode, code in _MODE_TO_CODE.items()}

_SEARCH_ID_RE = re.compile(r"[0-9a-f]{1,16}")
# длинные форматы раньше коротких на случай общих подстрок
_FORMAT_RE = re.compile("|".join(sorted(ALL_FORMATS, key=len, reverse=True)))


class InvalidCallbackData(ValueError):
    """Данные кнопки не разобрать: устаревшая кнопка либо подделка."""


@dataclass(frozen=True, slots=True)
class ShowBook:
    book_id: str


@dataclass(frozen=True, slots=True)
class ShowAnnotation:
    book_id: str


@dataclass(frozen=True, slots=True)
class SwitchMode:
    mode: Mode
    book_id: str


@dataclass(frozen=True, slots=True)
class GetBook:
    mode: Mode
    book_id: str
    book_format: str


@dataclass(frozen=True, slots=True)
class ShowPage:
    search_id: str
    page: int


@dataclass(frozen=True, slots=True)
class Noop:
    pass


Action = ShowBook | ShowAnnotation | SwitchMode | GetBook | ShowPage


@dataclass(frozen=True, slots=True)
class Retry:
    """Кнопка «Повторить» под сообщением об ошибке."""

    action: Action


Callback = Action | Retry | Noop


def _check_book_id(book_id: str) -> str:
    if not (book_id.isascii() and book_id.isdigit()):
        raise InvalidCallbackData(f"bad book id: {book_id!r}")

    return book_id


def _check_mode(mode: str) -> Mode:
    for known in MODES:
        if mode == known:
            return known

    raise InvalidCallbackData(f"bad mode: {mode!r}")


def _check_format(book_format: str) -> str:
    if book_format not in ALL_FORMATS:
        raise InvalidCallbackData(f"bad format: {book_format!r}")

    return book_format


def _check_search_id(search_id: str) -> str:
    if not _SEARCH_ID_RE.fullmatch(search_id):
        raise InvalidCallbackData(f"bad search id: {search_id!r}")

    return search_id


def _check_page(page: str | int) -> int:
    if isinstance(page, str) and not (page.isascii() and page.isdigit()):
        raise InvalidCallbackData(f"bad page: {page!r}")

    number = int(page)

    if not 0 <= number < 100_000:
        raise InvalidCallbackData(f"bad page: {page!r}")

    return number


def encode(callback: Callback) -> str:
    match callback:
        case ShowBook(book_id):
            data = f"b:{_check_book_id(book_id)}"
        case ShowAnnotation(book_id):
            data = f"a:{_check_book_id(book_id)}"
        case SwitchMode(mode, book_id):
            data = f"m:{_MODE_TO_CODE[_check_mode(mode)]}:{_check_book_id(book_id)}"
        case GetBook(mode, book_id, book_format):
            data = (
                f"g:{_MODE_TO_CODE[_check_mode(mode)]}"
                f":{_check_book_id(book_id)}:{_check_format(book_format)}"
            )
        case ShowPage(search_id, page):
            data = f"p:{_check_search_id(search_id)}:{_check_page(page)}"
        case Retry(action):
            if isinstance(action, Retry | Noop):
                raise TypeError(f"action can not be retried: {action!r}")

            data = f"r:{encode(action)}"
        case Noop():
            data = "n"
        case _:
            raise TypeError(f"unknown callback: {callback!r}")

    if len(data.encode()) > MAX_CALLBACK_DATA_BYTES:
        raise ValueError(f"callback data exceeds {MAX_CALLBACK_DATA_BYTES} bytes: {data!r}")

    return data


def normalize_format(raw: str) -> str:
    """'(fb2)', '(скачать pdf)', '.EPUB' -> 'fb2', 'pdf', 'epub'."""
    match = _FORMAT_RE.search(raw.lower())

    if match is None:
        raise InvalidCallbackData(f"bad format: {raw!r}")

    return match.group()


def _decode_legacy(data: str) -> Callback:
    command, _, arg = data.partition(" ")
    arg = arg.strip()

    match command:
        case "find_book_by_id":
            return ShowBook(_check_book_id(arg))
        case "show_annotation":
            return ShowAnnotation(_check_book_id(arg))
        case "switch_mode":
            mode, _, book_id = arg.partition(" ")
            return SwitchMode(_check_mode(mode), _check_book_id(book_id.strip()))
        case "get_book":
            parts = arg.split(" ", maxsplit=2)

            if len(parts) != 3:
                raise InvalidCallbackData(f"bad get_book: {data!r}")

            mode, book_id, raw_format = parts
            return GetBook(_check_mode(mode), _check_book_id(book_id), normalize_format(raw_format))
        case _:
            raise InvalidCallbackData(f"unknown command: {data!r}")


def _decode_current(data: str) -> Callback:
    if data.startswith("r:"):
        action = _decode_current(data.removeprefix("r:"))

        if isinstance(action, Retry | Noop):
            raise InvalidCallbackData(f"bad retry: {data!r}")

        return Retry(action)

    kind, *args = data.split(":")

    match kind, args:
        case "b", [book_id]:
            return ShowBook(_check_book_id(book_id))
        case "a", [book_id]:
            return ShowAnnotation(_check_book_id(book_id))
        case "m", [mode, book_id] if mode in _CODE_TO_MODE:
            return SwitchMode(_CODE_TO_MODE[mode], _check_book_id(book_id))
        case "g", [mode, book_id, book_format] if mode in _CODE_TO_MODE:
            return GetBook(_CODE_TO_MODE[mode], _check_book_id(book_id), _check_format(book_format))
        case "p", [search_id, page]:
            return ShowPage(_check_search_id(search_id), _check_page(page))
        case "n", []:
            return Noop()
        case _:
            raise InvalidCallbackData(f"unknown callback: {data!r}")


def decode(data: str | None) -> Callback:
    if not data or len(data.encode()) > MAX_CALLBACK_DATA_BYTES:
        raise InvalidCallbackData(f"bad callback data: {data!r}")

    if " " in data:
        return _decode_legacy(data)

    return _decode_current(data)
