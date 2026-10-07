"""Состояние диалога о почте: ожидание адреса и ожидание кода подтверждения.

Хранится в user_data обычным словарём (переживает рестарт через persistence
и не ломается при переименовании классов).
"""

import hmac
import secrets
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

FLOW_KEY = "email_flow"

STAGE_EMAIL = "await_email"
STAGE_CODE = "await_code"

EMAIL_INPUT_TTL = 10 * 60
CODE_TTL = 15 * 60
CODE_LENGTH = 6
MAX_CODE_ATTEMPTS = 5
MAX_CODES_PER_DAY = 5


class CodeCheck(Enum):
    OK = "ok"
    WRONG = "wrong"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"


@dataclass(slots=True)
class EmailFlow:
    stage: str
    expires_at: float
    email: str = ""
    code: str = ""
    attempts: int = 0
    book_id: str | None = None
    book_format: str | None = None

    def expired(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) >= self.expires_at

    @property
    def attempts_left(self) -> int:
        return max(MAX_CODE_ATTEMPTS - self.attempts, 0)


def generate_code() -> str:
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def normalize_code(text: str) -> str:
    return "".join(text.split())


def looks_like_code(text: str) -> bool:
    code = normalize_code(text)

    return len(code) == CODE_LENGTH and code.isascii() and code.isdigit()


def load(user_data: dict[Any, Any]) -> EmailFlow | None:
    raw = user_data.get(FLOW_KEY)

    if raw is None:
        return None

    try:
        flow = EmailFlow(**raw)
    except TypeError:
        flow = None

    if flow is None or flow.stage not in (STAGE_EMAIL, STAGE_CODE):
        user_data.pop(FLOW_KEY, None)
        return None

    return flow


def save(user_data: dict[Any, Any], flow: EmailFlow) -> None:
    user_data[FLOW_KEY] = asdict(flow)


def clear(user_data: dict[Any, Any]) -> bool:
    return user_data.pop(FLOW_KEY, None) is not None


def await_email(
    user_data: dict[Any, Any],
    *,
    book_id: str | None = None,
    book_format: str | None = None,
    now: float | None = None,
) -> EmailFlow:
    flow = EmailFlow(
        stage=STAGE_EMAIL,
        expires_at=(time.time() if now is None else now) + EMAIL_INPUT_TTL,
        book_id=book_id,
        book_format=book_format,
    )
    save(user_data, flow)

    return flow


def await_code(
    user_data: dict[Any, Any],
    *,
    email: str,
    code: str,
    book_id: str | None = None,
    book_format: str | None = None,
    now: float | None = None,
) -> EmailFlow:
    flow = EmailFlow(
        stage=STAGE_CODE,
        expires_at=(time.time() if now is None else now) + CODE_TTL,
        email=email,
        code=code,
        book_id=book_id,
        book_format=book_format,
    )
    save(user_data, flow)

    return flow


def check_code(
    user_data: dict[Any, Any],
    text: str,
    now: float | None = None,
) -> tuple[CodeCheck, EmailFlow | None]:
    """Проверяет код и сразу обновляет состояние: без await между чтением и записью,
    поэтому параллельные апдейты одного пользователя не обойдут лимит попыток."""
    flow = load(user_data)

    if flow is None or flow.stage != STAGE_CODE:
        return CodeCheck.EXPIRED, None

    if flow.expired(now):
        clear(user_data)
        return CodeCheck.EXPIRED, flow

    if hmac.compare_digest(normalize_code(text).encode(), flow.code.encode()):
        clear(user_data)
        return CodeCheck.OK, flow

    flow.attempts += 1

    if flow.attempts >= MAX_CODE_ATTEMPTS:
        clear(user_data)
        return CodeCheck.EXHAUSTED, flow

    save(user_data, flow)

    return CodeCheck.WRONG, flow
