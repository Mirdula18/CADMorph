// No-changes empty state: shown when outcome === "no_changes".
// Provides download links and a button to start a new comparison.

import { markupUrl, reportPdfUrl } from "../services/api";

interface NoChangesStateProps {
  comparisonId: string;
  oldFilename: string;
  newFilename: string;
  onReset: () => void;
}

export function NoChangesState({
  comparisonId,
  oldFilename,
  newFilename,
  onReset,
}: NoChangesStateProps) {
  return (
    <div className="no-changes-container">
      <div className="no-changes-card" role="status">
        <div className="no-changes-icon" aria-hidden="true">
          ✅
        </div>
        <h2 className="no-changes-title">No Changes Detected</h2>
        <p className="no-changes-message">
          The two revisions are identical — no differences were found.
        </p>
        <p className="no-changes-files">
          {oldFilename} → {newFilename}
        </p>
        <div className="no-changes-actions">
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
            📄 Printable Report
          </a>
          <button className="btn btn-ghost" onClick={onReset} type="button">
            New Comparison
          </button>
        </div>
      </div>
    </div>
  );
}
