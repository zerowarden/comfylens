import { describe, expect, it } from "vitest";

import { indexSuggestions, splitMatch, suggest } from "./suggest";

const index = indexSuggestions(
  ["red fox", "Fox", "arctic fox", "owl", "foxglove"].map((value, i) => ({ value, count: 9 - i })),
);
const values = (query: string, exclude: string[] = [], limit = 8) =>
  suggest(index, query, new Set(exclude), limit).map((s) => s.value);

describe("suggest", () => {
  it("puts values starting with the query first, each part most used first", () => {
    expect(values("fox")).toEqual(["Fox", "foxglove", "red fox", "arctic fox"]);
    expect(values("FO")).toEqual(["Fox", "foxglove", "red fox", "arctic fox"]);
  });

  it("lists everything for a blank query, and honours exclusions and the limit", () => {
    expect(values("  ")).toEqual(["red fox", "Fox", "arctic fox", "owl", "foxglove"]);
    expect(values("fox", ["Fox"], 2)).toEqual(["foxglove", "red fox"]);
    expect(values("cat")).toEqual([]);
  });
});

describe("splitMatch", () => {
  it("splits around the first match, ignoring case", () => {
    expect(splitMatch("Red Fox", "fox")).toEqual(["Red ", "Fox", ""]);
    expect(splitMatch("owl", "fox")).toEqual(["owl", "", ""]);
    expect(splitMatch("owl", " ")).toEqual(["owl", "", ""]);
  });
});
