// Contract test against a running server; skipped unless COMFYLENS_LIVE is set:
//   COMFYLENS_LIVE=http://127.0.0.1:8765 npm --prefix frontend test
// Sends the same requests the UI sends and checks each response has exactly the fields that
// types.ts declares. Read-only: it never calls /api/index/rescan.
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { emptyFilters, defaultSort } from "../state/filters";
import { api, ApiError } from "./client";
import type { Filters, Scope } from "./types";

const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env;
const base = env?.COMFYLENS_LIVE;

function expectKeys(value: unknown, keys: string[]) {
  expect(value).toBeTypeOf("object");
  expect(Object.keys(value as object).sort()).toEqual([...keys].sort());
}

const SCOPE_INFO = [
  "scope_kind",
  "scope_size",
  "excluded_no_metadata",
  "duplicates_removed",
  "analyzed",
];
const NUMERIC = [
  "n",
  "n_missing",
  "mode",
  "mode_tied",
  "mode_note",
  "mode_share",
  "median",
  "mean",
  "std",
  "min",
  "p25",
  "p75",
  "max",
  "histogram",
];
const IMAGE_ITEM = [
  "id",
  "content_hash",
  "rel_path",
  "width",
  "height",
  "family",
  "generated_at",
  "status",
  "has_warnings",
  "timestamp_suspect",
];

describe.skipIf(!base)("live API contract", () => {
  const realFetch = globalThis.fetch;
  beforeAll(() => {
    vi.stubGlobal("fetch", (path: string, init?: RequestInit) => realFetch(`${base}${path}`, init));
  });
  afterAll(() => vi.unstubAllGlobals());

  const all: Scope = { selection: [], filters: emptyFilters(), pool: false };

  it("library, status and facets", async () => {
    const library = await api.library();
    expectKeys(library, [
      "root",
      "total",
      "counts_by_status",
      "counts_by_family",
      "timestamp_suspect",
      "fts_available",
      "last_index_at",
      "index",
      "versions",
      "snapshot_built_at",
      "prompts_ready",
      "watching",
    ]);
    expect(library.watching).toBeTypeOf("boolean");
    expectKeys(library.versions, ["app", "schema_version", "extractor_version"]);
    expectKeys(await api.indexStatus(), [
      "state",
      "total",
      "done",
      "errors",
      "started_at",
      "last_error",
      "last_finished_at",
    ]);
    const facets = await api.facets();
    expectKeys(facets, [
      "families",
      "base_models",
      "samplers",
      "schedulers",
      "loras",
      "statuses",
      "date_range",
      "numeric_ranges",
    ]);
    expectKeys(facets.families[0], ["value", "count"]);
    expectKeys(facets.date_range, ["min", "max"]);
    expectKeys(facets.numeric_ranges.cfg, ["min", "max"]);
  });

  it("ids, pages, detail and raw with every filter set", async () => {
    const facets = await api.facets();
    const filters: Filters = {
      ...emptyFilters(),
      families: [facets.families[0]!.value],
      loras: { names: facets.loras.slice(0, 2).map((v) => v.value), mode: "any" },
      date_from: facets.date_range.min,
      date_to: facets.date_range.max,
      statuses: ["ok"],
      numeric: { cfg: [0, 100], steps: [1, 1000] },
      has_warnings: null,
    };
    for (const key of ["generated_at", "rel_path", "family", "steps", "cfg"] as const) {
      const ids = await api.ids({ filters, sort: { key, descending: key !== "rel_path" } });
      expectKeys(ids, ["ids"]);
    }
    const sort = defaultSort();
    const { ids } = await api.ids({ filters: emptyFilters(), sort });
    const page = await api.images({ filters: emptyFilters(), sort, offset: 500, limit: 500 });
    expectKeys(page, ["total", "offset", "items"]);
    expectKeys(page.items[0], IMAGE_ITEM);
    expect(page.items.map((i) => i.id)).toEqual(ids.slice(500, 1000)); // pages follow the id order

    const text = await api.ids({ filters: { ...emptyFilters(), text: "fox" }, sort });
    // A text search can only narrow the whole library: every id it returns is a known one.
    const known = new Set(ids);
    expect(text.ids.filter((textId) => !known.has(textId))).toEqual([]);
    const warned = await api.ids({ filters: { ...emptyFilters(), has_warnings: true }, sort });
    const id = warned.ids[0] ?? ids[0]!;

    const detail = await api.image(id);
    expectKeys(detail, [
      "file",
      "generation",
      "stages",
      "loras",
      "input_images",
      "nodes",
      "warnings",
    ]);
    expectKeys(detail.file, [
      "id",
      "rel_path",
      "format",
      "size",
      "width",
      "height",
      "megapixels",
      "aspect",
      "aspect_label",
      "content_hash",
      "generated_at",
      "timestamp_suspect",
      "status",
      "error",
    ]);
    if (detail.nodes[0])
      expectKeys(detail.nodes[0], ["id", "class_type", "title", "reachable", "inputs"]);
    if (detail.loras[0]) {
      expectKeys(detail.loras[0], [
        "position",
        "stage_index",
        "node_id",
        "entry",
        "class_type",
        "name_raw",
        "name",
        "base_name",
        "step",
        "strength_model",
        "strength_clip",
        "enabled",
        "reachable",
      ]);
    }
    expectKeys(await api.raw(id), ["sources", "prompt", "workflow", "other"]);
    const file = await realFetch(`${base}/api/images/${id}/file`);
    expect(file.status).toBe(200);
    const thumb = await realFetch(`${base}/thumbs/${detail.file.content_hash}.webp`);
    expect(thumb.status).toBe(200);
    expect((await realFetch(`${base}/thumbs/not-a-hash.webp`)).status).toBe(404);
  });

  it("stats for all, a selection, filters and pooled", async () => {
    const { ids } = await api.ids({ filters: emptyFilters(), sort: defaultSort() });
    const scopes: Scope[] = [
      all,
      { ...all, selection: ids.slice(0, 37) },
      { ...all, filters: { ...emptyFilters(), samplers: ["euler"] } },
      { ...all, pool: true },
    ];
    for (const scope of scopes) {
      const stats = await api.stats({
        ...scope,
        sections: ["numeric", "categorical", "seeds", "loras", "stacks", "configs"],
        lora_key: "name",
      });
      expectKeys(stats, ["scope", "groups"]);
      expectKeys(stats.scope, SCOPE_INFO);
      const g = stats.groups[0]!;
      expectKeys(g, [
        "family",
        "images",
        "numeric",
        "categorical",
        "seeds",
        "loras",
        "stacks",
        "configs",
      ]);
      expectKeys(g.numeric!.steps, NUMERIC);
      expectKeys(g.categorical!.sampler_name, ["n", "values", "other", "missing"]);
      expectKeys(g.seeds, ["n", "n_unique", "repeated"]);
      if (g.loras![0]) {
        expectKeys(g.loras![0], [
          "name",
          "images",
          "share",
          "strength_model",
          "strength_clip",
          "positions",
          "steps",
        ]);
      }
      if (g.stacks![0])
        expectKeys(g.stacks![0], ["key", "count", "share", "examples", "example_hashes"]);
      expectKeys(g.configs![0], ["key", "count", "share", "fields", "examples", "example_hashes"]);
    }
    expect(
      (await api.stats({ ...scopes[1]!, sections: ["numeric"], lora_key: "name" })).scope
        .scope_kind,
    ).toBe("selection");
    const pooled = await api.stats({
      ...all,
      pool: true,
      sections: ["categorical"],
      lora_key: "name",
    });
    expect(pooled.groups.map((g) => g.family)).toEqual(["all"]);
    const byBase = await api.stats({
      ...all,
      sections: ["loras", "stacks"],
      lora_key: "base_name",
    });
    expect(byBase.groups[0]!.numeric).toBeNull();
  });

  it("timeline in every bucket, with a selection", async () => {
    const { ids } = await api.ids({ filters: emptyFilters(), sort: defaultSort() });
    for (const bucket of ["day", "week", "month"] as const) {
      const t = await api.timeline({ ...all, selection: ids.slice(0, 5), bucket });
      expectKeys(t, ["bucket", "buckets", "series", "suspect", "selected", "date_min", "date_max"]);
      expect(t.selected?.length).toBe(t.buckets.length);
      for (const counts of Object.values(t.series)) expect(counts.length).toBe(t.buckets.length);
    }
  });

  it("prompts on both sides", async () => {
    for (const side of ["positive", "negative"] as const) {
      for (const by of ["image", "unique_prompt"] as const) {
        let p;
        try {
          p = await api.prompts({ ...all, side, include_template: by === "image", by });
        } catch (e) {
          // Acceptable only while prompt frames build; assertion diffs must not be caught.
          expect(e instanceof ApiError && e.warming).toBe(true);
          continue;
        }
        expectKeys(p, ["scope", "side", "groups"]);
        const g = p.groups[0]!;
        expectKeys(g, [
          "family",
          "images",
          "distinct_total",
          "all_template",
          "templates",
          "phrases",
          "unigrams",
          "bigrams",
          "trigrams",
          "distinct",
        ]);
        if (g.unigrams[0]) expectKeys(g.unigrams[0], ["term", "df", "share"]);
        if (g.distinct[0]) {
          expectKeys(g.distinct[0], [
            "key",
            "text",
            "count",
            "share",
            "first",
            "last",
            "examples",
            "example_hashes",
          ]);
        }
      }
    }
  });

  it("distinctive terms for a selection, on both sides", async () => {
    const ids = (await api.ids({ filters: emptyFilters(), sort: defaultSort() })).ids;
    const selection = ids.filter((_, i) => i % 7 === 0).slice(0, 300);
    for (const side of ["positive", "negative"] as const) {
      for (const by of ["image", "unique_prompt"] as const) {
        let d;
        try {
          d = await api.distinctive({ ...all, selection, side, by });
        } catch (e) {
          // Acceptable only while prompt frames build; assertion diffs must not be caught.
          expect(e instanceof ApiError && e.warming).toBe(true);
          continue;
        }
        expectKeys(d, ["scope", "side", "groups"]);
        expect(d.scope.scope_kind).toBe("selection");
        const g = d.groups[0]!;
        expectKeys(g, [
          "family",
          "selection_images",
          "rest_images",
          "phrases",
          "unigrams",
          "bigrams",
          "trigrams",
        ]);
        expectKeys(g.unigrams, ["selection", "rest"]);
        const term = g.unigrams.selection[0] ?? g.unigrams.rest[0];
        if (term) {
          expectKeys(term, [
            "term",
            "z",
            "selection_df",
            "selection_share",
            "rest_df",
            "rest_share",
          ]);
        }
        const zs = g.unigrams.selection.map((t) => t.z);
        expect(zs).toEqual([...zs].sort((x, y) => y - x));
      }
    }
    await expect(api.distinctive({ ...all, side: "positive", by: "image" })).rejects.toMatchObject({
      status: 400,
      code: "selection_required",
    });
  });

  it("node input keys and statistics", async () => {
    const keys = await api.nodeKeys(all);
    expectKeys(keys, ["scope", "keys"]);
    expectKeys(keys.keys[0], ["class_type", "input_name", "kind", "files"]);
    for (const kind of ["num", "str", "bool"] as const) {
      const key = keys.keys.find((k) => k.kind === kind);
      if (!key) continue;
      const stats = await api.nodeStats({
        ...all,
        class_type: key.class_type,
        input_name: key.input_name,
      });
      expectKeys(stats, ["scope", "class_type", "input_name", "groups"]);
      expectKeys(stats.groups[0], [
        "family",
        "files",
        "kind",
        "numeric",
        "categorical",
        "n_unique",
      ]);
    }
  });

  it("errors use the error envelope", async () => {
    await expect(api.image(999_999_999)).rejects.toMatchObject({ status: 404 });
    const bad = await realFetch(`${base}/api/stats`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selection: "nope" }),
    });
    expect(bad.status).toBe(400);
    expectKeys(await bad.json(), ["error"]);
  });
});
