import type { AlpineComponent } from "alpinejs";

interface Bucket {
  minute: string;
  count: number;
  errors: number;
  avg_duration_ms: number;
  max_duration_ms: number;
}

interface Summary {
  window_minutes: number;
  generated_at: string;
  total_requests: number;
  total_errors: number;
  error_rate: number;
  buckets: Bucket[];
}

interface DashboardAppData {
  windowMinutes: number;
  summary: Summary | null;
  loading: boolean;
  error: string;
  /** Bumped on every load() call; guards against a slow, superseded
   * request's response overwriting a faster, later one — e.g. switching the
   * window selector before the previous fetch has returned. */
  requestId: number;
  readonly recentBuckets: Bucket[];
  readonly errorRatePercent: string;
  init(): void;
  load(): Promise<void>;
}

// Matches Render's free-tier cold start (~1 min after idle) closely enough
// that a visitor sees the dashboard catch up shortly after the service wakes.
const REFRESH_MS = 30_000;

// Newest first, capped so the table stays "very basic" rather than an
// unbounded scroll.
const MAX_ROWS = 30;

export function dashboardApp(): AlpineComponent<DashboardAppData> {
  return {
    windowMinutes: 60,
    summary: null,
    loading: true,
    error: "",
    requestId: 0,

    get recentBuckets(): Bucket[] {
      if (!this.summary) return [];
      return [...this.summary.buckets].reverse().slice(0, MAX_ROWS);
    },

    get errorRatePercent(): string {
      return this.summary ? `${(this.summary.error_rate * 100).toFixed(1)}%` : "—";
    },

    init(): void {
      void this.load();
      setInterval(() => void this.load(), REFRESH_MS);
    },

    async load(): Promise<void> {
      const thisRequest = ++this.requestId;
      this.error = "";
      try {
        const response = await fetch(`/metrics/summary?minutes=${this.windowMinutes}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = (await response.json()) as Summary;
        if (thisRequest !== this.requestId) return; // superseded by a later load()
        this.summary = data;
      } catch (err) {
        if (thisRequest !== this.requestId) return;
        this.error = err instanceof Error ? err.message : "Failed to load metrics";
      } finally {
        if (thisRequest === this.requestId) this.loading = false;
      }
    },
  };
}
