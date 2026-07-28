import type { AlpineComponent } from "alpinejs";

import { ApiError, TaskApi } from "./api";
import type { Filter, LogEntry, Task } from "./types";

const LOG_LIMIT = 8;
const FILTERS: readonly Filter[] = ["all", "active", "done"];

export interface TaskAppData {
  tasks: Task[];
  newTitle: string;
  filter: Filter;
  filters: readonly Filter[];
  editingId: number | null;
  editTitle: string;
  error: string;
  loading: boolean;
  busy: boolean;
  /** Task ids with a request in flight, used to dim their row. */
  pending: number[];
  log: LogEntry[];

  readonly visible: Task[];
  readonly remaining: number;

  init(): Promise<void>;
  load(): Promise<void>;
  add(): Promise<void>;
  toggle(task: Task): Promise<void>;
  startEdit(task: Task, source: HTMLElement): void;
  saveEdit(task: Task): Promise<void>;
  remove(task: Task): Promise<void>;
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message;
  }
  return String(error);
}

export function taskApp(): AlpineComponent<TaskAppData> {
  // Kept in closure scope rather than on the data object so Alpine does not
  // wrap the client in a reactive proxy.
  const api = new TaskApi();

  return {
    tasks: [],
    newTitle: "",
    filter: "all",
    filters: FILTERS,
    editingId: null,
    editTitle: "",
    error: "",
    loading: true,
    busy: false,
    pending: [],
    log: [],

    // --- derived state: no network involved ------------------------------

    get visible(): Task[] {
      if (this.filter === "active") {
        return this.tasks.filter((task) => !task.finished);
      }
      if (this.filter === "done") {
        return this.tasks.filter((task) => task.finished);
      }
      return this.tasks;
    },

    get remaining(): number {
      return this.tasks.filter((task) => !task.finished).length;
    },

    // --- lifecycle --------------------------------------------------------

    async init(): Promise<void> {
      api.observe = (entry) => {
        this.log = [entry, ...this.log].slice(0, LOG_LIMIT);
      };
      await this.load();
    },

    async load(): Promise<void> {
      this.loading = true;
      try {
        this.tasks = await api.list();
      } catch (error) {
        this.error = messageOf(error);
      } finally {
        this.loading = false;
      }
    },

    // --- mutations --------------------------------------------------------

    async add(): Promise<void> {
      const title = this.newTitle.trim();
      if (title === "") {
        return;
      }

      this.busy = true;
      try {
        this.tasks.push(await api.create(title));
        this.newTitle = "";
        this.error = "";
      } catch (error) {
        this.error = messageOf(error);
      } finally {
        this.busy = false;
        // Disabling the input while busy blurs it (a disabled element can't
        // hold focus) -- re-focus once it's re-enabled so pressing Enter to
        // add a task doesn't kick the cursor out of the box.
        this.$nextTick(() => {
          const input = this.$refs["newTitle"];
          if (input instanceof HTMLInputElement) {
            input.focus();
          }
        });
      }
    },

    /** Optimistic: flip immediately, roll back if the server disagrees. */
    async toggle(task: Task): Promise<void> {
      const previous = task.finished;
      task.finished = !previous;
      this.pending.push(task.id);

      try {
        Object.assign(task, await api.update(task.id, { finished: task.finished }));
        this.error = "";
      } catch (error) {
        task.finished = previous;
        this.error = messageOf(error);
      } finally {
        this.pending = this.pending.filter((id) => id !== task.id);
      }
    },

    /** Entering edit mode is pure client state — no request at all.
     *
     * Looked up from *source* (the clicked element's own row) rather than
     * $refs: every task's edit input shares the x-for loop, so a single
     * $refs name would resolve to whichever one registered last -- always
     * the same task regardless of which row was actually clicked.
     */
    startEdit(task: Task, source: HTMLElement): void {
      this.editingId = task.id;
      this.editTitle = task.title;
      this.$nextTick(() => {
        const input = source.closest("li")?.querySelector<HTMLInputElement>("input.title");
        if (input) {
          input.focus();
          input.select();
        }
      });
    },

    async saveEdit(task: Task): Promise<void> {
      if (this.editingId !== task.id) {
        return;
      }

      const title = this.editTitle.trim();
      this.editingId = null;
      if (title === "" || title === task.title) {
        return; // nothing worth sending
      }

      const previous = task.title;
      task.title = title;
      this.pending.push(task.id);

      try {
        Object.assign(task, await api.update(task.id, { title }));
        this.error = "";
      } catch (error) {
        task.title = previous;
        this.error = messageOf(error);
      } finally {
        this.pending = this.pending.filter((id) => id !== task.id);
      }
    },

    async remove(task: Task): Promise<void> {
      const index = this.tasks.indexOf(task);
      if (index === -1) {
        return;
      }

      this.tasks.splice(index, 1);
      try {
        await api.remove(task.id);
        this.error = "";
      } catch (error) {
        this.tasks.splice(index, 0, task); // put it back
        this.error = messageOf(error);
      }
    },
  };
}
