import { useEffect, useId, useRef, useState } from "react";

/**
 * Monthly volume, as columns.
 *
 * One series, so one hue and no legend -- the card's title says what is
 * plotted, and a legend box with a single swatch would only restate it.
 * Only the last column is labelled: a number on every cap is the fastest
 * way to make a small chart unreadable, and the axis plus the hover
 * tooltip carry the rest.
 *
 * SVG here rather than divs (unlike BarList) because columns need a shared
 * baseline and a y-scale, which is what a viewBox is for. The viewBox is
 * measured from the container rather than fixed, so one SVG unit is one
 * CSS pixel at every width: a fixed 720-unit box scaled into a 360px phone
 * halves every font size with it, and 11px axis labels arrive at 5px.
 */
export interface Column {
  label: string;
  value: number;
  /** Pre-formatted, for the tooltip. */
  display: string;
  detail?: string;
}

const DEFAULT_WIDTH = 720;
const HEIGHT = 220;
const PAD = { top: 16, right: 12, bottom: 28, left: 44 };

/**
 * Round an axis maximum up to a number a reader can do arithmetic with --
 * 421 becomes 500. Without it the ticks read 0 / 211 / 421, which are
 * three numbers nobody asked for.
 */
function niceCeiling(value: number): number {
  if (value <= 5) return 5;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalised = value / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}

/**
 * The container's width in CSS pixels. Falls back to a sensible fixed
 * width where ResizeObserver doesn't exist -- jsdom, and any render
 * before layout -- so the chart still draws in tests.
 */
function useContainerWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const measured = entry.contentRect.width;
      if (measured > 0) setWidth(measured);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

/** A column with a 4px-rounded cap and a square foot on the baseline. */
function columnPath(x: number, y: number, width: number, height: number): string {
  const r = Math.min(4, width / 2, height);
  return [
    `M${x},${y + height}`,
    `V${y + r}`,
    `A${r},${r} 0 0 1 ${x + r},${y}`,
    `H${x + width - r}`,
    `A${r},${r} 0 0 1 ${x + width},${y + r}`,
    `V${y + height}`,
    "Z",
  ].join(" ");
}

export function ColumnChart({ columns, emptyMessage }: { columns: Column[]; emptyMessage: string }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const { ref, width } = useContainerWidth();
  const id = useId();

  const max = niceCeiling(Math.max(...columns.map((c) => c.value), 1));
  const plotWidth = width - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const band = plotWidth / Math.max(1, columns.length);
  // Capped rather than filling the band: the leftover is the air that keeps
  // a dense chart readable.
  const barWidth = Math.min(24, band * 0.6);
  const ticks = [0, max / 2, max];

  // The ref has to be attached on every path, including the empty one, or
  // the chart never measures itself once data arrives.
  return (
    <div className="chart" ref={ref} onMouseLeave={() => setHovered(null)}>
      {columns.length === 0 ? (
        <div className="card-state">{emptyMessage}</div>
      ) : (
        <>
          <svg viewBox={`0 0 ${width} ${HEIGHT}`} role="img" aria-labelledby={`${id}-title`} className="chart-svg">
            <title id={`${id}-title`}>Test requests per month</title>

            {ticks.map((tick) => {
              const y = PAD.top + plotHeight - (tick / max) * plotHeight;
              return (
                <g key={tick}>
                  <line x1={PAD.left} x2={width - PAD.right} y1={y} y2={y} className="chart-grid" />
                  <text x={PAD.left - 8} y={y + 4} textAnchor="end" className="chart-tick">
                    {Math.round(tick).toLocaleString()}
                  </text>
                </g>
              );
            })}

            {columns.map((column, index) => {
              const height = (column.value / max) * plotHeight;
              const x = PAD.left + index * band + (band - barWidth) / 2;
              const y = PAD.top + plotHeight - height;
              const isLast = index === columns.length - 1;
              return (
                // The handler sits on the group, not on the hit rectangle
                // underneath: the bar is painted over that rectangle, so
                // pointing at the *column* -- the obvious thing to point
                // at -- would otherwise land on the bar and hit nothing.
                <g key={column.label} onMouseEnter={() => setHovered(index)}>
                  {/* A full-height hit area, so the pointer finds the
                      column anywhere in its band. A 6px-tall bar in a quiet
                      month is not a target anyone can hit. */}
                  <rect
                    x={PAD.left + index * band}
                    y={PAD.top}
                    width={band}
                    height={plotHeight}
                    fill="transparent"
                  />
                  {column.value > 0 && (
                    // A path, not a rounded rect: the cap is rounded and
                    // the baseline is square, so every column sits on the
                    // axis rather than appearing to float a pixel above it.
                    <path
                      d={columnPath(x, y, barWidth, Math.max(2, height))}
                      className="chart-bar"
                      data-hovered={hovered === index}
                    />
                  )}
                  <text
                    x={PAD.left + index * band + band / 2}
                    y={HEIGHT - 8}
                    textAnchor="middle"
                    className="chart-tick"
                  >
                    {column.label}
                  </text>
                  {isLast && column.value > 0 && (
                    <text x={x + barWidth / 2} y={y - 6} textAnchor="middle" className="chart-caplabel">
                      {column.value.toLocaleString()}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>

          {hovered !== null && (
            <div className="chart-tooltip" style={{ left: `${((hovered + 0.5) / columns.length) * 100}%` }}>
              <strong>{columns[hovered].label}</strong>
              <span>{columns[hovered].display}</span>
              {columns[hovered].detail && <span className="chart-tooltip-detail">{columns[hovered].detail}</span>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
