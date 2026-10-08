import { useMemo, useState } from "react";

import type { Histogram, NumericStats } from "../../api/types";
import { chartColors, type EChartsOption } from "../../lib/echarts";
import { fmtInt, fmtNum, fmtPct } from "../../lib/format";
import { useUi } from "../../state/ui";
import Chart from "../Chart";
import { td, th } from "../ui";
import { rangeText } from "./format";

/** The mode as a value, or a muted dash when there is no repeated value to report. */
export function ModeText({ stats }: { stats: NumericStats }) {
  if (stats.mode.length === 0) return <span className="text-muted">—</span>;
  const values = stats.mode.map(fmtNum).join(", ");
  return (
    <>
      {values} ({fmtPct(stats.mode_share)}){stats.mode_tied ? " tied" : ""}
    </>
  );
}

function barLabel(bar: { x0: number; x1: number }, kind: Histogram["kind"]): string {
  return kind === "discrete" ? fmtNum(bar.x0) : `${fmtNum(bar.x0)}–${fmtNum(bar.x1)}`;
}

const PLOT = { width: 96, height: 30, pad: 5, axis: 22 };
const QUANTILES = ["min", "p25", "median", "p75", "max"] as const;

/** "min 1, p25 2, median 3, p75 4, max 5", leaving out the quantiles that are unknown. */
const rangeTitle = (stats: NumericStats) =>
  QUANTILES.filter((q) => stats[q] !== null)
    .map((q) => `${q} ${fmtNum(stats[q])}`)
    .join(", ");

/** Where a value sits on the plot; a single-valued range sits in the middle. */
const scale = (min: number, max: number) => (v: number) =>
  max === min ? PLOT.width / 2 : PLOT.pad + ((v - min) / (max - min)) * (PLOT.width - 2 * PLOT.pad);

/** Keep the median's label inside the plot near either end. */
function labelAnchor(x: number): "start" | "middle" | "end" {
  if (x < 14) return "start";
  return x > PLOT.width - 14 ? "end" : "middle";
}

/**
 * Min to max as an axis, the interquartile range as a shaded box and the median as a marker with
 * its value above, on the field's own scale. Colours are the range tokens in theme.css.
 */
function RangePlot({ stats }: { stats: NumericStats }) {
  const { min, p25, median, p75, max } = stats;
  if (min === null || max === null) return null;
  const x = scale(min, max);
  const { width: w, height: h, pad, axis } = PLOT;
  const title = rangeTitle(stats);
  return (
    <svg width={w} height={h} role="img" aria-label={title} className="block">
      <title>{title}</title>
      {p25 !== null && p75 !== null && max !== min && (
        <rect
          x={x(p25)}
          y={11}
          width={Math.max(2, x(p75) - x(p25))}
          height={h - 12}
          className="fill-range-box"
        />
      )}
      <line x1={pad} x2={w - pad} y1={axis} y2={axis} className="stroke-range-axis" />
      <line x1={pad} x2={pad} y1={axis - 3} y2={axis + 3} className="stroke-range-axis" />
      <line x1={w - pad} x2={w - pad} y1={axis - 3} y2={axis + 3} className="stroke-range-axis" />
      {median !== null && <MedianMarker x={x(median)} median={median} />}
    </svg>
  );
}

function MedianMarker({ x, median }: { x: number; median: number }) {
  const { axis } = PLOT;
  return (
    <>
      <polygon
        points={`${x},${axis - 7} ${x - 4},${axis + 1} ${x + 4},${axis + 1}`}
        className="fill-range-median"
      />
      <text x={x} y={8} textAnchor={labelAnchor(x)} className="fill-fg text-[9px] tabular-nums">
        {fmtNum(median)}
      </text>
    </>
  );
}

function HistogramChart({ histogram }: { histogram: Histogram }) {
  const theme = useUi((s) => s.theme);
  const option = useMemo<EChartsOption>(() => {
    const colors = chartColors();
    return {
      darkMode: theme === "dark",
      animation: false,
      grid: { left: 40, right: 8, top: 8, bottom: 40 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        type: "category",
        data: histogram.bars.map((b) => barLabel(b, histogram.kind)),
        axisLabel: { color: colors.text, fontSize: 10, rotate: 30 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: colors.text, fontSize: 10 },
        splitLine: { lineStyle: { color: colors.line } },
      },
      series: [
        { type: "bar", data: histogram.bars.map((b) => b.count), itemStyle: { color: colors.bar } },
      ],
    };
  }, [histogram, theme]);
  return <Chart option={option} className="h-44 w-full" />;
}

/** Numeric fields: the summary table, or plain values for a single selected image. */
export function NumericField({
  name,
  stats,
  single = false,
}: {
  name: string;
  stats: NumericStats;
  single?: boolean;
}) {
  const fields = { [name]: stats };
  return single ? <NumericValues stats={fields} /> : <NumericTable stats={fields} />;
}

/** The value of each numeric field in scope, without summary statistics: the single-image view. */
export function NumericValues({ stats }: { stats: Record<string, NumericStats> }) {
  const rows = Object.entries(stats).filter(([, s]) => s.n > 0);
  if (rows.length === 0) return null;
  return (
    <table className="w-full text-xs">
      <tbody>
        {rows.map(([name, s]) => (
          <tr key={name}>
            <td className={`${td} w-32 text-muted`}>{name}</td>
            <td className={`${td} tabular-nums`}>{fmtNum(s.median)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Clicking a row shows its histogram. */
export function NumericTable({ stats }: { stats: Record<string, NumericStats> }) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = Object.entries(stats).filter(([, s]) => s.n > 0);
  const chosen = open ? stats[open] : undefined;
  if (rows.length === 0) return null;
  return (
    <div>
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className={th}>field</th>
            <th className={th}>mode (share)</th>
            <th className={th}>median</th>
            <th className={th}>mean</th>
            <th className={th}>min–max</th>
            <th className={th}>n</th>
            <th className={th}>range</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, s]) => (
            <tr
              key={name}
              onClick={() => setOpen(open === name ? null : name)}
              className={`cursor-pointer hover:bg-hover ${open === name ? "bg-accent/10" : ""}`}
            >
              <td className={td}>{name}</td>
              <td className={td}>
                <ModeText stats={s} />
              </td>
              <td className={`${td} tabular-nums`}>{fmtNum(s.median)}</td>
              <td className={`${td} tabular-nums`}>{fmtNum(s.mean)}</td>
              <td className={`${td} whitespace-nowrap tabular-nums`}>{rangeText(s)}</td>
              <td className={`${td} tabular-nums`}>{fmtInt(s.n)}</td>
              <td className={td}>
                <RangePlot stats={s} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open && chosen?.histogram && (
        <div className="mt-2">
          <div className="text-xs text-muted">{open}</div>
          <HistogramChart histogram={chosen.histogram} />
        </div>
      )}
    </div>
  );
}
