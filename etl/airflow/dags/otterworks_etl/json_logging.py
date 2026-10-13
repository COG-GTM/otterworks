"""Structured JSON logging for Airflow task logs and the ETL library."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Render each record as one JSON object; ``extra={...}`` fields become top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for attr in ("dag_id", "task_id", "run_id", "try_number", "map_index"):
            val = getattr(record, attr, None)
            if val not in (None, "", -1):
                payload[attr] = val
        for key, val in record.__dict__.items():
            if key not in _RESERVED and key not in payload and not key.startswith("_"):
                payload[key] = val
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def log_event(logger: logging.Logger, message: str, level: int = logging.INFO, **fields) -> None:
    """Log ``message`` with ``fields`` attached, plus dag/task/run ids when inside a task."""
    try:
        from airflow.operators.python import get_current_context

        ctx = get_current_context()
        ti = ctx["ti"]
        fields.setdefault("dag_id", ti.dag_id)
        fields.setdefault("task_id", ti.task_id)
        fields.setdefault("run_id", ti.run_id)
        fields.setdefault("ds", ctx.get("ds"))
    except Exception:  # noqa: BLE001 - outside a running task there is no context
        pass
    logger.log(level, message, extra={"event": message, **fields})
