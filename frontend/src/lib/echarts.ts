import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

export { echarts };
export type EChartsOption = echarts.EChartsCoreOption;

/** The chart colours of the active theme, from theme.css (a canvas cannot read CSS variables). */
export function chartColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return { text: read("--chart-text"), line: read("--chart-line"), bar: read("--chart-bar") };
}
