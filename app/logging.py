"""Logging configuration.

Real provider error details (status codes, upstream messages) are only ever written
to these loggers; they never reach HTTP responses.
"""

from __future__ import annotations

import logging

APP_LOGGER_NAME = "polyglot"


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def get_logger(name: str | None = None) -> logging.Logger:
    full_name = APP_LOGGER_NAME if name is None else f"{APP_LOGGER_NAME}.{name}"
    return logging.getLogger(full_name)
