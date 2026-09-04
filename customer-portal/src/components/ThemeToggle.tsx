import { useState } from "react";
import { applyTheme, readTheme, type Theme } from "../theme";
import { Icon } from "./Icon";

/**
 * The label names what happens, not what is currently true: a button
 * reading "Light" switches to light. A button labelled with the current
 * state leaves the user guessing whether it is a label or a control.
 *
 * The label moved to aria-label when the header became a row of icon
 * buttons -- the accessible name is unchanged, so the control still answers
 * to "Light"/"Dark" for a screen reader and for its tests. The glyph shows
 * the destination for the same reason the text did: a sun means "go light".
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const next: Theme = theme === "dark" ? "light" : "dark";

  function toggle() {
    setTheme(next);
    applyTheme(next);
  }

  return (
    <button
      type="button"
      className="icon-btn"
      onClick={toggle}
      aria-label={next === "light" ? "Light" : "Dark"}
      title={`Switch to the ${next} theme`}
    >
      <Icon name={next === "light" ? "sun" : "moon"} />
    </button>
  );
}
