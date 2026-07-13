// Results page (T038): sheet viewer + change list side by side, ONE
// change-type filter driving both (FR-017), download buttons for the
// marked-up drawing and the printable report. Redesigned with filter
// chips, two-pane layout, and dedicated no-changes state.

import { useState } from "react";
import { ChangeList } from "../components/ChangeList";
import { NoChangesState } from "../components/NoChangesState";
import { OVERLAY_COLORS, SheetViewer } from "../components/SheetViewer";
import { ReportSummary } from "../components/ReportSummary";
import { ChangeReport, markupUrl, reportPdfUrl } from "../services/api";

const ALL_TYPES = ["added", "removed", "modified"] as const;

export function ResultsPage({
  comparisonId,
  report,
  onReset,
}: {
  comparisonId: string;
  report: ChangeReport;
  onReset: () => void;
}) {
  const [visibleTypes, setVisibleTypes] = useState<Set<string>>(
    new Set(ALL_TYPES),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [baseLayer, setBaseLayer] = useState<"old" | "new" | "split">("split");
  const [overlayMode, setOverlayMode] = useState<"boxes" | "heatmap">("boxes");

  function toggleType(type: string) {
    setVisibleTypes((previous) => {
      const next = new Set(previous);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
    setSelectedId(null);
  }

  // No-changes outcome gets a dedicated state
  if (report.outcome === "no_changes") {
    return (
      <NoChangesState
        comparisonId={comparisonId}
        oldFilename={report.revisions.old.source_filename}
        newFilename={report.revisions.new.source_filename}
        onReset={onReset}
      />
    );
  }

  return (
    <section className="results-container" aria-label="comparison results">
      {/* Toolbar: filters + downloads */}
      <div className="results-toolbar">
        <div className="results-toolbar-left">
          <div
            className="results-filters"
            role="group"
            aria-label="change type filter"
          >
            {ALL_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                className={`filter-chip${visibleTypes.has(type) ? " active" : ""}`}
                onClick={() => toggleType(type)}
                aria-pressed={visibleTypes.has(type)}
              >
                <span
                  className="chip-dot"
                  style={{ background: OVERLAY_COLORS[type] }}
                />
                {type}
              </button>
            ))}
          </div>

          <div className="segmented-control" role="group" aria-label="Base layer">
            <button
              type="button"
              className={baseLayer === "old" ? "active" : ""}
              onClick={() => setBaseLayer("old")}
            >
              Before
            </button>
            <button
              type="button"
              className={baseLayer === "new" ? "active" : ""}
              onClick={() => setBaseLayer("new")}
            >
              After
            </button>
            <button
              type="button"
              className={baseLayer === "split" ? "active" : ""}
              onClick={() => setBaseLayer("split")}
            >
              Side-by-Side
            </button>
          </div>

          <div className="segmented-control" role="group" aria-label="Overlay mode">
            <button
              type="button"
              className={overlayMode === "boxes" ? "active" : ""}
              onClick={() => setOverlayMode("boxes")}
            >
              Boxes
            </button>
            <button
              type="button"
              className={overlayMode === "heatmap" ? "active" : ""}
              onClick={() => setOverlayMode("heatmap")}
            >
              Heatmap
            </button>
          </div>
        </div>

        <div className="results-actions">
          <a
            className="btn btn-secondary"
            href={markupUrl(comparisonId)}
            download
          >
            📐 Marked-up Drawing
          </a>
          <a
            className="btn btn-secondary"
            href={reportPdfUrl(comparisonId)}
            download
          >
            📄 Report PDF
          </a>
        </div>
      </div>

      {/* Main stacked content pane */}
      <div className="results-panes">
        {/* Images at the top */}
        <div className="results-sheet-pane">
          {baseLayer === "split" ? (
            <div className="split-view-container">
              <div className="split-view-half">
                <h4 className="split-title">Before V(n-1)</h4>
                <SheetViewer
                  comparisonId={comparisonId}
                  report={report}
                  visibleTypes={visibleTypes}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  baseLayer="old"
                  overlayMode={overlayMode}
                />
              </div>
              <div className="split-view-half">
                <h4 className="split-title">After V(n)</h4>
                <SheetViewer
                  comparisonId={comparisonId}
                  report={report}
                  visibleTypes={visibleTypes}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  baseLayer="new"
                  overlayMode={overlayMode}
                />
              </div>
            </div>
          ) : (
            <SheetViewer
              comparisonId={comparisonId}
              report={report}
              visibleTypes={visibleTypes}
              selectedId={selectedId}
              onSelect={setSelectedId}
              baseLayer={baseLayer}
              overlayMode={overlayMode}
            />
          )}
        </div>
        
        {/* Statistics and summary below images */}
        <div className="results-summary-pane">
          <ReportSummary report={report} />
        </div>

        {/* Change list at the bottom */}
        <div className="results-list-pane">
          <ChangeList
            report={report}
            visibleTypes={visibleTypes}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
      </div>
    </section>
  );
}
