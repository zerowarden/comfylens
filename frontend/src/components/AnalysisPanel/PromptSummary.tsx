import { useState } from "react";

import type { PromptGroup } from "../../api/types";
import { CopyButton, Heading } from "../ui";

/** Positive prompts are tinted green, negative ones red. */
const TINTS = {
  positive: "border-success/30 bg-success/10",
  negative: "border-danger/30 bg-danger/10",
};

/** The most common non-empty prompt of one side, clamped until clicked. */
function Side({
  title,
  group,
  tint,
}: {
  title: string;
  group: PromptGroup | undefined;
  tint: keyof typeof TINTS;
}) {
  const [full, setFull] = useState(false);
  const prompt = group?.distinct.find((p) => p.text.trim() !== "");
  if (!prompt) return null;
  return (
    <div className="mb-3 text-xs">
      <div className="mb-0.5 font-semibold text-muted">{title}</div>
      <div className={`flex items-start gap-2 rounded border p-1.5 ${TINTS[tint]}`}>
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
    </div>
  );
}

/** The most common prompts, each with a copy button; the Prompts tab lists the rest. */
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
      <Side title="Prompt" group={positive} tint="positive" />
      <Side title="Negative prompt" group={negative} tint="negative" />
    </>
  );
}
