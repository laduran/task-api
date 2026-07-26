import Alpine from "alpinejs";

import { dashboardApp } from "./dashboardApp";
import { createThemeStore } from "./theme";

declare global {
  interface Window {
    Alpine: typeof Alpine;
  }
}

window.Alpine = Alpine;

Alpine.store("theme", createThemeStore());

Alpine.data("dashboardApp", dashboardApp);
Alpine.start();
