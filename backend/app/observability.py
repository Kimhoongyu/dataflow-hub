"""Structured JSON logs and Prometheus metrics shared by the API and the worker.

Logs go to stdout as one JSON object per line, so any collector (docker logs, Kubernetes,
NCP log services) can ingest them without parsing rules. Metric labels stay low-cardinality:
route templates and job types, never tenant, job or user IDs.
"""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
import sys

from prometheus_client import Counter, Histogram

# Set per HTTP request by the API and per job by the worker; added to every log line.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RECORD_FIELDS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "event": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        # Anything passed via `extra=` becomes a top-level field.
        entry.update({key: value for key, value in vars(record).items() if key not in _RECORD_FIELDS})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if os.getenv("LOG_FORMAT", "json") == "json":
        handler.setFormatter(JsonFormatter(service))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    # Route uvicorn's own loggers through the same handler; the API writes its own access log.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # Keep SDK chatter (e.g. credential lookups) out of the application log.
    logging.getLogger("botocore").setLevel(logging.WARNING)


HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests handled by the API", ["method", "route", "status"])
HTTP_DURATION = Histogram("http_request_duration_seconds", "API request latency", ["method", "route"],
                          buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
UPLOADS = Counter("dataflow_uploads_total", "CSV files accepted and queued", ["job_type"])
UPLOAD_BYTES = Counter("dataflow_upload_bytes_total", "Bytes of accepted CSV uploads")
