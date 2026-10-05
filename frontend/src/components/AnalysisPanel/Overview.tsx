import type { StatsResponse } from "../../api/types";
import { useFilters } from "../../state/filters";
import CategoricalTable from "./Categorical";
import { promptStatus, usePrompts } from "./data";
import FamilySections from "./FamilySections";
import { FILTERABLE } from "./format";
import { NumericTable } from "./Numeric";
import PromptSummary from "./PromptSummary";

const CATEGORIES: [string, string][] = [
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
  return (
    <FamilySections groups={data.groups} count={(g) => g.images}>
      {(group) => (
        <>
          <PromptSummary
            positive={positive.data?.groups.find((g) => g.family === group.family)}
            negative={negative.data?.groups.find((g) => g.family === group.family)}
            status={status}
          />
          {CATEGORIES.map(([field, title]) => {
            const values = group.categorical?.[field];
            const target = FILTERABLE[field];
            return values ? (
              <CategoricalTable
                key={field}
                title={title}
                data={values}
                onPick={target ? (v) => include(target, v) : undefined}
                chain={field === "model_family" ? "pipeline" : undefined}
              />
            ) : null;
          })}
          {group.numeric && (
            <NumericTable
              stats={Object.fromEntries(
                NUMERIC.filter((f) => group.numeric?.[f]).map((f) => [f, group.numeric![f]!]),
              )}
            />
          )}
        </>
      )}
    </FamilySections>
  );
}
