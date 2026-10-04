import { describe, expect, it } from "vitest";

import { side, textsDiffer, tokenize, wordDiff } from "./diff";

const kinds = (a: string, b: string) => wordDiff(a, b).ops.map((op) => [op.kind, op.a, op.b]);

describe("tokenize", () => {
  it("splits words, whitespace and punctuation", () => {
    expect(tokenize("a red-fox, 2 cats' toys!\n")).toEqual([
      "a", " ", "red-fox", ",", " ", "2", " ", "cats'", " ", "toys", "!", "\n",
    ]); // prettier-ignore
  });
  it("keeps non-Latin words whole", () => {
    expect(tokenize("猫が好き café")).toEqual(["猫が好き", " ", "café"]);
  });
});

describe("wordDiff", () => {
  it("finds nothing in identical texts", () => {
    const d = wordDiff("a red fox", "a red fox");
    expect(d.ops).toEqual([{ kind: "same", a: "a red fox", b: "a red fox" }]);
    expect(d.coarse).toBe(false);
  });

  it("marks an insertion", () => {
    expect(kinds("a fox", "a red fox")).toEqual([
      ["same", "a ", "a "],
      ["added", "", "red "],
      ["same", "fox", "fox"],
    ]);
  });

  it("marks a deletion", () => {
    expect(kinds("a big red fox", "a red fox")).toEqual([
      ["same", "a ", "a "],
      ["removed", "big ", ""],
      ["same", "red fox", "red fox"],
    ]);
  });

  it("marks a replacement as removed then added", () => {
    expect(kinds("a red fox", "a grey fox")).toEqual([
      ["same", "a ", "a "],
      ["removed", "red", ""],
      ["added", "", "grey"],
      ["same", " fox", " fox"],
    ]);
  });

  it("ignores whitespace-only changes but keeps each side's whitespace", () => {
    const d = wordDiff("a  red\nfox", "a red fox");
    expect(d.ops.every((op) => op.kind === "same")).toBe(true);
    expect(
      side(d, "a")
        .map((s) => s.text)
        .join(""),
    ).toBe("a  red\nfox");
    expect(
      side(d, "b")
        .map((s) => s.text)
        .join(""),
    ).toBe("a red fox");
    expect(textsDiffer("a  red\nfox", "a red fox")).toBe(false);
  });

  it("handles empty prompts", () => {
    expect(wordDiff("", "").ops).toEqual([]);
    expect(kinds("", "a fox")).toEqual([["added", "", "a fox"]]);
    expect(kinds("a fox", "")).toEqual([["removed", "a fox", ""]]);
  });

  it("falls back to a coarse diff for very long texts", () => {
    const a = "start " + Array.from({ length: 300 }, (_, i) => `a${i}`).join(" ") + " end";
    const b = "start " + Array.from({ length: 300 }, (_, i) => `b${i}`).join(" ") + " end";
    const d = wordDiff(a, b, 1000);
    expect(d.coarse).toBe(true);
    expect(d.ops.map((op) => op.kind)).toEqual(["same", "removed", "added", "same"]);
    expect(
      side(d, "a")
        .map((s) => s.text)
        .join(""),
    ).toBe(a);
    expect(
      side(d, "b")
        .map((s) => s.text)
        .join(""),
    ).toBe(b);
  });

  it("reassembles both texts exactly from their sides", () => {
    const a = "Convert the image, keep the pose.\n\nPlastic look";
    const b = "Convert this image; keep pose.\nFilm look";
    const d = wordDiff(a, b);
    expect(
      side(d, "a")
        .map((s) => s.text)
        .join(""),
    ).toBe(a);
    expect(
      side(d, "b")
        .map((s) => s.text)
        .join(""),
    ).toBe(b);
    expect(side(d, "a").some((s) => s.kind === "added")).toBe(false);
    expect(side(d, "b").some((s) => s.kind === "removed")).toBe(false);
  });
});
