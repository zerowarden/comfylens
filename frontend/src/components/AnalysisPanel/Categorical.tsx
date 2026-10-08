import type { Categorical } from "../../api/types";
import { fmtInt, fmtPct } from "../../lib/format";
import { ChainText } from "../icons";
import { FilterLink, Heading, ShareBar, td } from "../ui";

/** The values a field holds in scope, without frequency statistics: the single-image view. */
export function CategoryValues({
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
  if (data.values.length === 0) return null;
  return (
    <div className="mb-3">
      <Heading>{title}</Heading>
      <div className="flex flex-wrap gap-1 text-xs">
        {data.values.map((v) => (
          <span key={v.value} className="rounded bg-subtle px-1.5 py-0.5 break-all">
            <FilterLink onClick={onPick ? () => onPick(v.value) : undefined}>
              {chain ? <ChainText text={v.value} kind={chain} /> : v.value}
            </FilterLink>
          </span>
        ))}
      </div>
    </div>
  );
}

/** A field's values: shares and counts by default, plain values for a single selected image. */
export function CategoricalField({
  title,
  data,
  onPick,
  chain,
  single = false,
}: {
  title: string;
  data: Categorical;
  onPick?: (value: string) => void;
  /** Draws values as chains, e.g. a family pipeline. */
  chain?: "pipeline" | "lora";
  single?: boolean;
}) {
  return single ? (
    <CategoryValues title={title} data={data} onPick={onPick} chain={chain} />
  ) : (
    <CategoricalTable title={title} data={data} onPick={onPick} chain={chain} />
  );
}

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
      <Heading>{title}</Heading>
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
                {fmtInt(v.count)} <span className="text-muted">{fmtPct(v.share)}</span>
              </td>
            </tr>
          ))}
          {data.other > 0 && (
            <tr className="text-muted">
              <td className={td}>other</td>
              <td className={td} />
              <td className={`${td} text-right tabular-nums`}>{fmtInt(data.other)}</td>
            </tr>
          )}
          {data.missing > 0 && (
            <tr className="text-muted">
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
