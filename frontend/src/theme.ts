/**
 * Light/dark theme, chosen explicitly by the user.
 *
 * The system preference is deliberately ignored: the toggle is the only
 * input, so what the user picked is what they get on every visit.
 */

export type Theme = "light" | "dark";

export const STORAGE_KEY = "task-api-theme";
const DEFAULT_THEME: Theme = "light";

function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark";
}

/** Read the stored choice, falling back to the default. */
export function storedTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return isTheme(saved) ? saved : DEFAULT_THEME;
  } catch {
    // localStorage throws in private-browsing modes on some browsers.
    return DEFAULT_THEME;
  }
}

/** Stamp the theme onto <html>, which is what the CSS selects on. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset["theme"] = theme;
}

export interface ThemeStore {
  current: Theme;
  readonly isDark: boolean;
  /** Label for the control, describing what clicking it will do. */
  readonly label: string;
  init(): void;
  toggle(): void;
}

export function createThemeStore(): ThemeStore {
  return {
    current: DEFAULT_THEME,

    get isDark(): boolean {
      return this.current === "dark";
    },

    get label(): string {
      return `Switch to ${this.isDark ? "light" : "dark"} theme`;
    },

    init(): void {
      // The inline script in index.html has already applied this before
      // first paint; re-reading keeps the store in sync with the DOM.
      this.current = storedTheme();
      applyTheme(this.current);
    },

    toggle(): void {
      this.current = this.isDark ? "light" : "dark";
      applyTheme(this.current);
      try {
        localStorage.setItem(STORAGE_KEY, this.current);
      } catch {
        // Not persisting is survivable; the toggle still works this session.
      }
    },
  };
}
