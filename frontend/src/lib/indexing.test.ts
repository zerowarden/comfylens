import { describe, expect, it } from "vitest";

import type { IndexStatusModel } from "../api/types";
import { indexPollInterval, runLanded } from "./indexing";

describe("indexPollInterval", () => {
  it("polls every second while a run is in progress", () => {
    for (const state of ["scanning", "processing", "finalizing"]) {
      expect(indexPollInterval(state, false)).toBe(1000);
      expect(indexPollInterval(state, true)).toBe(1000);
    }
  });

  it("polls slowly while idle only when the library is watched", () => {
    expect(indexPollInterval("idle", true)).toBe(5000);
    expect(indexPollInterval("idle", false)).toBe(false);
    expect(indexPollInterval(undefined, false)).toBe(false);
  });
});

const status = (state: IndexStatusModel["state"], finished: number | null): IndexStatusModel => ({
  state,
  total: 0,
  done: 0,
  errors: 0,
  started_at: null,
  last_error: null,
  last_finished_at: finished,
});

describe("runLanded", () => {
  it("sees a run end when the state returns to idle", () => {
    expect(runLanded(status("processing", null), status("idle", 10))).toBe(true);
    expect(runLanded(status("finalizing", 5), status("idle", 5))).toBe(true);
  });

  it("sees a run that started and finished between two polls", () => {
    expect(runLanded(status("idle", 5), status("idle", 9))).toBe(true);
    expect(runLanded(status("idle", null), status("idle", 9))).toBe(true);
  });

  it("ignores polls without a finished run", () => {
    expect(runLanded(undefined, status("idle", 5))).toBe(false);
    expect(runLanded(status("idle", 5), status("idle", 5))).toBe(false);
    expect(runLanded(status("idle", 5), status("scanning", 5))).toBe(false);
    expect(runLanded(status("idle", null), status("idle", null))).toBe(false);
  });
});
