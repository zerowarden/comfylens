import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState, type PointerEvent } from "react";

import { api } from "../api/client";
import {
  buildCalendar,
  dayAt,
  inRange,
  level,
  longDate,
  monthLabels,
  nearestDay,
  ordered,
  type Calendar,
  type Day,
} from "../lib/calendar";
import { familyColor } from "../lib/colors";
import { fmtInt } from "../lib/format";
import { useElementWidth } from "../lib/hooks";
import { useScope } from "../lib/scope";
import { ChainText } from "./icons";
import { useFilters } from "../state/filters";

const HEIGHT = 120;
const TOP = 18; // month labels
const BOTTOM = 6;
const LEFT = 36; // weekday labels
const MAX_PITCH = (HEIGHT - TOP - BOTTOM) / 7;
const TOOLTIP = 220;
const WEEKDAYS: [number, string][] = [
  [0, "Mon"],
  [2, "Wed"],
  [4, "Fri"],
];
// One sequential hue, light to dark; dark mode runs dark to light against its surface.
const LEVELS = [
  { fill: "fill-zinc-200/70 dark:fill-zinc-800/70", bg: "bg-zinc-200/70 dark:bg-zinc-800/70" },
  { fill: "fill-sky-200 dark:fill-sky-900", bg: "bg-sky-200 dark:bg-sky-900" },
  { fill: "fill-sky-300 dark:fill-sky-700", bg: "bg-sky-300 dark:bg-sky-700" },
  { fill: "fill-sky-500 dark:fill-sky-500", bg: "bg-sky-500 dark:bg-sky-500" },
  { fill: "fill-sky-700 dark:fill-sky-300", bg: "bg-sky-700 dark:bg-sky-300" },
];

interface Drag {
  a: string;
  b: string;
}

function Tooltip({ day, left, top, flip }: { day: Day; left: number; top: number; flip: boolean }) {
  const shown = day.families.slice(0, 6);
  const rest = day.families.length - shown.length;
  return (
    <div
      className="pointer-events-none absolute z-20 rounded border border-zinc-200 bg-white px-2 py-1.5 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
      style={{
        top,
        width: TOOLTIP,
        ...(flip ? { right: `calc(100% - ${left}px)` } : { left }),
      }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium">{longDate(day.date)}</span>
        <span className="tabular-nums">{fmtInt(day.total)}</span>
      </div>
      {shown.map(([family, n]) => (
        <div key={family} className="flex items-center gap-1.5 text-zinc-500">
          <span
            className="inline-block h-2 w-2 shrink-0 rounded-full"
            style={{ background: familyColor(family) }}
          />
          <span className="min-w-0 flex-1 truncate">
            <ChainText text={family} kind="pipeline" />
          </span>
          <span className="tabular-nums">{fmtInt(n)}</span>
        </div>
      ))}
      {rest > 0 && <div className="text-zinc-500">+{rest} more families</div>}
      {day.selected > 0 && <div className="mt-0.5">{fmtInt(day.selected)} selected</div>}
      {day.suspect > 0 && (
        <div className="text-amber-600 dark:text-amber-400">
          {fmtInt(day.suspect)} with suspect timestamps
        </div>
      )}
    </div>
  );
}

function Heatmap({ calendar, width }: { calendar: Calendar; width: number }) {
  const dateFrom = useFilters((s) => s.filters.date_from);
  const dateTo = useFilters((s) => s.filters.date_to);
  const update = useFilters((s) => s.update);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [hover, setHover] = useState<Day | null>(null);
  const hatch = useId().replace(/:/g, "");

  const { weeks, thresholds } = calendar;
  const gridWidth = Math.max(0, width - LEFT - 12);
  // Square cells, shrunk when the weeks would overflow the strip.
  const pitch = weeks > 0 ? Math.min(MAX_PITCH, gridWidth / weeks) : 0;
  const gap = pitch >= 6 ? 2 : pitch >= 3 ? 1 : 0;
  const size = Math.max(1, pitch - gap);
  const round = pitch >= 6 ? 2 : 0;
  const range: [string | null, string | null] = drag ? ordered(drag.a, drag.b) : [dateFrom, dateTo];
  const [from, to] = range;
  const filtered = from !== null || to !== null;

  const cells = useMemo(
    () =>
      calendar.days.map((day) => {
        const x = LEFT + day.col * pitch;
        const y = TOP + day.row * pitch;
        const w = size;
        const h = size;
        return (
          <g key={day.date} opacity={filtered && !inRange(day.date, from, to) ? 0.25 : 1}>
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              rx={round}
              className={LEVELS[level(day.total, thresholds)]?.fill}
            />
            {day.suspect > 0 && (
              <rect x={x} y={y} width={w} height={h} rx={round} fill={`url(#${hatch})`} />
            )}
            {day.selected > 0 && (
              <rect
                x={x + 0.75}
                y={y + 0.75}
                width={Math.max(0, w - 1.5)}
                height={h - 1.5}
                rx={round}
                fill="none"
                strokeWidth={1.5}
                className="stroke-zinc-900 dark:stroke-zinc-100"
              />
            )}
          </g>
        );
      }),
    [calendar, pitch, size, round, thresholds, filtered, from, to, hatch],
  );

  // Days outside the data that complete its first and last month: outlined, not filled.
  const padding = useMemo(
    () =>
      calendar.padding.map((cell) => (
        <rect
          key={cell.date}
          x={LEFT + cell.col * pitch + 0.5}
          y={TOP + cell.row * pitch + 0.5}
          width={Math.max(0, size - 1)}
          height={Math.max(0, size - 1)}
          rx={round}
          fill="none"
          strokeWidth={1}
          className="stroke-zinc-300/60 dark:stroke-zinc-700/60"
        />
      )),
    [calendar, pitch, size, round],
  );

  const labels = useMemo(() => {
    const out: { x: number; label: string }[] = [];
    let next = 0;
    for (const { col, label } of monthLabels(calendar)) {
      const x = LEFT + col * pitch;
      if (x < next || x > LEFT + gridWidth) continue;
      out.push({ x, label });
      next = x + label.length * 5.5 + 6; // approximate width of 10px text
    }
    return out;
  }, [calendar, pitch, gridWidth]);

  /** The cell under the pointer; `clamp` snaps points outside the grid to the nearest day. */
  const dayFromPointer = (e: PointerEvent<SVGSVGElement>, clamp: boolean): Day | undefined => {
    const rect = e.currentTarget.getBoundingClientRect();
    const col = Math.floor((e.clientX - rect.left - LEFT) / pitch);
    const row = Math.floor((e.clientY - rect.top - TOP) / pitch);
    if (clamp)
      return nearestDay(
        calendar,
        Math.min(weeks - 1, Math.max(0, col)),
        Math.min(6, Math.max(0, row)),
      );
    if (col < 0 || col >= weeks || row < 0 || row > 6) return undefined;
    return dayAt(calendar, col, row);
  };

  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    const day = dayFromPointer(e, false);
    if (!day) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setHover(null);
    setDrag({ a: day.date, b: day.date });
  };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (drag) {
      const day = dayFromPointer(e, true);
      if (day && day.date !== drag.b) setDrag({ ...drag, b: day.date });
    } else {
      const day = dayFromPointer(e, false) ?? null;
      if (day !== hover) setHover(day);
    }
  };
  const onPointerUp = () => {
    if (!drag) return;
    const [lo, hi] = ordered(drag.a, drag.b);
    setDrag(null);
    update((f) => ({ ...f, date_from: lo, date_to: hi }));
  };

  const hoverX = hover ? LEFT + hover.col * pitch : 0;
  const hoverY = hover ? TOP + hover.row * pitch : 0;
  const flip = hoverX + pitch + 8 + TOOLTIP > width;
  return (
    <>
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label="Images per day. Drag across days to filter by date; double-click to clear."
        className="select-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => setDrag(null)}
        onPointerLeave={() => setHover(null)}
        onDoubleClick={() => {
          setDrag(null);
          update((f) => ({ ...f, date_from: null, date_to: null }));
        }}
      >
        <defs>
          <pattern
            id={hatch}
            width="3"
            height="3"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line x1="0" y1="0" x2="0" y2="3" strokeWidth="1.2" className="stroke-amber-500" />
          </pattern>
        </defs>
        {labels.map(({ x, label }) => (
          <text key={x} x={x} y={TOP - 6} fontSize={10} className="fill-zinc-500">
            {label}
          </text>
        ))}
        {pitch >= 9 &&
          WEEKDAYS.map(([row, label]) => (
            <text
              key={row}
              x={LEFT - 6}
              y={TOP + row * pitch + size / 2}
              fontSize={9}
              textAnchor="end"
              dominantBaseline="middle"
              className="fill-zinc-500"
            >
              {label}
            </text>
          ))}
        <rect
          x={LEFT}
          y={TOP}
          width={weeks * pitch}
          height={7 * pitch}
          fill="transparent"
          className="cursor-pointer"
        />
        <g className="pointer-events-none">{padding}</g>
        <g className="cursor-pointer">{cells}</g>
        {hover && (
          <rect
            x={hoverX - 0.5}
            y={hoverY - 0.5}
            width={size + 1}
            height={size + 1}
            rx={round}
            fill="none"
            strokeWidth={1}
            className="pointer-events-none stroke-zinc-500"
          />
        )}
      </svg>
      {hover && !drag && (
        <Tooltip
          day={hover}
          left={flip ? hoverX - 8 : hoverX + pitch + 8}
          top={hoverY - 4}
          flip={flip}
        />
      )}
      {filtered && (
        <div className="pointer-events-none absolute top-0.5 right-3 bg-white px-1 text-xs text-zinc-500 tabular-nums dark:bg-zinc-950">
          {from ?? "…"} – {to ?? "…"}
        </div>
      )}
    </>
  );
}

export default function Timeline() {
  const { scope, key } = useScope();
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const width = useElementWidth(element);

  const query = useQuery({
    queryKey: ["timeline", key],
    queryFn: () => api.timeline({ ...scope, bucket: "day" }),
    placeholderData: keepPreviousData,
  });
  const data = query.data;
  const calendar = useMemo(() => (data ? buildCalendar(data) : null), [data]);

  return (
    <div
      ref={setElement}
      className="relative shrink-0 border-b border-zinc-200 dark:border-zinc-800"
      style={{ height: HEIGHT }}
    >
      {calendar && calendar.days.length > 0 && width > 0 ? (
        <Heatmap calendar={calendar} width={width} />
      ) : (
        <div className="flex h-full items-center justify-center text-zinc-500">
          {query.isError ? query.error.message : calendar ? "No dated images" : "Loading timeline…"}
        </div>
      )}
    </div>
  );
}
