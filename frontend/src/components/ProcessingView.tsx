// Processing view (8-stage progress stepper): shows which backend stage
// is active as a real progress indicator with animated states.

const STAGES = [
  "extracting",
  "classifying",
  "registering",
  "matching",
  "diffing",
  "summarizing",
  "reporting",
  "done",
] as const;

const STAGE_LABELS: Record<string, string> = {
  extracting: "Extracting entities...",
  classifying: "Classifying elements...",
  registering: "Registering sheets...",
  matching: "Matching entities...",
  diffing: "Computing differences...",
  summarizing: "Generating summary...",
  reporting: "Building report...",
  done: "Finishing up...",
};

interface ProcessingViewProps {
  currentStage: string;
  fileOldName: string;
  fileNewName: string;
}

export function ProcessingView({
  currentStage,
  fileOldName,
  fileNewName,
}: ProcessingViewProps) {
  const currentIndex = STAGES.indexOf(currentStage as (typeof STAGES)[number]);
  const activeIndex = currentIndex >= 0 ? currentIndex : -1;
  const progressPercent =
    activeIndex >= 0 ? ((activeIndex + 1) / STAGES.length) * 100 : 5;
    
  const currentLabel = STAGE_LABELS[currentStage] || "Analyzing drawings...";

  return (
    <div className="processing-container">
      <div className="processing-card minimal" role="status" aria-live="polite">
        <div className="creative-loader">
          <div className="loader-ring"></div>
          <div className="loader-ring ring2"></div>
          <div className="loader-icon">✨</div>
        </div>

        <div className="processing-title">{currentLabel}</div>
        <div className="processing-subtitle">
          Comparing <strong>{fileOldName}</strong> with <strong>{fileNewName}</strong>
        </div>

        <div className="processing-progress-bar">
          <div
            className="processing-progress-fill"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>
    </div>
  );
}
