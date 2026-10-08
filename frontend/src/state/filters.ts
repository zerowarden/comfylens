import { create } from "zustand";

import type { Filters, NumericFilterField, Sort, SortKey, Status } from "../api/types";

export type ListField =
  "tags" | "families" | "base_models" | "samplers" | "schedulers" | "statuses";

const NUMERIC_FIELDS: NumericFilterField[] = ["steps", "cfg", "denoise", "guidance", "shift"];

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
  tags: [],
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
  saved: null,
  saved_prompt: null,
  sentences: [],
});

export const defaultSort = (): Sort => ({ key: "generated_at", descending: true });

// URL query string: repeated keys for lists, defaults omitted so a clean view has a clean URL.
// Every filter is one entry of PARAMS, which both writes and reads it.

type Entry = [string, string];

interface Param {
  /** The query-string entries for these filters; none when the filter is off. */
  write: (f: Filters) => Entry[];
  read: (p: URLSearchParams) => Partial<Filters>;
  /** Only qualifies another filter (the LoRA match mode): never filters the view by itself. */
  modifier?: true;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const PROMPT_ID = /^[1-9]\d{0,15}$/;
const SENTENCE = /^[0-9a-f]{16}$/;
const YES_NO = new Map([
  ["yes", true],
  ["no", false],
]);

const entries = (name: string, values: readonly string[]): Entry[] => values.map((v) => [name, v]);
/** One entry for a set value, none for null. */
const optional = (name: string, value: string | null): Entry[] =>
  value === null ? [] : [[name, value]];
const yesNo = (value: boolean | null) => (value === null ? null : value ? "yes" : "no");
/** `value` when it matches `pattern`, else null. */
const matching = (value: string | null, pattern: RegExp) =>
  value !== null && pattern.test(value) ? value : null;

/** "lo,hi" as a range: two finite numbers, lo first; null for anything else. */
function parseRange(raw: string | null): [number, number] | null {
  if (!raw) return null;
  const [lo, hi] = raw.split(",").map(Number);
  return Number.isFinite(lo) && Number.isFinite(hi) && lo! <= hi! ? [lo!, hi!] : null;
}

/** A repeated-key list filter; `valid` drops values the field cannot hold. */
const list = (field: ListField, name: string, valid: (v: string) => boolean = () => true) => ({
  write: (f: Filters) => entries(name, f[field]),
  read: (p: URLSearchParams) => ({ [field]: p.getAll(name).filter(valid) }),
});

const PARAMS: Param[] = [
  list("tags", "tag"),
  list("families", "family"),
  list("base_models", "base_model"),
  list("samplers", "sampler"),
  list("schedulers", "scheduler"),
  list("statuses", "status", (v) => (STATUSES as string[]).includes(v)),
  {
    write: (f) => entries("lora", f.loras.names),
    read: (p) => ({
      loras: { names: p.getAll("lora"), mode: p.get("lora_mode") === "all" ? "all" : "any" },
    }),
  },
  {
    modifier: true,
    write: (f) => optional("lora_mode", f.loras.mode === "all" ? "all" : null),
    read: () => ({}),
  },
  {
    write: (f) => optional("from", f.date_from),
    read: (p) => ({ date_from: matching(p.get("from"), DATE) }),
  },
  {
    write: (f) => optional("to", f.date_to),
    read: (p) => ({ date_to: matching(p.get("to"), DATE) }),
  },
  {
    write: (f) => optional("q", f.text.trim() ? f.text : null),
    read: (p) => ({ text: p.get("q") ?? "" }),
  },
  {
    write: (f) =>
      NUMERIC_FIELDS.flatMap((field) => {
        const range = f.numeric[field];
        return optional(field, range ? `${range[0]},${range[1]}` : null);
      }),
    read: (p) => ({
      numeric: Object.fromEntries(
        NUMERIC_FIELDS.map((field) => [field, parseRange(p.get(field))]).filter(([, r]) => r),
      ),
    }),
  },
  {
    write: (f) => optional("saved", yesNo(f.saved)),
    read: (p) => ({ saved: YES_NO.get(p.get("saved") ?? "") ?? null }),
  },
  {
    write: (f) => optional("prompt", f.saved_prompt === null ? null : String(f.saved_prompt)),
    read: (p) => {
      const id = matching(p.get("prompt"), PROMPT_ID);
      return { saved_prompt: id === null ? null : Number(id) };
    },
  },
  {
    write: (f) => entries("sentence", f.sentences),
    read: (p) => ({ sentences: p.getAll("sentence").filter((s) => SENTENCE.test(s)) }),
  },
];

export function hasActiveFilters(f: Filters): boolean {
  return PARAMS.some((param) => !param.modifier && param.write(f).length > 0);
}

export function toSearch(filters: Filters, sort: Sort): string {
  const d = defaultSort();
  return new URLSearchParams([
    ...PARAMS.flatMap((param) => param.write(filters)),
    ...optional("sort", sort.key === d.key ? null : sort.key),
    ...optional(
      "order",
      sort.descending === d.descending ? null : sort.descending ? "desc" : "asc",
    ),
  ]).toString();
}

export function fromSearch(search: string): { filters: Filters; sort: Sort } {
  const p = new URLSearchParams(search);
  const key = p.get("sort");
  return {
    filters: PARAMS.reduce((f, param) => ({ ...f, ...param.read(p) }), emptyFilters()),
    sort: {
      key: SORT_KEYS.find((k) => k === key) ?? defaultSort().key,
      descending: p.get("order") !== "asc",
    },
  };
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
