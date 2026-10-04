import { describe, expect, it } from "vitest";

import type { CollectionImage, Draft } from "../api/types";
import { useCollection } from "../state/collection";
import { emptyFilters, useFilters } from "../state/filters";
import { useSelection } from "../state/selection";
import { useUi } from "../state/ui";
import {
  appendReferences,
  emptySettings,
  fillEmptyFields,
  imageFiles,
  loraText,
  parseTags,
  promptSettingsRows,
  seedDraft,
  showInLibrary,
} from "./collection";
import { parseViewHash, viewHash } from "./viewHash";

function original(hash: string): CollectionImage {
  return {
    content_hash: hash,
    role: "reference",
    format: "png",
    width: 8,
    height: 8,
    has_workflow: false,
    library_ids: [],
  };
}

function draft(hash: string | null, metadata: Draft["metadata"] = "none"): Draft {
  return {
    original: hash ? original(hash) : null,
    title: hash ?? "text",
    positive: "",
    negative: "",
    model_family: null,
    settings: emptySettings(),
    metadata,
  };
}

describe("view hash", () => {
  it("parses the collection view and an open prompt", () => {
    expect(parseViewHash("")).toEqual({ view: "library", promptId: null });
    expect(parseViewHash("#collection")).toEqual({ view: "collection", promptId: null });
    expect(parseViewHash("#collection/12")).toEqual({ view: "collection", promptId: 12 });
    expect(parseViewHash("#collection/0")).toEqual({ view: "collection", promptId: null });
    expect(parseViewHash("#collection/x")).toEqual({ view: "library", promptId: null });
    expect(parseViewHash("#elsewhere")).toEqual({ view: "library", promptId: null });
  });

  it("writes what it parses", () => {
    for (const hash of ["", "#collection", "#collection/7"]) {
      expect(viewHash(parseViewHash(hash))).toBe(hash);
    }
    expect(viewHash({ view: "library", promptId: 3 })).toBe("");
  });
});

describe("seedDraft", () => {
  it("takes the text from the first draft with metadata and every image as a reference", () => {
    const seeded = seedDraft([draft("a"), draft("b", "comfyui"), draft("a"), draft("c")]);
    expect(seeded?.draft.title).toBe("b");
    expect(seeded?.references.map((r) => r.content_hash)).toEqual(["a", "b", "c"]);
  });

  it("falls back to the first draft, and to nothing", () => {
    expect(seedDraft([draft("a"), draft("b")])?.draft.title).toBe("a");
    expect(seedDraft([])).toBeNull();
  });
});

describe("parseTags", () => {
  it("splits on commas, trims, lowercases and drops duplicates", () => {
    expect(parseTags(" Moody,  film   grain ,moody,, ")).toEqual(["moody", "film grain"]);
    expect(parseTags("")).toEqual([]);
  });
});

describe("showInLibrary", () => {
  it("replaces the filters, clears the selection and switches view", () => {
    useFilters.setState({ filters: { ...emptyFilters(), families: ["flux"] } });
    useSelection.getState().setSelected(new Set([1, 2]));
    useUi.getState().setView("collection");
    useCollection.getState().openPrompt(5);
    showInLibrary(5);
    expect(useFilters.getState().filters).toEqual({ ...emptyFilters(), saved_prompt: 5 });
    expect(useSelection.getState().selected.size).toBe(0);
    expect(useUi.getState().view).toBe("library");
    expect(useCollection.getState().openId).toBeNull();
  });
});

describe("promptSettingsRows", () => {
  it("lists known settings in order and formats LoRAs", () => {
    const rows = promptSettingsRows({ ...emptySettings(), steps: 20, sampler_name: "euler" });
    expect(rows).toEqual([
      { label: "sampler", value: "euler" },
      { label: "steps", value: "20" },
    ]);
    expect(loraText({ name: "fox", strength_model: 0.8, strength_clip: 0.8 })).toBe("fox 0.8");
    expect(loraText({ name: "fox", strength_model: 0.8, strength_clip: 1 })).toBe("fox 0.8 / 1");
    expect(loraText({ name: "fox", strength_model: null, strength_clip: null })).toBe("fox ?");
  });
});

describe("adding images in the editor", () => {
  const fields = {
    title: "",
    positive: "",
    negative: "",
    family: "",
    settings: emptySettings(),
  };
  const withMetadata: Draft = {
    ...draft("m", "comfyui"),
    title: "a fox",
    positive: "a fox in snow",
    negative: "blurry",
    model_family: "flux",
    settings: { ...emptySettings(), steps: 20 },
  };

  it("appends new references once, in order", () => {
    const refs = appendReferences([original("a")], [draft("b"), draft("a"), draft(null)]);
    expect(refs.map((r) => r.content_hash)).toEqual(["a", "b"]);
  });

  it("leaves the fields alone when no image has metadata", () => {
    expect(fillEmptyFields(fields, [draft("a")])).toBe(fields);
  });

  it("fills only the empty fields from the first image with metadata", () => {
    expect(fillEmptyFields(fields, [draft("a"), withMetadata])).toEqual({
      title: "a fox",
      positive: "a fox in snow",
      negative: "blurry",
      family: "flux",
      settings: { ...emptySettings(), steps: 20 },
    });
    const typed = {
      ...fields,
      title: "Mine",
      positive: "typed by hand",
      settings: { ...emptySettings(), cfg: 4 },
    };
    expect(fillEmptyFields(typed, [withMetadata])).toEqual({
      ...typed,
      negative: "blurry",
      family: "flux",
    });
  });

  it("keeps image files only", () => {
    const png = new File(["x"], "a.png", { type: "image/png" });
    const text = new File(["x"], "a.txt", { type: "text/plain" });
    const unknown = new File(["x"], "a.webp");
    expect(imageFiles([png, text, unknown])).toEqual([png, unknown]);
  });
});
