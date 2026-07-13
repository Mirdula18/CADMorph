# Feature Specification: PDF Drawing Change Detection

**Feature Branch**: `001-pdf-change-detection`

**Created**: 2026-07-04

**Status**: Draft

**Input**: User description: "Compare two versions of a CAD-exported PDF and produce a change report. Given V(n-1) and V(n) of the same drawing sheet, the system aligns them, detects every added / removed / modified entity, and outputs a marked-up drawing plus a human-readable list of changes (e.g. \"Dimension D14 changed from 10 cm to 40 cm\"). Users are architects and civil engineers reviewing revisions."

## Clarifications

### Session 2026-07-04

- Q: How do users interact with the system — what is the delivery surface? → A: Web application — users upload V(n-1) and V(n) in the browser, review the marked-up drawing and change list interactively, and can download the report.
- Q: May drawing content be sent to third-party external services during processing? → A: No — self-contained; all processing stays within the operator's own infrastructure.
- Q: What downloadable formats must the change report support? → A: Human-readable only (marked-up drawing + readable change list); structured machine-readable export is out of scope for v1.
- Q: What sheet complexity must the 2-minute comparison target (SC-006) cover? → A: Sheets with up to 10,000 drawing entities.
- Q: How interactive must the web review screen be for v1? → A: Reviewers can filter the change list and highlights by change type (added / removed / modified); no persistent review state or user accounts in v1.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Compare Two Revisions and Get a Change List (Priority: P1)

An architect receives revision V(n) of a drawing sheet they last reviewed at
V(n-1). They provide both PDF files to the system and receive a complete,
human-readable list of every change between the two revisions. Each list item
names the affected entity, states the type of change (added, removed, or
modified), and — for modifications — shows the exact before and after values
taken from the drawings (e.g., "Dimension D14 changed from 10 cm to 40 cm").

**Why this priority**: This is the core value of the feature. Engineers
currently eyeball two printouts or overlay PDFs manually, which is slow and
misses changes. A trustworthy, complete change list is the minimum viable
product on its own, even without visual markup.

**Independent Test**: Can be fully tested by supplying a pair of drawing
revisions with known differences and verifying the returned list names every
difference — with correct change type and correct before/after values — and
nothing else.

**Acceptance Scenarios**:

1. **Given** two revisions of the same sheet where one dimension's value
   changed, **When** the user runs a comparison, **Then** the change list
   contains exactly one entry identifying that dimension, marked "modified",
   showing its prior and new values as they appear in the drawings.
2. **Given** two revisions where an entity (e.g., a door symbol, a note, a
   line segment) exists only in V(n), **When** the user runs a comparison,
   **Then** the change list contains an "added" entry identifying that entity
   and its location on the sheet.
3. **Given** two revisions where an entity exists only in V(n-1), **When**
   the user runs a comparison, **Then** the change list contains a "removed"
   entry identifying that entity and its former location.
4. **Given** two identical revisions, **When** the user runs a comparison,
   **Then** the system reports that no changes were detected, with an empty
   change list.
5. **Given** any completed comparison, **When** the user inspects any change
   entry, **Then** the entry exposes the specific entity affected and its
   full before and after states — no entry is a vague aggregate claim.

---

### User Story 2 - Review Changes on a Marked-Up Drawing (Priority: P2)

A civil engineer wants to see *where* on the sheet each change occurred, not
just read about it. After a comparison, the system produces a marked-up
version of the drawing in which every detected change is visually highlighted
at its location, color-coded by change type (added / removed / modified).
Each highlight corresponds to an entry in the change list, so the engineer
can move between the list and the drawing.

**Why this priority**: Spatial context is how drawing reviewers actually
work — a change list alone forces them to hunt for each item on the sheet.
Markup builds directly on the P1 change data and multiplies its usefulness.

**Independent Test**: Can be tested by running a comparison on a pair with
known differences and verifying the marked-up output highlights each known
change at the correct sheet location with the correct change-type color, with
a one-to-one correspondence between highlights and change-list entries.

**Acceptance Scenarios**:

1. **Given** a completed comparison with at least one change of each type,
   **When** the user opens the marked-up drawing, **Then** every change in
   the list appears as a highlight at the affected entity's location, and
   added, removed, and modified changes are visually distinguishable from
   one another.
2. **Given** a marked-up drawing, **When** the user selects a highlight or a
   change-list entry, **Then** they can identify the corresponding entry or
   highlight (each highlight carries the same identifier as its list entry).
3. **Given** a comparison with no detected changes, **When** the user opens
   the marked-up drawing, **Then** it shows the sheet with an explicit
   "no changes detected" indication and no highlights.

---

### User Story 3 - Compare Imperfectly Aligned Revisions (Priority: P3)

An engineer compares two revisions that were exported with slightly different
placement on the page (offset, scale, or page-size differences arising from
export settings). The system aligns the two sheets before comparing, so that
unchanged content is not falsely reported as changed. If the system cannot
establish a reliable alignment, it says so clearly instead of producing a
misleading report.

**Why this priority**: Real-world exports rarely overlay perfectly. Without
alignment, every comparison of realistic input would drown in false
positives — but the capability only matters once P1 comparison exists.

**Independent Test**: Can be tested by taking a revision pair with known
differences, shifting/scaling one export, and verifying the change report is
identical to the report for the un-shifted pair.

**Acceptance Scenarios**:

1. **Given** two revisions identical in content but exported with different
   page offsets or scales, **When** the user runs a comparison, **Then** the
   system reports no changes.
2. **Given** two revisions with real changes plus an export offset, **When**
   the user runs a comparison, **Then** the change report matches the report
   produced for the same pair without the offset.
3. **Given** two files that cannot be reliably aligned (e.g., different
   sheets of the project supplied by mistake), **When** the user runs a
   comparison, **Then** the system declines to produce a change report and
   tells the user the inputs do not appear to be revisions of the same sheet.

---

### Edge Cases

- Two identical files submitted: system reports zero changes rather than
  failing or fabricating differences.
- Entirely unrelated drawings submitted: system detects alignment failure and
  reports that the inputs do not appear to be the same sheet (US3, scenario 3).
- A PDF with no usable vector content (e.g., a scan) is submitted: system
  informs the user that the file is not a vector CAD export and does not
  silently produce lower-fidelity results (see Assumptions — raster handling
  is out of scope for this feature).
- An entity is moved rather than edited: system reports it as a modification
  (position change) of one entity, with before/after locations — not as an
  unrelated removal plus addition — whenever the entity's identity can be
  established across revisions.
- A value cannot be read for an entity involved in a change: the change entry
  states that the value is unavailable; it never shows a guessed value.
- Corrupt, password-protected, or unreadable PDF: system rejects the file
  with a message identifying which input failed and why.
- Very large change count (e.g., a full redraw): system still produces a
  complete list and markup, and summarizes the scale of change up front so
  the reviewer knows the revisions diverge heavily.
- Multi-page PDF supplied: system compares the corresponding single sheet
  (see Assumptions) and tells the user which page was compared.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept two PDF files designated as the earlier
  revision V(n-1) and the later revision V(n) of a single drawing sheet.
  DXF input is deferred to a later feature; this feature is PDF-only.
- **FR-002**: System MUST verify that each input contains usable vector
  drawing content and MUST reject non-vector (e.g., scanned) or unreadable
  inputs with a message stating which file was rejected and why.
- **FR-003**: System MUST align the two revisions before comparison so that
  differences in page placement, offset, or export scale are not reported as
  drawing changes.
- **FR-004**: System MUST detect an alignment failure and, in that case,
  decline to produce a change report, informing the user that the inputs do
  not appear to be revisions of the same sheet.
- **FR-005**: System MUST detect every entity that was added, removed, or
  modified between the two revisions, including geometry (lines, arcs,
  shapes), annotations (dimensions, text, labels, symbols), and their
  attributes (values, positions, sizes).
- **FR-006**: System MUST classify each detected change as exactly one of:
  added, removed, or modified.
- **FR-007**: For every detected change, system MUST record the specific
  entity affected together with its complete before state and after state
  (as applicable to the change type), and every item in the user-facing
  report MUST be traceable to one such record.
- **FR-008**: System MUST produce a human-readable change list in which each
  entry names the entity, the change type, and — for modifications — the
  exact prior and new values as extracted from the drawings (e.g.,
  "Dimension D14 changed from 10 cm to 40 cm").
- **FR-009**: All values shown in the change list (dimensions, labels,
  positions) MUST be taken from the drawing content itself; the system MUST
  NOT estimate, infer, or fabricate a value. Where a value cannot be
  extracted, the entry MUST state that explicitly.
- **FR-010**: System MUST produce a marked-up drawing output in which every
  detected change is highlighted at the affected entity's location on the
  sheet, visually distinguished by change type (added / removed / modified).
- **FR-011**: Each highlight in the marked-up drawing MUST share an
  identifier with its corresponding change-list entry, so users can match
  list entries to sheet locations and vice versa.
- **FR-012**: When no changes are detected, system MUST state this explicitly
  in both the change list (empty, with a "no changes" result) and the
  marked-up drawing (no highlights, with a "no changes" indication).
- **FR-013**: Repeating a comparison on the same pair of input files MUST
  produce the same change report.
- **FR-014**: System MUST report, alongside results, which revision was
  treated as earlier and which as later, so the direction of each change is
  unambiguous.
- **FR-015**: System MUST be delivered as a web application: users upload the
  two PDF revisions in a browser, review the marked-up drawing and change
  list interactively there, and can download the change report for use
  outside the browser.
- **FR-016**: All processing of drawing content MUST occur within the system
  operator's own infrastructure; drawing content MUST NOT be transmitted to
  third-party external services.
- **FR-017**: In the web review screen, users MUST be able to filter the
  change list and the corresponding highlights by change type (added /
  removed / modified). Persistent review state (marking changes as reviewed,
  user accounts, saved sessions) is out of scope for v1.

### Key Entities

- **Drawing Revision**: One version of a drawing sheet supplied as a PDF;
  has an ordering role in the comparison (earlier V(n-1) or later V(n)).
- **Drawing Entity**: A distinct element of the drawing — geometry (line,
  arc, shape), annotation (dimension, text, label, symbol) — with an
  identity, a location on the sheet, and readable attributes (e.g., a
  dimension's value).
- **Entity Change**: The unit of comparison output: one affected Drawing
  Entity, a change type (added / removed / modified), the entity's before
  state and after state, and a stable identifier used by both the change
  list and the marked-up drawing.
- **Change Report**: The complete result of one comparison: the ordered
  human-readable change list, the marked-up drawing, the identification of
  the two input revisions, and the overall outcome (changes found / no
  changes / comparison declined).
- **Marked-Up Drawing**: A rendition of the drawing sheet on which each
  Entity Change is highlighted at its location, color-coded by change type
  and labeled with its change identifier.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On benchmark revision pairs with known (ground-truth) change
  sets, the system detects at least 95% of all changes and at least 99% of
  dimension-value changes.
- **SC-002**: On benchmark pairs, at most 2% of reported changes are false
  positives (differences that do not exist between the revisions).
- **SC-003**: 100% of values quoted in change reports match the value
  present in the source drawings — zero fabricated or estimated values
  across the benchmark set.
- **SC-004**: Every entry in every change report can be traced to a specific
  entity with its before/after state; no untraceable or aggregate-only
  entries appear in any report.
- **SC-005**: Reviewers can locate any listed change on the marked-up
  drawing in under 30 seconds using the shared identifiers.
- **SC-006**: A comparison of a single drawing sheet containing up to 10,000
  drawing entities completes in under 2 minutes end to end.
- **SC-007**: Running the same comparison twice on identical inputs yields
  identical change reports in 100% of trials.
- **SC-008**: In evaluation with practicing architects/engineers, reviewers
  using the system identify at least 40% more of the actual changes in a
  revision pair than reviewers doing a manual side-by-side review of the
  same pair, in equal or less time.

## Assumptions

- Inputs are CAD-exported PDFs containing vector drawing content. Scanned or
  raster-only PDFs are out of scope for this feature; they are detected and
  rejected with a clear message rather than processed at lower fidelity
  (consistent with the project constitution's vector-native principle).
- Each comparison covers one drawing sheet. If a multi-page PDF is supplied,
  the system compares one corresponding page per run and reports which page
  was compared; batch multi-sheet comparison is a possible future feature.
- The two inputs are intended to be revisions of the same sheet; validating
  this is limited to the alignment check (FR-004), not project-metadata
  verification.
- The marked-up drawing is delivered as a viewable document of the same
  sheet (users need no CAD software to review results).
- Entity naming in the change list uses identifiers readable from the
  drawing where available (e.g., a dimension's label); otherwise entities
  are described by their kind and location (e.g., "text note near grid C-4").
- Units shown in change entries are the units as annotated in the drawing;
  the system does not convert units.
- Comparison is on-demand and user-initiated; no automatic monitoring of
  file repositories is included in this feature.
- Downloadable outputs are human-readable only (marked-up drawing and
  readable change list). A structured, machine-readable change-record export
  is out of scope for v1.
