import asyncio
import smtplib
from email.message import EmailMessage

from src.settings import settings

SMTP_TOO_LARGE_CODES = (552, 554)


class MailTooLargeError(Exception):
    """Почтовый сервер отказался принять письмо из-за размера."""


def mask_email(email: str) -> str:
    """Для логов: u***@example.com вместо полного адреса."""
    local, sep, domain = email.partition("@")

    if not sep:
        return "***"

    return f"{local[:1]}***@{domain}"


def build_book_message(content: bytes, filename: str, to_email: str) -> EmailMessage:
    msg = EmailMessage()

    msg["Subject"] = f"Книга: {filename}"
    msg["From"] = settings.smtp_user
    msg["To"] = to_email

    msg.set_content("Приятного чтения! Файл с книгой прикреплен к этому письму.")
    msg.add_attachment(content, maintype="application", subtype="octet-stream", filename=filename)

    return msg


def build_code_message(code: str, to_email: str) -> EmailMessage:
    msg = EmailMessage()

    msg["Subject"] = "Код подтверждения адреса"
    msg["From"] = settings.smtp_user
    msg["To"] = to_email

    msg.set_content(
        f"Код подтверждения: {code}\n\n"
        "Отправьте его в чат с ботом, чтобы получать книги на этот адрес.\n"
        "Если вы не запрашивали код, просто проигнорируйте это письмо."
    )

    return msg


def _send(msg: EmailMessage) -> None:
    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=settings.smtp_timeout,
    ) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_pass.get_secret_value())

        try:
            server.send_message(msg)
        except smtplib.SMTPResponseException as e:
            reason = e.smtp_error
            text = reason.decode(errors="replace") if isinstance(reason, bytes) else str(reason)

            if e.smtp_code in SMTP_TOO_LARGE_CODES and "size" in text.lower():
                raise MailTooLargeError from e
            raise


async def send_book(content: bytes, filename: str, to_email: str) -> None:
    await asyncio.to_thread(_send, build_book_message(content, filename, to_email))


async def send_code(code: str, to_email: str) -> None:
    await asyncio.to_thread(_send, build_code_message(code, to_email))
