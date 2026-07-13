"""Structured logging and per-stage metrics (research R9).

JSON lines to stdout plus a per-job log file, every event bound to
comparison_id and stage. Log payloads reference entity IDs and counts only —
never drawing content (FR-016). Each finished comparison writes metrics.json.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import structlog

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # basicConfig no-ops when the root logger already has handlers (e.g.
    # under pytest); the root level must still be INFO for stage events to
    # reach the stdout and job.log handlers
    logging.getLogger().setLevel(logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        # stdlib factory (not PrintLogger) so per-job FileHandlers can
        # capture the same JSON lines that go to stdout (R9: job.log)
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    _CONFIGURED = True


def stage_logger(comparison_id: str, stage: str) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger().bind(comparison_id=comparison_id, stage=stage)


def job_log_handler(path: str | Path, comparison_id: str) -> logging.Handler:
    """Per-job log file (R9): captures exactly the JSON lines bound to this
    comparison_id; unrelated traffic on the root logger is filtered out, so
    every line in job.log is comparison_id-correlated by construction."""
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(lambda record: comparison_id in record.getMessage())
    return handler


class MetricsRecorder:
    """Collects stage timings and quality signals for one comparison."""

    def __init__(self, comparison_id: str) -> None:
        self.comparison_id = comparison_id
        self.stage_timings_ms: dict[str, float] = {}
        self.signals: dict[str, Any] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[structlog.stdlib.BoundLogger]:
        log = stage_logger(self.comparison_id, name)
        log.info("stage_start")
        start = time.perf_counter()
        try:
            yield log
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.stage_timings_ms[name] = round(elapsed_ms, 3)
            log.info("stage_end", elapsed_ms=round(elapsed_ms, 3))

    def record(self, stage: str, **signals: Any) -> None:
        self.signals.setdefault(stage, {}).update(signals)

    def write(self, directory: str | Path) -> Path:
        path = Path(directory) / "metrics.json"
        payload = {
            "comparison_id": self.comparison_id,
            "stage_timings_ms": self.stage_timings_ms,
            "signals": self.signals,
        }
        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        return path
