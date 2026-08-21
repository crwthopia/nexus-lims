# NexusLIMS brand assets

The product is **NexusLIMS**. The lab it was built for is **NASAT** — those
are two different names, and the distinction decides which one belongs in a
given string. NexusLIMS goes in product chrome: the header lockup, the
browser tab, the login card. NASAT stays wherever the text is about the
laboratory itself, as in the customer portal's "Lab testing orders placed
with NASAT."

## Files

| File | Use |
|---|---|
| `nexuslims-mark.svg` | The mark alone, gradient tile. App icons, avatars, anywhere the name is already present. |
| `nexuslims-favicon.svg` | Small-size variant: flat fill, glyph scaled up ~8%. Copied into each app's `public/`. |
| `nexuslims-logo-dark.svg` | Full lockup for dark backgrounds. |
| `nexuslims-logo-light.svg` | Full lockup for light backgrounds. |

Inside the apps, use the `Logo` component rather than any of these — the
wordmark is live text there, so it takes the theme's own colours and stays
selectable. These files are for everything outside: slides, documents, an
email signature, a vendor who asks for a logo.

## The mark

Three connected nodes — the literal sense of "nexus", and the shape a
sample's life takes here: received, tested, reported, each step linked to
the one before it. Strokes and nodes are heavy on purpose; the mark has to
survive 16px, where the triangular counter is the first thing to close up.

It shares the geometric language of the NexusCRM mark — thick white strokes
on a rounded tile, with filled nodes — so the two read as one suite without
either being a copy.

## Colour

**`#06B6D4`** is the brand cyan.

It is not usable as text on a light background: it measures **2.16:1** on
the light canvas, below even the 3:1 that WCAG allows large text. So the
wordmark takes a per-theme value, exactly as `--color-primary` and
`--color-accent` do:

| Context | Value | Contrast |
|---|---|---|
| Wordmark on dark | `#06B6D4` | 7.48:1 on surface |
| Wordmark on light | `#0E7490` | 5.36:1 on white, 4.77:1 on canvas |
| Tile, both themes | `#06B6D4` → `#38DDEF` gradient | — |

The tile keeps the brand cyan in both themes. White on `#06B6D4` is 2.43:1,
which would fail as text — but a logotype is exempt under WCAG SC 1.4.3, and
the glyph is heavy enough to read cleanly at every size in practice.

In app code the value comes from `--color-brand`, never a literal. A
hardcoded hex renders unreadable in one of the two themes, which is what
`themeTokens.test.tsx` and `Logo.test.tsx` exist to prevent.

## Type

The wordmark is set in the same system stack the apps use
(`-apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`), bold,
with "Nexus" in the ink colour and "LIMS" in the brand cyan.

The two lockup SVGs carry that as **live `<text>`, not outlines**. No font
file travels with the file and the name stays selectable, but the shapes
depend on what the renderer has installed. Before sending either file to a
printer or a third party, convert the text to paths.
