import { useState } from "react";
import { applyTheme, readTheme, type Theme } from "../theme";

/**
 * The label names what happens, not what is currently true: a button
 * reading "Light" switches to light. A button labelled with the current
 * state leaves the user guessing whether it is a label or a control.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const next: Theme = theme === "dark" ? "light" : "dark";

  function toggle() {
    setTheme(next);
    applyTheme(next);
  }

  return (
    <button className="btn" onClick={toggle} title={`Switch to the ${next} theme`}>
      {next === "light" ? "Light" : "Dark"}
    </button>
  );
}
