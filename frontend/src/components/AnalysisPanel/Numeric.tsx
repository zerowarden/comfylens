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

/**
 * Min to max as an axis, the interquartile range as a shaded box and the median as a marker with
 * its value above, on the field's own scale. Colours are the range tokens in theme.css.
 */
export function RangePlot({ stats }: { stats: NumericStats }) {
  const { min, p25, median, p75, max } = stats;
  if (min === null || max === null) return null;
  const w = 96;
  const h = 30;
  const pad = 5;
  const axis = 22;
  const x = (v: number) => (max === min ? w / 2 : pad + ((v - min) / (max - min)) * (w - 2 * pad));
  const title = [
    `min ${fmtNum(min)}`,
    p25 !== null && `p25 ${fmtNum(p25)}`,
    median !== null && `median ${fmtNum(median)}`,
    p75 !== null && `p75 ${fmtNum(p75)}`,
    `max ${fmtNum(max)}`,
  ]
    .filter(Boolean)
    .join(", ");
  const xm = median === null ? null : x(median);
  // Keep the median's label inside the plot near either end.
  const anchor = xm === null ? "middle" : xm < 14 ? "start" : xm > w - 14 ? "end" : "middle";
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
      {xm !== null && median !== null && (
        <>
          <polygon
            points={`${xm},${axis - 7} ${xm - 4},${axis + 1} ${xm + 4},${axis + 1}`}
            className="fill-range-median"
          />
          <text x={xm} y={8} textAnchor={anchor} className="fill-fg text-[9px] tabular-nums">
            {fmtNum(median)}
          </text>
        </>
      )}
    </svg>
  );
}

export function HistogramChart({ histogram }: { histogram: Histogram }) {
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
