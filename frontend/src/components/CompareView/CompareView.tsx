import { useEffect, useMemo, useState } from "react";

import { fileUrl } from "../../api/client";
import type { DetailLora, ImageDetail } from "../../api/types";
import { compareFields, compareLoras, strengthLabel } from "../../lib/compare";
import { side, wordDiff, type Segment } from "../../lib/diff";
import { baseName } from "../../lib/files";
import { useImageDetail } from "../../lib/images";
import { useUi } from "../../state/ui";
import { chainKind } from "../../lib/chains";
import { ChainText } from "../icons";
import { Button, FamilyDot, Message, td, th } from "../ui";
import { ViewerHeader, ViewerModal } from "../Viewer";
import { loadingText } from "../../lib/format";

const name = (d: ImageDetail) => baseName(d.file.rel_path);

function Caption({ id, d }: { id: number; d: ImageDetail | undefined }) {
  const family = d?.generation?.model_family ?? null;
  return (
    <div className="flex min-w-0 items-center gap-2 px-2 py-1 text-xs">
      <FamilyDot family={family} large />
      <span className="font-medium">#{id}</span>
      <span className="truncate text-muted" title={d?.file.rel_path}>
        {d ? name(d) : "…"}
      </span>
    </div>
  );
}

function ImageCell({ id }: { id: number }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center bg-stage">
      {/* Both images fill their pane, so a small one is not dwarfed by its counterpart. */}
      <img src={fileUrl(id)} alt="" className="h-full w-full object-contain" />
    </div>
  );
}

/** Marks a differing row without relying on colour alone. */
function DiffMark({ differs }: { differs: boolean }) {
  return (
    <span className="inline-block w-3 text-warning" aria-label={differs ? "differs" : undefined}>
      {differs ? "≠" : ""}
    </span>
  );
}

const rowClass = (differs: boolean) => (differs ? "bg-warning/10" : "");

function Settings({ a, b, onlyDiff }: { a: ImageDetail; b: ImageDetail; onlyDiff: boolean }) {
  const rows = compareFields(a, b);
  const shown = onlyDiff ? rows.filter((r) => r.differs) : rows;
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold text-muted">
        Settings ({rows.filter((r) => r.differs).length} of {rows.length} differ)
      </h3>
      {shown.length === 0 ? (
        <div className="text-xs text-muted">No differences in these settings.</div>
      ) : (
        <table className="w-full table-fixed text-xs">
          <thead>
            <tr>
              <th className={`${th} w-36`}>field</th>
              <th className={th}>A</th>
              <th className={th}>B</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const kind = chainKind(r.label);
              const cell = (v: string) => (kind ? <ChainText text={v} kind={kind} /> : v);
              return (
                <tr key={r.label} className={rowClass(r.differs)}>
                  <td className={`${td} text-muted`}>
                    <DiffMark differs={r.differs} />
                    {r.label}
                  </td>
                  <td className={`${td} break-all`}>{cell(r.a)}</td>
                  <td className={`${td} break-all`}>{cell(r.b)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function UnusedList({ loras }: { loras: DetailLora[] }) {
  if (loras.length === 0) return <div className="text-muted">none</div>;
  return (
    <ul className="space-y-0.5">
      {loras.map((l) => (
        <li key={`${l.node_id}:${l.entry}`} className="break-all">
          node {l.node_id}: {l.name} ({strengthLabel(l)})
        </li>
      ))}
    </ul>
  );
}

function Loras({ a, b, onlyDiff }: { a: ImageDetail; b: ImageDetail; onlyDiff: boolean }) {
  const { chain, unusedA, unusedB } = compareLoras(a, b);
  const shown = onlyDiff ? chain.filter((r) => r.differs) : chain;
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold text-muted">LoRA chains</h3>
      {chain.length === 0 ? (
        <div className="text-xs text-muted">Neither image applies a LoRA.</div>
      ) : shown.length === 0 ? (
        <div className="text-xs text-muted">Both images apply the same LoRAs.</div>
      ) : (
        <table className="w-full table-fixed text-xs">
          <thead>
            <tr>
              <th className={`${th} w-36`}>LoRA</th>
              <th className={th}>A strength</th>
              <th className={th}>B strength</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={`${r.name}:${i}`} className={rowClass(r.differs)}>
                <td className={`${td} break-all`}>
                  <DiffMark differs={r.differs} />
                  {r.name}
                </td>
                <td className={td}>{r.a ?? <span className="text-muted">not applied</span>}</td>
                <td className={td}>{r.b ?? <span className="text-muted">not applied</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(unusedA.length > 0 || unusedB.length > 0) && (
        <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
          <div>
            <div className="font-semibold text-warning">Unused LoRAs in A</div>
            <UnusedList loras={unusedA} />
          </div>
          <div>
            <div className="font-semibold text-warning">Unused LoRAs in B</div>
            <UnusedList loras={unusedB} />
          </div>
        </div>
      )}
    </section>
  );
}

function Segments({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((s, i) =>
        s.kind === "removed" ? (
          <del key={i} title="Only in A" className="rounded bg-danger/20 text-danger decoration-2">
            {s.text}
          </del>
        ) : s.kind === "added" ? (
          <ins
            key={i}
            title="Only in B"
            className="rounded bg-success/20 text-success underline decoration-2 underline-offset-2"
          >
            {s.text}
          </ins>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </>
  );
}

/** One side of a prompt: its diff segments, or a note when there is no text to show. */
function PromptText({ text, segments }: { text: string | null; segments: Segment[] | null }) {
  if (text === null) return <span className="text-muted">(no prompt)</span>;
  if (text.trim() === "") return <span className="text-muted">(empty)</span>;
  return segments ? <Segments segments={segments} /> : <>{text}</>;
}

function PromptDiff({ label, a, b }: { label: string; a: string | null; b: string | null }) {
  const diff = useMemo(() => (a !== null && b !== null ? wordDiff(a, b) : null), [a, b]);
  if (a === null && b === null) return null;
  const texts = { a, b };
  const changed = !diff || diff.ops.some((op) => op.kind !== "same");
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold text-muted">
        {label} ({changed ? "differs" : "identical words"})
      </h3>
      {diff?.coarse && (
        <div className="mb-1 text-xs text-muted">
          Too long to align word by word: the differing middle is marked as a whole.
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 text-xs">
        {(["a", "b"] as const).map((which) => (
          <pre
            key={which}
            className="rounded bg-subtle p-2 font-sans break-words whitespace-pre-wrap"
          >
            <PromptText text={texts[which]} segments={diff && side(diff, which)} />
          </pre>
        ))}
      </div>
    </section>
  );
}

const PROMPTS = [
  ["Positive prompt", "positive_prompt"],
  ["Negative prompt", "negative_prompt"],
] as const;

function Comparison({ a, b, onlyDiff }: { a: ImageDetail; b: ImageDetail; onlyDiff: boolean }) {
  return (
    <div className="space-y-4 p-3">
      <Settings a={a} b={b} onlyDiff={onlyDiff} />
      <Loras a={a} b={b} onlyDiff={onlyDiff} />
      <div className="text-xs text-muted">
        Prompt words: <del className="decoration-2">struck through</del> only in A,{" "}
        <ins className="underline decoration-2 underline-offset-2">underlined</ins> only in B.
        Whitespace changes are ignored.
      </div>
      {PROMPTS.map(([label, field]) => (
        <PromptDiff
          key={field}
          label={label}
          a={a.generation?.[field] ?? null}
          b={b.generation?.[field] ?? null}
        />
      ))}
    </div>
  );
}

/** Two selected images side by side: settings, LoRA chains and a word-level prompt diff. */
export default function CompareView() {
  const ids = useUi((s) => s.compareIds);
  const openCompare = useUi((s) => s.openCompare);
  const detailOpen = useUi((s) => s.detailId !== null);

  useEffect(() => {
    if (ids === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !detailOpen) openCompare(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ids, detailOpen, openCompare]);

  if (ids === null) return null;
  return <Modal ids={ids} onClose={() => openCompare(null)} />;
}

function Modal({ ids, onClose }: { ids: [number, number]; onClose: () => void }) {
  const [idA, idB] = ids;
  const a = useImageDetail(idA);
  const b = useImageDetail(idB);
  const [onlyDiff, setOnlyDiff] = useState(false);
  const error = a.error ?? b.error;
  return (
    <ViewerModal layer="z-50" column label="Compare two images" onClose={onClose}>
      <ViewerHeader onClose={onClose}>
        <span className="font-medium">Compare</span>
        <span className="text-xs text-muted">
          A #{idA}, B #{idB}
        </span>
        <span className="flex-1" />
        <Button active={onlyDiff} onClick={() => setOnlyDiff(!onlyDiff)}>
          Only differences
        </Button>
      </ViewerHeader>
      <div className="grid h-[38%] shrink-0 grid-cols-2 gap-px border-b border-line bg-line">
        {[
          { id: idA, d: a.data },
          { id: idB, d: b.data },
        ].map(({ id, d }) => (
          <div key={id} className="flex min-h-0 flex-col bg-canvas">
            <Caption id={id} d={d} />
            <ImageCell id={id} />
          </div>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {a.data && b.data ? (
          <Comparison a={a.data} b={b.data} onlyDiff={onlyDiff} />
        ) : (
          <Message>{loadingText(error)}</Message>
        )}
      </div>
    </ViewerModal>
  );
}
