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
import { fmtInt } from "../lib/format";
import { useElementWidth } from "../lib/hooks";
import { useScope } from "../lib/scope";
import { ChainText } from "./icons";
import { useFilters } from "../state/filters";
import { FamilyDot } from "./ui";

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
// The heat scale from theme.css, empty to busiest.
const LEVELS = [
  { fill: "fill-heat-0", bg: "bg-heat-0" },
  { fill: "fill-heat-1", bg: "bg-heat-1" },
  { fill: "fill-heat-2", bg: "bg-heat-2" },
  { fill: "fill-heat-3", bg: "bg-heat-3" },
  { fill: "fill-heat-4", bg: "bg-heat-4" },
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
      className="pointer-events-none absolute z-20 rounded border border-control bg-surface px-2 py-1.5 text-xs shadow-lg"
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
        <div key={family} className="flex items-center gap-1.5 text-muted">
          <FamilyDot family={family} />
          <span className="min-w-0 flex-1 truncate">
            <ChainText text={family} kind="pipeline" />
          </span>
          <span className="tabular-nums">{fmtInt(n)}</span>
        </div>
      ))}
      {rest > 0 && <div className="text-muted">+{rest} more families</div>}
      {day.selected > 0 && <div className="mt-0.5">{fmtInt(day.selected)} selected</div>}
      {day.suspect > 0 && (
        <div className="text-warning">{fmtInt(day.suspect)} with suspect timestamps</div>
      )}
    </div>
  );
}

/** Square cells, shrunk when the weeks would overflow the strip; gaps and rounding only where
 * the cells are big enough to show them. */
function cellGeometry(width: number, weeks: number) {
  const gridWidth = Math.max(0, width - LEFT - 12);
  const pitch = weeks > 0 ? Math.min(MAX_PITCH, gridWidth / weeks) : 0;
  return { gridWidth, pitch, size: Math.max(1, pitch - cellGap(pitch)), round: pitch >= 6 ? 2 : 0 };
}

function cellGap(pitch: number): number {
  if (pitch >= 6) return 2;
  return pitch >= 3 ? 1 : 0;
}

type Geometry = ReturnType<typeof cellGeometry>;

/** Month labels left to right, skipping any that would overlap the previous one or fall past
 * the grid. */
function placeLabels(calendar: Calendar, { pitch, gridWidth }: Geometry) {
  return monthLabels(calendar).reduce<{ x: number; label: string }[]>((out, { col, label }) => {
    const x = LEFT + col * pitch;
    const last = out.at(-1);
    const free = last ? last.x + last.label.length * 5.5 + 6 : 0; // ~ width of 10px text
    return x < free || x > LEFT + gridWidth ? out : [...out, { x, label }];
  }, []);
}

/** The grid cell under a pointer, which may lie outside the grid. */
function pointerCell(e: PointerEvent<SVGSVGElement>, pitch: number) {
  const rect = e.currentTarget.getBoundingClientRect();
  return {
    col: Math.floor((e.clientX - rect.left - LEFT) / pitch),
    row: Math.floor((e.clientY - rect.top - TOP) / pitch),
  };
}

const clampTo = (value: number, max: number) => Math.min(max, Math.max(0, value));

/** The day under the pointer; `clamp` snaps points outside the grid to the nearest day. */
function dayUnder(
  calendar: Calendar,
  { col, row }: { col: number; row: number },
  clamp: boolean,
): Day | undefined {
  if (clamp) return nearestDay(calendar, clampTo(col, calendar.weeks - 1), clampTo(row, 6));
  const inside = col >= 0 && col < calendar.weeks && row >= 0 && row <= 6;
  return inside ? dayAt(calendar, col, row) : undefined;
}

interface CellProps {
  day: Day;
  geometry: Geometry;
  level: number;
  dimmed: boolean;
  hatch: string;
}

/** A day's square: its heat, hatched when a timestamp is suspect, outlined when selected. */
function DayCell({ day, geometry: { pitch, size, round }, level, dimmed, hatch }: CellProps) {
  const x = LEFT + day.col * pitch;
  const y = TOP + day.row * pitch;
  return (
    <g opacity={dimmed ? 0.25 : 1}>
      <rect x={x} y={y} width={size} height={size} rx={round} className={LEVELS[level]?.fill} />
      {day.suspect > 0 && (
        <rect x={x} y={y} width={size} height={size} rx={round} fill={`url(#${hatch})`} />
      )}
      {day.selected > 0 && (
        <rect
          x={x + 0.75}
          y={y + 0.75}
          width={Math.max(0, size - 1.5)}
          height={size - 1.5}
          rx={round}
          fill="none"
          strokeWidth={1.5}
          className="stroke-fg"
        />
      )}
    </g>
  );
}

function WeekdayLabels({ geometry: { pitch, size } }: { geometry: Geometry }) {
  if (pitch < 9) return null;
  return WEEKDAYS.map(([row, label]) => (
    <text
      key={row}
      x={LEFT - 6}
      y={TOP + row * pitch + size / 2}
      fontSize={9}
      textAnchor="end"
      dominantBaseline="middle"
      className="fill-muted"
    >
      {label}
    </text>
  ));
}

function HoverOutline({ day, geometry: { pitch, size, round } }: { day: Day; geometry: Geometry }) {
  return (
    <rect
      x={LEFT + day.col * pitch - 0.5}
      y={TOP + day.row * pitch - 0.5}
      width={size + 1}
      height={size + 1}
      rx={round}
      fill="none"
      strokeWidth={1}
      className="pointer-events-none stroke-muted"
    />
  );
}

/** The tooltip beside a day; it flips to the left near the right edge. */
function DayTooltip({ day, pitch, width }: { day: Day; pitch: number; width: number }) {
  const x = LEFT + day.col * pitch;
  const flip = x + pitch + 8 + TOOLTIP > width;
  return (
    <Tooltip
      day={day}
      left={flip ? x - 8 : x + pitch + 8}
      top={TOP + day.row * pitch - 4}
      flip={flip}
    />
  );
}

function RangeLabel({ from, to }: { from: string | null; to: string | null }) {
  return (
    <div className="pointer-events-none absolute top-0.5 right-3 bg-canvas px-1 text-xs text-muted tabular-nums">
      {from ?? "…"} – {to ?? "…"}
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

  const geometry = useMemo(() => cellGeometry(width, calendar.weeks), [width, calendar.weeks]);
  const { pitch, size, round } = geometry;
  const [from, to] = drag ? ordered(drag.a, drag.b) : [dateFrom, dateTo];
  const filtered = from !== null || to !== null;

  const cells = useMemo(
    () =>
      calendar.days.map((day) => (
        <DayCell
          key={day.date}
          day={day}
          geometry={geometry}
          level={level(day.total, calendar.thresholds)}
          dimmed={filtered && !inRange(day.date, from, to)}
          hatch={hatch}
        />
      )),
    [calendar, geometry, filtered, from, to, hatch],
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
          className="stroke-control/60"
        />
      )),
    [calendar, pitch, size, round],
  );

  const labels = useMemo(() => placeLabels(calendar, geometry), [calendar, geometry]);

  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    const day = e.button === 0 ? dayUnder(calendar, pointerCell(e, pitch), false) : undefined;
    if (!day) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setHover(null);
    setDrag({ a: day.date, b: day.date });
  };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    const day = dayUnder(calendar, pointerCell(e, pitch), drag !== null);
    if (!drag) setHover(day ?? null);
    else if (day && day.date !== drag.b) setDrag({ ...drag, b: day.date });
  };
  const onPointerUp = () => {
    if (!drag) return;
    const [lo, hi] = ordered(drag.a, drag.b);
    setDrag(null);
    update((f) => ({ ...f, date_from: lo, date_to: hi }));
  };

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
            <line x1="0" y1="0" x2="0" y2="3" strokeWidth="1.2" className="stroke-warning" />
          </pattern>
        </defs>
        {labels.map(({ x, label }) => (
          <text key={x} x={x} y={TOP - 6} fontSize={10} className="fill-muted">
            {label}
          </text>
        ))}
        <WeekdayLabels geometry={geometry} />
        <rect
          x={LEFT}
          y={TOP}
          width={calendar.weeks * pitch}
          height={7 * pitch}
          fill="transparent"
          className="cursor-pointer"
        />
        <g className="pointer-events-none">{padding}</g>
        <g className="cursor-pointer">{cells}</g>
        {hover && <HoverOutline day={hover} geometry={geometry} />}
      </svg>
      {hover && !drag && <DayTooltip day={hover} pitch={pitch} width={width} />}
      {filtered && <RangeLabel from={from} to={to} />}
    </>
  );
}

/** Why there is no heatmap to show. */
function timelineNote(error: Error | null, calendar: Calendar | null): string {
  if (error) return error.message;
  return calendar ? "No dated images" : "Loading timeline…";
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
      className="relative shrink-0 border-b border-line"
      style={{ height: HEIGHT }}
    >
      {calendar && calendar.days.length > 0 && width > 0 ? (
        <Heatmap calendar={calendar} width={width} />
      ) : (
        <div className="flex h-full items-center justify-center text-muted">
          {timelineNote(query.error, calendar)}
        </div>
      )}
    </div>
  );
}
