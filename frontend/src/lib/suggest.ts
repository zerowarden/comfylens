import type { FacetValue } from "../api/types";

/** A suggestion with its lowercased value, computed once per list rather than per keystroke. */
export interface Indexed extends FacetValue {
  lower: string;
}

export const indexSuggestions = (values: readonly FacetValue[] = []): Indexed[] =>
  values.map((v) => ({ ...v, lower: v.value.toLowerCase() }));

/**
 * Up to `limit` values containing `query`, ignoring case: those starting with it first, each part
 * in the list's own order (most used first). `exclude` leaves out values already chosen.
 */
export function suggest(
  index: readonly Indexed[],
  query: string,
  exclude: ReadonlySet<string>,
  limit: number,
): Indexed[] {
  const q = query.trim().toLowerCase();
  const matches = index.filter((v) => !exclude.has(v.value) && v.lower.includes(q));
  const prefixed = matches.filter((v) => v.lower.startsWith(q));
  return [...prefixed, ...matches.filter((v) => !v.lower.startsWith(q))].slice(0, limit);
}

/** `text` split around the first case-insensitive occurrence of `query`, for highlighting. */
export function splitMatch(text: string, query: string): [string, string, string] {
  const q = query.trim();
  const at = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (at < 0) return [text, "", ""];
  return [text.slice(0, at), text.slice(at, at + q.length), text.slice(at + q.length)];
}
