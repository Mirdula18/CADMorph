"""Comparison job lifecycle: filesystem store + state machine (data-model.md).

States: pending -> extracting -> classifying -> registering -> matching ->
diffing -> summarizing -> reporting -> done; plus terminal failed / rejected /
declined. T028 wires the full US1 chain with identity registration
(perfectly aligned exports); T041 (US3) replaces the registration stage
with seeded RANSAC.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from cadmorph.classify.model import CLASSIFIER_WEIGHTS, load_classifier, pinned_hash
from cadmorph.classify.stage import classify_graph, low_confidence_count
from cadmorph.deltas.compute import compute_deltas
from cadmorph.deltas.models import ChangeReport, canonical_json
from cadmorph.determinism import seed_all
from cadmorph.extraction.provider import get_provider
from cadmorph.extraction.validation import validate_input
from cadmorph.graph.build import build_graph
from cadmorph.match.cascade import match_entities
from cadmorph.match.model import ENCODER_WEIGHTS, load_encoder
from cadmorph.models import DrawingGraph
from cadmorph.observability import MetricsRecorder, job_log_handler, stage_logger
from cadmorph.register.anchors import build_anchor_pairs
from cadmorph.register.ransac import estimate_transform
from cadmorph.report.document import write_document
from cadmorph.report.markup import write_markup
from cadmorph.summarize.render import render_summaries

JobState = Literal[
    "pending", "extracting", "classifying", "registering", "matching",
    "diffing", "summarizing", "reporting", "done", "failed", "rejected", "declined",
]

TERMINAL_STATES: set[str] = {"done", "failed", "rejected", "declined"}
DEFAULT_TTL_HOURS = 24


def ttl_hours() -> float:
    """Artifact retention window (T045); operator-tunable via env."""
    return float(os.environ.get("CADMORPH_TTL_HOURS", DEFAULT_TTL_HOURS))


class ComparisonJob(BaseModel):
    comparison_id: str
    state: JobState = "pending"
    reason: str | None = None
    message: str | None = None
    page_index: int = 0
    created_at: datetime
    finished_at: datetime | None = None
    expires_at: datetime
    stage_timings_ms: dict[str, float] = {}


class JobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, comparison_id: str) -> Path:
        return self.root / comparison_id

    def create(self, file_old: bytes, name_old: str, file_new: bytes, name_new: str,
               page_index: int = 0) -> ComparisonJob:
        comparison_id = str(uuid.uuid4())
        directory = self.job_dir(comparison_id)
        directory.mkdir(parents=True)
        (directory / "upload_old.pdf").write_bytes(file_old)
        (directory / "upload_new.pdf").write_bytes(file_new)
        (directory / "names.json").write_text(
            json.dumps({"old": name_old, "new": name_new}), encoding="utf-8"
        )
        now = datetime.now(UTC)
        job = ComparisonJob(
            comparison_id=comparison_id,
            created_at=now,
            expires_at=now + timedelta(hours=ttl_hours()),
            page_index=page_index,
        )
        self.save(job)
        return job

    def save(self, job: ComparisonJob) -> None:
        (self.job_dir(job.comparison_id) / "job.json").write_text(
            job.model_dump_json(), encoding="utf-8"
        )

    def load(self, comparison_id: str) -> ComparisonJob | None:
        path = self.job_dir(comparison_id) / "job.json"
        if not path.exists():
            return None
        return ComparisonJob.model_validate_json(path.read_text(encoding="utf-8"))

    def finish(self, job: ComparisonJob, state: JobState, reason: str | None = None,
               message: str | None = None) -> None:
        job.state = state
        job.reason = reason
        job.message = message
        job.finished_at = datetime.now(UTC)
        self.save(job)

    def cleanup_expired(self) -> int:
        """Remove data/{comparison_id} trees whose TTL has lapsed (T045).

        Non-terminal jobs (pending/extracting/.../reporting) are NEVER swept,
        regardless of age — a slow or backlogged run must not lose its data
        mid-write. Directories without a readable job.json (crashed
        mid-create, corrupt state file) can't reveal a state, so they are
        removed only when the newest mtime across the directory and its
        files is older than the TTL — one fresh artifact keeps the tree.
        """
        removed = 0
        now = datetime.now(UTC)
        ttl = timedelta(hours=ttl_hours())
        for job_dir in self.root.iterdir():
            if not job_dir.is_dir():
                continue
            try:
                job = self.load(job_dir.name)
            except Exception:  # unreadable job.json -> age by tree mtime
                job = None
            if job is not None:
                if job.state not in TERMINAL_STATES:
                    continue  # running jobs are untouchable at any age
                expired = job.expires_at < now
            else:
                mtimes = [job_dir.stat().st_mtime,
                          *(p.stat().st_mtime for p in job_dir.iterdir())]
                newest = datetime.fromtimestamp(max(mtimes), tz=UTC)
                expired = now - newest > ttl
            if expired:
                shutil.rmtree(job_dir, ignore_errors=True)
                removed += 1
        return removed


async def cleanup_loop(store: JobStore, interval_s: float = 3600.0) -> None:
    """Recurring TTL sweep (T045), run for the app's lifetime via lifespan.

    Sweeps immediately on startup (catches artifacts that expired while the
    server was down), then every interval_s.
    """
    log = stage_logger("system", "cleanup")
    while True:
        removed = store.cleanup_expired()
        if removed:
            log.info("expired_artifacts_removed", removed=removed)
        await asyncio.sleep(interval_s)


@lru_cache(maxsize=1)
def _models():
    """Pinned models, loaded once per process (hash-checked at load, R11)."""
    return load_classifier(), load_encoder()


def pipeline_version() -> str:
    """Code version + model-weight hashes (audit/determinism, data-model.md)."""
    return (
        f"cadmorph-0.1.0+gat.{pinned_hash(CLASSIFIER_WEIGHTS)[:8]}"
        f"+siamese.{pinned_hash(ENCODER_WEIGHTS)[:8]}"
    )


def run_job(store: JobStore, comparison_id: str) -> None:
    """Execute available pipeline stages for one comparison."""
    job = store.load(comparison_id)
    if job is None:
        return
    metrics = MetricsRecorder(comparison_id)
    directory = store.job_dir(comparison_id)
    names = json.loads((directory / "names.json").read_text(encoding="utf-8"))
    log_handler = job_log_handler(directory / "job.log", comparison_id)
    logging.getLogger().addHandler(log_handler)
    try:
        seed_all()  # Constitution IV: every run draws from fixed seeds
        job.state = "extracting"
        store.save(job)

        with metrics.stage("validation") as log:
            for role in ("old", "new"):
                result = validate_input(directory / f"upload_{role}.pdf", job.page_index)
                if not result.ok:
                    log.info("input_rejected", role=role, reason=result.reason)
                    store.finish(job, "rejected", reason=result.reason,
                                 message=result.message.replace(f"upload_{role}.pdf", names[role])
                                 if result.message else None)
                    metrics.write(directory)
                    return
                log.info("input_valid", role=role, pages=result.page_count)

        graphs: dict[str, DrawingGraph] = {}
        with metrics.stage("extraction") as log:
            provider = get_provider("pdf")
            for role in ("old", "new"):
                graph = provider.extract(directory / f"upload_{role}.pdf", role, job.page_index)
                graph.revision.source_filename = names[role]  # user's name, not the stored one
                graph = build_graph(graph)
                graphs[role] = graph
                (directory / f"graph_{role}.json").write_text(
                    graph.model_dump_json(), encoding="utf-8"
                )
                log.info(
                    "extracted", role=role, entities=len(graph.entities), edges=len(graph.edges)
                )
                metrics.record("extraction", **{f"entities_{role}": len(graph.entities)})

        job.state = "classifying"
        store.save(job)
        with metrics.stage("classify") as log:
            classifier, encoder = _models()
            for role in ("old", "new"):
                graphs[role] = classify_graph(graphs[role], classifier)
                low = low_confidence_count(graphs[role])
                metrics.record("classify", **{f"low_confidence_{role}": low})
                log.info("classified", role=role, low_confidence=low)

        job.state = "registering"
        store.save(job)
        with metrics.stage("register") as log:
            anchors = build_anchor_pairs(graphs["old"], graphs["new"])
            registration = estimate_transform(anchors, graphs["new"].revision.sheet_diagonal)
            metrics.record(
                "register",
                inlier_ratio=registration.inlier_ratio,
                rms_residual_rel=registration.rms_residual_rel,
                anchors_used=registration.anchors_used,
                status=registration.status,
            )
            log.info(
                "registered",
                status=registration.status,
                anchors=registration.anchors_used,
                inlier_ratio=registration.inlier_ratio,
            )
            if registration.status == "failed":
                # FR-004: unalignable inputs are declined, never force-compared
                store.finish(
                    job,
                    "declined",
                    reason="alignment_failed",
                    message=(
                        f"'{names['old']}' and '{names['new']}' do not appear to "
                        "be revisions of the same sheet (alignment failed)"
                    ),
                )
                metrics.write(directory)
                return

        job.state = "matching"
        store.save(job)
        with metrics.stage("match") as log:
            outcome = match_entities(
                graphs["old"], graphs["new"], encoder, transform=registration.transform
            )
            metrics.record(
                "match",
                tier_counts=outcome.tier_counts,
                similarity_histogram=outcome.similarity_histogram,
                unmatched_old=len(outcome.unmatched_old),
                unmatched_new=len(outcome.unmatched_new),
            )
            log.info("matched", tier_counts=outcome.tier_counts,
                     unmatched_old=len(outcome.unmatched_old),
                     unmatched_new=len(outcome.unmatched_new))

        job.state = "diffing"
        store.save(job)
        with metrics.stage("diff") as log:
            deltas = compute_deltas(
                graphs["old"], graphs["new"], outcome, transform=registration.transform
            )
            by_type = dict(Counter(d.change_type for d in deltas))
            metrics.record("diff", **by_type)
            log.info("diffed", **by_type)

        job.state = "summarizing"
        store.save(job)
        with metrics.stage("summarize") as log:
            lines = render_summaries(deltas)
            log.info("summarized", lines=len(lines),
                     ungrounded=sum(1 for line in lines if not line.values_grounded))

        job.state = "reporting"
        store.save(job)
        with metrics.stage("report") as log:
            report = ChangeReport(
                comparison_id=comparison_id,
                revisions={"old": graphs["old"].revision, "new": graphs["new"].revision},
                outcome="changes_found" if deltas else "no_changes",
                deltas=deltas,
                summary_lines=lines,
                markup_ref="markup.pdf",
                metrics_ref="metrics.json",
                pipeline_version=pipeline_version(),
            )
            write_markup(
                directory / "upload_new.pdf", report, directory / "markup.pdf", job.page_index
            )
            write_document(
                report,
                directory / "report.pdf",
                source_pdf_old=directory / "upload_old.pdf",
                source_pdf_new=directory / "upload_new.pdf",
                registration=registration,
                page_index=job.page_index,
            )
            (directory / "report.json").write_text(canonical_json(report), encoding="utf-8")
            log.info("report_written", outcome=report.outcome, deltas=len(deltas))

        job.stage_timings_ms = metrics.stage_timings_ms
        store.finish(job, "done")
    except Exception as exc:  # noqa: BLE001 — any stage error fails the job with context
        store.finish(job, "failed", reason="internal", message=str(exc))
    finally:
        metrics.write(directory)
        logging.getLogger().removeHandler(log_handler)
        log_handler.close()
