import Alpine from "alpinejs";

import { taskApp } from "./taskApp";

declare global {
  interface Window {
    Alpine: typeof Alpine;
  }
}

// Exposed for debugging from the browser console.
window.Alpine = Alpine;

Alpine.data("taskApp", taskApp);
Alpine.start();
