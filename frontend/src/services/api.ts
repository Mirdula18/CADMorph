// API client for /api/v1 (contracts/api.md). Same-origin only (FR-016).

export interface EntityState {
  entity_id: string;
  kind: string;
  bbox: [number, number, number, number];
  text_payload: string | null;
  label: string | null;
  dimension_value: string | null;
  semantic_label: { value: string; provenance: string; confidence: number | null } | null;
}

export interface EntityDelta {
  delta_id: string;
  change_type: "added" | "removed" | "modified";
  modification_kinds: string[];
  before: EntityState | null;
  after: EntityState | null;
  anchor_bbox: [number, number, number, number];
}

export interface SummaryLine {
  delta_id: string;
  text: string;
  values_grounded: boolean;
}

export interface Revision {
  revision_id: "old" | "new";
  source_filename: string;
  page_index: number;
  sheet_width: number;
  sheet_height: number;
}

export interface ChangeReport {
  comparison_id: string;
  revisions: { old: Revision; new: Revision };
  outcome: "changes_found" | "no_changes" | "declined";
  deltas: EntityDelta[];
  summary_lines: SummaryLine[];
  pipeline_version: string;
}

export interface JobStatus {
  comparison_id: string;
  state: string;
  outcome: string | null;
  reason: string | null;
  message: string | null;
}

export interface ApiError {
  error: { code: string; message: string; comparison_id?: string };
}

async function errorMessage(response: Response): Promise<string> {
  // Tolerate any body shape: missing envelope, plain text, HTML, empty.
  const fallback = `Request failed (${response.status})`;
  try {
    const body = (await response.json()) as Partial<ApiError> | null;
    return body?.error?.message ?? fallback;
  } catch {
    return fallback;
  }
}

export async function createComparison(
  fileOld: File,
  fileNew: File,
  page: number,
): Promise<{ comparison_id: string }> {
  const form = new FormData();
  form.append("file_old", fileOld);
  form.append("file_new", fileNew);
  form.append("page", String(page));
  const response = await fetch("/api/v1/comparisons", { method: "POST", body: form });
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}

export async function getStatus(id: string): Promise<JobStatus> {
  const response = await fetch(`/api/v1/comparisons/${id}`);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}

export async function getReport(id: string): Promise<ChangeReport> {
  const response = await fetch(`/api/v1/comparisons/${id}/report`);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}

export function sheetUrl(id: string, revision: "old" | "new" = "new"): string {
  return `/api/v1/comparisons/${id}/sheet.png?revision=${revision}`;
}

export function markupUrl(id: string): string {
  return `/api/v1/comparisons/${id}/markup.pdf`;
}

export function reportPdfUrl(id: string): string {
  return `/api/v1/comparisons/${id}/report.pdf`;
}
