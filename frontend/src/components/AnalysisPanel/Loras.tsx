import { useState } from "react";

import type { LoraKey, LoraRow, NumericStats } from "../../api/types";
import { fmtInt, fmtNum, fmtPct, isSingleSelection, loadingText } from "../../lib/format";
import { useFilters } from "../../state/filters";
import { FilterLink, Message, Segmented, ShareBar, td, th } from "../ui";
import { useStats } from "./data";
import FamilySections from "./FamilySections";
import { rangeText } from "./format";
import { ModeText } from "./Numeric";

/** The LoRAs in use and their strengths, without frequency statistics: the single-image view. */
function LoraValues({ loras }: { loras: LoraRow[] }) {
  const strength = (s: NumericStats) =>
    s.min !== null && s.min === s.max ? fmtNum(s.min) : rangeText(s);
  return (
    <ul className="space-y-1 text-xs">
      {loras.map((row) => (
        <li key={row.name} className="break-all">
          {row.name}
          <span className="text-muted"> — strength {strength(row.strength_model)}</span>
          {row.strength_clip && (
            <span className="text-muted"> (clip {strength(row.strength_clip)})</span>
          )}
          {row.steps && row.steps.length > 0 && (
            <span className="text-muted">
              , steps {row.steps.map((s) => s.value ?? "none").join(", ")}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function Loras() {
  const [key, setKey] = useState<LoraKey>("name");
  const stats = useStats(key);
  const includeLora = useFilters((s) => s.includeLora);
  const data = stats.data;
  const single = data !== undefined && isSingleSelection(data.scope);
  return (
    <div>
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="text-xs text-muted">Group by</span>
        <Segmented
          value={key}
          options={[
            { value: "name", label: "name" },
            { value: "base_name", label: "base name" },
          ]}
          onChange={setKey}
        />
      </div>
      {!data ? (
        <Message>{loadingText(stats.error)}</Message>
      ) : (
        <FamilySections groups={data.groups} count={single ? undefined : (g) => g.images}>
          {(group) => {
            const loras = group.loras ?? [];
            if (loras.length === 0) return <div className="text-muted">No LoRAs in use.</div>;
            if (single) return <LoraValues loras={loras} />;
            return (
              <table className="mb-3 w-full text-xs">
                <thead>
                  <tr>
                    <th className={th}>LoRA</th>
                    <th className={th}>images</th>
                    <th className={th}>strength mode</th>
                    <th className={th}>median</th>
                    <th className={th}>mean</th>
                    <th className={th}>range</th>
                  </tr>
                </thead>
                <tbody>
                  {loras.map((row) => (
                    <tr key={row.name}>
                      <td className={td}>
                        {/* Filters match LoRA names; base names are a grouping only. */}
                        <FilterLink
                          onClick={key === "name" ? () => includeLora(row.name) : undefined}
                        >
                          {row.name}
                        </FilterLink>
                        {row.steps && row.steps.length > 0 && (
                          <div className="text-muted">
                            steps:{" "}
                            {row.steps.map((s) => `${s.value ?? "none"} ×${s.count}`).join(", ")}
                          </div>
                        )}
                      </td>
                      <td className={`${td} w-20`}>
                        <div className="tabular-nums">
                          {fmtInt(row.images)}{" "}
                          <span className="text-muted">{fmtPct(row.share)}</span>
                        </div>
                        <ShareBar share={row.share} />
                      </td>
                      <td className={td}>
                        <ModeText stats={row.strength_model} />
                      </td>
                      <td className={`${td} tabular-nums`}>{fmtNum(row.strength_model.median)}</td>
                      <td className={`${td} tabular-nums`}>{fmtNum(row.strength_model.mean)}</td>
                      <td className={`${td} whitespace-nowrap tabular-nums`}>
                        {rangeText(row.strength_model)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            );
          }}
        </FamilySections>
      )}
    </div>
  );
}
