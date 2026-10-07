import time
import traceback
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from telegram import Bot, Update
from telegram.error import Conflict, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut

from src.bot import texts
from src.bot.helpers import Context, safe_answer
from src.bot.search import SearchFailed
from src.bot.throttle import Throttled
from src.custom_logging import get_logger
from src.settings import settings

logger = get_logger(__name__)

ADMIN_NOTIFY_INTERVAL = 5 * 60
ADMIN_TRACEBACK_LENGTH = 3000


class AdminNotifier:
    """Не чаще одного уведомления за интервал; пропущенные считаются и
    упоминаются в следующем."""

    def __init__(
        self,
        min_interval: float = ADMIN_NOTIFY_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._last_sent: float | None = None
        self._suppressed = 0

    def acquire(self) -> int | None:
        """None — уведомление нужно пропустить; иначе число пропущенных с прошлого раза."""
        now = self._clock()

        if self._last_sent is not None and now - self._last_sent < self._min_interval:
            self._suppressed += 1
            return None

        suppressed, self._suppressed = self._suppressed, 0
        self._last_sent = now

        return suppressed


admin_notifier = AdminNotifier()


def is_transient(error: BaseException) -> bool:
    """Сетевые сбои и ограничения Telegram: писать пользователю и будить админа незачем."""
    return isinstance(error, TimedOut | Forbidden | RetryAfter | Conflict) or (
        type(error) is NetworkError
    )


def format_admin_report(error: BaseException, suppressed: int = 0) -> str:
    trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    trace = trace.replace(settings.token.get_secret_value(), "<token>")

    report = f"⚠️ Необработанная ошибка в боте: {type(error).__name__}\n\n"
    report += trace[-ADMIN_TRACEBACK_LENGTH:]

    if suppressed:
        report += f"\n\nЕщё ошибок с прошлого уведомления: {suppressed}"

    return report


async def notify_admins(bot: Bot, error: BaseException) -> None:
    if not settings.admins:
        return

    suppressed = admin_notifier.acquire()

    if suppressed is None:
        return

    report = format_admin_report(error, suppressed)

    for admin_id in settings.admins:
        try:
            await bot.send_message(chat_id=admin_id, text=report)
        except TelegramError:
            logger.warning("Failed to notify admin", extra={"admin_id": admin_id}, exc_info=True)


async def tell_user(update: object, context: Context, text: str) -> None:
    if not isinstance(update, Update) or update.effective_chat is None:
        return

    try:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    except TelegramError:
        logger.warning("Failed to send error message to user", exc_info=True)


def _request_url(error: httpx.HTTPError) -> str | None:
    try:
        return str(error.request.url)
    except RuntimeError:
        # у ошибки может не быть привязанного запроса
        return None


async def report_flib_error(error: Exception, update: object, context: Context) -> None:
    extra: dict[str, str | None] = {
        "exception_type": type(error).__name__,
        "exception": repr(error),
    }

    if isinstance(error, httpx.HTTPError):
        extra["url"] = _request_url(error)

    logger.error("Flibusta request failed", extra=extra)

    await tell_user(update, context, texts.FLIBUSTA_ERROR)


async def report_unexpected(update: object, context: Context, error: BaseException) -> None:
    user = update.effective_user if isinstance(update, Update) else None
    extra = {
        "exception_type": type(error).__name__,
        "exception": repr(error),
        "user_id": user.id if user else None,
    }
    exc_info = (type(error), error, error.__traceback__)

    if is_transient(error):
        logger.warning("Telegram request failed", extra=extra, exc_info=exc_info)
        return

    logger.error("Unhandled error", extra=extra, exc_info=exc_info)

    await tell_user(update, context, texts.UNEXPECTED_ERROR)
    await notify_admins(context.bot, error)


async def report_throttled(update: Update, context: Context, error: Throttled) -> None:
    text = texts.THROTTLED_BUSY if error.busy else texts.THROTTLED_TOO_FAST

    if update.callback_query is not None:
        await safe_answer(update.callback_query, text)
    else:
        await tell_user(update, context, text)


@asynccontextmanager
async def guard(update: Update, context: Context) -> AsyncIterator[None]:
    """Любая ошибка внутри блока заканчивается ответом пользователю."""
    try:
        yield
    except Throttled as e:
        await report_throttled(update, context, e)
    except SearchFailed as e:
        await report_flib_error(e.errors[0], update, context)

        # не сетевой сбой, а, скорее всего, изменившаяся вёрстка сайта
        bug = next((err for err in e.errors if not isinstance(err, httpx.HTTPError)), None)

        if bug is not None:
            await notify_admins(context.bot, bug)
    except httpx.HTTPError as e:
        await report_flib_error(e, update, context)
    except Exception as e:
        await report_unexpected(update, context, e)


async def error_handler(update: object, context: Context) -> None:
    if context.error is not None:
        await report_unexpected(update, context, context.error)
