import logging
import sys
from datetime import datetime, UTC

from json_log_formatter import JSONFormatter, _json_serializable


class CustomJSONFormatter(JSONFormatter):
    def to_json(self, record):
        try:
            return self.json_lib.dumps(record, ensure_ascii=False, default=_json_serializable)
        except (TypeError, ValueError, OverflowError):
            try:
                return self.json_lib.dumps(record)
            except (TypeError, ValueError, OverflowError):
                return "{}"

    def json_record(self, message, extra, record):
        result = {}
        if "time" not in extra:
            result["time"] = datetime.now(UTC)

        result["levelname"] = record.levelname
        result["message"] = message
        result.update(extra)

        if record.exc_info:
            result["exc_info"] = self.formatException(record.exc_info)

        return result


formatter = CustomJSONFormatter()

logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        encoding="utf-8",
        level=logging.INFO,
)


def get_logger(name: str):
    logger = logging.getLogger(name)
    logger.propagate = False
    file_handler = logging.FileHandler(filename="search_log.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return
