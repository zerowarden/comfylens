import { useMemo, useState } from "react";

import type { Histogram, NumericStats } from "../../api/types";
import { axisColors, type EChartsOption } from "../../lib/echarts";
import { fmtInt, fmtNum } from "../../lib/format";
import { useUi } from "../../state/ui";
import Chart from "../Chart";
import { td, th } from "../ui";
import { modeText, rangeText } from "./format";

function barLabel(bar: { x0: number; x1: number }, kind: Histogram["kind"]): string {
  return kind === "discrete" ? fmtNum(bar.x0) : `${fmtNum(bar.x0)}–${fmtNum(bar.x1)}`;
}

/**
 * Min to max as a whisker, the interquartile range as a bar and the median as a tick, on the
 * field's own scale.
 */
export function RangePlot({ stats }: { stats: NumericStats }) {
  const { min, p25, median, p75, max } = stats;
  if (min === null || max === null) return null;
  const w = 64;
  const h = 14;
  const pad = 2;
  const mid = h / 2;
  const x = (v: number | null) =>
    v === null || max === min ? w / 2 : pad + ((v - min) / (max - min)) * (w - 2 * pad);
  const title = [
    `min ${fmtNum(min)}`,
    p25 !== null && `p25 ${fmtNum(p25)}`,
    median !== null && `median ${fmtNum(median)}`,
    p75 !== null && `p75 ${fmtNum(p75)}`,
    `max ${fmtNum(max)}`,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <svg width={w} height={h} role="img" aria-label={title}>
      <title>{title}</title>
      {max === min ? (
        <circle cx={w / 2} cy={mid} r={2.5} className="fill-sky-500" />
      ) : (
        <>
          <line x1={x(min)} x2={x(max)} y1={mid} y2={mid} className="stroke-zinc-400" />
          <line x1={x(min)} x2={x(min)} y1={mid - 3} y2={mid + 3} className="stroke-zinc-400" />
          <line x1={x(max)} x2={x(max)} y1={mid - 3} y2={mid + 3} className="stroke-zinc-400" />
          {p25 !== null && p75 !== null && (
            <rect
              x={x(p25)}
              y={mid - 3.5}
              width={Math.max(1.5, x(p75) - x(p25))}
              height={7}
              rx={1}
              className="fill-sky-500/40 stroke-sky-500"
            />
          )}
          {median !== null && (
            <line
              x1={x(median)}
              x2={x(median)}
              y1={mid - 4.5}
              y2={mid + 4.5}
              strokeWidth={2}
              className="stroke-zinc-900 dark:stroke-zinc-100"
            />
          )}
        </>
      )}
    </svg>
  );
}

export function HistogramChart({ histogram }: { histogram: Histogram }) {
  const dark = useUi((s) => s.theme === "dark");
  const option = useMemo<EChartsOption>(() => {
    const colors = axisColors(dark);
    return {
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
        { type: "bar", data: histogram.bars.map((b) => b.count), itemStyle: { color: "#0ea5e9" } },
      ],
    };
  }, [histogram, dark]);
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
              className={`cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-900 ${open === name ? "bg-sky-500/10" : ""}`}
            >
              <td className={td}>{name}</td>
              <td className={td}>{modeText(s)}</td>
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
          <div className="text-xs text-zinc-500">{open}</div>
          <HistogramChart histogram={chosen.histogram} />
        </div>
      )}
    </div>
  );
}
