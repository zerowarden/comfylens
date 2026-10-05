import type { ScopeInfo } from "../api/types";

const integer = new Intl.NumberFormat("en-US");

export const fmtInt = (n: number) => integer.format(n);

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

const plural = (n: number, word: string) => `${fmtInt(n)} ${word}${n === 1 ? "" : "s"}`;

/**
 * The analysis header in two parts: `main` ("Analyzing 37 selected images") and `notes` on files
 * without metadata and duplicates ("" when there are none).
 */
export function scopeParts(scope: ScopeInfo): { main: string; notes: string } {
  const n = scope.scope_size;
  const main =
    scope.scope_kind === "selection"
      ? `Analyzing ${fmtInt(n)} selected image${n === 1 ? "" : "s"}`
      : scope.scope_kind === "all"
        ? `Analyzing all ${plural(n, "image")}`
        : `Analyzing ${fmtInt(n)} filtered image${n === 1 ? "" : "s"}`;
  const notes: string[] = [];
  if (scope.excluded_no_metadata > 0)
    notes.push(`${fmtInt(scope.excluded_no_metadata)} without metadata`);
  if (scope.duplicates_removed > 0)
    notes.push(`${plural(scope.duplicates_removed, "duplicate")} counted once`);
  return { main, notes: notes.join(", ") };
}

/** The header as one sentence: "Analyzing 37 selected images (2 without metadata)". */
export function scopeSentence(scope: ScopeInfo): string {
  const { main, notes } = scopeParts(scope);
  return notes ? `${main} (${notes})` : main;
}

/** What a pending query shows: its error, or that it is still loading. */
export function loadingText(error: Error | null): string {
  return error ? error.message : "Loading…";
}
