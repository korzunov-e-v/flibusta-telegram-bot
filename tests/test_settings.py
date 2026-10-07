import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from src.settings import Settings


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    return Settings(_env_file=None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("123456789", [123456789]),  # формат, который сейчас стоит в проде
        ("1,2,3", [1, 2, 3]),
        (" 1, 2 ,3, ", [1, 2, 3]),
        ("1 2;3", [1, 2, 3]),
        ("[1, 2]", [1, 2]),
        ("", []),
    ],
)
def test_admins_parsing(monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[int]) -> None:
    assert _settings(monkeypatch, ADMINS=raw).admins == expected


def test_admins_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMINS")

    assert Settings(_env_file=None).admins == []


def test_admins_garbage_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _settings(monkeypatch, ADMINS="vasya")


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FLIBUSTA_URL", "EMAIL_DAILY_LIMIT", "DATA_DIR"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.flibusta_url == "https://flibusta.is"
    assert settings.email_daily_limit == 10
    assert settings.data_dir == "data"
    assert settings.max_chat_file_size == 50 * 1024 * 1024
    assert settings.max_email_file_size == 18 * 1024 * 1024


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch,
        FLIBUSTA_URL="http://mirror.example/",
        EMAIL_DAILY_LIMIT="3",
        DATA_DIR="/srv/data",
    )

    assert settings.flibusta_url == "http://mirror.example"
    assert settings.email_daily_limit == 3
    assert settings.data_dir == "/srv/data"


def test_database_url_keeps_password_with_special_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "p@ss/w%rd +1:x"
    url = _settings(monkeypatch, POSTGRES_PASSWORD=password, POSTGRES_HOST="db").database_url

    assert url.password == password
    assert url.drivername == "postgresql+psycopg" and url.host == "db"
    # строковое представление разбирается обратно без потерь и не светит пароль в логах
    assert make_url(url.render_as_string(hide_password=False)).password == password
    assert password not in str(url)
