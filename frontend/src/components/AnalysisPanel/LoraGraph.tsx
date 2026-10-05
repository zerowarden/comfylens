import { useMemo } from "react";

import type { LoraGraph as LoraGraphData, LoraKey } from "../../api/types";
import { chartColors, withAlpha, type EChartsOption } from "../../lib/echarts";
import { useFilters } from "../../state/filters";
import { useUi } from "../../state/ui";
import Chart, { type ChartClick } from "../Chart";
import { Heading } from "../ui";

/** Node area grows with use, capped so one popular LoRA cannot fill the canvas. */
const nodeSize = (images: number) => Math.min(46, 8 + Math.sqrt(images) * 4);

/** Edge width grows with co-occurrence, logarithmically. */
const linkWidth = (images: number) => Math.min(8, 1 + Math.log2(1 + images));

/** LoRA co-occurrence: nodes are LoRAs, edges connect LoRAs used in the same image. */
export default function LoraGraph({ graph, loraKey }: { graph: LoraGraphData; loraKey: LoraKey }) {
  const theme = useUi((s) => s.theme);
  const toggleLora = useFilters((s) => s.toggleLora);
  const update = useFilters((s) => s.update);
  const colors = useMemo(() => {
    // chartColors() reads the live CSS variables; `theme` is the signal that they changed.
    void theme;
    return chartColors();
  }, [theme]);
  const option = useMemo<EChartsOption>(() => {
    return {
      tooltip: {
        trigger: "item",
        padding: [3, 6],
        textStyle: { fontSize: 11 },
        formatter: (params: { dataType?: string; data?: unknown }) => {
          const data = params.data as { name?: string; source?: string; target?: string };
          if (!data) return "";
          return params.dataType === "edge" ? `${data.source} + ${data.target}` : (data.name ?? "");
        },
      },
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          force: { repulsion: 400, edgeLength: [100, 240], gravity: 0.03 },
          // Labels sit on the node, so a narrow panel cannot clip them at its edge; the text
          // stays fully opaque while the node itself is translucent.
          label: {
            show: true,
            position: "inside",
            color: colors.text,
            fontSize: 10,
            opacity: 1,
          },
          lineStyle: { color: colors.line, opacity: 0.7, curveness: 0.05 },
          emphasis: { focus: "adjacency", label: { show: true } },
          // A translucent fill, not itemStyle.opacity: opacity would fade the label with it.
          itemStyle: {
            color: withAlpha(colors.bar, 0.45),
            borderColor: colors.bar,
            borderWidth: 1,
          },
          data: graph.nodes.map((node) => ({
            name: node.name,
            images: node.images,
            median: node.median,
            symbolSize: nodeSize(node.images),
          })),
          links: graph.links.map((link) => ({
            source: link.source,
            target: link.target,
            images: link.images,
            lineStyle: { width: linkWidth(link.images) },
          })),
        },
      ],
    };
  }, [graph, colors]);

  const onClick = (params: ChartClick) => {
    const data = params.data as { name?: string; source?: string; target?: string } | undefined;
    if (!data || loraKey !== "name") return;
    if (params.dataType === "edge" && data.source && data.target) {
      const [a, b] = [data.source, data.target];
      update((f) => {
        const same =
          f.loras.mode === "all" &&
          f.loras.names.length === 2 &&
          f.loras.names.includes(a) &&
          f.loras.names.includes(b);
        return { ...f, loras: same ? { names: [], mode: "any" } : { names: [a, b], mode: "all" } };
      });
    } else if (params.dataType === "node" && data.name) {
      toggleLora(data.name);
    }
  };

  if (graph.nodes.length === 0) return null;
  return (
    <div className="mb-3">
      <Heading>Co-occurrence</Heading>
      <Chart option={option} onClick={onClick} className="h-72 w-full" />
    </div>
  );
}
