// Upload page (T030): two file inputs (V(n-1) / V(n)), page selector,
// status polling, rejection messages naming the offending file (FR-002).
// Redesigned with drag-and-drop zones, app shell, step indicator, and
// dedicated processing/error/results views.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChangeReport,
  createComparison,
  getReport,
  getStatus,
} from "../services/api";
import { ErrorState } from "../components/ErrorState";
import { ProcessingView } from "../components/ProcessingView";
import { ResultsPage } from "./ResultsPage";

const TERMINAL = new Set(["done", "failed", "rejected", "declined"]);
const POLL_MS = 1000;

type AppStep = "upload" | "processing" | "results" | "error";

function resolveStep(
  state: string,
  report: ChangeReport | null,
  error: string | null,
): AppStep {
  if (error) return "error";
  if (report) return "results";
  if (state !== "idle" && !TERMINAL.has(state)) return "processing";
  if (TERMINAL.has(state) && state !== "done") return "error";
  return "upload";
}

const STEPS: { key: AppStep; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "processing", label: "Processing" },
  { key: "results", label: "Results" },
];

interface DropZoneProps {
  label: string;
  hint: string;
  file: File | null;
  onFile: (f: File | null) => void;
  id: string;
}

function DropZone({ label, hint, file, onFile, id }: DropZoneProps) {
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files?.[0];
      if (f && f.name.toLowerCase().endsWith(".pdf")) {
        onFile(f);
      }
    },
    [onFile],
  );

  const cls = [
    "drop-zone",
    dragOver ? "drag-over" : "",
    file ? "has-file" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={cls}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <input
        type="file"
        accept=".pdf"
        id={id}
        aria-label={label}
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      <span className="drop-zone-icon" aria-hidden="true">
        {file ? "📄" : "📁"}
      </span>
      <div className="drop-zone-label">{label}</div>
      <div className="drop-zone-hint">{hint}</div>
      {file && (
        <div className="drop-zone-filename">
          ✓ {file.name}
        </div>
      )}
    </div>
  );
}

export function ComparePage() {
  const [fileOld, setFileOld] = useState<File | null>(null);
  const [fileNew, setFileNew] = useState<File | null>(null);
  const [page, setPage] = useState(0);
  const [state, setState] = useState<string>("idle");
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ChangeReport | null>(null);
  const [comparisonId, setComparisonId] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function poll(id: string, retries = 0) {
    try {
      const status = await getStatus(id);
      setState(status.state);
      if (!TERMINAL.has(status.state)) {
        timer.current = window.setTimeout(() => poll(id, 0), POLL_MS);
        return;
      }
      if (status.state === "done") {
        setReport(await getReport(id));
      } else {
        // rejected/declined messages name the offending file (FR-002/FR-004)
        const fallback =
          status.reason === "alignment_failed"
            ? "The inputs do not appear to be revisions of the same sheet."
            : (status.reason ?? `comparison ${status.state}`);
        setError(status.message ?? fallback);
      }
    } catch (err) {
      if (retries < 3) {
        // Tolerate transient backend errors (e.g., file read race conditions)
        timer.current = window.setTimeout(() => poll(id, retries + 1), POLL_MS);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!fileOld || !fileNew) return;
    setError(null);
    setReport(null);
    setComparisonId(null);
    setState("uploading");
    try {
      const { comparison_id } = await createComparison(fileOld, fileNew, page);
      setComparisonId(comparison_id);
      setState("pending");
      poll(comparison_id, 0);
    } catch (err) {
      setState("idle");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function reset() {
    window.clearTimeout(timer.current);
    setState("idle");
    setError(null);
    setReport(null);
    setComparisonId(null);
  }

  const currentStep = resolveStep(state, report, error);
  const busy = currentStep === "processing";

  // Step indicator states
  function stepStatus(stepKey: AppStep) {
    const order: AppStep[] = ["upload", "processing", "results"];
    const currentIdx = order.indexOf(currentStep);
    const stepIdx = order.indexOf(stepKey);
    if (currentStep === "error") {
      if (stepKey === "upload") return "completed";
      if (stepKey === "processing") return "error";
      return "upcoming";
    }
    if (stepIdx < currentIdx) return "completed";
    if (stepIdx === currentIdx) return "active";
    return "upcoming";
  }

  function connectorStatus(afterIdx: number) {
    const order: AppStep[] = ["upload", "processing", "results"];
    const currentIdx = order.indexOf(currentStep);
    if (currentStep === "error") {
      return afterIdx === 0 ? "completed" : "";
    }
    if (afterIdx < currentIdx) return "completed";
    if (afterIdx === currentIdx - 1) return "active";
    return "";
  }

  return (
    <>
      {/* Header */}
      <header className="app-header">
        <div className="app-logo">
          <div className="app-logo-mark">
            CAD<span>Morph</span>
          </div>
          <div className="app-logo-tagline">Drawing Change Detection</div>
        </div>
        {currentStep !== "upload" && (
          <button className="btn btn-ghost" onClick={reset} type="button">
            ← New Comparison
          </button>
        )}
      </header>

      {/* Step Indicator */}
      <nav className="step-indicator" aria-label="comparison progress">
        {STEPS.map((step, i) => (
          <div key={step.key} style={{ display: "contents" }}>
            {i > 0 && (
              <div
                className={`step-connector ${connectorStatus(i - 1)}`}
              />
            )}
            <div className="step-item">
              <div className={`step-circle ${stepStatus(step.key)}`}>
                {stepStatus(step.key) === "completed"
                  ? "✓"
                  : stepStatus(step.key) === "error"
                    ? "✕"
                    : i + 1}
              </div>
              <span className={`step-label ${stepStatus(step.key)}`}>
                {step.label}
              </span>
            </div>
          </div>
        ))}
      </nav>

      {/* Content */}
      <div className="app-content">
        {currentStep === "upload" && (
          <div className="upload-container">
            <form className="upload-card" onSubmit={submit}>
              <h1 className="upload-title">Compare Revisions</h1>
              <p className="upload-subtitle">
                Upload two PDF revisions of a CAD drawing to detect changes
              </p>

              <div className="upload-fields">
                <DropZone
                  id="file-old"
                  label="Previous Revision V(n−1)"
                  hint="Drag & drop a PDF or click to browse"
                  file={fileOld}
                  onFile={setFileOld}
                />

                <DropZone
                  id="file-new"
                  label="New Revision V(n)"
                  hint="Drag & drop a PDF or click to browse"
                  file={fileNew}
                  onFile={setFileNew}
                />

                <div className="page-field">
                  <label htmlFor="page-number">
                    Page index (for multi-page PDFs)
                  </label>
                  <input
                    id="page-number"
                    type="number"
                    min={0}
                    value={page}
                    onChange={(e) => setPage(Number(e.target.value))}
                  />
                </div>

                {/* Show upload-phase errors inline */}
                {error && state === "idle" && (
                  <div className="inline-alert" role="alert">
                    <span className="inline-alert-icon" aria-hidden="true">
                      ⚠️
                    </span>
                    <span className="inline-alert-text">{error}</span>
                  </div>
                )}

                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={!fileOld || !fileNew || busy}
                >
                  {busy ? "Comparing…" : "Compare"}
                </button>
              </div>
            </form>
          </div>
        )}

        {currentStep === "processing" && (
          <ProcessingView
            currentStage={state}
            fileOldName={fileOld?.name ?? ""}
            fileNewName={fileNew?.name ?? ""}
          />
        )}

        {currentStep === "error" && error && (
          <ErrorState message={error} onReset={reset} />
        )}

        {currentStep === "results" && report && comparisonId && (
          <ResultsPage
            comparisonId={comparisonId}
            report={report}
            onReset={reset}
          />
        )}
      </div>
    </>
  );
}
