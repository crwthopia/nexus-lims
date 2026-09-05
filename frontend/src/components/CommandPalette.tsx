import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "./Icon";
import { navItems, type NavItem } from "./navigation";

/**
 * Ctrl-K / Cmd-K quick navigation.
 *
 * It searches the console's own destinations and nothing else. That is a
 * deliberate limit rather than a first step towards a global search: the API
 * has no cross-resource search endpoint, and a palette that quietly returns
 * only the sections while looking like it searches records would be worse
 * than one that never claimed to.
 *
 * The list is a listbox owned by the text input (aria-activedescendant), not
 * a set of focusable buttons: focus has to stay in the field so typing keeps
 * filtering while the arrow keys move the selection.
 */
export function CommandPalette({
  open,
  onClose,
  hasRole,
}: {
  open: boolean;
  onClose: () => void;
  hasRole: (...roleNames: string[]) => boolean;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useMemo(() => {
    const items = navItems(hasRole);
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => `${item.label} ${item.keywords ?? ""} ${item.to}`.toLowerCase().includes(q));
  }, [query, hasRole]);

  // Reopening on a stale query is disorienting -- the palette should always
  // open on the full list, however it was closed.
  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      inputRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  function choose(item: NavItem | undefined) {
    if (!item) return;
    onClose();
    navigate(item.to);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (results.length ? (i + 1) % results.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (results.length ? (i - 1 + results.length) % results.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  }

  return (
    // The backdrop closes on click; the panel stops the event so a click
    // inside it (selecting text in the field, say) doesn't dismiss.
    <div className="palette" onMouseDown={onClose} role="presentation">
      <div
        className="palette-panel"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Go to"
      >
        <input
          ref={inputRef}
          className="palette-input"
          type="text"
          placeholder="Go to…"
          aria-label="Go to"
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-results"
          aria-activedescendant={results.length ? `palette-option-${active}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
        {results.length === 0 ? (
          <p className="palette-empty">Nothing here matches “{query}”.</p>
        ) : (
          <ul className="palette-list" id="palette-results" role="listbox" aria-label="Destinations">
            {results.map((item, i) => (
              <li key={item.to} role="presentation">
                <button
                  type="button"
                  id={`palette-option-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className="palette-option"
                  // Selection follows the pointer so the highlight and the
                  // row under the cursor can never disagree about what
                  // Enter would open.
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(item)}
                  // The input keeps focus: mousedown would take it away
                  // before the click lands.
                  onMouseDown={(e) => e.preventDefault()}
                  tabIndex={-1}
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
