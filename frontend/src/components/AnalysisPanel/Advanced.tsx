import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../../api/client";
import type { NodeInputKey } from "../../api/types";
import { fmtInt, fmtNum } from "../../lib/format";
import { useScope } from "../../lib/scope";
import { Message, td, th } from "../ui";
import CategoricalTable from "./Categorical";
import FamilySections from "./FamilySections";
import { modeText, rangeText } from "./format";
import { HistogramChart } from "./Numeric";

const keyOf = (k: Pick<NodeInputKey, "class_type" | "input_name">) =>
  `${k.class_type}.${k.input_name}`;

function KeyStats({ chosen }: { chosen: NodeInputKey }) {
  const { scope, key } = useScope();
  const query = useQuery({
    queryKey: ["node-stats", key, chosen.class_type, chosen.input_name],
    queryFn: () =>
      api.nodeStats({ ...scope, class_type: chosen.class_type, input_name: chosen.input_name }),
    placeholderData: keepPreviousData,
  });
  if (!query.data) return <Message>{query.isError ? query.error.message : "Loading…"}</Message>;
  return (
    <FamilySections groups={query.data.groups} count={(g) => g.files}>
      {(group) => (
        <>
          {group.numeric && (
            <>
              <table className="w-full text-xs">
                <thead>
                  <tr>
                    <th className={th}>mode (share)</th>
                    <th className={th}>median</th>
                    <th className={th}>mean</th>
                    <th className={th}>min–max</th>
                    <th className={th}>n</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className={td}>{modeText(group.numeric)}</td>
                    <td className={`${td} tabular-nums`}>{fmtNum(group.numeric.median)}</td>
                    <td className={`${td} tabular-nums`}>{fmtNum(group.numeric.mean)}</td>
                    <td className={`${td} tabular-nums`}>{rangeText(group.numeric)}</td>
                    <td className={`${td} tabular-nums`}>{fmtInt(group.numeric.n)}</td>
                  </tr>
                </tbody>
              </table>
              {group.numeric.histogram && <HistogramChart histogram={group.numeric.histogram} />}
            </>
          )}
          {group.categorical && <CategoricalTable title="Values" data={group.categorical} />}
          {group.n_unique !== null && (
            <div className="text-xs text-zinc-500">
              {fmtInt(group.n_unique)} distinct values (long text: values not listed)
            </div>
          )}
        </>
      )}
    </FamilySections>
  );
}

export default function Advanced() {
  const { scope, key } = useScope();
  const keys = useQuery({
    queryKey: ["node-keys", key],
    queryFn: () => api.nodeKeys(scope),
    placeholderData: keepPreviousData,
  });
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState<NodeInputKey | null>(null);
  const matching = useMemo(() => {
    const needle = search.toLowerCase();
    return (keys.data?.keys ?? []).filter((k) => keyOf(k).toLowerCase().includes(needle));
  }, [keys.data, search]);

  return (
    <div>
      <div className="px-3 py-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search class_type.input_name"
          className="w-full rounded border border-zinc-300 bg-transparent px-2 py-1 dark:border-zinc-700"
        />
      </div>
      <div className="max-h-64 overflow-y-auto border-y border-zinc-200 dark:border-zinc-800">
        {!keys.data && <Message>{keys.isError ? keys.error.message : "Loading…"}</Message>}
        <ul className="text-xs">
          {matching.slice(0, 300).map((k) => (
            <li key={`${keyOf(k)}:${k.kind}`}>
              <button
                type="button"
                onClick={() => setChosen(k)}
                className={`flex w-full gap-2 px-3 py-0.5 text-left hover:bg-zinc-100 dark:hover:bg-zinc-900 ${
                  chosen && keyOf(chosen) === keyOf(k) && chosen.kind === k.kind
                    ? "bg-sky-500/10"
                    : ""
                }`}
              >
                <span className="min-w-0 flex-1 truncate font-mono">{keyOf(k)}</span>
                <span className="text-zinc-500">{k.kind}</span>
                <span className="w-14 text-right text-zinc-500 tabular-nums">
                  {fmtInt(k.files)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      {chosen ? (
        <>
          <div className="px-3 pt-2 font-mono text-xs">{keyOf(chosen)}</div>
          <KeyStats chosen={chosen} />
        </>
      ) : (
        <Message>Pick a node input to see its statistics.</Message>
      )}
    </div>
  );
}
