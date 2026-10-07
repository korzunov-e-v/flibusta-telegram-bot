import re
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

MEGABYTE = 1024 * 1024


class Settings(BaseSettings):
    token: SecretStr
    # NoDecode: иначе pydantic-settings разбирает список как JSON и падает на "1,2,3"
    admins: Annotated[list[int], NoDecode] = Field(default_factory=list)

    flibusta_url: str = "https://flibusta.is"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str
    smtp_pass: SecretStr
    smtp_timeout: float = 30.0

    email_daily_limit: int = 10
    max_chat_file_mb: int = 50
    # у Gmail 25 МБ на всё письмо, а вложение в base64 вырастает на треть
    max_email_file_mb: int = 18

    data_dir: str = "data"

    postgres_db: str = "flibusta"
    postgres_user: str = "flibusta"
    postgres_password: SecretStr
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("admins", mode="before")
    @classmethod
    def parse_admins(cls, value: Any) -> Any:
        if isinstance(value, int):
            return [value]

        if isinstance(value, str):
            return [int(part) for part in re.split(r"[\s,;]+", value.strip("[] \t")) if part]

        return value

    @field_validator("flibusta_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def max_chat_file_size(self) -> int:
        return self.max_chat_file_mb * MEGABYTE

    @property
    def max_email_file_size(self) -> int:
        return self.max_email_file_mb * MEGABYTE

    @property
    def database_url(self) -> URL:
        # URL.create сам экранирует спецсимволы пароля; строка с quote_plus ломалась на пробелах
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


settings = Settings()
