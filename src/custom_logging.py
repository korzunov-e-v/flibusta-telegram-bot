import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from json_log_formatter import JSONFormatter

# httpx на уровне INFO пишет URL запросов, а в URL Bot API входит токен бота
NOISY_LOGGERS = ("httpx", "httpcore")


def _default(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()

    return str(obj)


class CustomJSONFormatter(JSONFormatter):
    def to_json(self, record: dict[str, Any]) -> str:
        try:
            return json.dumps(record, ensure_ascii=False, default=_default)
        except (TypeError, ValueError, OverflowError):
            return json.dumps({key: str(value) for key, value in record.items()})

    def json_record(
        self,
        message: str,
        extra: dict[str, Any],
        record: logging.LogRecord,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "time": datetime.now(UTC),
            "levelname": record.levelname,
            "name": record.name,
            "message": message,
        }
        result.update(extra)

        if record.exc_info:
            result["exc_info"] = self.formatException(record.exc_info)

        return result


def setup_logging(level: int = logging.INFO) -> None:
    """Один JSON-handler на stdout для всех логгеров: своих, PTB, SQLAlchemy, httpx."""
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(CustomJSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
