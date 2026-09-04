/**
 * The console's icon set, as one component over a table of path data.
 *
 * Inline SVG rather than an icon font or a package: the rail needs perhaps a
 * dozen glyphs, and every icon library that renders them costs more bytes
 * than the glyphs do. `currentColor` is what makes the nav's active state a
 * one-property change -- the icon follows the label's colour without the
 * caller doing anything.
 *
 * Every icon is drawn on the same 24x24 grid with the same stroke weight, so
 * they sit on a line together without per-icon nudging. They are decorative:
 * each is `aria-hidden`, and whatever it sits beside carries the name.
 */

export type IconName =
  | "samples"
  | "documents"
  | "investigations"
  | "equipment"
  | "training"
  | "reports"
  | "billing"
  | "system"
  | "testing"
  | "review"
  | "search"
  | "sidebar"
  | "sun"
  | "moon"
  | "logout"
  | "arrowLeft"
  | "enter";

const PATHS: Record<IconName, string[]> = {
  // Flask: the sample worklist.
  samples: ["M9 3h6", "M10 3v6.5L4.7 18a2 2 0 0 0 1.7 3h11.2a2 2 0 0 0 1.7-3L14 9.5V3", "M7.2 14h9.6"],
  documents: ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5", "M9 13h6", "M9 17h4"],
  // Magnifier over a fault line: an investigation into something that went wrong.
  investigations: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "m16 16 4.5 4.5", "M11 7.5v4", "M11 14.5h.01"],
  equipment: ["M5 7h14v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z", "M9 7V4h6v3", "M9 12h6", "M9 16h3"],
  training: ["M12 3 2.5 8 12 13l9.5-5z", "M6.5 10.3V16c0 1.4 2.5 2.6 5.5 2.6s5.5-1.2 5.5-2.6v-5.7", "M21.5 8v6"],
  reports: ["M5 20V10", "M12 20V4", "M19 20v-7", "M3 20h18"],
  billing: ["M3 6h18v12H3z", "M3 10h18", "M7 15h4"],
  system: ["M12 3l8 3.5V12c0 4.6-3.2 7.7-8 9-4.8-1.3-8-4.4-8-9V6.5z", "M12 8.5v4", "M12 15.5h.01"],
  testing: ["M4 6h2l1 1 2-2", "M4 12h2l1 1 2-2", "M4 18h2l1 1 2-2", "M13 6h7", "M13 12h7", "M13 18h7"],
  review: ["M9 4h6v3H9z", "M15 5.5h2.5a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 19V7a1.5 1.5 0 0 1 1.5-1.5H9", "m8.8 13.4 2 2 4.4-4.4"],
  search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "m16 16 4.5 4.5"],
  sidebar: ["M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z", "M10 5v14"],
  sun: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M12 2v2", "M12 20v2", "M2 12h2", "M20 12h2", "m4.9 4.9 1.4 1.4", "m17.7 17.7 1.4 1.4", "m19.1 4.9-1.4 1.4", "m6.3 17.7-1.4 1.4"],
  moon: ["M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"],
  logout: ["M15 17v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v2", "M10 12h11", "m18 9 3 3-3 3"],
  arrowLeft: ["M20 12H4", "m10 6-6 6 6 6"],
  enter: ["M20 6v5a3 3 0 0 1-3 3H4", "m8 10-4 4 4 4"],
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
