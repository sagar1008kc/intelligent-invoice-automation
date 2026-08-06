"""Structured logging and stage timing helpers."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from acme_invoice.config import get_settings
from acme_invoice.models import StageLog


def setup_logging(level: str | None = None) -> logging.Logger:
    settings = get_settings()
    log_level = (level or settings.log_level).upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("acme_invoice")


logger = logging.getLogger("acme_invoice")


def log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, default=str))


@contextmanager
def stage_timer(stage: str, status_on_success: str = "ok") -> Iterator[StageLog]:
    start = time.perf_counter()
    record = StageLog(stage=stage, status="running")
    try:
        yield record
        record.status = status_on_success
    except Exception as exc:  # noqa: BLE001 - bubble after logging
        record.status = "error"
        record.message = str(exc)
        raise
    finally:
        record.duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log_event(
            "stage_complete",
            stage=record.stage,
            status=record.status,
            duration_ms=record.duration_ms,
            message=record.message,
            details=record.details,
        )
