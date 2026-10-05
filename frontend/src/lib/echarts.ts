import { BarChart, GraphChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([BarChart, GraphChart, GridComponent, TooltipComponent, CanvasRenderer]);

export { echarts };
export type EChartsOption = echarts.EChartsCoreOption;

/** The chart colours of the active theme, from theme.css (a canvas cannot read CSS variables). */
export function chartColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return { text: read("--chart-text"), line: read("--chart-line"), bar: read("--chart-bar") };
}

/**
 * `color` with `alpha` mixed in, for #rgb, #rrggbb and rgb()/rgba() colours. Unlike
 * `itemStyle.opacity` this leaves the element's opacity at 1, so a label on the shape stays
 * fully opaque.
 */
export function withAlpha(color: string, alpha: number): string {
  const value = color.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value);
  if (hex) {
    const short = hex[1]!;
    const full = short.length === 3 ? [...short].map((c) => c + c).join("") : short;
    const n = parseInt(full, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }
  const rgb = /^rgba?\(([^)]+)\)$/i.exec(value);
  if (rgb) {
    const [r, g, b] = rgb[1]!.split(",").map((part) => part.trim());
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  return value;
}
