import { useState } from "react";

import type { DistinctPrompt, PromptGroup } from "../../api/types";
import { fmtInt, fmtPct } from "../../lib/format";
import { useUi } from "../../state/ui";
import { CopyButton, Heading } from "../ui";

const SHOWN = 3;

function Entry({ prompt, counted }: { prompt: DistinctPrompt; counted: boolean }) {
  const [full, setFull] = useState(false);
  return (
    <li className="rounded border border-line p-1.5">
      <div className="flex items-start gap-2">
        <button
          type="button"
          title={full ? "Show less" : "Show the whole prompt"}
          onClick={() => setFull(!full)}
          className={`min-w-0 flex-1 text-left break-words whitespace-pre-wrap ${full ? "" : "line-clamp-4"}`}
        >
          {prompt.text}
        </button>
        <CopyButton label="Copy prompt" text={prompt.text} />
      </div>
      {counted && (
        <div className="mt-0.5 text-muted tabular-nums">
          {fmtInt(prompt.count)} images ({fmtPct(prompt.share)})
        </div>
      )}
    </li>
  );
}

function Side({ title, group }: { title: string; group: PromptGroup | undefined }) {
  const setTab = useUi((s) => s.setTab);
  const prompts = group?.distinct.filter((p) => p.text.trim() !== "") ?? [];
  if (prompts.length === 0) return null;
  const several = group !== undefined && group.distinct_total > 1;
  return (
    <div className="mb-3 text-xs">
      <div className="mb-0.5 flex items-baseline gap-2">
        <span className="font-semibold text-muted">{title}</span>
        {several && (
          <>
            <span className="text-muted">
              {fmtInt(Math.min(SHOWN, prompts.length))} of {fmtInt(group.distinct_total)} distinct
            </span>
            <button
              type="button"
              onClick={() => setTab("prompts")}
              className="text-link hover:underline"
            >
              All in Prompts
            </button>
          </>
        )}
      </div>
      <ul className="space-y-1">
        {prompts.slice(0, SHOWN).map((p) => (
          <Entry key={p.key} prompt={p} counted={several} />
        ))}
      </ul>
    </div>
  );
}

/** The prompts themselves, most common first, each with a copy button. */
export default function PromptSummary({
  positive,
  negative,
  status,
}: {
  positive: PromptGroup | undefined;
  negative: PromptGroup | undefined;
  /** Shown while the positive prompts load, warm up or fail. */
  status: string | null;
}) {
  if (status && !positive)
    return (
      <div className="mb-3 text-xs">
        <Heading>Prompt</Heading>
        <div className="text-muted">{status}</div>
      </div>
    );
  return (
    <>
      <Side title="Prompt" group={positive} />
      <Side title="Negative prompt" group={negative} />
    </>
  );
}
