import type { ConfigRow, StatsResponse } from "../../api/types";
import { fmtInt, fmtPct } from "../../lib/format";
import { ChainText } from "../icons";
import { CopyButton } from "../ui";
import FamilySections from "./FamilySections";
import { configParts, configText } from "./format";
import Thumbs from "./Thumbs";

function configsText(configs: ConfigRow[], withFamily: boolean): string {
  return configs
    .map(
      (c, i) => `${i + 1}. ${configText(c.fields, withFamily)} | ${c.count} (${fmtPct(c.share)})`,
    )
    .join("\n");
}

/** The fields as separate chips, with the family pipeline and LoRA stack drawn as chains. */
function ConfigLine({
  fields,
  withFamily,
}: {
  fields: Record<string, unknown>;
  withFamily: boolean;
}) {
  const parts = configParts(fields, withFamily);
  const lora = withFamily ? 2 : 1;
  return (
    <div className="flex flex-wrap gap-1">
      {parts.map((part, i) => (
        <span key={i} className="rounded bg-zinc-100 px-1.5 py-0.5 break-words dark:bg-zinc-900">
          {withFamily && i === 0 ? (
            <ChainText text={part} kind="pipeline" />
          ) : i === lora ? (
            <ChainText text={part} kind="lora" />
          ) : (
            part
          )}
        </span>
      ))}
    </div>
  );
}

export default function Configs({ data, pooled }: { data: StatsResponse; pooled: boolean }) {
  return (
    <FamilySections groups={data.groups} count={(g) => g.images}>
      {(group) => {
        const configs = group.configs ?? [];
        return (
          <>
            <div className="mb-2 flex justify-end">
              <CopyButton label="Copy all as text" text={() => configsText(configs, pooled)}>
                All as text
              </CopyButton>
            </div>
            <ol className="space-y-2">
              {configs.map((c, i) => (
                <li key={c.key} className="flex gap-2 text-xs">
                  <span className="w-5 shrink-0 text-right text-zinc-500">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <ConfigLine fields={c.fields} withFamily={pooled} />
                    <div className="text-zinc-500 tabular-nums">
                      {fmtInt(c.count)} images ({fmtPct(c.share)})
                    </div>
                    <Thumbs ids={c.examples} hashes={c.example_hashes} />
                  </div>
                </li>
              ))}
            </ol>
          </>
        );
      }}
    </FamilySections>
  );
}
