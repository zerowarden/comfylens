import type { SeedStats, StatsResponse } from "../../api/types";
import { isSingleSelection } from "../../lib/format";
import { Heading, td } from "../ui";
import { CategoricalField } from "./Categorical";
import FamilySections from "./FamilySections";
import { NumericField } from "./Numeric";

/** The seeds shared by more than one image; nothing at all when no seed repeats. */
function Seeds({ seeds }: { seeds: SeedStats }) {
  if (seeds.repeated.length === 0) return null;
  return (
    <div className="mt-3 text-xs">
      <Heading>Seeds</Heading>
      <table className="mt-1 w-full">
        <tbody>
          {seeds.repeated.map((s) => (
            <tr key={s.seed}>
              <td className={`${td} font-mono`}>{s.seed}</td>
              <td className={`${td} text-right tabular-nums`}>×{s.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Resolution({ data }: { data: StatsResponse }) {
  const single = isSingleSelection(data.scope);
  return (
    <FamilySections groups={data.groups} count={single ? undefined : (g) => g.images}>
      {(group) => (
        <>
          {group.categorical?.resolution && (
            <CategoricalField
              title="Resolution"
              data={group.categorical.resolution}
              single={single}
            />
          )}
          {group.categorical?.aspect_label && (
            <CategoricalField
              title="Aspect"
              data={group.categorical.aspect_label}
              single={single}
            />
          )}
          {group.numeric?.megapixels && (
            <NumericField name="megapixels" stats={group.numeric.megapixels} single={single} />
          )}
          {group.seeds && <Seeds seeds={group.seeds} />}
        </>
      )}
    </FamilySections>
  );
}
