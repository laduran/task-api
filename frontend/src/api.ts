import type {
  DeleteResult,
  ErrorPayload,
  LogEntry,
  Task,
  TaskUpdate,
} from "./types";

type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

/** Thrown for any non-2xx response, carrying the decoded payload. */
export class ApiError extends Error {
  readonly status: number;
  readonly payload: ErrorPayload | null;

  constructor(message: string, status: number, payload: ErrorPayload | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

/** Collapse the API's error payload into one readable sentence. */
export function describeError(
  payload: ErrorPayload | null,
  status: number,
): string {
  if (payload === null) {
    return `HTTP ${status}`;
  }

  const fields = payload.errors?.json;
  if (fields !== undefined) {
    const parts = Object.entries(fields).map(([field, messages]) => {
      const text = Array.isArray(messages) ? messages.join(", ") : messages;
      // `_schema` holds whole-body errors, which read better without a prefix.
      return field === "_schema" ? text : `${field}: ${text}`;
    });
    if (parts.length > 0) {
      return parts.join("; ");
    }
  }

  return payload.message ?? payload.status ?? `HTTP ${status}`;
}

/** Called after every request, for the UI's request log. */
export type RequestObserver = (entry: LogEntry) => void;

export class TaskApi {
  /** Reassigned by the component once it can capture `this`. */
  observe: RequestObserver = () => {};

  list(): Promise<Task[]> {
    return this.request<Task[]>("GET", "/tasks");
  }

  create(title: string): Promise<Task> {
    return this.request<Task>("POST", "/tasks", { title });
  }

  update(id: number, changes: TaskUpdate): Promise<Task> {
    return this.request<Task>("PUT", `/tasks/${id}`, changes);
  }

  remove(id: number): Promise<DeleteResult> {
    return this.request<DeleteResult>("DELETE", `/tasks/${id}`);
  }

  private async request<T>(
    method: HttpMethod,
    url: string,
    body?: unknown,
  ): Promise<T> {
    const init: RequestInit = { method };
    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }

    const response = await fetch(url, init);
    const payload: unknown =
      response.status === 204 ? null : await response.json().catch(() => null);

    this.observe({ method, url, status: response.status, ok: response.ok });

    if (!response.ok) {
      const error = payload as ErrorPayload | null;
      throw new ApiError(describeError(error, response.status), response.status, error);
    }

    return payload as T;
  }
}
