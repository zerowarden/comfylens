import { useState, type ReactNode } from "react";

import type { PromptGroup, PromptSide, TermRow } from "../../api/types";
import { saveTextToCollection } from "../../lib/collection";
import { fmtDateTime, fmtInt, fmtPct, loadingText } from "../../lib/format";
import { useFilters } from "../../state/filters";
import { Glyph } from "../icons";
import { Button, FilterLink, Heading, Message, Segmented, ShareBar, td } from "../ui";
import { isWarming, promptStatus, useDistinctive, usePrompts, WARMING_TEXT } from "./data";
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
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="text-xs text-link hover:underline"
        >
          {all ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
    </div>
  );
}

function Group({
  group,
  side,
  distinctive,
}: {
  group: PromptGroup;
  side: PromptSide;
  distinctive: ReactNode;
}) {
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
      <Heading>Distinct prompts ({fmtInt(group.distinct_total)})</Heading>
      <ul className="space-y-1.5 text-xs">
        {group.distinct.map((p) => (
          <li key={p.key} className="flex items-start gap-1">
            <details className="group min-w-0 flex-1">
              <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
                <Glyph
                  name="chevronRight"
                  className="mr-0.5 size-3 align-[-0.125em] text-muted transition-transform duration-150 group-open:rotate-90"
                />
                <span className="tabular-nums">
                  {fmtInt(p.count)} ({fmtPct(p.share)})
                </span>{" "}
                <span className="text-muted">
                  {fmtDateTime(p.first)} – {fmtDateTime(p.last)}
                </span>
                {/* Two lines while closed, the whole prompt once open. */}
                <div className="line-clamp-2 break-words whitespace-pre-wrap group-open:line-clamp-none">
                  {p.text || "(empty)"}
                </div>
              </summary>
              <Thumbs ids={p.examples} hashes={p.example_hashes} />
            </details>
            {/* Positive prompts only: a negative prompt alone is no style to come back to. */}
            {side === "positive" && p.text && (
              <Button
                className="shrink-0 px-1"
                title="Save to collection: the images with this prompt are its matches"
                ariaLabel="Save this prompt to the collection"
                onClick={() => void saveTextToCollection(p.text)}
              >
                <Glyph name="bookmarkPlus" className="size-3.5" />
              </Button>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

export default function Prompts() {
  const [side, setSide] = useState<PromptSide>("positive");
  const [includeTemplate, setIncludeTemplate] = useState(false);
  const [by, setBy] = useState<"image" | "unique_prompt">("image");
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
          {(group) => (
            <Group group={group} side={side} distinctive={distinctiveFor(group.family)} />
          )}
        </FamilySections>
      )}
    </div>
  );
}
