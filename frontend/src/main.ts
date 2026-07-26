import Alpine from "alpinejs";

import { taskApp } from "./taskApp";
import { createThemeStore } from "./theme";

declare global {
  interface Window {
    Alpine: typeof Alpine;
  }
}

// Exposed for debugging from the browser console.
window.Alpine = Alpine;

// A store rather than component state: the toggle lives outside the task
// component, and Alpine calls init() on stores automatically.
Alpine.store("theme", createThemeStore());

Alpine.data("taskApp", taskApp);
Alpine.start();
