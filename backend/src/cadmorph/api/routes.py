"""API routes per contracts/api.md (Phase 2 scope: upload + status)."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from cadmorph.pipeline import JobStore, run_job
from cadmorph.report.render import render_sheet, transform_header

router = APIRouter()


def max_upload_bytes() -> int:
    """Per-file upload cap (T046, FR-016 hardening); env-tunable."""
    return int(os.environ.get("CADMORPH_MAX_UPLOAD_MB", "50")) * 1024 * 1024


def _envelope(code: str, message: str, comparison_id: str | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if comparison_id is not None:
        error["comparison_id"] = comparison_id
    return {"error": error}


@router.post("/comparisons", status_code=202)
async def create_comparison(
    request: Request,
    background: BackgroundTasks,
    file_old: UploadFile = File(...),
    file_new: UploadFile = File(...),
    page: int = Form(0),
) -> JSONResponse:
    store: JobStore = request.app.state.store

    for upload in (file_old, file_new):
        name = upload.filename or "upload"
        if not name.lower().endswith(".pdf"):
            return JSONResponse(
                status_code=400,
                content=_envelope(
                    "unsupported_format",
                    f"'{name}' is not a PDF; feature 001 accepts vector PDFs only "
                    "(DXF support is deferred to a later feature)",
                ),
            )

    limit = max_upload_bytes()
    data_old = await file_old.read()
    data_new = await file_new.read()
    for name, data in (
        (file_old.filename or "old.pdf", data_old),
        (file_new.filename or "new.pdf", data_new),
    ):
        if len(data) > limit:
            return JSONResponse(
                status_code=413,
                content=_envelope(
                    "file_too_large",
                    f"'{name}' is {len(data) / 1048576:.1f} MiB; "
                    f"the per-file limit is {limit // 1048576} MiB",
                ),
            )

    job = store.create(
        data_old, file_old.filename or "old.pdf",
        data_new, file_new.filename or "new.pdf",
        page_index=page,
    )
    background.add_task(run_job, store, job.comparison_id)
    return JSONResponse(status_code=202, content={"comparison_id": job.comparison_id})


@router.get("/comparisons/{comparison_id}")
async def get_status(comparison_id: str, request: Request) -> JSONResponse:
    store: JobStore = request.app.state.store
    job = store.load(comparison_id)
    if job is None:
        return JSONResponse(
            status_code=404, content=_envelope("not_found", "unknown comparison id", comparison_id)
        )
    outcome = None
    if job.state == "done":
        report_path = store.job_dir(comparison_id) / "report.json"
        outcome = json.loads(report_path.read_text(encoding="utf-8"))["outcome"]
    return JSONResponse(
        content={
            "comparison_id": job.comparison_id,
            "state": job.state,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "outcome": outcome,
            "reason": job.reason,
            "message": job.message,
        }
    )


@router.get("/comparisons/{comparison_id}/report")
async def get_report(comparison_id: str, request: Request) -> Response:
    """Full ChangeReport JSON (contracts/api.md). 409 until the job is done.
    Serves the canonical report bytes verbatim (FR-013 byte-identity)."""
    store: JobStore = request.app.state.store
    job = store.load(comparison_id)
    if job is None:
        return JSONResponse(
            status_code=404, content=_envelope("not_found", "unknown comparison id", comparison_id)
        )
    if job.state != "done":
        return JSONResponse(
            status_code=409,
            content=_envelope(
                "conflict", f"comparison is '{job.state}'; report is available when done",
                comparison_id,
            ),
        )
    report_path = store.job_dir(comparison_id) / "report.json"
    return Response(content=report_path.read_bytes(), media_type="application/json")


def _finished_job_or_error(store: JobStore, comparison_id: str):
    """Shared guard for artifact endpoints: (job, None) or (None, error response)."""
    job = store.load(comparison_id)
    if job is None:
        return None, JSONResponse(
            status_code=404, content=_envelope("not_found", "unknown comparison id", comparison_id)
        )
    if job.state != "done":
        return None, JSONResponse(
            status_code=409,
            content=_envelope(
                "conflict", f"comparison is '{job.state}'; artifacts are available when done",
                comparison_id,
            ),
        )
    return job, None


@router.get("/comparisons/{comparison_id}/markup.pdf")
async def get_markup(comparison_id: str, request: Request):
    """Marked-up vector PDF (FR-010/011; banner page on no_changes, FR-012)."""
    store: JobStore = request.app.state.store
    _, error = _finished_job_or_error(store, comparison_id)
    if error:
        return error
    return FileResponse(store.job_dir(comparison_id) / "markup.pdf", media_type="application/pdf")


@router.get("/comparisons/{comparison_id}/report.pdf")
async def get_report_pdf(comparison_id: str, request: Request):
    """Printable human-readable change report (contracts/api.md)."""
    store: JobStore = request.app.state.store
    _, error = _finished_job_or_error(store, comparison_id)
    if error:
        return error
    return FileResponse(store.job_dir(comparison_id) / "report.pdf", media_type="application/pdf")


@router.get("/comparisons/{comparison_id}/sheet.png")
async def get_sheet(comparison_id: str, request: Request, revision: str = "new"):
    """Display raster of the compared sheet (presentation only, Constitution I)
    with the X-Sheet-Transform delta-coordinate -> pixel mapping header."""
    store: JobStore = request.app.state.store
    if revision not in ("old", "new"):
        return JSONResponse(
            status_code=400,
            content=_envelope("error", "revision must be 'old' or 'new'", comparison_id),
        )
    job, error = _finished_job_or_error(store, comparison_id)
    if error:
        return error
    directory = store.job_dir(comparison_id)
    png_path = directory / f"sheet_{revision}.png"
    meta_path = directory / f"sheet_{revision}.json"
    if not png_path.exists():  # rendered lazily, cached per revision
        transform = render_sheet(
            directory / f"upload_{revision}.pdf", png_path, page_index=job.page_index
        )
        meta_path.write_text(json.dumps(transform), encoding="utf-8")
    transform = json.loads(meta_path.read_text(encoding="utf-8"))
    return Response(
        content=png_path.read_bytes(),
        media_type="image/png",
        headers={"X-Sheet-Transform": transform_header(transform)},
    )
