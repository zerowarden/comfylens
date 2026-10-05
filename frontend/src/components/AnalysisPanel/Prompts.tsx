import { useState, type ReactNode } from "react";

import type { PromptBy, PromptCluster, PromptGroup, PromptSide, TermRow } from "../../api/types";
import { fmtInt, fmtPct, loadingText } from "../../lib/format";
import { useFilters } from "../../state/filters";
import {
  Button,
  FilterLink,
  Heading,
  Message,
  Segmented,
  ShareBar,
  ShowAllToggle,
  td,
} from "../ui";
import { WARMING_TEXT } from "../../api/client";
import { isWarming, promptStatus, useDistinctive, usePrompts } from "./data";
import Distinctive from "./Distinctive";
import FamilySections from "./FamilySections";
import Thumbs from "./Thumbs";

function Terms({ title, rows }: { title: string; rows: TermRow[] }) {
  const update = useFilters((s) => s.update);
  const [all, setAll] = useState(false);
  if (rows.length === 0) return null;
  const shown = all ? rows : rows.slice(0, 15);
  return (
    <div className="mb-3">
      <Heading>{title}</Heading>
      <table className="w-full text-xs">
        <tbody>
          {shown.map((r) => (
            <tr key={r.term}>
              <td className={`${td} w-[55%]`}>
                <FilterLink
                  title="Search prompts for this"
                  onClick={() => update((f) => ({ ...f, text: r.term }))}
                >
                  {r.term}
                </FilterLink>
              </td>
              <td className={`${td} w-[25%]`}>
                <ShareBar share={r.share} />
              </td>
              <td className={`${td} text-right whitespace-nowrap tabular-nums`}>
                {fmtInt(r.df)} <span className="text-muted">{fmtPct(r.share)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 15 && (
        <ShowAllToggle count={rows.length} all={all} onToggle={() => setAll(!all)} className="" />
      )}
    </div>
  );
}

/** Near-duplicate sentences; clicking a cluster filters the library to its images. */
function Clusters({ clusters }: { clusters: PromptCluster[] }) {
  const update = useFilters((s) => s.update);
  const active = useFilters((s) => s.filters.sentences);
  const same = (keys: string[]) =>
    keys.length === active.length && keys.every((key) => active.includes(key));
  const filterTo = (keys: string[]) => update((f) => ({ ...f, sentences: same(keys) ? [] : keys }));
  if (clusters.length === 0) {
    return <div className="mb-3 text-xs text-muted">No similar sentences in this family.</div>;
  }
  return (
    <div className="mb-3">
      <Heading>Similar sentences</Heading>
      <ul className="space-y-1.5 text-xs">
        {clusters.map((cluster) => {
          const keys = cluster.members.map((m) => m.key);
          const selected = same(keys);
          return (
            <li
              key={cluster.key}
              className={`rounded border p-1.5 ${selected ? "border-accent" : "border-line"}`}
            >
              <button
                type="button"
                title={selected ? "Clear this filter" : "Filter the library to these images"}
                onClick={() => filterTo(keys)}
                className="w-full text-left hover:text-link"
              >
                <span className="font-medium tabular-nums">{fmtInt(cluster.images)}</span>{" "}
                <span className="text-muted">
                  images in {fmtInt(cluster.prompts)} {cluster.prompts === 1 ? "prompt" : "prompts"}
                </span>
                <div className="break-words whitespace-pre-wrap">{cluster.text}</div>
              </button>
              <Thumbs ids={cluster.examples} hashes={cluster.example_hashes} />
              <details className="mt-0.5">
                <summary className="cursor-pointer text-muted">
                  {fmtInt(cluster.members.length)} similar sentences
                </summary>
                <ul className="mt-0.5 space-y-0.5">
                  {cluster.members.map((member) => (
                    <li key={member.key} className="flex items-baseline gap-1.5">
                      <button
                        type="button"
                        title="Filter to this sentence"
                        onClick={() => filterTo([member.key])}
                        className="min-w-0 flex-1 text-left text-soft hover:text-link"
                      >
                        {member.text}
                      </button>
                      <span className="shrink-0 text-muted tabular-nums">{fmtInt(member.df)}</span>
                    </li>
                  ))}
                </ul>
              </details>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Group({ group, distinctive }: { group: PromptGroup; distinctive: ReactNode }) {
  return (
    <>
      {distinctive}
      {group.templates.length > 0 && (
        <div className="mb-3">
          <Heading>Template sentences</Heading>
          <ul className="space-y-1 text-xs">
            {group.templates.map((t) => (
              <li key={t.text} className="flex gap-2">
                <span className="flex-1 text-soft italic">{t.text}</span>
                <span className="text-muted tabular-nums">{fmtPct(t.share)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {group.all_template ? (
        <div className="mb-3 text-xs text-muted">
          Every sentence in scope is template text: there is nothing that differs between these
          prompts. Turn on “include template” to count it anyway.
        </div>
      ) : (
        <>
          <Terms title="Phrases" rows={group.phrases} />
          <Terms title="Words" rows={group.unigrams} />
          <Terms title="Bigrams" rows={group.bigrams} />
          <Terms title="Trigrams" rows={group.trigrams} />
        </>
      )}
      <Clusters clusters={group.clusters} />
    </>
  );
}

export default function Prompts() {
  const [side, setSide] = useState<PromptSide>("positive");
  const [includeTemplate, setIncludeTemplate] = useState(false);
  const [by, setBy] = useState<PromptBy>("image");
  const query = usePrompts(side, includeTemplate, by);
  const warming = isWarming(query.failureReason);

  const distinctive = useDistinctive(side, by);
  const selecting = distinctive.isEnabled;
  const distinctiveStatus = promptStatus(distinctive, "No distinctive terms for this family.");
  const distinctiveFor = (family: string): ReactNode =>
    selecting ? (
      <Distinctive
        group={distinctive.data?.groups.find((g) => g.family === family)}
        status={distinctiveStatus}
      />
    ) : null;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <Segmented
          value={side}
          options={[
            { value: "positive", label: "Positive" },
            { value: "negative", label: "Negative" },
          ]}
          onChange={setSide}
        />
        <Segmented
          value={by}
          options={[
            { value: "image", label: "per image" },
            { value: "unique_prompt", label: "per prompt" },
          ]}
          onChange={setBy}
        />
        <Button active={includeTemplate} onClick={() => setIncludeTemplate(!includeTemplate)}>
          Include template
        </Button>
      </div>
      {!selecting && (
        <div className="px-3 pb-1 text-xs text-muted">
          Select images to see the prompt terms that set them apart from the rest.
        </div>
      )}
      {warming && !query.data ? (
        <Message>{WARMING_TEXT}</Message>
      ) : !query.data ? (
        <Message>{loadingText(query.error)}</Message>
      ) : (
        <FamilySections groups={query.data.groups} count={(g) => g.images}>
          {(group) => <Group group={group} distinctive={distinctiveFor(group.family)} />}
        </FamilySections>
      )}
    </div>
  );
}
