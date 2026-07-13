// Sheet viewer (T036): server-rendered sheet.png with an SVG overlay drawn
// from delta JSON (never from pixels — Constitution I/III). The SVG viewBox
// is in PDF points, so anchor_bbox coordinates map 1:1; list <-> highlight
// selection is synced via delta_id.
//
// CRITICAL: The viewBox uses sheet_width/sheet_height from the report's
// revisions object (PDF points) — NOT the PNG's pixel dimensions. Mixing
// these misaligns every overlay box.

import { useState } from "react";
import { ChangeReport, sheetUrl } from "../services/api";

// Keep in sync with backend report/markup.py COLORS.
export const OVERLAY_COLORS: Record<string, string> = {
  added: "#0a991a",
  removed: "#d91a1a",
  modified: "#f28c00",
};

interface SheetViewerProps {
  comparisonId: string;
  report: ChangeReport;
  visibleTypes: Set<string>;
  selectedId: string | null;
  onSelect: (deltaId: string | null) => void;
  baseLayer: "old" | "new";
  overlayMode: "boxes" | "heatmap";
}

export function SheetViewer({
  comparisonId,
  report,
  visibleTypes,
  selectedId,
  onSelect,
  baseLayer,
  overlayMode,
}: SheetViewerProps) {
  const [loaded, setLoaded] = useState(false);
  const { sheet_width: w, sheet_height: h } = report.revisions.new;
  const visible = report.deltas.filter((d) => visibleTypes.has(d.change_type));

  // Determine a reasonable blur radius based on sheet size
  const blurRadius = Math.max(w, h) * 0.015; // 1.5% of sheet size

  return (
    <div className="sheet-viewer-wrap">
      {/* Loading skeleton while image loads */}
      {!loaded && <div className="sheet-skeleton" />}

      <img
        src={sheetUrl(comparisonId, baseLayer)}
        alt={`Sheet V(n): ${report.revisions[baseLayer].source_filename}`}
        onLoad={() => setLoaded(true)}
        style={{ display: loaded ? "block" : "none" }}
      />

      {loaded && (
        <svg
          viewBox={`0 0 ${w} ${h}`}
          onClick={() => onSelect(null)}
          aria-label="change highlights"
        >
          {overlayMode === "heatmap" && (
            <defs>
              <filter id="heatmap-blur" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation={blurRadius} />
              </filter>
            </defs>
          )}

          {visible.map((delta) => {
            const [x0, y0, x1, y1] = delta.anchor_bbox;
            const selected = delta.delta_id === selectedId;
            const color = OVERLAY_COLORS[delta.change_type];

            if (overlayMode === "heatmap") {
              const cx = (x0 + x1) / 2;
              const cy = (y0 + y1) / 2;
              // Circle radius based on bounding box size, but with a minimum for small changes
              const r = Math.max(Math.max(x1 - x0, y1 - y0) / 2, blurRadius);
              return (
                <circle
                  key={delta.delta_id}
                  cx={cx}
                  cy={cy}
                  r={r}
                  fill={color}
                  fillOpacity={selected ? 0.9 : 0.65}
                  filter="url(#heatmap-blur)"
                  style={{ cursor: "pointer" }}
                  data-delta-id={delta.delta_id}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(selected ? null : delta.delta_id);
                  }}
                >
                  <title>{delta.delta_id}</title>
                </circle>
              );
            }

            return (
              <rect
                key={delta.delta_id}
                x={x0 - 2}
                y={y0 - 2}
                width={x1 - x0 + 4}
                height={y1 - y0 + 4}
                fill={color}
                fillOpacity={selected ? 0.25 : 0.08}
                stroke={color}
                strokeWidth={selected ? 2.5 : 1.2}
                style={{ cursor: "pointer" }}
                data-delta-id={delta.delta_id}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(selected ? null : delta.delta_id);
                }}
              >
                <title>{delta.delta_id}</title>
              </rect>
            );
          })}
        </svg>
      )}
    </div>
  );
}
