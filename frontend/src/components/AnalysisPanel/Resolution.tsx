import type { StatsResponse } from "../../api/types";
import { fmtInt } from "../../lib/format";
import { td } from "../ui";
import CategoricalTable from "./Categorical";
import FamilySections from "./FamilySections";
import { NumericTable } from "./Numeric";

export default function Resolution({ data }: { data: StatsResponse }) {
  return (
    <FamilySections groups={data.groups} count={(g) => g.images}>
      {(group) => (
        <>
          {group.categorical?.resolution && (
            <CategoricalTable title="Resolution" data={group.categorical.resolution} />
          )}
          {group.categorical?.aspect_label && (
            <CategoricalTable title="Aspect" data={group.categorical.aspect_label} />
          )}
          {group.numeric && (
            <NumericTable
              stats={Object.fromEntries(
                ["megapixels", "width", "height", "aspect"]
                  .filter((f) => group.numeric?.[f])
                  .map((f) => [f, group.numeric![f]!]),
              )}
            />
          )}
          {group.seeds && (
            <div className="mt-3 text-xs">
              <div className="mb-0.5 font-semibold text-zinc-500">Seeds</div>
              <div>
                {fmtInt(group.seeds.n_unique)} unique of {fmtInt(group.seeds.n)} images with a seed
              </div>
              {group.seeds.repeated.length > 0 && (
                <table className="mt-1 w-full">
                  <tbody>
                    {group.seeds.repeated.map((s) => (
                      <tr key={s.seed}>
                        <td className={`${td} font-mono`}>{s.seed}</td>
                        <td className={`${td} text-right tabular-nums`}>×{s.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}
    </FamilySections>
  );
}
