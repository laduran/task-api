/** Shapes exchanged with the Task API. Mirrors backend/openapi.json. */

export interface Task {
  id: number;
  title: string;
  finished: boolean;
}

/** Body accepted by PUT /tasks/{id}. At least one field must be present. */
export interface TaskUpdate {
  title?: string;
  finished?: boolean;
}

export interface DeleteResult {
  message: string;
}

/**
 * Error payload emitted by flask-smorest for every non-2xx response.
 *
 * Validation failures (422) put per-field messages under `errors.json`;
 * schema-level failures use the `_schema` key.
 */
export interface ErrorPayload {
  code?: number;
  status?: string;
  message?: string;
  errors?: {
    json?: Record<string, string | string[]>;
  };
}

export type Filter = "all" | "active" | "done";

export interface LogEntry {
  method: string;
  url: string;
  status: number;
  ok: boolean;
}
