import { useUi } from "../state/ui";
import { Glyph } from "./icons";

/**
 * A sliding switch: the knob sits left with a sun in the light theme and right with a moon in the
 * dark one. Its colours are the toggle tokens in theme.css.
 */
export default function ThemeToggle() {
  const dark = useUi((s) => s.theme === "dark");
  const toggleTheme = useUi((s) => s.toggleTheme);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Dark theme"
      title={dark ? "Switch to the light theme" : "Switch to the dark theme"}
      onClick={toggleTheme}
      className="relative h-6 w-11 shrink-0 rounded-full bg-toggle-track shadow-inner ring-1 ring-overlay/10 transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <span
        className={`absolute top-0.5 left-0.5 flex size-5 items-center justify-center rounded-full bg-toggle-knob text-toggle-icon shadow transition-transform duration-200 ${
          dark ? "translate-x-5" : ""
        }`}
      >
        <Glyph
          name={dark ? "moon" : "sun"}
          className={`size-3.5 ${dark ? "[&_path]:fill-current" : ""}`}
        />
      </span>
    </button>
  );
}
