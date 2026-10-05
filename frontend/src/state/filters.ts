import { create } from "zustand";

import type { Filters, NumericFilterField, Sort, SortKey, Status } from "../api/types";

export type ListField = "families" | "base_models" | "samplers" | "schedulers" | "statuses";

export const NUMERIC_FIELDS: NumericFilterField[] = [
  "steps",
  "cfg",
  "denoise",
  "guidance",
  "shift",
];

/** One range step per numeric field. */
export const NUMERIC_STEPS: Record<NumericFilterField, number> = {
  steps: 1,
  cfg: 0.1,
  denoise: 0.01,
  guidance: 0.1,
  shift: 0.05,
};

/** The numeric fields that get range sliders; the others only appear in the query string. */
export const RANGE_SLIDER_FIELDS: NumericFilterField[] = ["cfg", "steps", "denoise"];
export const SORT_KEYS: SortKey[] = ["generated_at", "rel_path", "family", "steps", "cfg"];
const STATUSES: Status[] = ["ok", "partial", "no_metadata", "error"];

export const emptyFilters = (): Filters => ({
  families: [],
  base_models: [],
  samplers: [],
  schedulers: [],
  loras: { names: [], mode: "any" },
  date_from: null,
  date_to: null,
  statuses: [],
  text: "",
  numeric: {},
  has_warnings: null,
  saved: null,
  saved_prompt: null,
  sentences: [],
});

export const defaultSort = (): Sort => ({ key: "generated_at", descending: true });

export function hasActiveFilters(f: Filters): boolean {
  return (
    f.families.length > 0 ||
    f.base_models.length > 0 ||
    f.samplers.length > 0 ||
    f.schedulers.length > 0 ||
    f.loras.names.length > 0 ||
    f.date_from !== null ||
    f.date_to !== null ||
    f.statuses.length > 0 ||
    f.text.trim() !== "" ||
    Object.keys(f.numeric).length > 0 ||
    f.has_warnings !== null ||
    f.saved !== null ||
    f.saved_prompt !== null ||
    f.sentences.length > 0
  );
}

// URL query string: repeated keys for lists, defaults omitted so a clean view has a clean URL.

const LIST_PARAMS: [ListField, string][] = [
  ["families", "family"],
  ["base_models", "base_model"],
  ["samplers", "sampler"],
  ["schedulers", "scheduler"],
  ["statuses", "status"],
];
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function toSearch(filters: Filters, sort: Sort): string {
  const p = new URLSearchParams();
  for (const [field, name] of LIST_PARAMS) for (const v of filters[field]) p.append(name, v);
  for (const v of filters.loras.names) p.append("lora", v);
  if (filters.loras.mode === "all") p.set("lora_mode", "all");
  if (filters.date_from) p.set("from", filters.date_from);
  if (filters.date_to) p.set("to", filters.date_to);
  if (filters.text.trim()) p.set("q", filters.text);
  for (const field of NUMERIC_FIELDS) {
    const range = filters.numeric[field];
    if (range) p.set(field, `${range[0]},${range[1]}`);
  }
  if (filters.has_warnings !== null) p.set("warnings", filters.has_warnings ? "yes" : "no");
  if (filters.saved !== null) p.set("saved", filters.saved ? "yes" : "no");
  if (filters.saved_prompt !== null) p.set("prompt", String(filters.saved_prompt));
  for (const sentence of filters.sentences) p.append("sentence", sentence);
  const d = defaultSort();
  if (sort.key !== d.key) p.set("sort", sort.key);
  if (sort.descending !== d.descending) p.set("order", sort.descending ? "desc" : "asc");
  return p.toString();
}

export function fromSearch(search: string): { filters: Filters; sort: Sort } {
  const p = new URLSearchParams(search);
  const filters = emptyFilters();
  for (const [field, name] of LIST_PARAMS) {
    const values = p.getAll(name);
    if (field === "statuses") {
      filters.statuses = values.filter((v): v is Status => (STATUSES as string[]).includes(v));
    } else {
      filters[field] = values;
    }
  }
  filters.loras = { names: p.getAll("lora"), mode: p.get("lora_mode") === "all" ? "all" : "any" };
  const from = p.get("from");
  const to = p.get("to");
  filters.date_from = from && DATE.test(from) ? from : null;
  filters.date_to = to && DATE.test(to) ? to : null;
  filters.text = p.get("q") ?? "";
  for (const field of NUMERIC_FIELDS) {
    const raw = p.get(field);
    if (!raw) continue;
    const [lo, hi] = raw.split(",").map(Number);
    if (
      lo !== undefined &&
      hi !== undefined &&
      Number.isFinite(lo) &&
      Number.isFinite(hi) &&
      lo <= hi
    ) {
      filters.numeric[field] = [lo, hi];
    }
  }
  const warnings = p.get("warnings");
  filters.has_warnings = warnings === "yes" ? true : warnings === "no" ? false : null;
  const saved = p.get("saved");
  filters.saved = saved === "yes" ? true : saved === "no" ? false : null;
  const prompt = p.get("prompt");
  filters.saved_prompt = prompt && /^[1-9]\d{0,15}$/.test(prompt) ? Number(prompt) : null;
  filters.sentences = p.getAll("sentence").filter((s) => /^[0-9a-f]{16}$/.test(s));

  const sort = defaultSort();
  const key = p.get("sort");
  if (key && (SORT_KEYS as string[]).includes(key)) sort.key = key as SortKey;
  const order = p.get("order");
  if (order === "asc") sort.descending = false;
  return { filters, sort };
}

interface FilterStore {
  filters: Filters;
  sort: Sort;
  update: (change: (f: Filters) => Filters) => void;
  toggle: (field: ListField, value: string) => void;
  /** Click-to-filter: include the value without toggling it off. */
  include: (field: ListField, value: string) => void;
  toggleLora: (name: string) => void;
  includeLora: (name: string) => void;
  setSort: (sort: Sort) => void;
  clear: () => void;
}

const toggled = (values: string[], value: string) =>
  values.includes(value) ? values.filter((v) => v !== value) : [...values, value];

/** `values` with `value` added once; the same array when it is already there. */
const included = (values: string[], value: string) =>
  values.includes(value) ? values : [...values, value];

const initial = typeof window === "undefined" ? null : fromSearch(window.location.search);

export const useFilters = create<FilterStore>((set) => ({
  filters: initial?.filters ?? emptyFilters(),
  sort: initial?.sort ?? defaultSort(),
  update: (change) => set((s) => ({ filters: change(s.filters) })),
  // Statuses are typed narrower than the other lists; values come from facets or the API.
  toggle: (field, value) =>
    set((s) => ({
      filters: { ...s.filters, [field]: toggled(s.filters[field] as string[], value) },
    })),
  include: (field, value) =>
    set((s) => {
      const values = s.filters[field] as string[];
      const next = included(values, value);
      return next === values ? s : { filters: { ...s.filters, [field]: next } };
    }),
  toggleLora: (name) =>
    set((s) => ({
      filters: {
        ...s.filters,
        loras: { ...s.filters.loras, names: toggled(s.filters.loras.names, name) },
      },
    })),
  includeLora: (name) =>
    set((s) => {
      const names = s.filters.loras.names;
      const next = included(names, name);
      return next === names
        ? s
        : { filters: { ...s.filters, loras: { ...s.filters.loras, names: next } } };
    }),
  setSort: (sort) => set({ sort }),
  clear: () => set({ filters: emptyFilters() }),
}));
