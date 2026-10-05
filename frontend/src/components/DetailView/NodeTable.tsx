import type { DetailNode } from "../../api/types";
import { Collapsible, td, th } from "../ui";

function summarize(inputs: Record<string, unknown>): string {
  return Object.entries(inputs)
    .map(([k, v]) => {
      const text = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}=${text.length > 60 ? `${text.slice(0, 57)}…` : text}`;
    })
    .join("  ");
}

/** Every node of the API prompt; nodes that never executed are greyed out. */
export default function NodeTable({ nodes }: { nodes: DetailNode[] }) {
  return (
    <Collapsible title={`Nodes (${nodes.length})`}>
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className={th}>id</th>
            <th className={th}>class</th>
            <th className={th}>inputs</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((n) => (
            <tr key={n.id} className={n.reachable ? "" : "text-faint"}>
              <td className={`${td} font-mono`}>{n.id}</td>
              <td className={td}>
                {n.class_type}
                {n.title && n.title !== n.class_type && <div className="text-muted">{n.title}</div>}
                {!n.reachable && <div>unreachable</div>}
              </td>
              <td className={`${td} font-mono break-all`}>{summarize(n.inputs)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Collapsible>
  );
}
