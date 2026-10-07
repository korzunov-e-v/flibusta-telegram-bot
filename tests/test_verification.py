from src.bot import verification as v
from src.bot.verification import CodeCheck


def test_generate_code() -> None:
    codes = {v.generate_code() for _ in range(200)}

    assert all(len(code) == v.CODE_LENGTH and code.isdigit() for code in codes)
    assert len(codes) > 150


def test_looks_like_code() -> None:
    assert v.looks_like_code("012345")
    assert v.looks_like_code(" 012 345 ")
    assert not v.looks_like_code("12345")
    assert not v.looks_like_code("1234567")
    assert not v.looks_like_code("12345a")
    assert not v.looks_like_code("１２３４５６")  # полноширинные цифры
    assert not v.looks_like_code("Война и мир")


def test_await_email_roundtrip_is_plain_dict() -> None:
    user_data: dict[str, object] = {}

    v.await_email(user_data, book_id="5", book_format="fb2", now=1000)
    flow = v.load(user_data)

    assert type(user_data[v.FLOW_KEY]) is dict  # переживает pickle без привязки к классам
    assert flow is not None
    assert (flow.stage, flow.book_id, flow.book_format) == (v.STAGE_EMAIL, "5", "fb2")
    assert not flow.expired(1000 + v.EMAIL_INPUT_TTL - 1)
    assert flow.expired(1000 + v.EMAIL_INPUT_TTL)


def test_load_drops_corrupted_state() -> None:
    for broken in (
        {"stage": "await_code"},
        {"unknown": 1},
        "мусор",
        {"stage": "x", "expires_at": 1},
    ):
        user_data: dict[str, object] = {v.FLOW_KEY: broken}

        assert v.load(user_data) is None
        assert v.FLOW_KEY not in user_data

    assert v.load({}) is None


def test_clear() -> None:
    user_data: dict[str, object] = {}
    v.await_email(user_data)

    assert v.clear(user_data) is True
    assert v.clear(user_data) is False


def test_check_code_ok() -> None:
    user_data: dict[str, object] = {}
    v.await_code(user_data, email="a@b.c", code="123456", book_id="5", book_format="pdf", now=0)

    result, flow = v.check_code(user_data, " 123 456 ", now=10)

    assert result is CodeCheck.OK
    assert flow is not None and (flow.email, flow.book_id, flow.book_format) == (
        "a@b.c",
        "5",
        "pdf",
    )
    assert v.FLOW_KEY not in user_data
    # код одноразовый
    assert v.check_code(user_data, "123456", now=11)[0] is CodeCheck.EXPIRED


def test_check_code_attempts_are_limited() -> None:
    user_data: dict[str, object] = {}
    v.await_code(user_data, email="a@b.c", code="123456", now=0)

    for attempt in range(1, v.MAX_CODE_ATTEMPTS):
        result, flow = v.check_code(user_data, "000000", now=1)

        assert result is CodeCheck.WRONG
        assert flow is not None and flow.attempts_left == v.MAX_CODE_ATTEMPTS - attempt

    result, _ = v.check_code(user_data, "000000", now=1)

    assert result is CodeCheck.EXHAUSTED
    assert v.FLOW_KEY not in user_data
    # после исчерпания попыток не помогает и верный код
    assert v.check_code(user_data, "123456", now=1)[0] is CodeCheck.EXPIRED


def test_check_code_expired() -> None:
    user_data: dict[str, object] = {}
    v.await_code(user_data, email="a@b.c", code="123456", now=0)

    result, _ = v.check_code(user_data, "123456", now=v.CODE_TTL)

    assert result is CodeCheck.EXPIRED
    assert v.FLOW_KEY not in user_data


def test_check_code_wrong_stage() -> None:
    user_data: dict[str, object] = {}
    v.await_email(user_data, now=0)

    assert v.check_code(user_data, "", now=1) == (CodeCheck.EXPIRED, None)
    assert v.FLOW_KEY in user_data
