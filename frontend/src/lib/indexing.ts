import type { IndexStatusModel } from "../api/types";

/**
 * How often to poll GET /api/index/status: every second while a run is in progress. While idle,
 * only when the server watches the library, because runs then start without a click: every 5 s.
 */
export function indexPollInterval(state: string | undefined, watching: boolean): number | false {
  if (state !== undefined && state !== "idle") return 1000;
  return watching ? 5000 : false;
}

/**
 * Whether an index run finished between two status polls, so the data should be refreshed.
 * A watched library's runs can start and finish between two polls, so a changed
 * `last_finished_at` counts as well as a busy-to-idle transition.
 */
export function runLanded(
  previous: IndexStatusModel | undefined,
  next: IndexStatusModel | undefined,
): boolean {
  if (!previous || !next) return false;
  if (previous.state !== "idle" && next.state === "idle") return true;
  return next.last_finished_at !== null && next.last_finished_at !== previous.last_finished_at;
}
