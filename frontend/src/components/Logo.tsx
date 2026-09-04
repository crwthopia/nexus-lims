/**
 * The NexusLIMS lockup, as live text rather than an <img>.
 *
 * The mark is inline SVG so it can sit on the same baseline as the
 * wordmark and scale with it, and the wordmark is real text so it stays
 * selectable, searchable, and picks up the theme's own colours -- an
 * exported PNG would need one file per theme and would still be wrong at
 * the user's font size. The standalone files in brand/ are for anything
 * outside the apps.
 */

export function Logo({ compact = false, wordmark = true }: { compact?: boolean; wordmark?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 9 }}>
      <svg viewBox="0 0 96 96" width={compact ? 24 : 28} height={compact ? 24 : 28} aria-hidden="true">
        <defs>
          <linearGradient id="nexuslims-tile" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#38DDEF" />
            <stop offset="1" stopColor="#06B6D4" />
          </linearGradient>
        </defs>
        <rect width="96" height="96" rx="22" fill="url(#nexuslims-tile)" />
        <g stroke="#fff" strokeWidth="7" strokeLinecap="round" fill="none">
          <path d="M48 30 L29 63" />
          <path d="M48 30 L67 63" />
          <path d="M29 63 L67 63" />
        </g>
        <g fill="#fff">
          <circle cx="48" cy="30" r="10" />
          <circle cx="29" cy="63" r="10" />
          <circle cx="67" cy="63" r="10" />
        </g>
      </svg>
      {/* The collapsed nav rail shows the mark alone; the tile is the part
          that still reads at 24px, and the wordmark would only be clipped. */}
      {wordmark && (
        <span className="brand-text" style={{ fontWeight: 700, fontSize: "1.05rem", letterSpacing: "-0.01em" }}>
          <span style={{ color: "var(--color-text)" }}>Nexus</span>
          <span style={{ color: "var(--color-brand)" }}>LIMS</span>
        </span>
      )}
    </span>
  );
}
