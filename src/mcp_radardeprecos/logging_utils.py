"""Logging estruturado com request_id.

Cada chamada de tool ganha um request_id próprio, propagado via contextvar
para todas as linhas de log daquela chamada — correlação sem acoplamento.
"""
from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

from .config import settings

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s level=%(levelname)s request_id=%(request_id)s "
            "logger=%(name)s message=%(message)s"
        )
    )
    handler.addFilter(RequestIdFilter())
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers = [handler]


def new_request_id() -> str:
    """Gera e associa um novo request_id ao contexto de execução atual."""
    rid = uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
