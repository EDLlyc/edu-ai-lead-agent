from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import structlog

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "body",
    "content",
    "raw_html",
}


def safe_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        lowered = key.lower().replace("-", "_")
        if any(secret in lowered for secret in SENSITIVE_KEYS):
            redacted[key] = "[REDACTED]"
        elif isinstance(item, Mapping):
            redacted[key] = redact_mapping(item)
        else:
            redacted[key] = item
    return redacted


def _redact_event(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    return redact_mapping(event_dict)


def configure_logging(*, json_output: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # httpx logs full request URLs at INFO, which would expose access tokens and secrets
    # carried in query parameters. Provider request details are represented by our own
    # structured, redacted events instead.
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_event,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
