"""Strukturiertes Logging: JSON auf stdout (für Docker/Loki/ELK) plus rotierende Datei unter data/logs."""
from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
from datetime import datetime, timezone

from wtserver.config import Settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id_var.get()
        return super().format(record)


def setup_logging(settings: Settings) -> None:
    formatter: logging.Formatter = JsonFormatter() if settings.log_json else TextFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log_to_file:
        try:
            settings.logs_dir.mkdir(parents=True, exist_ok=True)
            handlers.append(
                logging.handlers.RotatingFileHandler(
                    settings.logs_dir / "app.log", maxBytes=10_000_000, backupCount=10, encoding="utf-8"
                )
            )
        except OSError:
            pass  # Dateilogging ist optional, stdout genügt
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    logging.getLogger("uvicorn.access").disabled = True  # ersetzt durch die Request-Middleware
