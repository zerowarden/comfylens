import type { StatsResponse } from "../../api/types";
import { isSingleSelection } from "../../lib/format";
import { useFilters } from "../../state/filters";
import { CategoricalField } from "./Categorical";
import { promptStatus, usePrompts } from "./data";
import FamilySections from "./FamilySections";
import { FILTERABLE } from "./format";
import { NumericValues, NumericTable } from "./Numeric";
import PromptSummary from "./PromptSummary";

const CATEGORIES: [string, string][] = [
  ["tags", "Tags"],
  ["model_family", "Family"],
  ["base_model", "Model"],
  ["text_encoder", "Text encoder"],
  ["vae", "VAE"],
  ["sampler_name", "Sampler"],
  ["scheduler", "Scheduler"],
];
const NUMERIC = ["steps", "cfg", "denoise", "guidance", "shift", "stage_count", "megapixels"];

export default function Overview({ data }: { data: StatsResponse }) {
  const include = useFilters((s) => s.include);
  const positive = usePrompts("positive");
  const negative = usePrompts("negative");
  const status = promptStatus(positive, null);
  const single = isSingleSelection(data.scope);
  return (
    <FamilySections groups={data.groups} count={single ? undefined : (g) => g.images}>
      {(group) => (
        <>
          <PromptSummary
            positive={positive.data?.groups.find((g) => g.family === group.family)}
            negative={negative.data?.groups.find((g) => g.family === group.family)}
            status={status}
          />
          {CATEGORIES.map(([field, title]) => {
            const values = group.categorical?.[field];
            if (!values) return null;
            const target = FILTERABLE[field];
            return (
              <CategoricalField
                key={field}
                title={title}
                data={values}
                single={single}
                onPick={target ? (v: string) => include(target, v) : undefined}
                chain={field === "model_family" ? "pipeline" : undefined}
              />
            );
          })}
          {group.numeric &&
            (single ? (
              <NumericValues
                stats={Object.fromEntries(
                  NUMERIC.filter((f) => group.numeric?.[f]).map((f) => [f, group.numeric![f]!]),
                )}
              />
            ) : (
              <NumericTable
                stats={Object.fromEntries(
                  NUMERIC.filter((f) => group.numeric?.[f]).map((f) => [f, group.numeric![f]!]),
                )}
              />
            ))}
        </>
      )}
    </FamilySections>
  );
}
