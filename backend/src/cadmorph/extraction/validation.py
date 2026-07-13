"""Input validation (FR-002): vector-content detection and rejection reasons.

A file is usable only if it is a readable PDF whose compared page carries
vector drawings or text. Raster-only pages (scans) are rejected — never
silently processed at lower fidelity (Constitution I).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

RejectionReason = str  # "unsupported_format" | "unreadable" | "raster_or_empty"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    format: str | None = None
    page_count: int = 0
    reason: RejectionReason | None = None
    message: str | None = None


def validate_input(path: str | Path, page_index: int = 0) -> ValidationResult:
    path = Path(path)
    name = path.name

    with open(path, "rb") as fh:
        header = fh.read(5)
    if header != b"%PDF-":
        return ValidationResult(
            ok=False,
            reason="unsupported_format",
            message=f"'{name}' is not a PDF file; feature 001 accepts vector PDFs only "
            "(DXF support is deferred to a later feature)",
        )

    try:
        doc = fitz.open(path)
    except Exception:
        return ValidationResult(
            ok=False, reason="unreadable", message=f"'{name}' could not be opened (corrupt PDF?)"
        )

    try:
        if doc.needs_pass:
            return ValidationResult(
                ok=False,
                reason="unreadable",
                message=f"'{name}' is password-protected and cannot be read",
            )
        if page_index >= doc.page_count:
            return ValidationResult(
                ok=False,
                reason="unreadable",
                message=f"'{name}' has {doc.page_count} page(s); page {page_index} does not exist",
            )
        page = doc[page_index]
        has_vector = bool(page.get_drawings()) or bool(page.get_text("words"))
        if not has_vector:
            return ValidationResult(
                ok=False,
                reason="raster_or_empty",
                message=f"'{name}' page {page_index} has no vector drawing content "
                "(scanned/raster PDFs are out of scope for this feature)",
            )
        return ValidationResult(ok=True, format="pdf", page_count=doc.page_count)
    finally:
        doc.close()
