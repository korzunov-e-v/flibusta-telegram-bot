import json
import logging
import smtplib
from typing import Any

import pytest

from src import mailer
from src.custom_logging import CustomJSONFormatter, get_logger, setup_logging


def test_formatter_outputs_json_with_extra_and_traceback() -> None:
    try:
        raise ValueError("бум")
    except ValueError:
        record = logging.getLogger("x.y").makeRecord(
            "x.y",
            logging.ERROR,
            __file__,
            1,
            "сообщение %s",
            ("арг",),
            __import__("sys").exc_info(),
        )

    record.user_id = 42
    record.obj = object()
    payload = json.loads(CustomJSONFormatter().format(record))

    assert payload["message"] == "сообщение арг"
    assert payload["levelname"] == "ERROR"
    assert payload["name"] == "x.y"
    assert payload["user_id"] == 42
    assert "ValueError: бум" in payload["exc_info"]
    assert "time" in payload and isinstance(payload["obj"], str)


def test_setup_logging_single_root_handler(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)

    try:
        setup_logging()
        setup_logging()

        assert len(root.handlers) == 1
        assert logging.getLogger("httpx").level == logging.WARNING

        for name in ("src.bot.app", "telegram.ext", "sqlalchemy.engine"):
            assert get_logger(name).propagate
            assert not get_logger(name).handlers

        get_logger("telegram.ext").warning("привет", extra={"a": 1})
        line = capsys.readouterr().out.strip().splitlines()[-1]

        assert json.loads(line)["message"] == "привет"
        assert "привет" in line  # кириллица не экранируется
    finally:
        root.handlers, root.level = saved[0], saved[1]


@pytest.mark.parametrize(
    ("email", "masked"),
    [("user@example.com", "u***@example.com"), ("@x.y", "***@x.y"), ("мусор", "***")],
)
def test_mask_email(email: str, masked: str) -> None:
    assert mailer.mask_email(email) == masked


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    error: Exception | None = None

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.sent: list[Any] = []
        self.logged_in = False
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self) -> None:
        pass

    def login(self, user: str, password: str) -> None:
        self.logged_in = True

    def send_message(self, msg: Any) -> None:
        if FakeSMTP.error is not None:
            raise FakeSMTP.error

        self.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.error = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    return FakeSMTP


async def test_send_book_uses_timeout_and_attaches_file(fake_smtp: type[FakeSMTP]) -> None:
    await mailer.send_book(b"content", "Книга.fb2", "reader@example.com")

    (smtp,) = fake_smtp.instances
    (msg,) = smtp.sent
    (attachment,) = msg.iter_attachments()

    assert smtp.timeout == 30.0 and smtp.logged_in
    assert msg["To"] == "reader@example.com"
    assert attachment.get_filename() == "Книга.fb2"
    assert attachment.get_payload(decode=True) == b"content"


async def test_send_code(fake_smtp: type[FakeSMTP]) -> None:
    await mailer.send_code("123456", "reader@example.com")

    (msg,) = fake_smtp.instances[0].sent

    assert "123456" in msg.get_content()
    assert not list(msg.iter_attachments())


async def test_size_rejection_becomes_mail_too_large(fake_smtp: type[FakeSMTP]) -> None:
    fake_smtp.error = smtplib.SMTPSenderRefused(552, b"5.3.4 Message size exceeds limit", "a@b.c")

    with pytest.raises(mailer.MailTooLargeError):
        await mailer.send_book(b"x", "a.fb2", "reader@example.com")


async def test_other_smtp_errors_propagate(fake_smtp: type[FakeSMTP]) -> None:
    fake_smtp.error = smtplib.SMTPDataError(554, b"5.7.1 rejected as spam")

    with pytest.raises(smtplib.SMTPDataError):
        await mailer.send_book(b"x", "a.fb2", "reader@example.com")
