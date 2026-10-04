import type { ReactNode } from "react";

import type { ImageDetail } from "../../api/types";
import { disabledLoras, stageChains, strengthLabel, unusedLoras } from "../../lib/compare";
import { Glyph } from "../icons";

function Box({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  return (
    <span
      className={`rounded border px-1.5 py-0.5 break-all ${
        muted
          ? "border-zinc-300 text-zinc-500 dark:border-zinc-700"
          : "border-sky-500/50 bg-sky-500/10"
      }`}
    >
      {children}
    </span>
  );
}

function ChainLink() {
  return <Glyph name="link" label="chained to" className="size-3 text-zinc-500" />;
}

/**
 * Base model, LoRAs (strength) and sampler linked in order, one row per model chain (a pass
 * through another model gets its own), then LoRAs that never reached a sampler.
 */
export default function LoraChain({ detail }: { detail: ImageDetail }) {
  const chains = stageChains(detail);
  const disabled = disabledLoras(detail);
  const unused = unusedLoras(detail);
  const warningFor = (nodeId: string) =>
    detail.warnings.find((w) => w.code === "UNUSED_LORA" && w.node_id === nodeId);
  const rows =
    chains.length > 0
      ? chains
      : [{ stages: [], base_model: detail.generation?.base_model ?? null, loras: [] }];

  return (
    <div className="space-y-2 text-xs">
      {rows.map((chain, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1">
          <Box muted={!chain.base_model}>{chain.base_model ?? "unknown model"}</Box>
          {chain.loras.map((l) => (
            <span key={`${l.node_id}:${l.entry}`} className="flex items-center gap-1">
              <ChainLink />
              <Box>
                {l.name} <span className="text-zinc-500">({strengthLabel(l)})</span>
              </Box>
            </span>
          ))}
          {chain.stages.length > 0 && (
            <span className="flex items-center gap-1">
              <ChainLink />
              <Box muted>{chain.stages.map((s) => `${s.class_type} #${s.node_id}`).join(", ")}</Box>
            </span>
          )}
        </div>
      ))}
      {disabled.length > 0 && (
        <div className="text-zinc-500">
          Switched off: {disabled.map((l) => `${l.name} (${l.entry || l.node_id})`).join(", ")}
        </div>
      )}
      {unused.length > 0 && (
        <div>
          <div className="font-semibold text-amber-600">Unused LoRAs</div>
          <ul className="space-y-0.5">
            {unused.map((l) => (
              <li key={`${l.node_id}:${l.entry}`}>
                node {l.node_id}: {l.name} ({strengthLabel(l)})
                <span className="text-zinc-500">
                  {" "}
                  — {warningFor(l.node_id)?.message ?? "not connected to any sampler"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
