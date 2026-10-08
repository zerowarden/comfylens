import type { ConfigRow, StatsResponse } from "../../api/types";
import { fmtInt, fmtPct, isSingleSelection } from "../../lib/format";
import { ChainText } from "../icons";
import { CopyButton } from "../ui";
import FamilySections from "./FamilySections";
import { configParts, configText } from "./format";
import Thumbs from "./Thumbs";

function configsText(configs: ConfigRow[]): string {
  return configs
    .map((c, i) => `${i + 1}. ${configText(c.fields)} | ${c.count} (${fmtPct(c.share)})`)
    .join("\n");
}

/** The fields as separate chips, with the LoRA stack drawn as a chain. */
function ConfigLine({ fields }: { fields: Record<string, unknown> }) {
  const parts = configParts(fields);
  return (
    <div className="flex flex-wrap gap-1">
      {parts.map((part, i) => (
        <span key={i} className="rounded bg-subtle px-1.5 py-0.5 break-words">
          {i === 1 ? <ChainText text={part} kind="lora" /> : part}
        </span>
      ))}
    </div>
  );
}

export default function Configs({ data }: { data: StatsResponse }) {
  const single = isSingleSelection(data.scope);
  return (
    <FamilySections groups={data.groups} count={single ? undefined : (g) => g.images}>
      {(group) => {
        const configs = group.configs ?? [];
        return (
          <>
            {!single && (
              <div className="mb-2 flex justify-end">
                <CopyButton label="Copy all as text" text={() => configsText(configs)}>
                  All as text
                </CopyButton>
              </div>
            )}
            <ol className="space-y-2">
              {configs.map((c, i) => (
                <li key={c.key} className="flex gap-2 text-xs">
                  <span className="w-5 shrink-0 text-right text-muted">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <ConfigLine fields={c.fields} />
                    {!single && (
                      <div className="text-muted tabular-nums">
                        {fmtInt(c.count)} images ({fmtPct(c.share)})
                      </div>
                    )}
                    {!single && <Thumbs ids={c.examples} hashes={c.example_hashes} />}
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
