import type { Categorical } from "../../api/types";
import { fmtInt, fmtPct } from "../../lib/format";
import { ChainText } from "../icons";
import { FilterLink, ShareBar, td } from "../ui";

/** A frequency table: top values with count and share, then the other and missing buckets. */
export default function CategoricalTable({
  title,
  data,
  onPick,
  chain,
}: {
  title: string;
  data: Categorical;
  onPick?: (value: string) => void;
  /** Draws values as chains, e.g. a family pipeline. */
  chain?: "pipeline" | "lora";
}) {
  if (data.n === 0 && data.missing === 0) return null;
  const total = data.n + data.missing;
  return (
    <div className="mb-3">
      <div className="mb-0.5 text-xs font-semibold text-zinc-500">{title}</div>
      <table className="w-full text-xs">
        <tbody>
          {data.values.map((v) => (
            <tr key={v.value}>
              <td className={`${td} w-[50%]`}>
                <FilterLink onClick={onPick ? () => onPick(v.value) : undefined}>
                  {chain ? <ChainText text={v.value} kind={chain} /> : v.value}
                </FilterLink>
              </td>
              <td className={`${td} w-[20%]`}>
                <ShareBar share={v.share} />
              </td>
              <td className={`${td} text-right whitespace-nowrap tabular-nums`}>
                {fmtInt(v.count)} <span className="text-zinc-500">{fmtPct(v.share)}</span>
              </td>
            </tr>
          ))}
          {data.other > 0 && (
            <tr className="text-zinc-500">
              <td className={td}>other</td>
              <td className={td} />
              <td className={`${td} text-right tabular-nums`}>{fmtInt(data.other)}</td>
            </tr>
          )}
          {data.missing > 0 && (
            <tr className="text-zinc-500">
              <td className={td}>missing</td>
              <td className={td} />
              <td className={`${td} text-right tabular-nums`}>
                {fmtInt(data.missing)} <span>{fmtPct(total ? data.missing / total : 0)}</span>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
