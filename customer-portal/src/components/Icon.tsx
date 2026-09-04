/**
 * The portal's icon set, as one component over a table of path data.
 *
 * The same construction as the Staff Console's Icon (frontend/src/components/
 * Icon.tsx) and deliberately not the same list: the portal's navigation is
 * words, not glyphs, so only the handful of controls that have no room for a
 * label are here. Inline SVG rather than a package -- four glyphs cost less
 * than any library that could draw them -- and `currentColor` throughout, so
 * an icon follows the colour of whatever it sits in.
 *
 * They are decorative: each is aria-hidden, and the control around it carries
 * the accessible name.
 */

export type IconName = "sun" | "moon" | "logout" | "arrowLeft";

const PATHS: Record<IconName, string[]> = {
  sun: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M12 2v2", "M12 20v2", "M2 12h2", "M20 12h2", "m4.9 4.9 1.4 1.4", "m17.7 17.7 1.4 1.4", "m19.1 4.9-1.4 1.4", "m6.3 17.7-1.4 1.4"],
  moon: ["M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"],
  logout: ["M15 17v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v2", "M10 12h11", "m18 9 3 3-3 3"],
  arrowLeft: ["M20 12H4", "m10 6-6 6 6 6"],
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
