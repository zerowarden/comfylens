import { describe, expect, it } from "vitest";

import type { TimelineResponse } from "../api/types";
import {
  addDays,
  buildCalendar,
  dayAt,
  inRange,
  level,
  monthEnd,
  monthLabels,
  nearestDay,
  ordered,
  weekday,
} from "./calendar";

const timeline = (over: Partial<TimelineResponse>): TimelineResponse => ({
  bucket: "day",
  buckets: [],
  series: {},
  suspect: [],
  selected: null,
  date_min: null,
  date_max: null,
  ...over,
});

describe("dates", () => {
  it("counts weekdays from Monday", () => {
    expect(weekday("2026-10-05")).toBe(0); // Monday
    expect(weekday("2026-10-04")).toBe(6); // Sunday
  });

  it("adds days across month ends", () => {
    expect(addDays("2026-01-31", 1)).toBe("2026-02-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("finds the last day of a month, including leap years", () => {
    expect(monthEnd("2026-10-04")).toBe("2026-10-31");
    expect(monthEnd("2028-02-10")).toBe("2028-02-29");
    expect(monthEnd("2026-12-31")).toBe("2026-12-31");
  });
});

describe("buildCalendar", () => {
  // Saturday 2026-10-03 to Tuesday 2026-10-06.
  const data = timeline({
    buckets: ["2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06"],
    series: { flux: [2, 0, 5, 0], sdxl: [1, 0, 7, 0] },
    suspect: [0, 0, 3, 0],
    selected: [1, 0, 0, 0],
  });
  const calendar = buildCalendar(data);

  it("places days in Monday-first weeks, padded to whole months and a full year", () => {
    // October 2026 starts on a Thursday; the year runs to September 2027.
    expect(calendar.offset).toBe(3);
    expect(calendar.lead).toBe(2);
    expect(calendar.weeks).toBe(53);
    expect(calendar.days.map((d) => [d.col, d.row])).toEqual([
      [0, 5],
      [0, 6],
      [1, 0],
      [1, 1],
    ]);
    expect(calendar.padding).toHaveLength(361);
    expect(calendar.padding[0]).toEqual({ date: "2026-10-01", col: 0, row: 3 });
    expect(calendar.padding[2]).toEqual({ date: "2026-10-07", col: 1, row: 2 });
    expect(calendar.padding.at(-1)).toEqual({ date: "2027-09-30", col: 52, row: 3 });
  });

  it("extends past a year only to finish the last month with data", () => {
    const buckets = Array.from({ length: 400 }, (_, i) => addDays("2026-01-15", i));
    const long = buildCalendar(timeline({ buckets }));
    expect(long.padding[0]?.date).toBe("2026-01-01");
    expect(long.padding.at(-1)?.date).toBe("2027-02-28");
  });

  it("totals families, largest first, and keeps the busiest day", () => {
    expect(calendar.days[2]).toMatchObject({
      total: 12,
      suspect: 3,
      selected: 0,
      families: [
        ["sdxl", 7],
        ["flux", 5],
      ],
    });
    expect(calendar.days[1]?.families).toEqual([]);
    expect(calendar.days[0]?.selected).toBe(1);
    expect(calendar.max).toBe(12);
  });

  it("handles an empty timeline", () => {
    expect(buildCalendar(timeline({}))).toEqual({
      days: [],
      padding: [],
      weeks: 0,
      offset: 0,
      lead: 0,
      max: 0,
      thresholds: [0, 0, 0],
    });
  });

  it("finds no day on padding or empty slots", () => {
    expect(dayAt(calendar, 1, 0)?.date).toBe("2026-10-05");
    expect(dayAt(calendar, 0, 3)).toBeUndefined();
    expect(dayAt(calendar, 0, 0)).toBeUndefined();
    expect(dayAt(calendar, 52, 3)).toBeUndefined();
  });

  it("clamps cells before the first or after the last day", () => {
    expect(nearestDay(calendar, 0, 0)?.date).toBe("2026-10-03");
    expect(nearestDay(calendar, 52, 6)?.date).toBe("2026-10-06");
    expect(nearestDay(calendar, 1, 0)?.date).toBe("2026-10-05");
  });
});

describe("level", () => {
  it("is 0 for empty days, then the quartile of the non-empty days", () => {
    const totals = [1, 2, 3, 4, 5, 6, 7, 8, 0];
    const { thresholds } = buildCalendar(
      timeline({
        buckets: totals.map((_, i) => addDays("2026-01-01", i)),
        series: { flux: totals },
      }),
    );
    expect(thresholds).toEqual([2, 4, 6]);
    expect(totals.map((n) => level(n, thresholds))).toEqual([1, 1, 2, 2, 3, 3, 4, 4, 0]);
  });

  it("puts every day of an even library on one step", () => {
    expect(level(5, [5, 5, 5])).toBe(1);
  });
});

describe("ranges", () => {
  it("orders the ends of a drag and tests membership inclusively", () => {
    expect(ordered("2026-02-01", "2026-01-01")).toEqual(["2026-01-01", "2026-02-01"]);
    expect(inRange("2026-01-01", "2026-01-01", "2026-01-31")).toBe(true);
    expect(inRange("2026-02-01", "2026-01-01", "2026-01-31")).toBe(false);
    expect(inRange("2026-02-01", null, null)).toBe(true);
  });
});

describe("monthLabels", () => {
  it("labels the first week and each month start, with the year on January", () => {
    const buckets = Array.from({ length: 70 }, (_, i) => addDays("2025-11-20", i));
    const labels = monthLabels(buildCalendar(timeline({ buckets })));
    expect(labels.map((l) => l.label)).toEqual([
      "Nov 2025",
      "Dec",
      "Jan 2026",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "Jul",
      "Aug",
      "Sep",
      "Oct",
    ]);
  });
});
