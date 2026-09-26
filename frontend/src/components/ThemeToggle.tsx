import { useTheme, type ThemePreference } from "../theme/ThemeProvider";

const OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

/**
 * A compact segmented control for the color theme preference (light / dark /
 * system). Rendered inside the profile menu. Uses a radiogroup so the current
 * choice is announced and keyboard-selectable.
 */
export function ThemeToggle() {
  const { preference, setPreference } = useTheme();

  return (
    <div className="px-3 py-2">
      <p className="mb-1.5 text-xs text-fg-subtle">Theme</p>
      <div
        role="radiogroup"
        aria-label="Color theme"
        className="flex gap-1 rounded-md bg-surface-muted p-1"
      >
        {OPTIONS.map((option) => {
          const selected = preference === option.value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => setPreference(option.value)}
              className={[
                "flex-1 rounded px-2 py-1 text-xs font-medium",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                selected
                  ? "bg-surface text-fg shadow-sm"
                  : "text-fg-muted hover:text-fg",
              ].join(" ")}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
