import { useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { FacetValue, Facets, Filters, NumericFilterField, Range } from "../api/types";
import { useSavedPrompt } from "../lib/collection";
import { fmtInt, fmtNum, fractionOf } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import {
  NUMERIC_STEPS,
  RANGE_SLIDER_FIELDS,
  hasActiveFilters,
  useFilters,
  type ListField,
} from "../state/filters";
import { ChainText, Glyph } from "./icons";
import {
  Button,
  ClearButton,
  ErrorState,
  FIELD,
  FamilyDot,
  Reveal,
  SectionTitle,
  Segmented,
  ShowAllToggle,
} from "./ui";

const SHOWN = 8;

function FacetList({
  title,
  values,
  selected,
  onToggle,
  colored = false,
}: {
  title: string;
  values: FacetValue[];
  selected: string[];
  onToggle: (value: string) => void;
  colored?: boolean;
}) {
  const [all, setAll] = useState(false);
  const [search, setSearch] = useState("");
  const matching = values.filter((v) => v.value.toLowerCase().includes(search.toLowerCase()));
  // Selected values stay visible even when they fall outside the top entries.
  const shown =
    all || search ? matching : matching.filter((v, i) => i < SHOWN || selected.includes(v.value));
  if (values.length === 0) return null;
  return (
    <Section>
      <SectionTitle>{title}</SectionTitle>
      {values.length > 12 && (
        <input
          autoComplete="off"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search"
          className={`mb-1 w-full px-1.5 py-0.5 text-xs ${FIELD}`}
        />
      )}
      <ul>
        {shown.map((v) => (
          <li key={v.value}>
            <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 transition-colors duration-(--dur-fast) hover:bg-hover">
              <input
                type="checkbox"
                checked={selected.includes(v.value)}
                onChange={() => onToggle(v.value)}
              />
              {colored && <FamilyDot family={v.value} />}
              <span className="min-w-0 flex-1 truncate" title={v.value}>
                {colored ? <ChainText text={v.value} kind="pipeline" /> : v.value}
              </span>
              <span className="text-xs text-muted tabular-nums">{fmtInt(v.count)}</span>
            </label>
          </li>
        ))}
      </ul>
      {!search && matching.length > SHOWN && (
        <ShowAllToggle count={matching.length} all={all} onToggle={() => setAll(!all)} />
      )}
    </Section>
  );
}

function Section({ children }: { children: ReactNode }) {
  return <div className="border-b border-line px-3 py-2">{children}</div>;
}

/** Range sliders for a field whose values span more than one number. */
function RangeFilter({ field, range }: { field: NumericFilterField; range: Range }) {
  if (range.min === null || range.max === null || range.min === range.max) return null;
  return <RangeSlider field={field} min={range.min} max={range.max} />;
}

type Span = [number, number];

/** A comparable key for an optional range. */
const spanKey = (span: Span | undefined) => span?.join(",") ?? "";

/** The span with one end moved to `to`, never past the other end. */
const moveEnd = ([lo, hi]: Span, end: 0 | 1, to: number): Span =>
  end === 0 ? [Math.min(to, hi), hi] : [lo, Math.max(to, lo)];

/** The numeric filters with `field` set to `span`, or without it when `span` is undefined. */
function withSpan(numeric: Filters["numeric"], field: NumericFilterField, span: Span | undefined) {
  const rest = Object.fromEntries(Object.entries(numeric).filter(([k]) => k !== field));
  return span ? { ...rest, [field]: span } : rest;
}

/** Two overlaid range inputs; the filter is dropped when the range covers everything. */
function RangeSlider({ field, min, max }: { field: NumericFilterField; min: number; max: number }) {
  const current = useFilters((s) => s.filters.numeric[field]);
  const update = useFilters((s) => s.update);
  const external: Span = current ?? [min, max];
  const [value, setValue] = useState<Span>(external);
  const [seen, setSeen] = useState(external);
  if (spanKey(seen) !== spanKey(external)) {
    // Cleared or changed elsewhere (Clear filters, the URL): follow the store.
    setSeen(external);
    setValue(external);
  }
  const committed = useDebounced(value, 300);

  useEffect(() => {
    const next = committed[0] <= min && committed[1] >= max ? undefined : committed;
    if (spanKey(next) === spanKey(current)) return;
    update((f) => ({ ...f, numeric: withSpan(f.numeric, field, next) }));
    // Commit only when the debounced value changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committed]);

  const narrowed = value[0] > min || value[1] < max;
  // The lower thumb goes on top once past the middle, so two thumbs pushed to the top end can
  // still be pulled apart.
  const lowOnTop = value[0] > (min + max) / 2;
  return (
    <div className="mb-1.5">
      <div className="flex items-center gap-1 text-xs">
        <span className="flex-1">{field}</span>
        <span className={`tabular-nums ${narrowed ? "text-accent-text" : "text-muted"}`}>
          {fmtNum(value[0])} – {fmtNum(value[1])}
        </span>
        {/* Always there, hidden when unused: the numbers never shift when it appears. */}
        <span className={narrowed ? "" : "invisible"}>
          <ClearButton label={`Clear the ${field} filter`} onClick={() => setValue([min, max])} />
        </span>
      </div>
      <div className="relative h-4">
        <div className="absolute inset-x-0 top-1.5 h-1 rounded bg-track" />
        {/* The chosen span; thumb centres travel 6px in from each end (see index.css). */}
        <div
          className="absolute top-1.5 h-1 rounded bg-accent"
          style={{
            left: `calc(6px + (100% - 12px) * ${fractionOf(value[0], min, max)})`,
            right: `calc(6px + (100% - 12px) * ${1 - fractionOf(value[1], min, max)})`,
          }}
        />
        {([0, 1] as const).map((end) => (
          <input
            key={end}
            type="range"
            className={`dual absolute inset-0 w-full ${end === 0 && lowOnTop ? "z-10" : ""}`}
            min={min}
            max={max}
            step={NUMERIC_STEPS[field]}
            value={value[end]}
            aria-label={`${field} ${end === 0 ? "minimum" : "maximum"}`}
            onChange={(e) => setValue(moveEnd(value, end, Number(e.target.value)))}
          />
        ))}
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
    <Section>
      <div className="relative">
        <Glyph
          name="search"
          className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted"
        />
        <input
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Search prompts"
          className={`w-full py-1 pr-6 pl-7 ${FIELD}`}
        />
        {value && (
          <span className="absolute top-1/2 right-1.5 flex -translate-y-1/2">
            <ClearButton label="Clear the search" onClick={() => setValue("")} />
          </span>
        )}
      </div>
    </Section>
  );
}

/** The similar-sentence cluster filter, set in the Prompts tab and cleared here. */
function SentenceFilter() {
  const sentences = useFilters((s) => s.filters.sentences);
  const update = useFilters((s) => s.update);
  return (
    <Reveal open={sentences.length > 0}>
      <Section>
        <SectionTitle
          right={<Button onClick={() => update((f) => ({ ...f, sentences: [] }))}>Clear</Button>}
        >
          Similar sentences
        </SectionTitle>
        <div className="text-xs text-muted">
          {fmtInt(sentences.length)} similar {sentences.length === 1 ? "sentence" : "sentences"}
        </div>
      </Section>
    </Reveal>
  );
}

/** Saved or not, and the one saved prompt "Show in library" filters to. */
function CollectionFilter() {
  const saved = useFilters((s) => s.filters.saved);
  const promptId = useFilters((s) => s.filters.saved_prompt);
  const update = useFilters((s) => s.update);
  const prompt = useSavedPrompt(promptId);
  return (
    <Section>
      <SectionTitle>Collection</SectionTitle>
      <YesNoAny
        value={saved}
        labels={["Any", "Saved", "Not saved"]}
        onChange={(value) => update((x) => ({ ...x, saved: value }))}
      />
      <Reveal open={promptId !== null}>
        <div className="mt-2 flex items-center gap-1.5 rounded bg-accent/10 px-2 py-1 text-xs">
          <Glyph name="bookmark" className="size-3 shrink-0 text-link" />
          <span
            className="min-w-0 flex-1 truncate"
            title="Linked to this saved prompt, or the same prompt text"
          >
            {prompt.data?.title ?? (prompt.isError ? "a deleted saved prompt" : "…")}
          </span>
          <ClearButton
            label="Clear the saved prompt filter"
            onClick={() => update((x) => ({ ...x, saved_prompt: null }))}
          />
        </div>
      </Reveal>
    </Section>
  );
}

const YES_NO_ANY = { any: null, yes: true, no: false } as const;
type YesNoAnyKey = keyof typeof YES_NO_ANY;

/** A segmented any / yes / no control for an optional boolean filter. */
function YesNoAny({
  value,
  labels: [any, yes, no],
  onChange,
}: {
  value: boolean | null;
  labels: [string, string, string];
  onChange: (value: boolean | null) => void;
}) {
  const key: YesNoAnyKey = value === null ? "any" : value ? "yes" : "no";
  return (
    <Segmented<YesNoAnyKey>
      value={key}
      options={[
        { value: "any", label: any },
        { value: "yes", label: yes },
        { value: "no", label: no },
      ]}
      onChange={(v) => onChange(YES_NO_ANY[v])}
    />
  );
}

const DATE_ENDS = ["date_from", "date_to"] as const;

function DateFilter({ range }: { range: Facets["date_range"] }) {
  const filters = useFilters((s) => s.filters);
  const update = useFilters((s) => s.update);
  return (
    <Section>
      <SectionTitle>Date</SectionTitle>
      <div className="flex items-center gap-1">
        {DATE_ENDS.map((end, i) => (
          <Fragment key={end}>
            {i > 0 && <span>–</span>}
            <input
              autoComplete="off"
              type="date"
              className={`w-full min-w-0 px-1 ${FIELD}`}
              value={filters[end] ?? ""}
              min={range.min ?? undefined}
              max={range.max ?? undefined}
              onChange={(e) => update((x) => ({ ...x, [end]: e.target.value || null }))}
            />
          </Fragment>
        ))}
      </div>
    </Section>
  );
}

/** The facet lists, in sidebar order; the LoRA list goes after the first LORA_AFTER. */
const LISTS: [string, ListField][] = [
  ["Tags", "tags"],
  ["Family", "families"],
  ["Base model", "base_models"],
  ["Sampler", "samplers"],
  ["Scheduler", "schedulers"],
];
const LORA_AFTER = 3;

/** Every filter whose options come from the library's facets. */
function FacetFilters({ facets }: { facets: Facets }) {
  const filters = useFilters((s) => s.filters);
  const toggle = useFilters((s) => s.toggle);
  const toggleLora = useFilters((s) => s.toggleLora);
  const lists = LISTS.map(([title, field]) => (
    <FacetList
      key={field}
      title={title}
      values={facets[field]}
      selected={filters[field]}
      onToggle={(v) => toggle(field, v)}
      colored={field === "families"}
    />
  ));
  return (
    <>
      {lists.slice(0, LORA_AFTER)}
      <FacetList
        title="LoRA"
        values={facets.loras}
        selected={filters.loras.names}
        onToggle={toggleLora}
      />
      {lists.slice(LORA_AFTER)}
      <DateFilter range={facets.date_range} />
      <Section>
        <SectionTitle>Settings</SectionTitle>
        {RANGE_SLIDER_FIELDS.map((field) => {
          const range = facets.numeric_ranges[field];
          return range && <RangeFilter key={field} field={field} range={range} />;
        })}
      </Section>
    </>
  );
}

/** Stand-ins for the facet lists while they load, so the sections below don't jump down. */
function FacetSkeleton() {
  return (
    <div aria-hidden="true" className="animate-pulse">
      {[5, 4, 6].map((rows, i) => (
        <Section key={i}>
          <div className="mb-2 h-3 w-16 rounded bg-subtle" />
          {Array.from({ length: rows }, (_, j) => (
            <div key={j} className="my-1.5 flex items-center gap-2 px-1">
              <div className="size-3.5 rounded bg-subtle" />
              <div className="h-3 flex-1 rounded bg-subtle" />
            </div>
          ))}
        </Section>
      ))}
    </div>
  );
}

export default function FilterSidebar() {
  const facets = useQuery({ queryKey: ["facets"], queryFn: api.facets });
  const filters = useFilters((s) => s.filters);
  const clear = useFilters((s) => s.clear);
  return (
    <aside className="flex w-[280px] shrink-0 flex-col overflow-y-auto border-r border-line">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="font-semibold">Filters</span>
        <Button onClick={clear} disabled={!hasActiveFilters(filters)}>
          Clear filters
        </Button>
      </div>
      <TextSearch />
      {facets.isError && <ErrorState error={facets.error} className="px-3 py-2" />}
      {facets.data ? (
        <div className="motion-safe:animate-fade-in">
          <FacetFilters facets={facets.data} />
        </div>
      ) : (
        !facets.isError && <FacetSkeleton />
      )}
      <CollectionFilter />
      <SentenceFilter />
    </aside>
  );
}
