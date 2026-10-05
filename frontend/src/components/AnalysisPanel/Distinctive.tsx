import { useState } from "react";

import type { DistinctiveGroup, DistinctiveTerm } from "../../api/types";
import { fmtPct } from "../../lib/format";
import { useFilters } from "../../state/filters";
import { FilterLink, Heading, Segmented } from "../ui";

/** |z| at or above this is unlikely by chance (two-sided 5%). */
const NOTABLE_Z = 1.96;

type Kind = "phrases" | "unigrams" | "bigrams" | "trigrams";
const KINDS: { value: Kind; label: string }[] = [
  { value: "unigrams", label: "Words" },
  { value: "bigrams", label: "Bigrams" },
  { value: "phrases", label: "Phrases" },
  { value: "trigrams", label: "Trigrams" },
];

const LEGEND =
  "Score: the z-scored log-odds ratio of a term in the selection versus the rest of the " +
  "filtered images, with the whole library as an informative prior (Monroe et al. 2008). " +
  "Rare terms are not over-ranked. |z| ≥ 1.96 is unlikely by chance; fainter terms are not.";

function Column({
  title,
  terms,
  tone,
}: {
  title: string;
  terms: DistinctiveTerm[];
  tone: "selection" | "rest";
}) {
  const update = useFilters((s) => s.update);
  const [all, setAll] = useState(false);
  const shown = all ? terms : terms.slice(0, 12);
  const top = Math.max(...terms.map((t) => Math.abs(t.z)), NOTABLE_Z);
  return (
    <div className="min-w-0">
      <Heading>{title}</Heading>
      {terms.length === 0 ? (
        <div className="text-xs text-muted">none</div>
      ) : (
        <ul className="space-y-1 text-xs">
          {shown.map((t) => {
            const notable = Math.abs(t.z) >= NOTABLE_Z;
            return (
              <li
                key={t.term}
                className={notable ? "" : "opacity-50"}
                title={`z = ${t.z.toFixed(2)}${notable ? "" : " (within chance)"}\nselection: ${t.selection_df} (${fmtPct(t.selection_share)})\nrest: ${t.rest_df} (${fmtPct(t.rest_share)})`}
              >
                <FilterLink
                  title="Search prompts for this"
                  onClick={() => update((f) => ({ ...f, text: t.term }))}
                >
                  {t.term}
                </FilterLink>
                <div className="flex items-center gap-1.5">
                  <div className="h-1.5 flex-1 rounded bg-track">
                    <div
                      className={`h-1.5 rounded ${tone === "selection" ? "bg-accent" : "bg-warning"}`}
                      style={{ width: `${Math.min(100, (Math.abs(t.z) / top) * 100)}%` }}
                    />
                  </div>
                  <span className="shrink-0 text-muted tabular-nums">
                    {fmtPct(t.selection_share)} vs {fmtPct(t.rest_share)}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {terms.length > 12 && (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="mt-1 text-xs text-link hover:underline"
        >
          {all ? "Show fewer" : `Show all ${terms.length}`}
        </button>
      )}
    </div>
  );
}

/** What sets the selection apart from the rest of the filtered images. */
export default function Distinctive({
  group,
  status,
}: {
  group: DistinctiveGroup | undefined;
  /** Shown instead of the lists while there is no group: loading, warming up or an error. */
  status: string;
}) {
  const [kind, setKind] = useState<Kind>("unigrams");
  return (
    <div className="mb-4 rounded border border-line p-2">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold">Distinctive terms</span>
        <span className="cursor-help text-xs text-muted underline decoration-dotted" title={LEGEND}>
          what is this?
        </span>
        <span className="flex-1" />
        <Segmented value={kind} options={KINDS} onChange={setKind} />
      </div>
      {!group ? (
        <div className="text-xs text-muted">{status}</div>
      ) : group.rest_images === 0 ? (
        <div className="text-xs text-muted">
          Every filtered image of this family is selected: there is nothing to compare against.
        </div>
      ) : group.selection_images === 0 ? (
        <div className="text-xs text-muted">The selected images have no prompt on this side.</div>
      ) : (
        <>
          <div className="mb-1.5 text-xs text-muted">
            {group.selection_images} selected vs {group.rest_images} other filtered images
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Column title="More in selection" terms={group[kind].selection} tone="selection" />
            <Column title="More in the rest" terms={group[kind].rest} tone="rest" />
          </div>
        </>
      )}
    </div>
  );
}
