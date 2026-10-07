import os

# Обязательные настройки — до первого импорта src.*: settings создаётся при импорте.
os.environ.setdefault("TOKEN", "123456:test-token")
os.environ.setdefault("ADMINS", "123456789")
os.environ.setdefault("SMTP_USER", "bot@example.com")
os.environ.setdefault("SMTP_PASS", "test-smtp-pass")
os.environ.setdefault("POSTGRES_PASSWORD", "test-postgres-pass")

from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from telegram import CallbackQuery, Chat, Message, Update, User  # noqa: E402

USER_ID = 42
CHAT_ID = 4242


@pytest.fixture(autouse=True)
def _isolated_bot_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Троттлинг, кеш выдачи и антиспам уведомлений живут в модулях — обнуляем между тестами."""
    from src.bot import errors, search, throttle

    monkeypatch.setattr(throttle, "heavy", throttle.Throttle(0, exclusive=True))
    monkeypatch.setattr(throttle, "light", throttle.Throttle(0, exclusive=False))
    monkeypatch.setattr(search, "cache", search.SearchCache())
    monkeypatch.setattr(errors, "admin_notifier", errors.AdminNotifier())


@pytest.fixture
def context() -> MagicMock:
    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.user_data = {}
    ctx.args = []
    ctx.error = None

    return ctx


def _base_update() -> MagicMock:
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User, id=USER_ID)
    update.effective_chat = MagicMock(spec=Chat, id=CHAT_ID)
    update.callback_query = None
    update.effective_message = None

    return update


def make_message_update(text: str) -> MagicMock:
    message = MagicMock(spec=Message)
    message.text = text
    message.chat_id = CHAT_ID
    message.reply_text = AsyncMock()

    update = _base_update()
    update.effective_message = message
    update.message = message

    return update


def make_callback_update(data: str | None, reply_markup: Any = None) -> MagicMock:
    message = MagicMock(spec=Message)
    message.reply_markup = reply_markup

    query = MagicMock(spec=CallbackQuery)
    query.data = data
    query.message = message
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()

    update = _base_update()
    update.callback_query = query

    return update


def sent_texts(bot: AsyncMock) -> list[str]:
    return [call.kwargs["text"] for call in bot.send_message.await_args_list]


def replies(update: MagicMock) -> list[str]:
    return [call.args[0] for call in update.effective_message.reply_text.await_args_list]
