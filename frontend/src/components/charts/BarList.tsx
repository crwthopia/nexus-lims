import { useId, useState } from "react";

/**
 * A ranked list of bars: the leading analyses, longest first.
 *
 * A table with bars in it rather than a bar chart proper, because the
 * reader's question is "which ones, and by how much" and the labels are
 * rate-card names too long to hang off an axis. Every bar is the *same*
 * colour: length already encodes magnitude, and shading each bar darker
 * where it is bigger would spend the one free channel restating it.
 *
 * The value beside each bar is the reason there is no axis -- a direct
 * label on every row is legible here in a way it would not be on a
 * scatter, because there is one number per row and the rows are sorted.
 */
export interface BarListRow {
  key: string;
  label: string;
  sublabel?: string;
  value: number;
  /** Shown at the row's end. Pre-formatted -- this component never formats money. */
  display: string;
  /** Second line in the tooltip. */
  detail?: string;
  /** Renders in the muted ink, for the folded "other" row. */
  muted?: boolean;
}

export function BarList({ rows, emptyMessage }: { rows: BarListRow[]; emptyMessage: string }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const id = useId();

  if (rows.length === 0) return <div className="card-state">{emptyMessage}</div>;

  const max = Math.max(...rows.map((row) => row.value), 1);

  return (
    <ul className="barlist" aria-describedby={`${id}-hint`}>
      <li id={`${id}-hint`} className="visually-hidden">
        Each row shows a count and its share of the largest.
      </li>
      {rows.map((row) => (
        <li
          key={row.key}
          className="barlist-row"
          onMouseEnter={() => setHovered(row.key)}
          onMouseLeave={() => setHovered(null)}
          data-hovered={hovered === row.key}
        >
          <div className="barlist-head">
            <span className="barlist-label">
              {row.label}
              {row.sublabel && <span className="barlist-sublabel">{row.sublabel}</span>}
            </span>
            <span className="barlist-value">{row.display}</span>
          </div>
          <div className="barlist-track">
            {/* The bar is a div, not an SVG rect: one measure per row needs
                no coordinate system, and a div scales with the card without
                a viewBox to keep in step. */}
            <div
              className="barlist-bar"
              style={{ width: `${Math.max(2, (row.value / max) * 100)}%`, opacity: row.muted ? 0.45 : 1 }}
            />
          </div>
          {row.detail && <div className="barlist-detail">{row.detail}</div>}
        </li>
      ))}
    </ul>
  );
}
