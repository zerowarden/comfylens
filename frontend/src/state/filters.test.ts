import { describe, expect, it } from "vitest";

import type { Filters } from "../api/types";
import {
  defaultSort,
  emptyFilters,
  fromSearch,
  hasActiveFilters,
  toSearch,
  useFilters,
} from "./filters";

describe("URL sync", () => {
  it("a clean view has an empty query string", () => {
    expect(toSearch(emptyFilters(), defaultSort())).toBe("");
    expect(fromSearch("")).toEqual({ filters: emptyFilters(), sort: defaultSort() });
  });

  it("round-trips every filter and the sort", () => {
    const filters: Filters = {
      families: ["qwen-image-2.1", "(no metadata)"],
      base_models: ["flux1-dev"],
      samplers: ["euler"],
      schedulers: ["beta", "simple"],
      loras: { names: ["a & b", "c"], mode: "all" },
      date_from: "2026-09-01",
      date_to: "2026-09-30",
      statuses: ["ok", "error"],
      text: "realistic photograph",
      numeric: { cfg: [1.5, 3], steps: [20, 40] },
      has_warnings: false,
      saved: true,
      saved_prompt: 12,
      sentences: ["0123456789abcdef", "fedcba9876543210"],
    };
    const sort = { key: "cfg" as const, descending: false };
    const search = toSearch(filters, sort);
    expect(search).toContain("family=qwen-image-2.1");
    expect(search).toContain("lora_mode=all");
    expect(search).toContain("saved=yes");
    expect(search).toContain("prompt=12");
    expect(search).toContain("sentence=0123456789abcdef");
    expect(fromSearch(search)).toEqual({ filters, sort });
    expect(fromSearch(`?${search}`)).toEqual({ filters, sort });
  });

  it("ignores invalid values", () => {
    const { filters, sort } = fromSearch(
      "status=bogus&status=ok&from=yesterday&cfg=3,1&steps=x,2&sort=nope&order=sideways&warnings=maybe",
    );
    expect(filters.statuses).toEqual(["ok"]);
    expect(filters.date_from).toBeNull();
    expect(filters.numeric).toEqual({});
    expect(filters.has_warnings).toBeNull();
    expect(sort).toEqual(defaultSort());
  });

  it("accepts only a positive integer saved prompt and a yes/no saved flag", () => {
    for (const bad of ["prompt=abc", "prompt=0", "prompt=-3", "prompt=1.5", "saved=maybe"]) {
      const { filters } = fromSearch(bad);
      expect(filters.saved_prompt).toBeNull();
      expect(filters.saved).toBeNull();
    }
    expect(fromSearch("saved=no").filters.saved).toBe(false);
  });

  it("counts the collection filters as active", () => {
    expect(hasActiveFilters({ ...emptyFilters(), saved: false })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters(), saved_prompt: 3 })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters(), sentences: ["0123456789abcdef"] })).toBe(true);
  });

  it("accepts only 16-hex-digit sentence hashes", () => {
    expect(fromSearch("sentence=0123456789abcdef&sentence=nope").filters.sentences).toEqual([
      "0123456789abcdef",
    ]);
  });
});

describe("filter store", () => {
  it("toggles, includes without toggling off, and clears", () => {
    const store = useFilters.getState();
    store.toggle("samplers", "euler");
    useFilters.getState().include("samplers", "euler");
    expect(useFilters.getState().filters.samplers).toEqual(["euler"]);
    useFilters.getState().toggle("samplers", "euler");
    expect(useFilters.getState().filters.samplers).toEqual([]);
    useFilters.getState().includeLora("x");
    expect(hasActiveFilters(useFilters.getState().filters)).toBe(true);
    useFilters.getState().clear();
    expect(useFilters.getState().filters).toEqual(emptyFilters());
  });
});
