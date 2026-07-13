// Change list (T031/T037): one entry per delta with change type, grounded
// before/after values, delta_id, revision direction, no-changes state.
// Optional filter + selection props sync with the sheet overlay (FR-017/011).
// Redesigned with card rows, color-coded badges, keyboard navigation.

import { useCallback, useEffect, useRef } from "react";
import { ChangeReport, EntityDelta } from "../services/api";

function values(delta: EntityDelta): string | null {
  const before =
    delta.before?.dimension_value ?? delta.before?.text_payload ?? null;
  const after =
    delta.after?.dimension_value ?? delta.after?.text_payload ?? null;
  if (
    delta.change_type === "modified" &&
    before !== after &&
    (before || after)
  ) {
    return `${before ?? "value unavailable"} → ${after ?? "value unavailable"}`;
  }
  return after ?? before;
}

interface ChangeListProps {
  report: ChangeReport;
  visibleTypes?: Set<string>;
  selectedId?: string | null;
  onSelect?: (deltaId: string | null) => void;
}

export function ChangeList({
  report,
  visibleTypes,
  selectedId,
  onSelect,
}: ChangeListProps) {
  const summaries = new Map(
    report.summary_lines.map((line) => [line.delta_id, line]),
  );
  const deltas = report.deltas.filter(
    (d) => !visibleTypes || visibleTypes.has(d.change_type),
  );
  const listRef = useRef<HTMLOListElement>(null);

  // Scroll selected item into view
  useEffect(() => {
    if (!selectedId || !listRef.current) return;
    const el = listRef.current.querySelector(
      `[data-delta-id="${selectedId}"]`,
    );
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedId]);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!onSelect || deltas.length === 0) return;
      const currentIdx = deltas.findIndex((d) => d.delta_id === selectedId);

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next =
          currentIdx < deltas.length - 1 ? currentIdx + 1 : 0;
        onSelect(deltas[next].delta_id);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prev =
          currentIdx > 0 ? currentIdx - 1 : deltas.length - 1;
        onSelect(deltas[prev].delta_id);
      } else if (e.key === "Escape") {
        e.preventDefault();
        onSelect(null);
      }
    },
    [deltas, selectedId, onSelect],
  );

  return (
    <section aria-label="change list">
      <div className="change-list-header">
        <h2 className="change-list-title">
          Changes ({deltas.length})
        </h2>
        <div className="change-list-meta">
          {report.revisions.old.source_filename} →{" "}
          {report.revisions.new.source_filename} · page{" "}
          {report.revisions.new.page_index}
        </div>
      </div>

      {deltas.length === 0 ? (
        <div className="change-list-empty">
          <div className="change-list-empty-icon" aria-hidden="true">
            🔍
          </div>
          <p>No changes of the selected types.</p>
        </div>
      ) : (
        <ol
          className="change-list-items"
          ref={listRef}
          onKeyDown={handleKeyDown}
          role="listbox"
          aria-label="detected changes"
          tabIndex={0}
        >
          {deltas.map((delta) => {
            const line = summaries.get(delta.delta_id);
            const value = values(delta);
            const selected = delta.delta_id === selectedId;
            return (
              <li
                key={delta.delta_id}
                data-delta-id={delta.delta_id}
                className={`change-item${selected ? " selected" : ""}`}
                onClick={() => onSelect?.(selected ? null : delta.delta_id)}
                role="option"
                aria-selected={selected}
                tabIndex={-1}
              >
                <div className="change-item-header">
                  <span
                    className={`change-badge ${delta.change_type}`}
                    data-change-type={delta.change_type}
                  >
                    {delta.change_type}
                  </span>
                  {delta.modification_kinds.length > 0 && (
                    <span className="change-mod-kinds">
                      {delta.modification_kinds.map((kind) => (
                        <span key={kind} className="mod-kind-tag">
                          {kind}
                        </span>
                      ))}
                    </span>
                  )}
                </div>
                {line?.text && (
                  <div className="change-summary">{line.text}</div>
                )}
                {value && <div className="change-values">{value}</div>}
                <div className="change-delta-id">{delta.delta_id}</div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
