import { ChangeReport } from "../services/api";

export function ReportSummary({ report }: { report: ChangeReport }) {
  const total = report.deltas.length;
  const added = report.deltas.filter((d) => d.change_type === "added").length;
  const removed = report.deltas.filter((d) => d.change_type === "removed").length;
  const modified = report.deltas.filter((d) => d.change_type === "modified").length;

  return (
    <div className="report-summary-container">
      <div className="summary-stats">
        <div className="stat-card">
          <div className="stat-value">{total}</div>
          <div className="stat-label">Total Changes</div>
        </div>
        <div className="stat-card added">
          <div className="stat-value">{added}</div>
          <div className="stat-label">Added</div>
        </div>
        <div className="stat-card removed">
          <div className="stat-value">{removed}</div>
          <div className="stat-label">Removed</div>
        </div>
        <div className="stat-card modified">
          <div className="stat-value">{modified}</div>
          <div className="stat-label">Modified</div>
        </div>
      </div>

      {report.summary_lines.length > 0 && (
        <div className="summary-text-card">
          <h3 className="summary-text-title">Executive Summary</h3>
          <ul className="summary-text-list">
            {report.summary_lines.map((line, i) => (
              <li key={i} className="summary-text-item">
                <span className="summary-text-bullet"></span>
                <span>{line.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
