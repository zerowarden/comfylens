import { describe, expect, it } from "vitest";

import type { ImageItem, ImagesPage } from "../api/types";
import { imageItem } from "../test/fixtures";
import {
  attachmentName,
  baseName,
  chunks,
  extension,
  nameProblem,
  MAX_TAG_LENGTH,
  nextRemaining,
  splitTags,
  removeFromPages,
  retag,
  tagProblem,
  updateItems,
  withBaseName,
} from "./files";

const page = (offset: number, ids: number[]): ImagesPage => ({
  total: 0,
  offset,
  items: ids.map((id) => imageItem(id)),
});
const itemIds = (p: ImagesPage | undefined) => p?.items.map((i) => i.id);

describe("attachmentName", () => {
  it("reads the plain and the escaped form", () => {
    expect(attachmentName('attachment; filename="fox1.png"')).toBe("fox1.png");
    expect(attachmentName("attachment; filename*=utf-8''a%20%22fox%22%20%C3%A9.png")).toBe(
      'a "fox" é.png',
    );
  });

  it("is null without a usable name", () => {
    expect(attachmentName("")).toBeNull();
    expect(attachmentName("attachment")).toBeNull();
    expect(attachmentName("attachment; filename*=utf-8''%E0%A4%A")).toBeNull();
  });
});

describe("names", () => {
  it("splits paths and extensions", () => {
    expect(baseName("a/b/c.png")).toBe("c.png");
    expect(baseName("c.png")).toBe("c.png");
    expect(withBaseName("a/b/c.png", "d.png")).toBe("a/b/d.png");
    expect(withBaseName("c.png", "d.png")).toBe("d.png");
    expect(extension("a.b.PNG")).toBe(".PNG");
    expect(extension(".hidden")).toBe("");
    expect(extension("none")).toBe("");
  });

  it.each([
    ["b.png", null],
    ["B.PNG", null],
    ["two words ✓.png", null],
    ["", "Enter a name."],
    ["   ", "Enter a name."],
    [" b.png", "The name cannot start or end with a space."],
    ["x/b.png", "The name cannot contain a slash."],
    ["b\u0007.png", "The name cannot contain control characters."],
    ["é".repeat(127) + ".png", "The name is too long."],
    ["b.jpg", "The name must keep the .png extension."],
    [".png", "The name must keep the .png extension."],
  ])("checks %j", (name, problem) => {
    expect(nameProblem("a.png", name)).toBe(problem);
  });
});

describe("chunks", () => {
  it("splits into runs of at most the size", () => {
    expect(chunks([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
    expect(chunks([], 2)).toEqual([]);
  });
});

describe("removeFromPages", () => {
  // Pages of 3: [1 2 3] [4 5 6] [7 8 9], the last one not cached.
  const order = [1, 2, 3, 4, 5, 6, 7, 8, 9];
  const cached = new Map([
    [0, page(0, [1, 2, 3])],
    [1, page(3, [4, 5, 6])],
  ]);

  it("moves later images up across page boundaries", () => {
    const pages = removeFromPages(order, cached, new Set([2]), 3);
    expect(itemIds(pages.get(0))).toEqual([1, 3, 4]);
    expect(pages.get(0)?.offset).toBe(0);
    expect(pages.get(0)?.total).toBe(8);
    // 7 is on no cached page: the page stops before it rather than show another image there.
    expect(itemIds(pages.get(1))).toEqual([5, 6]);
    expect(pages.get(1)?.offset).toBe(3);
  });

  it("empties pages past the end and leaves others untouched", () => {
    const pages = removeFromPages(order, cached, new Set([1, 2, 3, 4, 5, 6, 7, 8, 9]), 3);
    expect(itemIds(pages.get(0))).toEqual([]);
    expect(itemIds(pages.get(1))).toEqual([]);
    expect([...removeFromPages(order, cached, new Set([9]), 3).keys()]).toEqual([0, 1]);
    expect(itemIds(removeFromPages(order, cached, new Set([9]), 3).get(1))).toEqual([4, 5, 6]);
  });
});

describe("updateItems", () => {
  it("changes the given items and keeps an unrelated page as it is", () => {
    const p = page(0, [1, 2, 3]);
    const rename = (i: ImageItem) => ({ ...i, rel_path: `new/${i.id}.png` });
    expect(updateItems(p, new Set([1, 3]), rename).items.map((i) => i.rel_path)).toEqual([
      "new/1.png",
      "2.png",
      "new/3.png",
    ]);
    expect(updateItems(p, new Set([9]), rename)).toBe(p);
  });
});

describe("tags", () => {
  it("parses a comma-separated field", () => {
    expect(splitTags(" fox , red fox,, ")).toEqual(["fox", "red fox"]);
    expect(splitTags("")).toEqual([]);
  });

  it("removes, then adds, keeping tags sorted and unique", () => {
    expect(retag(["owl", "fox"], ["cat", "fox"], ["owl"])).toEqual(["cat", "fox"]);
    expect(retag(["fox"], ["fox"], ["fox"])).toEqual(["fox"]); // added back after removal
  });

  it("mirrors the server's checks", () => {
    expect(tagProblem("red fox")).toBeNull();
    expect(tagProblem("é".repeat(MAX_TAG_LENGTH))).toBeNull(); // characters, not bytes
    expect(tagProblem("x".repeat(MAX_TAG_LENGTH + 1))).toMatch(/at most 64/);
    expect(tagProblem("a\tb")).toMatch(/control/);
  });
});

describe("nextRemaining", () => {
  const order = [10, 20, 30, 40];
  it("steps forward past removed images, else back", () => {
    expect(nextRemaining(order, 20, new Set([20, 30]))).toBe(40);
    expect(nextRemaining(order, 40, new Set([40, 30]))).toBe(20);
    expect(nextRemaining(order, 20, new Set(order))).toBeNull();
    expect(nextRemaining(order, 99, new Set([99]))).toBeNull();
  });
});
