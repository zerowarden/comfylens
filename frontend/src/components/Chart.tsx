import { useEffect, useRef } from "react";

import { echarts, type EChartsOption } from "../lib/echarts";

/** What an ECharts click reports: `dataType` and the clicked data item. */
export interface ChartClick {
  dataType?: string;
  data?: unknown;
}

/** A resizing ECharts canvas; `onClick` receives clicks on data items. */
export default function Chart({
  option,
  className,
  onClick,
}: {
  option: EChartsOption;
  className?: string;
  onClick?: (params: ChartClick) => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const click = useRef(onClick);
  useEffect(() => {
    click.current = onClick;
  });

  useEffect(() => {
    const el = element.current;
    if (!el) return;
    const instance = echarts.init(el);
    chart.current = instance;
    instance.on("click", (params) => click.current?.(params));
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(el);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    instance.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={element} className={className} />;
}
