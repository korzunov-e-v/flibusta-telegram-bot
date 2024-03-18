from datetime import datetime

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
            result["time"] = datetime.utcnow()

        result["levelname"] = record.levelname
        result["message"] = message
        result.update(extra)

        if record.exc_info:
            result["exc_info"] = self.formatException(record.exc_info)

        return result
