import type { ScopeInfo } from "../api/types";

const integer = new Intl.NumberFormat("en-US");

export const fmtInt = (n: number) => integer.format(n);

/** What a missing value shows as, everywhere. */
export const MISSING = "—";

/** `v` as text, or `missing` for null, undefined and the empty string. */
export function text(v: string | number | null | undefined, missing = MISSING): string {
  return v === null || v === undefined || v === "" ? missing : String(v);
}

/** Up to 4 decimals, trailing zeros trimmed: 2 -> "2", 1.4623 -> "1.4623". */
export function fmtNum(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return String(Math.round(x * 10_000) / 10_000);
}

export function fmtPct(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return `${(x * 100).toFixed(1)}%`;
}

export function fmtDateTime(unix: number | null | undefined): string {
  if (unix === null || unix === undefined) return "—";
  const d = new Date(unix * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export const plural = (n: number, word: string) => `${fmtInt(n)} ${word}${n === 1 ? "" : "s"}`;

const SCOPE_IMAGES: Record<ScopeInfo["scope_kind"], (n: number) => string> = {
  selection: (n) => plural(n, "selected image"),
  filtered: (n) => plural(n, "filtered image"),
  all: (n) => `all ${plural(n, "image")}`,
};

/**
 * The analysis header in two parts: `main` ("Analyzing 37 selected images") and `notes` on files
 * without metadata and duplicates ("" when there are none).
 */
export function scopeParts(scope: ScopeInfo): { main: string; notes: string } {
  const notes = [
    scope.excluded_no_metadata > 0 && `${fmtInt(scope.excluded_no_metadata)} without metadata`,
    scope.duplicates_removed > 0 && `${plural(scope.duplicates_removed, "duplicate")} counted once`,
  ];
  return {
    main: `Analyzing ${SCOPE_IMAGES[scope.scope_kind](scope.scope_size)}`,
    notes: notes.filter(Boolean).join(", "),
  };
}

/** The header as one sentence: "Analyzing 37 selected images (2 without metadata)". */
export function scopeSentence(scope: ScopeInfo): string {
  const { main, notes } = scopeParts(scope);
  return notes ? `${main} (${notes})` : main;
}

/**
 * Whether the analysis covers exactly one selected image. Statistics say nothing there: every
 * share is 1 and every count is 1, so the panel shows only the image's values.
 */
export function isSingleSelection(scope: ScopeInfo): boolean {
  return scope.scope_kind === "selection" && scope.scope_size === 1;
}

/** What a pending query shows: its error, or that it is still loading. */
export function loadingText(error: Error | null): string {
  return error ? error.message : "Loading…";
}

/** A caught value's message for a notice, whatever it turned out to be. */
export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** How far `value` sits between `min` and `max`, from 0 to 1; 0 when they are equal. */
export const fractionOf = (value: number, min: number, max: number) =>
  max > min ? (value - min) / (max - min) : 0;
