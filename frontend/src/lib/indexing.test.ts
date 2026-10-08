import { describe, expect, it } from "vitest";

import type { FixSummary, IndexStatusModel } from "../api/types";
import { fixNotice, indexPollInterval, runLanded } from "./indexing";

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
  last_fix: null,
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

describe("fixNotice", () => {
  const fix = (over: Partial<FixSummary>): FixSummary => ({
    fixed: 0,
    first_failure: null,
    failed: 0,
    error: null,
    finished_at: 1,
    ...over,
  });

  it("reports what was fixed, or that nothing was", () => {
    expect(fixNotice(fix({ fixed: 1 }))).toEqual({ text: "Fixed 1 image", tone: "info" });
    expect(fixNotice(fix({ fixed: 1200 }))).toEqual({ text: "Fixed 1,200 images", tone: "info" });
    expect(fixNotice(fix({}))).toEqual({ text: "Nothing to fix", tone: "info" });
  });

  it("names the first failure, and a run that failed outright", () => {
    expect(fixNotice(fix({ fixed: 2, failed: 3, first_failure: "a.png: busy" }))).toEqual({
      text: "Fixed 2 images; 3 images could not be fixed: a.png: busy",
      tone: "error",
    });
    expect(fixNotice(fix({ error: "another indexer runs" }))).toEqual({
      text: "Fix failed: another indexer runs",
      tone: "error",
    });
  });
});
