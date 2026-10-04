import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { FacetValue, NumericFilterField, Range } from "../api/types";
import { familyColor } from "../lib/colors";
import { fmtInt, fmtNum } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import { hasActiveFilters, useFilters, type ListField } from "../state/filters";
import { ChainText, Glyph } from "./icons";
import { Button, Segmented } from "./ui";

const SHOWN = 8;

function FacetList({
  title,
  values,
  selected,
  onToggle,
  colored = false,
  extra,
}: {
  title: string;
  values: FacetValue[];
  selected: string[];
  onToggle: (value: string) => void;
  colored?: boolean;
  extra?: ReactNode;
}) {
  const [all, setAll] = useState(false);
  const [search, setSearch] = useState("");
  const matching = values.filter((v) => v.value.toLowerCase().includes(search.toLowerCase()));
  // Selected values stay visible even when they fall outside the top entries.
  const shown =
    all || search ? matching : matching.filter((v, i) => i < SHOWN || selected.includes(v.value));
  if (values.length === 0) return null;
  return (
    <div className="border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">{title}</span>
        {extra}
      </div>
      {values.length > 12 && (
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search"
          className="mb-1 w-full rounded border border-zinc-300 bg-transparent px-1.5 py-0.5 text-xs dark:border-zinc-700"
        />
      )}
      <ul>
        {shown.map((v) => (
          <li key={v.value}>
            <label className="flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-900">
              <input
                type="checkbox"
                checked={selected.includes(v.value)}
                onChange={() => onToggle(v.value)}
              />
              {colored && (
                <span
                  className="inline-block h-2 w-2 shrink-0 rounded-full"
                  style={{ background: familyColor(v.value) }}
                />
              )}
              <span className="min-w-0 flex-1 truncate" title={v.value}>
                {colored ? <ChainText text={v.value} kind="pipeline" /> : v.value}
              </span>
              <span className="text-xs text-zinc-500 tabular-nums">{fmtInt(v.count)}</span>
            </label>
          </li>
        ))}
      </ul>
      {!search && matching.length > SHOWN && (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="mt-0.5 text-xs text-sky-600 hover:underline dark:text-sky-400"
        >
          {all ? "Show fewer" : `Show all ${matching.length}`}
        </button>
      )}
    </div>
  );
}

const STEPS: Record<string, number> = {
  steps: 1,
  cfg: 0.1,
  denoise: 0.01,
  guidance: 0.1,
  shift: 0.05,
};

/** Two overlaid range inputs; the filter is dropped when the range covers everything. */
function RangeFilter({ field, range }: { field: NumericFilterField; range: Range }) {
  const current = useFilters((s) => s.filters.numeric[field]);
  const update = useFilters((s) => s.update);
  const min = range.min ?? 0;
  const max = range.max ?? 0;
  const external: [number, number] = current ?? [min, max];
  const [value, setValue] = useState<[number, number]>(external);
  const [seen, setSeen] = useState(external);
  if (seen[0] !== external[0] || seen[1] !== external[1]) {
    // Cleared or changed elsewhere (Clear filters, the URL): follow the store.
    setSeen(external);
    setValue(external);
  }
  const committed = useDebounced(value, 300);

  useEffect(() => {
    const full = committed[0] <= min && committed[1] >= max;
    const same = current && current[0] === committed[0] && current[1] === committed[1];
    if (same || (full && !current)) return;
    update((f) => {
      const numeric = { ...f.numeric };
      if (full) delete numeric[field];
      else numeric[field] = committed;
      return { ...f, numeric };
    });
    // Commit only when the debounced value changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committed]);

  if (range.min === null || range.max === null || range.min === range.max) return null;
  const step = STEPS[field] ?? 0.01;
  const input =
    "pointer-events-none absolute inset-0 w-full appearance-none bg-transparent [&::-webkit-slider-thumb]:pointer-events-auto [&::-moz-range-thumb]:pointer-events-auto";
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs">
        <span>{field}</span>
        <span className="text-zinc-500 tabular-nums">
          {fmtNum(value[0])} – {fmtNum(value[1])}
          {current && (
            <button
              type="button"
              title={`Clear the ${field} filter`}
              aria-label={`Clear the ${field} filter`}
              className="ml-1 align-[-0.125em] hover:text-red-500"
              onClick={() => setValue([min, max])}
            >
              <Glyph name="x" className="size-3" />
            </button>
          )}
        </span>
      </div>
      <div className="relative h-5">
        <div className="absolute top-2 h-1 w-full rounded bg-zinc-200 dark:bg-zinc-800" />
        <input
          type="range"
          className={input}
          min={min}
          max={max}
          step={step}
          value={value[0]}
          aria-label={`${field} minimum`}
          onChange={(e) => setValue([Math.min(Number(e.target.value), value[1]), value[1]])}
        />
        <input
          type="range"
          className={input}
          min={min}
          max={max}
          step={step}
          value={value[1]}
          aria-label={`${field} maximum`}
          onChange={(e) => setValue([value[0], Math.max(Number(e.target.value), value[0])])}
        />
      </div>
    </div>
  );
}

function TextSearch() {
  const text = useFilters((s) => s.filters.text);
  const update = useFilters((s) => s.update);
  const [value, setValue] = useState(text);
  const [seen, setSeen] = useState(text);
  if (seen !== text) {
    // Click-to-filter and Clear filters set the text from outside.
    setSeen(text);
    setValue(text);
  }
  const debounced = useDebounced(value, 300);
  useEffect(() => {
    if (debounced !== text) update((f) => ({ ...f, text: debounced }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);
  return (
    <div className="border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search prompts"
        className="w-full rounded border border-zinc-300 bg-transparent px-2 py-1 dark:border-zinc-700"
      />
    </div>
  );
}

export default function FilterSidebar() {
  const facets = useQuery({ queryKey: ["facets"], queryFn: api.facets });
  const filters = useFilters((s) => s.filters);
  const toggle = useFilters((s) => s.toggle);
  const toggleLora = useFilters((s) => s.toggleLora);
  const update = useFilters((s) => s.update);
  const clear = useFilters((s) => s.clear);
  const f = facets.data;

  const lists: [string, ListField, FacetValue[]][] = f
    ? [
        ["Family", "families", f.families],
        ["Base model", "base_models", f.base_models],
        ["Sampler", "samplers", f.samplers],
        ["Scheduler", "schedulers", f.schedulers],
        ["Status", "statuses", f.statuses],
      ]
    : [];

  return (
    <aside className="flex w-[280px] shrink-0 flex-col overflow-y-auto border-r border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="font-semibold">Filters</span>
        <Button onClick={clear} disabled={!hasActiveFilters(filters)}>
          Clear filters
        </Button>
      </div>
      <TextSearch />
      {facets.isError && <div className="px-3 py-2 text-red-600">{facets.error.message}</div>}
      {lists.slice(0, 2).map(([title, field, values]) => (
        <FacetList
          key={field}
          title={title}
          values={values}
          selected={filters[field]}
          onToggle={(v) => toggle(field, v)}
          colored={field === "families"}
        />
      ))}
      {f && (
        <FacetList
          title="LoRA"
          values={f.loras}
          selected={filters.loras.names}
          onToggle={toggleLora}
          extra={
            <Segmented
              value={filters.loras.mode}
              options={[
                { value: "any", label: "any" },
                { value: "all", label: "all" },
              ]}
              onChange={(mode) => update((x) => ({ ...x, loras: { ...x.loras, mode } }))}
            />
          }
        />
      )}
      {lists.slice(2).map(([title, field, values]) => (
        <FacetList
          key={field}
          title={title}
          values={values}
          selected={filters[field]}
          onToggle={(v) => toggle(field, v)}
        />
      ))}
      {f && (
        <div className="border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
          <div className="mb-1 text-xs font-semibold tracking-wide text-zinc-500 uppercase">
            Date
          </div>
          <div className="flex items-center gap-1">
            <input
              type="date"
              className="w-full rounded border border-zinc-300 bg-transparent px-1 dark:border-zinc-700"
              value={filters.date_from ?? ""}
              min={f.date_range.min ?? undefined}
              max={f.date_range.max ?? undefined}
              onChange={(e) => update((x) => ({ ...x, date_from: e.target.value || null }))}
            />
            <span>–</span>
            <input
              type="date"
              className="w-full rounded border border-zinc-300 bg-transparent px-1 dark:border-zinc-700"
              value={filters.date_to ?? ""}
              min={f.date_range.min ?? undefined}
              max={f.date_range.max ?? undefined}
              onChange={(e) => update((x) => ({ ...x, date_to: e.target.value || null }))}
            />
          </div>
        </div>
      )}
      {f && (
        <div className="border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
          <div className="mb-1 text-xs font-semibold tracking-wide text-zinc-500 uppercase">
            Settings
          </div>
          {(["cfg", "steps", "denoise"] as const).map((field) => {
            const range = f.numeric_ranges[field];
            return range ? <RangeFilter key={field} field={field} range={range} /> : null;
          })}
        </div>
      )}
      <div className="px-3 py-2">
        <div className="mb-1 text-xs font-semibold tracking-wide text-zinc-500 uppercase">
          Warnings
        </div>
        <Segmented
          value={filters.has_warnings === null ? "any" : filters.has_warnings ? "with" : "without"}
          options={[
            { value: "any", label: "Any" },
            { value: "with", label: "With warnings" },
            { value: "without", label: "Without" },
          ]}
          onChange={(v) =>
            update((x) => ({ ...x, has_warnings: v === "any" ? null : v === "with" }))
          }
        />
      </div>
    </aside>
  );
}
