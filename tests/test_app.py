from pathlib import Path
from typing import Any

import pytest
from telegram import Bot, Update, User
from telegram.ext import AIORateLimiter, Application, PicklePersistence

from src.bot import app as bot_app
from src.bot import buttons, commands, messages
from src.settings import settings

USER = {"id": 42, "is_bot": False, "first_name": "U"}
CHAT = {"id": 42, "type": "private"}


@pytest.fixture
def application(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Application:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "nested" / "data"))

    application = bot_app.build_application()
    # вместо get_me: CommandHandler сверяет имя бота в командах вида /start@bot
    application.bot._bot_user = User(id=1, first_name="bot", is_bot=True, username="test_bot")

    return application


def _message(bot: Bot, text: str, *, key: str = "message") -> Update:
    payload: dict[str, Any] = {"message_id": 1, "date": 0, "chat": CHAT, "from": USER, "text": text}

    if text.startswith("/"):
        command = text.split()[0]
        payload["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]

    return Update.de_json({"update_id": 1, key: payload}, bot)


def _route(application: Application, update: Update) -> Any:
    for handler in application.handlers[0]:
        if handler.check_update(update) not in (None, False):
            return handler.callback

    return None


def test_application_settings(application: Application, tmp_path: Path) -> None:
    persistence = application.persistence

    assert application.update_processor.max_concurrent_updates > 1
    assert isinstance(application.bot.rate_limiter, AIORateLimiter)
    assert isinstance(persistence, PicklePersistence)
    assert persistence.filepath == tmp_path / "nested" / "data" / bot_app.PERSISTENCE_FILE
    assert persistence.filepath.parent.is_dir()
    assert persistence.store_data.user_data and not persistence.store_data.chat_data
    assert application.error_handlers


def test_unwritable_data_dir_disables_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setattr(settings, "data_dir", str(blocker / "data"))

    assert bot_app.build_persistence() is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/start", commands.start_command),
        ("/help", commands.help_command),
        ("/email a@b.c", commands.email_command),
        ("/cancel", commands.cancel_command),
        ("/foo", commands.unknown_command),
        ("/foo bar", commands.unknown_command),
        ("1984\nОруэлл", messages.handle_text),
    ],
)
def test_routing(application: Application, text: str, expected: Any) -> None:
    assert _route(application, _message(application.bot, text)) is expected


@pytest.mark.parametrize("text", ["1984", "/start", "/foo"])
@pytest.mark.parametrize("key", ["edited_message", "channel_post"])
def test_edited_messages_and_channel_posts_are_ignored(
    application: Application,
    text: str,
    key: str,
) -> None:
    assert _route(application, _message(application.bot, text, key=key)) is None


def test_callback_query_routing(application: Application) -> None:
    update = Update.de_json(
        {
            "update_id": 1,
            "callback_query": {"id": "1", "from": USER, "chat_instance": "x", "data": "b:1"},
        },
        None,
    )

    assert _route(application, update) is buttons.button


async def test_persistence_roundtrip_of_bot_state(tmp_path: Path) -> None:
    """Состояние диалога и запросы для листания — обычные dict, pickle их переживает."""
    from src.bot import search, verification

    user_data: dict[Any, Any] = {}
    verification.await_code(user_data, email="a@b.c", code="123456", book_id="7", book_format="fb2")
    search_id = search.remember_query(user_data, search.SearchQuery("1984", "Оруэлл"))

    first = PicklePersistence(filepath=tmp_path / "state.pickle")
    await first.update_user_data(42, user_data)
    await first.flush()

    restored = (await PicklePersistence(filepath=tmp_path / "state.pickle").get_user_data())[42]

    assert verification.load(restored) == verification.load(user_data)
    assert search.recall_query(restored, search_id) == search.SearchQuery("1984", "Оруэлл")
