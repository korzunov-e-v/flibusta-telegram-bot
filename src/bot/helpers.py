from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from telegram import Bot, CallbackQuery, Message
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from src.custom_logging import get_logger

logger = get_logger(__name__)

Context = ContextTypes.DEFAULT_TYPE


def get_user_data(context: Context) -> dict[Any, Any]:
    if context.user_data is None:
        raise RuntimeError("user_data is not available for this update")

    return context.user_data


async def safe_delete(message: Message | None) -> None:
    if message is None:
        return

    try:
        await message.delete()
    except TelegramError:
        logger.debug("Failed to delete message", exc_info=True)


async def safe_answer(
    query: CallbackQuery, text: str | None = None, *, alert: bool = False
) -> None:
    """Ответ на нажатие кнопки; протухший query не должен ронять обработку."""
    try:
        await query.answer(text=text, show_alert=alert)
    except TelegramError:
        logger.debug("Failed to answer callback query", exc_info=True)


class Status:
    def __init__(self, message: Message | None) -> None:
        self._message = message

    async def edit(self, text: str) -> None:
        if self._message is None:
            return

        try:
            await self._message.edit_text(text)
        except TelegramError:
            logger.debug("Failed to edit status message", exc_info=True)

    async def delete(self) -> None:
        message, self._message = self._message, None
        await safe_delete(message)


@asynccontextmanager
async def status_message(bot: Bot, chat_id: int, text: str) -> AsyncIterator[Status]:
    """«Статус → работа → удалить»: сообщение убирается и при ошибке внутри блока."""
    try:
        message: Message | None = await bot.send_message(chat_id=chat_id, text=text)
    except TelegramError:
        logger.warning("Failed to send status message", exc_info=True)
        message = None

    status = Status(message)

    try:
        yield status
    finally:
        await status.delete()
