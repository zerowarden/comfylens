import { useEffect, useRef } from "react";

import { echarts, type EChartsOption } from "../lib/echarts";

/** A resizing ECharts canvas. */
export default function Chart({
  option,
  className,
}: {
  option: EChartsOption;
  className?: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const el = element.current;
    if (!el) return;
    const instance = echarts.init(el);
    chart.current = instance;
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
