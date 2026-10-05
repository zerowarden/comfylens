import type { TimelineResponse } from "../api/types";

const DAY_MS = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const parse = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
const format = (ms: number) => new Date(ms).toISOString().slice(0, 10);

export function addDays(iso: string, days: number): string {
  return format(parse(iso) + days * DAY_MS);
}

/** 0 = Monday … 6 = Sunday, matching the backend's Monday weeks. */
export function weekday(iso: string): number {
  return (new Date(parse(iso)).getUTCDay() + 6) % 7;
}

function daysBetween(a: string, b: string): number {
  return Math.round((parse(b) - parse(a)) / DAY_MS);
}

/** The first day of the month `months` after the one holding `iso`. */
function addMonths(iso: string, months: number): string {
  const index = Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1 + months;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}-01`;
}

/** Months a calendar spans at least, from the first month with data. */
export const MIN_MONTHS = 12;

/** The last day of the month holding `iso`. */
export function monthEnd(iso: string): string {
  return format(Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)), 0));
}

export interface Cell {
  date: string;
  col: number; // week
  row: number; // weekday
}

export interface Day extends Cell {
  total: number;
  suspect: number;
  selected: number;
  /** Non-zero counts per family, largest first. */
  families: [string, number][];
}

export interface Calendar {
  days: Day[];
  /** Dates outside the data that complete its first and last month, or the minimum span. */
  padding: Cell[];
  weeks: number;
  /** Weekday of the first cell: the empty slots before it in the first week. */
  offset: number;
  /** Padding cells before the first day. */
  lead: number;
  max: number;
  /** Upper bounds of colour steps 1-3: the quartiles of the non-empty days. */
  thresholds: [number, number, number];
}

/**
 * Lays out day buckets (contiguous, ascending) as a weeks by weekdays grid, padded to whole months
 * and to at least MIN_MONTHS months.
 */
export function buildCalendar(data: TimelineResponse): Calendar {
  const first = data.buckets[0];
  const last = data.buckets.at(-1);
  if (first === undefined || last === undefined)
    return { days: [], padding: [], weeks: 0, offset: 0, lead: 0, max: 0, thresholds: [0, 0, 0] };
  const start = `${first.slice(0, 8)}01`;
  const lead = daysBetween(start, first);
  const minEnd = monthEnd(addMonths(start, MIN_MONTHS - 1));
  const trail = daysBetween(last, last > minEnd ? monthEnd(last) : minEnd);
  const offset = weekday(start);
  const place = (k: number): Cell => ({
    date: addDays(start, k),
    col: Math.floor((k + offset) / 7),
    row: (k + offset) % 7,
  });
  const n = data.buckets.length;
  const padding = [
    ...Array.from({ length: lead }, (_, k) => place(k)),
    ...Array.from({ length: trail }, (_, j) => place(lead + n + j)),
  ];
  const series = Object.entries(data.series);
  let max = 0;
  const days = data.buckets.map((date, i): Day => {
    const families = series
      .map(([family, counts]): [string, number] => [family, counts[i] ?? 0])
      .filter(([, n]) => n > 0)
      .sort((a, b) => b[1] - a[1]);
    const total = families.reduce((sum, [, n]) => sum + n, 0);
    max = Math.max(max, total);
    const { col, row } = place(lead + i);
    return {
      date,
      col,
      row,
      total,
      suspect: data.suspect[i] ?? 0,
      selected: data.selected?.[i] ?? 0,
      families,
    };
  });
  return {
    days,
    padding,
    weeks: Math.ceil((lead + n + trail + offset) / 7),
    offset,
    lead,
    max,
    thresholds: quartiles(days.map((d) => d.total).filter((n) => n > 0)),
  };
}

function quartiles(values: number[]): [number, number, number] {
  const sorted = [...values].sort((a, b) => a - b);
  const at = (q: number) => sorted[Math.floor(q * (sorted.length - 1))] ?? 0;
  return [at(0.25), at(0.5), at(0.75)];
}

/** The day at a grid cell, or undefined on padding and empty slots. */
export function dayAt(calendar: Calendar, col: number, row: number): Day | undefined {
  return calendar.days[col * 7 + row - calendar.offset - calendar.lead];
}

/** The day at a grid cell, clamped to the calendar's first and last day. */
export function nearestDay(calendar: Calendar, col: number, row: number): Day | undefined {
  const { days, offset, lead } = calendar;
  const index = Math.min(days.length - 1, Math.max(0, col * 7 + row - offset - lead));
  return days[index];
}

/**
 * Colour step 0-4: 0 for an empty day, then the quartile of the non-empty days. Quartiles keep the
 * steps spread whether counts are even or heavily skewed (a batch day can hold thousands).
 */
export function level(count: number, thresholds: readonly [number, number, number]): number {
  if (count <= 0) return 0;
  const [q1, q2, q3] = thresholds;
  return count <= q1 ? 1 : count <= q2 ? 2 : count <= q3 ? 3 : 4;
}

export function ordered(a: string, b: string): [string, string] {
  return a <= b ? [a, b] : [b, a];
}

export function inRange(date: string, from: string | null, to: string | null): boolean {
  return (!from || date >= from) && (!to || date <= to);
}

/** A label for the week holding each month's first day, with the year on January and on the first
 *  label. */
export function monthLabels(calendar: Calendar): { col: number; label: string }[] {
  const out: { col: number; label: string }[] = [];
  const cells: Cell[] = [...calendar.padding, ...calendar.days];
  cells.sort((a, b) => (a.date < b.date ? -1 : 1));
  for (const day of cells) {
    if (out.length > 0 && !day.date.endsWith("-01")) continue;
    const month = Number(day.date.slice(5, 7)) - 1;
    const name = MONTHS[month] ?? "";
    out.push({
      col: day.col,
      label: out.length === 0 || month === 0 ? `${name} ${day.date.slice(0, 4)}` : name,
    });
  }
  return out;
}

export function longDate(iso: string): string {
  return new Date(parse(iso)).toLocaleDateString("en-US", {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
