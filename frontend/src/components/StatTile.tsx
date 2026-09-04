import type { ReactNode } from "react";

/**
 * One headline number.
 *
 * A stat tile rather than a one-bar chart: when the data is a single
 * value, the number *is* the visualisation, and drawing a bar beside it
 * adds ink that carries nothing.
 *
 * `delta` is a share change against the preceding period of equal length.
 * It is deliberately not colour-coded good/bad: more samples is good, a
 * longer turnaround is not, and a component cannot know which it is
 * holding. The arrow states direction; the reader knows the rest.
 */
export function StatTile({
  label,
  value,
  hint,
  delta,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  delta?: { pct: number; label: string } | null;
}) {
  return (
    <div className="card stat-tile">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-foot">
        {delta && (
          <span className="stat-delta" title={delta.label}>
            <span aria-hidden="true">{delta.pct >= 0 ? "▲" : "▼"}</span>
            {Math.abs(delta.pct).toFixed(0)}%
            <span className="visually-hidden">{delta.pct >= 0 ? " up on " : " down on "}</span>
            <span className="stat-delta-label">{delta.label}</span>
          </span>
        )}
        {hint && <span className="stat-hint">{hint}</span>}
      </div>
    </div>
  );
}
