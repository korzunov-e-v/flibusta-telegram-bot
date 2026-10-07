from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from telegram.error import BadRequest, Forbidden, TimedOut

from src import flib, mailer
from src.bot import callbacks as cb
from src.bot import errors, search, texts, throttle, verification
from src.bot.buttons import button
from src.bot.commands import cancel_command, email_command, start_command
from src.bot.helpers import status_message
from src.bot.keyboards import book_keyboard
from src.bot.messages import handle_text
from src.database import crud
from src.flib import Book, DownloadedFile
from src.settings import settings
from tests.conftest import (
    CHAT_ID,
    USER_ID,
    make_callback_update,
    make_message_update,
    replies,
    sent_texts,
)

BOOK = Book(
    id="7",
    title="Tom & <Jerry>",
    author="Автор",
    link="https://flibusta.is/b/7",
    formats={"fb2": "https://flibusta.is/b/7/fb2", "pdf": "https://flibusta.is/b/7/pdf"},
    cover="https://flibusta.is/i/7/cover.jpg",
    annotation="Аннотация <b>&</b>",
)


class FakeDB:
    """Подмена src.database.crud: адреса и журнал писем в памяти."""

    def __init__(self) -> None:
        self.emails: dict[int, str] = {}
        self.sent: list[tuple[int, str]] = []

    async def get_email(self, user_id: int) -> str | None:
        return self.emails.get(user_id)

    async def set_email(self, user_id: int, email: str) -> None:
        self.emails[user_id] = email

    async def log_sent_email(self, user_id: int, kind: str) -> None:
        self.sent.append((user_id, kind))

    async def count_sent_emails(self, user_id: int, kind: str, period: timedelta) -> int:
        return self.sent.count((user_id, kind))


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> FakeDB:
    fake = FakeDB()

    for name in ("get_email", "set_email", "log_sent_email", "count_sent_emails"):
        monkeypatch.setattr(crud, name, getattr(fake, name))

    return fake


@pytest.fixture
def mail(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {"send_book": AsyncMock(), "send_code": AsyncMock()}

    for name, mock in mocks.items():
        monkeypatch.setattr(mailer, name, mock)

    return mocks


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "get_book_by_id": AsyncMock(return_value=BOOK),
        "download_cover": AsyncMock(return_value=b"jpeg"),
        "download_book": AsyncMock(return_value=DownloadedFile(b"data", "book.fb2")),
        "search_by_title": AsyncMock(return_value=[]),
        "search_by_author": AsyncMock(return_value=[]),
        "search_by_title_and_author": AsyncMock(return_value=[]),
    }

    for name, mock in mocks.items():
        monkeypatch.setattr(flib, name, mock)

    return mocks


def _books(count: int) -> list[Book]:
    return [Book(id=str(i), title=f"Книга {i}", author="Автор") for i in range(1, count + 1)]


# --- callback-кнопки -------------------------------------------------------


@pytest.mark.parametrize("data", ["мусор", "get_book chat 7 (rtf)", "b:abc", None])
async def test_button_stale_data_gets_polite_answer(context: MagicMock, data: str | None) -> None:
    update = make_callback_update(data)

    await button(update, context)

    update.callback_query.answer.assert_awaited_once_with(text=texts.STALE_BUTTON, show_alert=True)
    context.bot.send_message.assert_not_awaited()


async def test_show_book_sends_cover_bytes_with_escaped_caption(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    update = make_callback_update(cb.encode(cb.ShowBook("7")))

    await button(update, context)

    kwargs = context.bot.send_photo.await_args.kwargs
    assert kwargs["photo"] == b"jpeg"
    assert kwargs["parse_mode"] == "HTML"
    assert "<b>Tom &amp; &lt;Jerry&gt;</b>" in kwargs["caption"]
    assert kwargs["reply_markup"] == book_keyboard("7", ["fb2", "pdf"])
    # статус «идёт загрузка» отправлен и удалён
    assert sent_texts(context.bot) == [texts.LOADING]
    context.bot.send_message.return_value.delete.assert_awaited_once()


async def test_show_book_without_cover_or_with_rejected_cover(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    context.bot.send_photo.side_effect = BadRequest("IMAGE_PROCESS_FAILED")

    await button(make_callback_update("find_book_by_id 7"), context)

    card = context.bot.send_message.await_args_list[-1].kwargs
    assert card["text"].startswith(texts.NO_COVER)
    assert card["parse_mode"] == "HTML"


async def test_show_book_not_found(context: MagicMock, site: dict[str, AsyncMock]) -> None:
    site["get_book_by_id"].return_value = None

    await button(make_callback_update("b:7"), context)

    assert sent_texts(context.bot) == [texts.LOADING, texts.BOOK_NOT_FOUND]


async def test_flibusta_error_is_reported_to_user(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    site["get_book_by_id"].side_effect = httpx.ConnectError("boom")

    await button(make_callback_update("b:7"), context)

    assert sent_texts(context.bot) == [texts.LOADING, texts.FLIBUSTA_ERROR]
    context.bot.send_message.return_value.delete.assert_awaited_once()


async def test_unexpected_error_answers_user_and_notifies_admins(
    context: MagicMock, site: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admins", [1, 2])
    site["get_book_by_id"].side_effect = RuntimeError("баг")

    await button(make_callback_update("b:7"), context)

    calls = context.bot.send_message.await_args_list
    assert [c.kwargs["chat_id"] for c in calls] == [CHAT_ID, CHAT_ID, 1, 2]
    assert calls[1].kwargs["text"] == texts.UNEXPECTED_ERROR
    assert "RuntimeError" in calls[2].kwargs["text"]


async def test_show_annotation(context: MagicMock, site: dict[str, AsyncMock]) -> None:
    await button(make_callback_update("show_annotation 7"), context)

    sent = context.bot.send_message.await_args_list[-1].kwargs
    assert sent["text"] == "📖 <b>Tom &amp; &lt;Jerry&gt;</b>\n\nАннотация &lt;b&gt;&amp;&lt;/b&gt;"
    assert sent["parse_mode"] == "HTML"


async def test_switch_mode_does_not_hit_the_site(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    update = make_callback_update("m:e:7", reply_markup=book_keyboard("7", ["fb2", "pdf"]))

    await button(update, context)

    site["get_book_by_id"].assert_not_awaited()
    update.callback_query.edit_message_reply_markup.assert_awaited_once_with(
        reply_markup=book_keyboard("7", ["fb2", "pdf"], mode="email")
    )


async def test_switch_mode_ignores_not_modified(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    update = make_callback_update("m:c:7", reply_markup=book_keyboard("7", ["fb2"]))
    update.callback_query.edit_message_reply_markup.side_effect = BadRequest(
        "Message is not modified: specified new message content is the same"
    )

    await button(update, context)

    context.bot.send_message.assert_not_awaited()


async def test_get_book_to_chat(context: MagicMock, site: dict[str, AsyncMock]) -> None:
    await button(make_callback_update("get_book chat 7 (fb2)"), context)

    site["download_book"].assert_awaited_once_with(BOOK, "fb2", max_size=50 * 1024 * 1024)
    context.bot.send_document.assert_awaited_once_with(
        chat_id=CHAT_ID, document=b"data", filename="book.fb2"
    )
    context.bot.send_message.return_value.delete.assert_awaited_once()


async def test_get_book_too_large(context: MagicMock, site: dict[str, AsyncMock]) -> None:
    site["download_book"].side_effect = flib.BookTooLargeError(80 * 1024 * 1024)

    await button(make_callback_update("g:c:7:fb2"), context)

    assert "Файл слишком большой (размер файла — 80.0 МБ)" in sent_texts(context.bot)[-1]
    context.bot.send_document.assert_not_awaited()


async def test_get_book_missing_format_and_failed_download(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    await button(make_callback_update("g:c:7:djvu"), context)
    assert sent_texts(context.bot)[-1] == texts.FORMAT_UNAVAILABLE

    site["download_book"].return_value = None
    await button(make_callback_update("g:c:7:fb2"), context)
    assert sent_texts(context.bot)[-1] == texts.DOWNLOAD_FAILED


async def test_get_book_while_busy_is_throttled(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    update = make_callback_update("g:c:7:fb2")

    with throttle.heavy.slot(USER_ID):
        await button(update, context)

    update.callback_query.answer.assert_awaited_once_with(
        text=texts.THROTTLED_BUSY, show_alert=False
    )
    site["download_book"].assert_not_awaited()


async def test_get_book_by_email(
    context: MagicMock, site: dict[str, AsyncMock], db: FakeDB, mail: dict[str, AsyncMock]
) -> None:
    db.emails[USER_ID] = "reader@example.com"

    await button(make_callback_update("g:e:7:fb2"), context)

    site["download_book"].assert_awaited_once_with(BOOK, "fb2", max_size=18 * 1024 * 1024)
    mail["send_book"].assert_awaited_once_with(b"data", "book.fb2", "reader@example.com")
    assert db.sent == [(USER_ID, crud.KIND_BOOK)]
    assert "успешно отправлена на reader@example.com" in sent_texts(context.bot)[-1]
    assert "parse_mode" not in context.bot.send_message.await_args_list[-1].kwargs


async def test_get_book_by_email_daily_limit(
    context: MagicMock, site: dict[str, AsyncMock], db: FakeDB, mail: dict[str, AsyncMock]
) -> None:
    db.emails[USER_ID] = "reader@example.com"
    db.sent = [(USER_ID, crud.KIND_BOOK)] * settings.email_daily_limit

    await button(make_callback_update("g:e:7:fb2"), context)

    assert "Достигнут лимит" in sent_texts(context.bot)[-1]
    site["download_book"].assert_not_awaited()
    mail["send_book"].assert_not_awaited()


async def test_get_book_by_email_smtp_failure_is_not_counted(
    context: MagicMock, site: dict[str, AsyncMock], db: FakeDB, mail: dict[str, AsyncMock]
) -> None:
    db.emails[USER_ID] = "reader@example.com"
    mail["send_book"].side_effect = OSError("smtp down")

    await button(make_callback_update("g:e:7:fb2"), context)

    assert sent_texts(context.bot)[-1] == texts.EMAIL_SEND_FAILED
    assert db.sent == []


# --- подтверждение адреса --------------------------------------------------


async def test_full_email_flow_from_button_to_delivery(
    context: MagicMock, site: dict[str, AsyncMock], db: FakeDB, mail: dict[str, AsyncMock]
) -> None:
    # 1. кнопка «на почту» без сохранённого адреса — бот просит адрес
    await button(make_callback_update("g:e:7:pdf"), context)

    assert sent_texts(context.bot) == [texts.EMAIL_ASK]
    site["download_book"].assert_not_awaited()

    # 2. невалидный адрес — остаёмся в режиме ввода
    update = make_message_update("не адрес")
    await handle_text(update, context)
    assert replies(update) == [texts.EMAIL_INVALID_RETRY]

    # 3. валидный адрес — уходит код, адрес ещё не сохранён
    update = make_message_update("Reader@Example.com")
    await handle_text(update, context)

    code, to_email = mail["send_code"].await_args_list[0].args
    assert to_email == "Reader@example.com"
    assert db.emails == {} and db.sent == [(USER_ID, crud.KIND_CODE)]
    assert "отправлено письмо с кодом" in replies(update)[0]

    # 4. неверный код
    update = make_message_update("000000" if code != "000000" else "111111")
    await handle_text(update, context)
    assert replies(update) == [texts.EMAIL_CODE_WRONG.format(left=4)]

    # 5. пока ждём код, обычный текст — это поиск
    update = make_message_update("1984\nОруэлл")
    await handle_text(update, context)
    site["search_by_title_and_author"].assert_awaited_once_with("1984", "Оруэлл")

    # 6. верный код — адрес сохранён, отложенная книга отправлена
    update = make_message_update(code)
    await handle_text(update, context)

    assert db.emails == {USER_ID: "Reader@example.com"}
    assert "подтверждён" in replies(update)[0]
    site["download_book"].assert_awaited_once_with(BOOK, "pdf", max_size=18 * 1024 * 1024)
    mail["send_book"].assert_awaited_once_with(b"data", "book.fb2", "Reader@example.com")
    assert verification.FLOW_KEY not in context.user_data


async def test_email_command_requires_code_and_keeps_old_address(
    context: MagicMock, db: FakeDB, mail: dict[str, AsyncMock]
) -> None:
    db.emails[USER_ID] = "old@example.com"
    context.args = ["new@example.com"]
    update = make_message_update("/email new@example.com")

    await email_command(update, context)

    assert db.emails[USER_ID] == "old@example.com"
    assert mail["send_code"].await_args_list[0].args[1] == "new@example.com"

    context.args = []
    update = make_message_update("/email")
    await email_command(update, context)

    assert "old@example.com" in replies(update)[0] and "new@example.com" in replies(update)[0]


async def test_email_command_validation_and_same_address(
    context: MagicMock, db: FakeDB, mail: dict[str, AsyncMock]
) -> None:
    db.emails[USER_ID] = "old@example.com"

    for arg, expected in (
        ("мусор", texts.EMAIL_INVALID),
        ("old@example.com", texts.EMAIL_UNCHANGED.format(email="old@example.com")),
    ):
        context.args = [arg]
        update = make_message_update(f"/email {arg}")
        await email_command(update, context)

        assert replies(update) == [expected]

    mail["send_code"].assert_not_awaited()


async def test_verification_codes_per_day_are_limited(
    context: MagicMock, db: FakeDB, mail: dict[str, AsyncMock]
) -> None:
    db.sent = [(USER_ID, crud.KIND_CODE)] * verification.MAX_CODES_PER_DAY
    context.args = ["new@example.com"]
    update = make_message_update("/email new@example.com")

    await email_command(update, context)

    assert replies(update) == [texts.EMAIL_CODE_LIMIT]
    mail["send_code"].assert_not_awaited()


async def test_code_send_failure(
    context: MagicMock, db: FakeDB, mail: dict[str, AsyncMock]
) -> None:
    mail["send_code"].side_effect = OSError("smtp down")
    context.args = ["new@example.com"]
    update = make_message_update("/email new@example.com")

    await email_command(update, context)

    assert replies(update) == [texts.EMAIL_CODE_SEND_FAILED]
    assert verification.FLOW_KEY not in context.user_data
    assert db.sent == [(USER_ID, crud.KIND_CODE)]  # попытка всё равно идёт в лимит


@pytest.mark.parametrize("command", [cancel_command, start_command])
async def test_cancel_and_start_leave_email_mode(
    context: MagicMock, site: dict[str, AsyncMock], command: Any
) -> None:
    verification.await_email(context.user_data, book_id="7", book_format="fb2")

    await command(make_message_update("/cancel"), context)
    assert verification.FLOW_KEY not in context.user_data

    await handle_text(make_message_update("1984"), context)
    site["search_by_title"].assert_awaited_once_with("1984")


async def test_cancel_without_pending_request(context: MagicMock) -> None:
    update = make_message_update("/cancel")

    await cancel_command(update, context)

    assert replies(update) == [texts.NOTHING_TO_CANCEL]


async def test_expired_email_request_falls_back_to_search(
    context: MagicMock, site: dict[str, AsyncMock], mail: dict[str, AsyncMock]
) -> None:
    verification.await_email(context.user_data, now=0)

    await handle_text(make_message_update("reader@example.com"), context)

    mail["send_code"].assert_not_awaited()
    site["search_by_title"].assert_awaited_once_with("reader@example.com")
    assert verification.FLOW_KEY not in context.user_data


async def test_expired_code(context: MagicMock, db: FakeDB) -> None:
    verification.await_code(context.user_data, email="a@example.com", code="123456", now=0)
    update = make_message_update("123456")

    await handle_text(update, context)

    assert replies(update) == [texts.EMAIL_CODE_EXPIRED]
    assert db.emails == {}


# --- поиск и листание ------------------------------------------------------


async def test_search_shows_first_page(context: MagicMock, site: dict[str, AsyncMock]) -> None:
    site["search_by_title"].return_value = _books(25)
    site["search_by_author"].return_value = _books(3)
    update = make_message_update("книга")

    await handle_text(update, context)

    (call,) = update.effective_message.reply_text.await_args_list
    markup = call.kwargs["reply_markup"]
    (search_id,) = context.user_data[search.SEARCHES_KEY]

    assert call.args[0] == "Найдено книг: 25. Страница 1 из 3. Выберите книгу:"
    assert len(markup.inline_keyboard) == 11
    assert markup.inline_keyboard[-1][-1].callback_data == f"p:{search_id}:1"
    assert sent_texts(context.bot) == [texts.SEARCHING]
    context.bot.send_message.return_value.delete.assert_awaited_once()


async def test_search_nothing_found_and_errors(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    update = make_message_update("книга\nЛев Толстой")
    await handle_text(update, context)
    assert replies(update) == [texts.NOTHING_FOUND + "\n\n" + texts.AUTHOR_HINT]

    site["search_by_title"].side_effect = httpx.ConnectError("a")
    site["search_by_author"].side_effect = httpx.ConnectError("b")
    update = make_message_update("книга")
    await handle_text(update, context)

    assert sent_texts(context.bot)[-1] == texts.FLIBUSTA_ERROR
    assert search.SEARCHES_KEY not in context.user_data


async def test_empty_text(context: MagicMock, site: dict[str, AsyncMock]) -> None:
    update = make_message_update("   ")

    await handle_text(update, context)

    assert replies(update) == [texts.EMPTY_QUERY]


async def test_parallel_search_of_same_user_is_throttled(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    with throttle.heavy.slot(USER_ID):
        await handle_text(make_message_update("книга"), context)

    assert sent_texts(context.bot) == [texts.THROTTLED_BUSY]
    site["search_by_title"].assert_not_awaited()


async def test_paging_uses_cache_and_survives_newer_searches(
    context: MagicMock, site: dict[str, AsyncMock]
) -> None:
    site["search_by_title"].return_value = _books(25)
    await handle_text(make_message_update("первый"), context)
    (first_id,) = context.user_data[search.SEARCHES_KEY]

    site["search_by_title"].return_value = _books(12)
    await handle_text(make_message_update("второй"), context)
    site["search_by_title"].reset_mock()

    update = make_callback_update(f"p:{first_id}:2")
    await button(update, context)

    (text,) = update.callback_query.edit_message_text.await_args.args
    markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]

    assert text == "Найдено книг: 25. Страница 3 из 3. Выберите книгу:"
    assert [row[0].callback_data for row in markup.inline_keyboard[:-1]] == [
        f"b:{i}" for i in range(21, 26)
    ]
    site["search_by_title"].assert_not_awaited()


async def test_paging_after_restart_repeats_search(
    context: MagicMock, site: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    site["search_by_title"].return_value = _books(25)
    await handle_text(make_message_update("книга"), context)
    (search_id,) = context.user_data[search.SEARCHES_KEY]

    monkeypatch.setattr(search, "cache", search.SearchCache())  # «рестарт»: память пуста
    site["search_by_title"].reset_mock()

    update = make_callback_update(f"p:{search_id}:1")
    await button(update, context)

    site["search_by_title"].assert_awaited_once_with("книга")
    assert "Страница 2 из 3" in update.callback_query.edit_message_text.await_args.args[0]


async def test_paging_unknown_search(context: MagicMock) -> None:
    update = make_callback_update("p:deadbeef:1")

    await button(update, context)

    update.callback_query.answer.assert_awaited_once_with(text=texts.STALE_SEARCH, show_alert=True)


# --- общий обработчик ошибок и статус-сообщения ----------------------------


async def test_error_handler_replies_and_rate_limits_admin_notifications(
    context: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [0.0]
    monkeypatch.setattr(settings, "admins", [1])
    monkeypatch.setattr(errors, "admin_notifier", errors.AdminNotifier(60, clock=lambda: now[0]))
    update = make_message_update("x")

    for _ in range(3):
        context.error = ValueError(f"секрет {settings.token.get_secret_value()}")
        await errors.error_handler(update, context)

    calls = context.bot.send_message.await_args_list
    assert [c.kwargs["chat_id"] for c in calls] == [CHAT_ID, 1, CHAT_ID, CHAT_ID]
    assert settings.token.get_secret_value() not in calls[1].kwargs["text"]

    now[0] = 61
    context.error = ValueError("ещё")
    await errors.error_handler(update, context)

    assert "Ещё ошибок с прошлого уведомления: 2" in calls[-1].kwargs["text"]


@pytest.mark.parametrize("error", [TimedOut(), Forbidden("bot was blocked by the user")])
async def test_error_handler_ignores_transient_errors(
    context: MagicMock, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(settings, "admins", [1])
    context.error = error

    await errors.error_handler(make_message_update("x"), context)

    context.bot.send_message.assert_not_awaited()


async def test_error_handler_without_chat(
    context: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admins", [])
    context.error = RuntimeError("job failed")

    await errors.error_handler(None, context)

    context.bot.send_message.assert_not_awaited()


async def test_status_message_survives_telegram_failures() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.delete.side_effect = BadRequest("message to delete not found")
    bot.send_message.return_value.edit_text.side_effect = BadRequest("message not found")

    async with status_message(bot, CHAT_ID, "статус") as status:
        await status.edit("другой текст")

    bot.send_message.return_value.delete.assert_awaited_once()

    bot = AsyncMock()
    bot.send_message.side_effect = TimedOut()

    async with status_message(bot, CHAT_ID, "статус") as status:
        await status.edit("другой текст")
