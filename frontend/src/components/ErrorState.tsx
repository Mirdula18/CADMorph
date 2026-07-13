// Error state display for failed/rejected/declined comparisons.
// Shows the full error message (never truncated — messages name the
// offending file per FR-002/FR-004).

interface ErrorStateProps {
  message: string;
  onReset: () => void;
}

export function ErrorState({ message, onReset }: ErrorStateProps) {
  return (
    <div className="error-container">
      <div className="error-card" role="alert">
        <div className="error-icon" aria-hidden="true">
          ⚠️
        </div>
        <h2 className="error-title">Comparison Failed</h2>
        <p className="error-message">{message}</p>
        <div className="error-actions">
          <button className="btn btn-primary" onClick={onReset} type="button">
            Try Again
          </button>
        </div>
      </div>
    </div>
  );
}
