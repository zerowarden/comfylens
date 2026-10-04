import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

export { echarts };
export type EChartsOption = echarts.EChartsCoreOption;

export function axisColors(dark: boolean) {
  return {
    text: dark ? "#a1a1aa" : "#52525b",
    line: dark ? "#3f3f46" : "#d4d4d8",
  };
}
