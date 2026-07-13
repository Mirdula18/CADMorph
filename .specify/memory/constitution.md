<!--
Sync Impact Report
Version change: (template, unversioned) → 1.0.0 (initial ratification)
Modified principles: N/A (initial adoption of Principles I–V)
Added sections: Core Principles; Pipeline Constraints; Development Workflow & Quality Gates; Governance
Removed sections: none
Templates:
- ✅ .specify/templates/plan-template.md — generic Constitution Check gate; compatible as-is
- ✅ .specify/templates/spec-template.md — no constitution-specific references
- ✅ .specify/templates/tasks-template.md — no constitution-specific references
- ✅ .specify/templates/checklist-template.md — no constitution-specific references
Follow-up TODOs: none
-->

# CADMorph Constitution

CADMorph is an AI-based CAD drawing change-detection system: it compares two
revisions of an engineering drawing (PDF/DXF), detects entity-level changes,
and produces grounded natural-language change summaries.

## Core Principles

### I. Vector-Native First

The system MUST parse exact vector geometry from PDF and DXF sources whenever
a vector layer exists. Rasterizing a drawing that contains usable vector data
is prohibited on the primary path. Rasterization, and any pixel-based
comparison built on it, is a fallback path only — invoked exclusively when no
vector layer is available (e.g., scanned drawings) — and outputs produced via
the fallback path MUST be labeled as raster-derived.

**Rationale**: Vector data carries exact coordinates, text, and structure.
Discarding it for pixels destroys precision the system can never recover and
turns deterministic reads into probabilistic inference.

### II. Grounded Outputs

NLP change summaries MUST be generated only from structured entity deltas —
never directly from raw pixels. Every dimension value, coordinate, or entity
attribute stated in a summary MUST originate from parsed source data or a
computed delta; fabricating, estimating, or "filling in" dimension values is
prohibited. If a value cannot be extracted, the summary MUST say so rather
than invent one.

**Rationale**: A change report that hallucinates a dimension is worse than no
report — engineers act on these numbers. Grounding every claim in structured
data makes summaries verifiable and safe to trust.

### III. Entity-Level Traceability

Every reported change MUST be traceable to a specific entity and its
before/after state. Each change record MUST identify the entity (stable ID or
source handle), the change type (added / removed / modified), and the
entity's full prior and posterior state where applicable. No aggregate or
free-floating change claims are permitted: if a summary sentence cannot be
mapped back to at least one concrete entity delta, it MUST NOT be emitted.

**Rationale**: Traceability is what lets a reviewer audit any claim back to
the drawings. It is also the enforcement mechanism for Principle II — a
summary grounded in deltas is only checkable if the deltas themselves point
at real entities.

### IV. Determinism Where Possible

On the vector path, bounding boxes, dimension reads, and text extraction MUST
come from source coordinates and text layers — not from model inference.
Inference (ML detection, OCR, LLM extraction) is permitted only where
deterministic extraction is impossible (the raster fallback path), and any
inference-derived value MUST be flagged as such with an associated confidence.
Given identical input files, the vector pipeline MUST produce identical
structured deltas.

**Rationale**: Deterministic reads are exactly reproducible, unit-testable,
and immune to model drift. Reserving inference for genuinely ambiguous inputs
keeps the error surface small and clearly demarcated.

### V. Ground-Truth Validation Before Trust

Each pipeline phase (parsing, entity matching, delta detection, summary
generation) MUST be validated against synthetic ground-truth drawing pairs —
pairs with known, programmatically injected changes — before its output is
trusted by downstream phases or shipped. Validation MUST report detection
precision/recall against the known change set, and a phase failing its
validation gate MUST NOT be built upon until fixed.

**Rationale**: Real drawing pairs lack authoritative answer keys. Synthetic
pairs with known deltas are the only way to measure correctness objectively,
and validating per-phase localizes failures before they compound.

## Pipeline Constraints

- **Input formats**: PDF (vector and scanned) and DXF are first-class inputs.
  Format detection MUST determine vector availability before choosing a path
  (Principle I).
- **Structured delta schema**: Entity deltas are the single contract between
  detection and summarization. The schema MUST capture entity identity,
  change type, before/after state, and provenance (vector-exact vs.
  inference-derived, per Principle IV).
- **Provenance labeling**: Every output artifact (delta record, overlay box,
  summary sentence) MUST carry provenance sufficient to distinguish the
  deterministic vector path from the raster fallback path.
- **Fallback discipline**: The raster path MUST NOT silently substitute for
  the vector path. Falling back is an explicit, logged decision.

## Development Workflow & Quality Gates

- **Constitution Check at plan time**: Every feature plan MUST pass a
  Constitution Check against Principles I–V before Phase 0 research and again
  after design (per `.specify/templates/plan-template.md`).
- **Synthetic fixtures precede implementation**: For any phase-level feature,
  the synthetic ground-truth pairs used to validate it (Principle V) MUST be
  defined no later than the phase's implementation tasks.
- **Grounding review**: Any change to summary generation MUST include a check
  that every emitted claim maps to a structured delta (Principles II–III);
  reviewers MUST reject summary code paths that can access raw pixels.
- **Determinism tests**: The vector pipeline MUST have tests asserting
  byte-identical structured deltas across repeated runs on the same inputs.

## Governance

This constitution supersedes all other development practices for CADMorph.

- **Amendments**: Any amendment MUST be made via a change to this file that
  updates the version line, documents the change in the Sync Impact Report,
  and propagates required updates to dependent templates in
  `.specify/templates/`.
- **Versioning policy**: Semantic versioning — MAJOR for principle removals
  or backward-incompatible redefinitions, MINOR for new principles or
  materially expanded guidance, PATCH for clarifications and wording fixes.
- **Compliance review**: All PRs and reviews MUST verify compliance with the
  Core Principles. Violations require an entry in the plan's Complexity
  Tracking table justifying why the violation is needed and why the compliant
  alternative was rejected; unjustified violations block merge.

**Version**: 1.0.0 | **Ratified**: 2026-07-04 | **Last Amended**: 2026-07-04
