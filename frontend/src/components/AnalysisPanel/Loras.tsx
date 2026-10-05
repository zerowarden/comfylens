import { useState } from "react";

import type { LoraKey } from "../../api/types";
import { fmtInt, fmtNum, fmtPct, loadingText } from "../../lib/format";
import { useFilters } from "../../state/filters";
import { FilterLink, Message, Segmented, ShareBar, td, th } from "../ui";
import { useStats } from "./data";
import FamilySections from "./FamilySections";
import { rangeText } from "./format";
import LoraGraph from "./LoraGraph";
import { ModeText } from "./Numeric";

export default function Loras() {
  const [key, setKey] = useState<LoraKey>("name");
  const stats = useStats(key);
  const includeLora = useFilters((s) => s.includeLora);
  const data = stats.data;
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
        <FamilySections groups={data.groups} count={(g) => g.images}>
          {(group) => (
            <>
              {(group.loras ?? []).length === 0 && (
                <div className="text-muted">No LoRAs in use.</div>
              )}
              {(group.loras ?? []).length > 0 && (
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
                    {group.loras!.map((row) => (
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
                        <td className={`${td} tabular-nums`}>
                          {fmtNum(row.strength_model.median)}
                        </td>
                        <td className={`${td} tabular-nums`}>{fmtNum(row.strength_model.mean)}</td>
                        <td className={`${td} whitespace-nowrap tabular-nums`}>
                          {rangeText(row.strength_model)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {group.graph && <LoraGraph graph={group.graph} loraKey={key} />}
            </>
          )}
        </FamilySections>
      )}
    </div>
  );
}
