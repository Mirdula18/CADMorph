# CADMorph

**AI-based CAD drawing change detection - a vector-native, entity-level pipeline for tracking revisions across CAD-exported PDFs.**

CADMorph compares two versions of a CAD drawing (`V(n-1)` and `V(n)`) and produces a grounded, human-readable change report: every addition, removal, and modification is traced back to an exact entity in the source file - never inferred from pixels, never fabricated.

---

## Table of contents

- [Why this exists](#why-this-exists)
- [Core design principle](#core-design-principle)
- [Methodology — how the pipeline works](#methodology--how-the-pipeline-works)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Setup & installation](#setup--installation)
- [Running your first comparison](#running-your-first-comparison)
- [Configuration](#configuration)
- [Testing](#testing)
- [Determinism & grounding guarantees](#determinism--grounding-guarantees)
- [Current scope & limitations](#current-scope--limitations)
- [Roadmap](#roadmap)
- [Development workflow](#development-workflow)
- [References](#references)
- [License](#license)

---

## Why this exists

Design and construction firms iterate on drawings continuously: a drawing is exported from AutoCAD as a PDF, revised against client feedback, and re-exported. Confirming exactly what changed between two revisions is today a manual, visual task - slow, and error-prone precisely when differences are subtle and scattered across a dense sheet.

Generic "number of changes" or "confidence percentage" metrics aren't useful to an architect or engineer. What's needed is a report that reads like a person wrote it: *"Wall shifted from 4 in to 5 in,"* not *"37 pixels changed, 62% confidence."*

## Core design principle

**Work in vector space, not pixel space.**

A CAD-exported PDF is not fundamentally an image - it's a container of exact vector geometry: lines, arcs, text, and dimensions, each with precise coordinates. Rasterizing that geometry and comparing pixels throws away perfect information and manufactures the exact alignment and noise problems that make classical computer-vision diffing brittle (export drift, anti-aliasing, misregistration).

CADMorph parses and reasons over the vector entities directly. This turns three hard problems into tractable, near-exact ones:

- **Alignment** becomes geometric transform estimation (RANSAC over stable anchors), not image registration.
- **Change detection** becomes entity matching on a graph, not pixel differencing.
- **Bounding boxes** fall out of each entity's own coordinate extent — exact, not detector-inferred.

A raster fallback path (for scanned/flattened drawings) is designed but not yet built — see [Roadmap](#roadmap).

## Methodology — how the pipeline works

Every comparison runs through a deterministic, staged pipeline:

```
1. VALIDATION     Reject raster-only, corrupt, encrypted, or non-PDF input,
                   naming the offending file. No comparison is forced on
                   unusable input.

2. EXTRACTION      Parse exact vector geometry AND text directly from the PDF
                   (PyMuPDF) into an attributed drawing graph. Dimension
                   values, labels, and positions are read verbatim from the
                   source -- never OCR'd, never guessed.

3. CLASSIFICATION  A Graph Attention Network (GAT) labels each entity's likely
                   semantic type (wall, door, window, furniture, dimension...).
                   This is the ONE deliberately inference-based step on the
                   vector path -- every label carries its confidence and is
                   flagged as inference-derived, never presented as fact.

4. REGISTRATION    Deterministic anchor correspondences (unique text strings,
                   unique geometry signatures) feed a seeded RANSAC estimator
                   that fits a similarity transform (translation + uniform
                   scale + rotation) correcting real-world export drift
                   (AutoCAD's manual "window selection" shifts sheets between
                   revisions). If no reliable alignment exists -- e.g. the
                   two files aren't the same sheet -- the comparison is
                   explicitly DECLINED, never force-compared.

5. MATCHING        A three-tier cascade pairs entities across revisions:
                     Tier 1 (exact)     -- identical content signature at the
                                          registered position
                     Tier 2 (attribute) -- same label/shape, in place, with a
                                          changed attribute (style, dimension
                                          value, text)
                     Tier 3 (learned)   -- a Siamese graph encoder + Hungarian
                                          assignment recovers correspondences
                                          for moved/ambiguous entities, with
                                          a calibrated displacement rule to
                                          distinguish a genuine "moved" entity
                                          from a look-alike "removed + added"
                                          pair (identical siblings, symmetric
                                          symbols, etc.)

6. DIFFING         Matched/unmatched entities become typed EntityDelta
                   records: change_type (added/removed/modified),
                   modification_kinds (moved, geometry, text, dimension_value,
                   style), and full before/after state -- computed
                   deterministically from the registered geometry.

7. SUMMARIZATION   Grounded, TEMPLATE-based natural-language generation --
                   no LLM call. Every stated value is read directly from the
                   delta record; the summarizer is structurally forbidden
                   (enforced by an import-linter contract, not just
                   convention) from ever importing raw geometry, pixels, or
                   the extraction layer. It cannot fabricate a value even by
                   accident.

8. REPORTING       A results UI (side-by-side sheet + filterable change list,
                   click-to-sync selection), a downloadable color-coded
                   vector markup PDF, and a structured printable PDF report
                   (cover dashboard, before/after pages, overlay page,
                   itemized change table) -- all derived from the same
                   grounded delta records.
```

Given identical input files, the entire pipeline -- including the two ML stages -- produces a **byte-identical** report. See [Determinism & grounding guarantees](#determinism--grounding-guarantees).

## Architecture

```
                         +-------------------------+
                         |   PDF input (V1, V2)    |
                         +------------+------------+
                                      |
                    +-----------------+------------------+
                    |        VECTOR-NATIVE PATH          |
                    |            (primary)               |
                    |                                    |
                    |  Entity parsing (PyMuPDF)          |
                    |        |                           |
                    |  Drawing graph + GAT labeling      |
                    |        |                           |
                    |  Anchor extraction + seeded RANSAC |
                    |        |                           |
                    |  3-tier match (exact/attribute/    |
                    |  learned Siamese + Hungarian)      |
                    +-----------------+------------------+
                                      |
                    +-----------------+-------------------+
                    |      SHARED SEMANTIC + OUTPUT       |
                    |                                     |
                    |  Typed entity deltas                |
                    |        |                            |
                    |  Grounded template summarizer       |
                    |        |                            |
                    |  Web UI - markup.pdf - report.pdf   |
                    +-------------------------------------+

   (A raster fallback path -- feature 002 -- is designed to slot in behind
    the same shared layer via the ExtractionProvider interface; not built.)
```

## Tech stack

| Layer | Component | Technology |
|---|---|---|
| Backend | API & orchestration | Python 3.11+, FastAPI |
| Backend | Vector parsing | PyMuPDF (fitz) |
| Backend | Graph representation & models | PyTorch, PyTorch Geometric |
| Backend | Classification | Graph Attention Network (GAT) |
| Backend | Matching | Siamese GNN encoder + Hungarian assignment |
| Backend | Registration | Seeded RANSAC (complex-plane similarity fit) |
| Backend | Report generation | ReportLab (structured PDF), PyMuPDF (vector markup) |
| Backend | Logging / observability | structlog |
| Backend | Data modeling | Pydantic |
| Frontend | App | React, TypeScript, Vite |
| Testing | Test runner | pytest (unit, integration, determinism, ground-truth suites) |
| Testing | Synthetic ground truth | `synthgen` -- an in-repo tool generating labeled before/after CAD-style PDF pairs with a known answer key |

## Project structure

```
CADMorph/
+-- backend/
|   +-- src/cadmorph/
|   |   +-- api/            FastAPI app + routes
|   |   +-- extraction/     PDF parsing, input validation, provider interface
|   |   +-- graph/          Drawing graph construction
|   |   +-- classify/       GAT model, inference stage
|   |   +-- register/       Anchor extraction, seeded RANSAC
|   |   +-- match/          Tiered matching cascade, Siamese model + training
|   |   +-- deltas/         Typed delta computation, canonical JSON contract
|   |   +-- summarize/      Grounded template-based NLP
|   |   +-- report/         Vector markup, sheet rendering, structured PDF
|   |   +-- models.py       Core geometry/entity Pydantic models
|   |   +-- pipeline.py     Stage orchestration
|   |   +-- config.py       Calibrated thresholds, severity rules
|   |   +-- observability.py
|   +-- tests/
|       +-- unit/           Contract, schema, and seam tests
|       +-- integration/    API-level behavior, self-containment, TTL
|       +-- determinism/    Byte-identity across repeat runs
|       +-- groundtruth/    Precision/recall against synthgen answer keys
+-- frontend/
|   +-- src/                Upload flow, results view, sheet overlay
+-- tools/synthgen/         Synthetic ground-truth pair generator
+-- specs/001-pdf-change-detection/
    +-- spec.md, plan.md, research.md, data-model.md
    +-- contracts/          Frozen API & delta schema contracts
    +-- quickstart.md       Runnable end-to-end validation scenarios
```

## Setup & installation

**Prerequisites:** Python 3.11+, Node 20+.

```bash
git clone https://github.com/Mirdula18/CADMorph.git
cd CADMorph

# Backend -- the [ml] extra is required from the classification/matching
# stages onward; the app will fail to import without it.
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e "backend[dev,ml]"
pip install -e tools/synthgen

# Frontend
npm install --prefix frontend
```

**Start the app** (two terminals):

```bash
# Terminal 1 -- backend
cd backend
python -m uvicorn cadmorph.api.app:app --port 8000
# Prefer `python -m uvicorn ...` over a bare `uvicorn` command -- it
# guarantees the server runs inside the active virtual environment's
# Python, avoiding PATH ambiguity if multiple Python installs are present.

# Terminal 2 -- frontend (proxies /api to the backend above)
npm run dev --prefix frontend
```

Open the printed frontend URL (typically `http://localhost:5173`).

## Running your first comparison

You'll need two PDFs to compare. If you don't have real CAD exports handy, generate a labeled synthetic pair:

```bash
python -m synthgen make-pair \
  --preset floorplan \
  --mutations dim-change,add,remove,move \
  --seed 42 \
  --out data/manual-test/pair01
```

This writes `v1.pdf`, `v2.pdf`, and `answer-key.json` (the ground-truth changes) into the output directory. Upload `v1.pdf` as "Previous revision" and `v2.pdf` as "New revision" in the UI, click Compare, and review the results -- then download the marked-up PDF and the printable report to see the same changes reflected there.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `CADMORPH_DATA_DIR` | `data` | Root directory for per-comparison job artifacts |
| `CADMORPH_TTL_HOURS` | `24` | Artifact retention window before cleanup |
| `CADMORPH_CLEANUP_INTERVAL_S` | `3600` | How often the retention sweep runs |
| `CADMORPH_MAX_UPLOAD_MB` | `50` | Per-file upload size cap (rejected beyond this, naming the file) |

## Testing

```bash
pytest backend/tests
```

Test suites and what they guarantee:

- **Unit** -- delta schema conformance, provider/import seam boundaries (e.g. the summarizer cannot import raw geometry or pixel-handling code), severity/affected-area arithmetic.
- **Integration** -- API contract behavior, input rejection (FR-002), self-containment (no network egress beyond the process's own internal loopback), TTL-based cleanup correctness, markup traceability.
- **Determinism** -- byte-identical output across repeated runs on identical input, including through both ML stages (pinned, hash-checked model weights; fixed seeding; deterministic algorithm mode).
- **Ground-truth** -- precision/recall against `synthgen`-generated answer keys for classification, matching (including a calibrated move-distance sweep and adversarial "twin" fixtures), and full end-to-end detection.

Performance: a synthetic sheet at ~10,000 entities per side completes in ~12 seconds wall-clock (budget: 120 seconds).

## Determinism & grounding guarantees

These are enforced by tests, not just design intent:

- **Byte-identical repeat runs.** Identical input files always produce identical output bytes -- report JSON, the vector markup PDF, and the printable report -- even though two neural network stages sit in the pipeline (achieved via pinned model weights, fixed seeding, and forced deterministic algorithm execution).
- **No fabricated values.** Every dimension, label, and position stated in a report is read verbatim from the source file or computed deterministically from it. A value that can't be determined is stated as such -- never estimated or invented.
- **Confidence appears only where it's honest.** A confidence/percentage value is shown *only* on the two genuinely inference-derived fields in the whole pipeline (the GAT semantic label, and a learned-tier match similarity) -- never attached to a deterministic detection, and this is enforced by a negative-assertion test on the report generator.
- **Self-contained by design.** All processing -- including both ML models and summary generation -- runs in-process on your own infrastructure. No drawing content is ever sent to a third-party API. Verified by a test that blocks all outbound network connections during a full comparison and confirms it still completes.
- **Declines rather than guesses.** If two uploaded files can't be reliably aligned (not the same sheet, or unrelated), the system explicitly declines the comparison rather than producing a misleading result.

## Current scope & limitations

Honest boundaries of what's built today:

- **Vector-native PDF input only.** A PDF must have genuine vector geometry and a text layer. Rasterized/scanned PDFs are correctly detected and rejected -- not degraded to a lesser analysis.
- **DXF/DWG input is not yet supported**, though the architecture anticipates it.
- **One sheet per comparison.** Multi-page PDFs are supported for upload, but only one selected page per file is compared per run.
- **No structured (JSON/CSV) export in the UI** beyond the full JSON already returned by the API -- human-readable output is the primary deliverable today.
- **No accounts or persistent comparison history** -- jobs are ephemeral, cleaned up on a TTL.

## Roadmap

**Raster fallback path (feature 002)** -- for scanned or flattened drawings without usable vector data: learned image registration, a change-detection network adapted from the remote-sensing literature, and an extraction stack to recover structured entities from pixels, feeding into the *same* shared semantic/summarization/reporting layer this vector path already uses. The seam for this (`ExtractionProvider`) already exists in the codebase; the raster implementation itself does not yet.

Other candidates: DXF/DWG native ingestion, multi-sheet batch comparison, structured export formats.

## Development workflow

This project was built using a spec-driven workflow: a project constitution defines non-negotiable engineering principles (vector-native-first, grounded outputs, entity-level traceability, determinism, ground-truth validation before trust), and each feature moves through specification -> clarification -> technical planning -> task breakdown -> cross-artifact consistency analysis -> implementation. Full artifacts for the current feature -- including the original specification, technical plan, research decisions, data model, and frozen API/schema contracts -- are in `specs/001-pdf-change-detection/`.

## References

- Zheng et al., *GAT-CADNet: Graph Attention Network for Panoptic Symbol Spotting in CAD Drawings*
- *Automated Parsing of Engineering Drawings for Structured Information Extraction Using a Fine-tuned Document Understanding Transformer*
- eDOCr -- OCR system for mechanical engineering drawings

## License

_Add your chosen license here (e.g. MIT, Apache 2.0) before publishing._