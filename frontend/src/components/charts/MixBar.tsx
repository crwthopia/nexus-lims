import { useState } from "react";

/**
 * Part-to-whole across the service lines, as one horizontal stacked bar.
 *
 * Not a donut. Two or three segments in a ring is the shape a pie chart is
 * worst at -- the reader compares arcs instead of lengths -- and a bar
 * carries the same information in a quarter of the space, with room for
 * direct labels beside it.
 *
 * Identity never rests on colour alone: every segment is direct-labelled
 * below the bar with its own swatch, so the chart survives a colourblind
 * reader, a greyscale print, and forced-colors mode.
 */
export interface MixSegment {
  key: string;
  label: string;
  value: number;
}

const SERIES_CLASS = ["chart-fill-1", "chart-fill-2"];

export function MixBar({ segments, unit, emptyMessage }: { segments: MixSegment[]; unit: string; emptyMessage: string }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);

  if (total === 0) return <div className="card-state">{emptyMessage}</div>;

  // More than two service lines is not a thing the lab has, but folding the
  // tail is cheaper than discovering a third hue is needed on a Friday.
  const shown = segments.slice(0, SERIES_CLASS.length);
  const rest = segments.slice(SERIES_CLASS.length);
  const rows = rest.length
    ? [...shown, { key: "other", label: "Other", value: rest.reduce((sum, s) => sum + s.value, 0) }]
    : shown;

  return (
    <div>
      <div className="mixbar" role="img" aria-label={`${unit} by service line`}>
        {rows.map((segment, index) => (
          <div
            key={segment.key}
            className={`mixbar-segment ${SERIES_CLASS[index] ?? "chart-fill-muted"}`}
            style={{ flexGrow: segment.value }}
            data-hovered={hovered === segment.key}
            onMouseEnter={() => setHovered(segment.key)}
            onMouseLeave={() => setHovered(null)}
            title={`${segment.label}: ${segment.value.toLocaleString()} ${unit}`}
          />
        ))}
      </div>
      <ul className="chart-legend">
        {rows.map((segment, index) => (
          <li key={segment.key} data-hovered={hovered === segment.key}>
            <span className={`chart-swatch ${SERIES_CLASS[index] ?? "chart-fill-muted"}`} aria-hidden="true" />
            <span className="chart-legend-label">{segment.label}</span>
            <span className="chart-legend-value">
              {segment.value.toLocaleString()} · {Math.round((segment.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
