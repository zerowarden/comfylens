import { describe, expect, it } from "vitest";

import type { ScopeInfo } from "../api/types";
import { fmtNum, fractionOf, isSingleSelection, scopeParts, scopeSentence } from "./format";

const scope = (over: Partial<ScopeInfo>): ScopeInfo => ({
  scope_kind: "all",
  scope_size: 0,
  excluded_no_metadata: 0,
  duplicates_removed: 0,
  analyzed: 0,
  ...over,
});

describe("scopeSentence", () => {
  it("states selections, filters and the whole library", () => {
    expect(scopeSentence(scope({ scope_kind: "selection", scope_size: 37 }))).toBe(
      "Analyzing 37 selected images",
    );
    expect(scopeSentence(scope({ scope_kind: "all", scope_size: 4212 }))).toBe(
      "Analyzing all 4,212 images",
    );
    expect(scopeSentence(scope({ scope_kind: "filtered", scope_size: 812 }))).toBe(
      "Analyzing 812 filtered images",
    );
  });

  it("uses the singular for one image", () => {
    expect(scopeSentence(scope({ scope_kind: "selection", scope_size: 1 }))).toBe(
      "Analyzing 1 selected image",
    );
    expect(scopeSentence(scope({ scope_kind: "all", scope_size: 1 }))).toBe(
      "Analyzing all 1 image",
    );
  });

  it("adds files without metadata and duplicates", () => {
    expect(
      scopeSentence(
        scope({
          scope_kind: "all",
          scope_size: 4212,
          excluded_no_metadata: 12,
          duplicates_removed: 1,
        }),
      ),
    ).toBe("Analyzing all 4,212 images (12 without metadata, 1 duplicate counted once)");
  });

  it("splits into a main line and notes for the fixed-height header", () => {
    expect(scopeParts(scope({ scope_kind: "filtered", scope_size: 3 }))).toEqual({
      main: "Analyzing 3 filtered images",
      notes: "",
    });
    expect(scopeParts(scope({ scope_size: 9, duplicates_removed: 2 })).notes).toBe(
      "2 duplicates counted once",
    );
  });
});

describe("fmtNum", () => {
  it("trims to four decimals", () => {
    expect(fmtNum(2)).toBe("2");
    expect(fmtNum(1.46234)).toBe("1.4623");
    expect(fmtNum(null)).toBe("—");
  });
});

describe("isSingleSelection", () => {
  it("is true only for exactly one selected image", () => {
    expect(isSingleSelection(scope({ scope_kind: "selection", scope_size: 1 }))).toBe(true);
    expect(isSingleSelection(scope({ scope_kind: "selection", scope_size: 2 }))).toBe(false);
    expect(isSingleSelection(scope({ scope_kind: "filtered", scope_size: 1 }))).toBe(false);
    expect(isSingleSelection(scope({ scope_kind: "all", scope_size: 1 }))).toBe(false);
  });
});

describe("fractionOf", () => {
  it("places a value between two ends, and an empty span at its start", () => {
    expect([fractionOf(5, 0, 10), fractionOf(0, 0, 10), fractionOf(3, 3, 3)]).toEqual([0.5, 0, 0]);
  });
});
