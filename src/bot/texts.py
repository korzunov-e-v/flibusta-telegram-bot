"""Тексты сообщений и форматирование. Всё, что уходит с parse_mode="HTML",
собирается здесь и экранируется через escape()."""

import html

from src.flib import Book

# лимиты Telegram считаются по тексту после разбора разметки; берём с запасом
MAX_MESSAGE_LENGTH = 4000
MAX_CAPTION_LENGTH = 1000
MAX_BUTTON_TEXT_LENGTH = 60

MAX_TITLE_LENGTH = 300
MAX_AUTHOR_LENGTH = 200
MAX_SIZE_LENGTH = 50

ELLIPSIS = "…"

START = (
    "Введите название книги (без автора) "
    "ИЛИ добавьте фамилию автора на новой строке.\n\n"
    "Пример:\n"
    "1984\n"
    "Оруэлл\n\n"
    "Также вы можете задать почту для отправки книг командой /email.\n"
    "Подробнее — /help"
)

HELP = (
    "Я ищу книги на Флибусте и присылаю их в чат или на электронную почту.\n\n"
    "Как искать:\n"
    "• отправьте название книги или фамилию автора;\n"
    "• чтобы уточнить поиск, напишите название, а на следующей строке — фамилию автора;\n"
    "• если знаете номер книги на сайте, отправьте его.\n\n"
    "Выберите книгу из списка, затем формат. Кнопка «Отправить на почту» переключает "
    "доставку: файл уйдёт на ваш адрес (удобно для электронных книг).\n\n"
    "Команды:\n"
    "/email — показать адрес почты\n"
    "/email адрес@почта.com — задать или сменить адрес (потребуется код из письма)\n"
    "/cancel — отменить ввод адреса или кода\n"
    "/help — эта справка\n\n"
    "Ограничения: файл в чат — до {chat_mb} МБ, на почту — до {email_mb} МБ, "
    "не больше {daily} писем в сутки."
)

COMMANDS = (
    ("start", "Начать поиск"),
    ("email", "Почта для отправки книг"),
    ("cancel", "Отменить ввод почты или кода"),
    ("help", "Справка"),
)

UNKNOWN_COMMAND = "Не знаю такой команды. Список команд — /help"
EMPTY_QUERY = "Отправьте название книги или фамилию автора."

SEARCHING = "Подождите, идёт поиск..."
LOADING = "Подождите, идёт загрузка..."
LOADING_ANNOTATION = "Загружаю аннотацию..."
DOWNLOADING = "Подождите, идёт скачивание..."

NOTHING_FOUND = "К сожалению, ничего не найдено =("
NOTHING_FOUND_PARTIAL = (
    "Ничего не найдено, но часть запросов к сайту завершилась ошибкой. Попробуйте ещё раз позже."
)
AUTHOR_HINT = "Вероятно вместо фамилии автора на второй строке было указано что-то ещё"
SEARCH_PARTIAL = "⚠️ Часть запросов к сайту завершилась ошибкой, выдача может быть неполной."
SEARCH_TRUNCATED = "Показаны первые {limit} — уточните запрос, если нужной книги нет."

BOOK_NOT_FOUND = "Книга не найдена."
NO_ANNOTATION = "К сожалению, для этой книги нет аннотации на сайте."
NO_COVER = "[обложки нет]"
FORMAT_UNAVAILABLE = "Этот формат для книги больше недоступен. Откройте карточку книги заново."
DOWNLOAD_FAILED = "Произошла ошибка при скачивании файла."
SEND_FAILED = "Не удалось отправить файл в чат. Попробуйте другой формат или отправку на почту."

FLIBUSTA_ERROR = "Произошла ошибка на сервере. Попробуйте ещё раз позже."
UNEXPECTED_ERROR = "Что-то пошло не так. Попробуйте ещё раз позже."

STALE_BUTTON = "Кнопка устарела. Повторите поиск, пожалуйста."
STALE_SEARCH = "Эта выдача устарела. Повторите поиск, пожалуйста."

THROTTLED_BUSY = "Дождитесь завершения предыдущего запроса."
THROTTLED_TOO_FAST = "Слишком часто. Подождите пару секунд."

EMAIL_NOT_SET = "У вас не задан email. Напишите: /email ваш@адрес.com"
EMAIL_CURRENT = "Ваш текущий email: {email}\nЧтобы изменить его, напишите: /email ваш@адрес.com"
EMAIL_UNCHANGED = "Этот адрес уже задан: {email}"
EMAIL_INVALID = "❌ Неверный формат email."
EMAIL_INVALID_RETRY = "❌ Неверный формат email.\nПопробуйте ещё раз или отмените командой /cancel."
EMAIL_ASK = (
    "У вас не задан E-mail.\n"
    "Пожалуйста, отправьте адрес вашей электронной почты ответным сообщением.\n"
    "Отмена — /cancel"
)
EMAIL_CODE_SENT = (
    "На адрес {email} отправлено письмо с кодом подтверждения.\n"
    "Пришлите код сюда в течение {minutes} минут. Отмена — /cancel\n\n"
    "Не забудьте проверить папку «Спам»."
)
EMAIL_CODE_PENDING = "Ожидается код подтверждения для адреса {email}. Отмена — /cancel"
EMAIL_CODE_SEND_FAILED = (
    "❌ Не удалось отправить письмо с кодом. Проверьте адрес и попробуйте позже."
)
EMAIL_CODE_LIMIT = "Слишком много запросов кода за сутки. Попробуйте завтра."
EMAIL_CODE_WRONG = "❌ Неверный код. Осталось попыток: {left}."
EMAIL_CODE_EXHAUSTED = "❌ Попытки закончились. Запросите новый код командой /email ваш@адрес.com"
EMAIL_CODE_EXPIRED = "Срок действия кода истёк. Запросите новый: /email ваш@адрес.com"
EMAIL_SAVED = (
    "✅ Email {email} подтверждён и сохранён!\n"
    "Если захотите заменить его в будущем, воспользуйтесь командой /email."
)
EMAIL_SENDING = "Отправляю книгу на {email}..."
EMAIL_SENT = (
    "✅ Книга {filename} успешно отправлена на {email}!\n\n"
    "Не забудьте проверить папку «Спам», если письма долго нет во входящих."
)
EMAIL_SEND_FAILED = "❌ Ошибка отправки. Попробуйте ещё раз позже."
EMAIL_DAILY_LIMIT = "Достигнут лимит: {limit} писем в сутки. Попробуйте позже или скачайте в чат."
EMAIL_REJECTED_SIZE = "❌ Почтовый сервер не принял письмо: файл слишком большой."

CANCELLED = "Отменено. Можно искать книги дальше."
NOTHING_TO_CANCEL = "Отменять нечего. Отправьте название книги, чтобы начать поиск."


def escape(text: str) -> str:
    return html.escape(text, quote=False)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    return text[: max(limit - len(ELLIPSIS), 0)].rstrip() + ELLIPSIS


def help_text(chat_mb: int, email_mb: int, daily: int) -> str:
    return HELP.format(chat_mb=chat_mb, email_mb=email_mb, daily=daily)


def book_button_text(book: Book) -> str:
    text = f"{book.title} — {book.author}" if book.author else book.title

    return truncate(" ".join(text.split()) or book.id, MAX_BUTTON_TEXT_LENGTH)


def book_caption(book: Book, *, with_cover: bool) -> str:
    """HTML-подпись карточки. Поля обрезаются до экранирования, чтобы подпись
    к фото уложилась в лимит (1024 символа) и не разрезалась HTML-сущность."""
    lines = [f"📖 <b>{escape(truncate(book.title.strip(), MAX_TITLE_LENGTH))}</b>"]

    if book.author:
        lines.append(f"🗣 {escape(truncate(book.author.strip(), MAX_AUTHOR_LENGTH))}")

    if book.size:
        lines.append(f"⚖️ {escape(truncate(book.size.strip(), MAX_SIZE_LENGTH))}")

    if book.link:
        lines.append(f"🌐 Страница книги {escape(book.link)}")

    caption = "\n".join(lines)

    return caption if with_cover else f"{NO_COVER}\n\n{caption}"


def annotation_text(book: Book) -> str:
    title = truncate(book.title.strip(), MAX_TITLE_LENGTH)
    annotation = truncate(book.annotation.strip(), MAX_MESSAGE_LENGTH - len(title) - 10)

    return f"📖 <b>{escape(title)}</b>\n\n{escape(annotation)}"


def search_results_text(
    *,
    total: int,
    page: int,
    pages: int,
    partial: bool = False,
    truncated_to: int | None = None,
) -> str:
    lines = [f"Найдено книг: {total}. Выберите книгу:"]

    if pages > 1:
        lines[0] = f"Найдено книг: {total}. Страница {page + 1} из {pages}. Выберите книгу:"

    if truncated_to is not None:
        lines.append(SEARCH_TRUNCATED.format(limit=truncated_to))

    if partial:
        lines.append(SEARCH_PARTIAL)

    return "\n".join(lines)


def too_large_text(limit_mb: int, size: int | None, *, by_email: bool) -> str:
    where = "по почте" if by_email else "в чат"
    actual = f" (размер файла — {size / 1024 / 1024:.1f} МБ)" if size else ""
    hint = "" if by_email else " Попробуйте другой формат."

    return f"Файл слишком большой{actual}: {where} можно отправить не больше {limit_mb} МБ.{hint}"
